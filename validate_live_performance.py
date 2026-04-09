#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validazione performance live — ML filter vs risultati reali.

Confronta i segnali degli ultimi N giorni con:
  1. I fill reali da IBKR (se connesso e autenticato)
  2. L'outcome simulato forward dai dati candele nel DB

Per ogni segnale calcola:
  - ml_score (punteggio modello ML)
  - outcome forward (tp1_hit, pnl_r) dai dati OHLCV nel DB
  - match con fill IBKR (se disponibile)

Report finale:
  - WR per segnali sopra/sotto soglia ML
  - Calibrazione: ml_score alto → WR effettivo più alto?
  - Confronto fill IBKR vs segnali ML (se disponibile)

Uso:
    python validate_live_performance.py [--days 30] [--threshold 0.54] [--no-ibkr]

Richiede:
    $env:PYTHONPATH = "backend"
    $env:DATABASE_URL = "postgresql+asyncpg://..."
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Forza stdout UTF-8 su Windows per evitare UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import and_, or_, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_indicator import CandleIndicator
from app.models.candle_pattern import CandlePattern
from app.services.regime_filter_service import load_regime_filter, normalize_regime_variant
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    _d,
    _eligible_plan,
    _simulate_long_after_entry,
    _simulate_short_after_entry,
    build_trade_plan_v1_for_stored_pattern,
)  # noqa: PLC2701 — funzioni private necessarie per la simulazione forward

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("validate_live")

_MODEL_PATH = Path("eda_output/lgbm_baseline_tp1_hit.pkl")
_OUTPUT_JSON = Path("eda_output/live_performance_report.json")


# ─────────────────────────────────────────────────────────────────────────────
# ML Scoring (autonomo, senza il backend running)
# ─────────────────────────────────────────────────────────────────────────────

def _load_model():
    if not _MODEL_PATH.exists():
        return None, None
    try:
        import joblib
        model = joblib.load(_MODEL_PATH)
        raw = model.feature_name_
        features = list(raw() if callable(raw) else raw)
        return model, features
    except Exception as exc:
        logger.warning("Modello ML non caricabile: %s", exc)
        return None, None


_CAT_COLS_ML = [
    "direction", "timeframe", "symbol_group", "regime_spy",
    "ctx_market_regime", "ctx_volatility_regime", "ctx_candle_expansion",
    "ctx_direction_bias", "rs_signal", "cvd_trend", "session", "vix_regime",
]


def _score_batch(model, features, feature_dicts: list[dict]) -> list[float | None]:
    """
    Scoring in batch: una sola chiamata predict_proba su tutti i segnali.
    ~100x più veloce dello scoring uno-a-uno.
    """
    if model is None or not feature_dicts:
        return [None] * len(feature_dicts)
    try:
        import pandas as pd
        df = pd.DataFrame(feature_dicts)
        cat_present = [c for c in _CAT_COLS_ML if c in df.columns]
        if cat_present:
            df = pd.get_dummies(df, columns=cat_present, drop_first=False, dummy_na=True)
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        for f in features:
            if f not in df.columns:
                df[f] = 0.0
        df = df[features].fillna(0.0)
        probas = model.predict_proba(df)[:, 1]
        return [round(float(p), 4) for p in probas]
    except Exception as exc:
        logger.warning("Batch scoring fallito: %s", exc)
        return [None] * len(feature_dicts)


def _build_feature_dict(pat, ind, ctx, candle, regime_filter) -> dict:
    """Versione semplificata del feature builder (no VIX/earnings in live-script)."""
    from app.services.ml_signal_scorer import build_signal_feature_dict
    try:
        return build_signal_feature_dict(
            pat=pat, ind=ind, ctx=ctx, candle=candle,
            regime_filter=regime_filter,
        )
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Outcome forward (replica logica build_trade_dataset.py)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_outcome(pat, candle, ctx, pq_lookup, candles_series, candle_idx):
    plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)
    if not _eligible_plan(plan):
        return None
    entry_px = _d(plan.entry_price)
    stop = _d(plan.stop_loss)
    tp1 = _d(plan.take_profit_1)
    tp2 = _d(plan.take_profit_2)
    if candle_idx + 1 >= len(candles_series):
        return None

    direction = plan.trade_direction
    entry_bar = candle_idx + 1
    entry_px = _d(candles_series[entry_bar].open)

    if direction == "long":
        outcome_label, pnl_r, _ = _simulate_long_after_entry(
            candles_series, entry_bar,
            entry=entry_px, stop=stop, tp1=tp1, tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY, cost_rate=0.0015,
        )
    else:
        outcome_label, pnl_r, _ = _simulate_short_after_entry(
            candles_series, entry_bar,
            entry=entry_px, stop=stop, tp1=tp1, tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY, cost_rate=0.0015,
        )

    return {
        "tp1_hit": int(outcome_label in ("tp1", "tp2")),
        "tp2_hit": int(outcome_label == "tp2"),
        "stop_hit": int(outcome_label == "stop"),
        "pnl_r": round(float(pnl_r), 4) if pnl_r is not None else None,
        "outcome_label": outcome_label,
    }


# ─────────────────────────────────────────────────────────────────────────────
# IBKR fills fetcher
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_ibkr_fills() -> list[dict]:
    """Tenta di recuperare i fill reali da IBKR. Restituisce lista vuota se non disponibile."""
    if not settings.ibkr_enabled:
        return []
    try:
        from app.services.ibkr_service import get_ibkr_service
        svc = get_ibkr_service()
        if not await svc.is_authenticated():
            logger.warning("IBKR non autenticato — fill non disponibili")
            return []
        fills = await svc.get_executions(days=60)
        await svc.aclose()
        return fills
    except Exception as exc:
        logger.warning("IBKR fills: %s", exc)
        return []


def _match_fill_to_signal(fills: list[dict], pat_symbol: str, pat_ts: datetime) -> dict | None:
    """
    Trova il fill IBKR più vicino al segnale per simbolo e timestamp (±4 ore).
    IBKR usa 'sym' o 'symbol' per il ticker e 'exec_time' / 'trade_time' per il timestamp.
    """
    sym_clean = pat_symbol.upper().replace("/USDT", "").replace("/USD", "")
    best = None
    best_delta = timedelta(hours=4)

    for fill in fills:
        fill_sym = (fill.get("symbol") or fill.get("sym") or "").upper()
        if fill_sym != sym_clean:
            continue
        ts_raw = fill.get("exec_time") or fill.get("trade_time") or fill.get("order_time")
        if not ts_raw:
            continue
        try:
            if isinstance(ts_raw, (int, float)):
                fill_ts = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)
            else:
                fill_ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            delta = abs(fill_ts - pat_ts)
            if delta < best_delta:
                best_delta = delta
                best = {**fill, "_delta_minutes": round(delta.total_seconds() / 60, 1)}
        except Exception:
            continue
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_SYMBOLS = (
    "GOOGL,TSLA,AMD,META,NVDA,NFLX,COIN,MSTR,HOOD,SHOP,SOFI,ZS,NET,CELH,RBLX,PLTR,"
    "HPE,MDB,SMCI,DELL,ACHR,ASTS,JOBY,RKLB,NNE,OKLO,WULF,APLD,SMR,RXRX,NVO,LLY,"
    "MRNA,NKE,TGT,NEM,SCHW,WMT,SPY"
)


async def main_async() -> None:
    ap = argparse.ArgumentParser(description="Validazione performance live ML")
    ap.add_argument("--days", type=int, default=30, help="Giorni da analizzare (default: 30)")
    ap.add_argument("--threshold", type=float, default=0.54, help="Soglia ML_MIN_SCORE attiva")
    ap.add_argument("--provider", default="yahoo_finance")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--no-ibkr", action="store_true", help="Salta fetch fill IBKR")
    ap.add_argument("--min-strength", type=float, default=0.70)
    ap.add_argument(
        "--symbols", default=_DEFAULT_SYMBOLS,
        help="Simboli da includere (comma-separated). Default: universo v4.2",
    )
    ap.add_argument("--no-symbol-filter", action="store_true", help="Includi tutti i simboli")
    ap.add_argument("--max-signals", type=int, default=0, help="Limite segnali (0=nessuno, utile per test)")
    args = ap.parse_args()

    symbols_filter = (
        None if args.no_symbol_filter
        else [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    )

    dt_from = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"\nValidazione live — ultimi {args.days} giorni (dal {dt_from.strftime('%Y-%m-%d')})")
    print(f"Soglia ML attiva: {args.threshold} | Provider: {args.provider} | TF: {args.timeframe}")
    if symbols_filter:
        print(f"Simboli filtrati: {len(symbols_filter)} ({', '.join(symbols_filter[:5])}{'…' if len(symbols_filter) > 5 else ''})")
    print()

    # Carica modello ML
    model, features = _load_model()
    if model is None:
        print("[!] Modello ML non trovato -- score ML non disponibile (report solo outcome).")
    else:
        print(f"[OK] Modello ML caricato ({len(features)} feature)")

    # Fetch IBKR fills (opzionale)
    ibkr_fills: list[dict] = []
    if not args.no_ibkr:
        print("Connessione IBKR per fills reali…")
        ibkr_fills = await _fetch_ibkr_fills()
        print(f"  {len(ibkr_fills)} fill trovati" if ibkr_fills else "  IBKR non disponibile (modalita' paper)")

    async with AsyncSessionLocal() as session:
        from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf

        # Pattern recenti
        where_clauses = [
            CandlePattern.provider == args.provider,
            CandlePattern.timeframe == args.timeframe,
            CandlePattern.pattern_strength >= args.min_strength,
            CandlePattern.timestamp >= dt_from,
        ]
        if symbols_filter:
            from sqlalchemy import func
            where_clauses.append(func.upper(CandlePattern.symbol).in_(symbols_filter))

        stmt = (
            select(CandlePattern, Candle, CandleContext, CandleIndicator)
            .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
            .join(Candle, CandleFeature.candle_id == Candle.id)
            .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
            .outerjoin(CandleIndicator, CandleIndicator.candle_id == Candle.id)
            .where(*where_clauses)
            .order_by(CandlePattern.timestamp.asc())
        )
        rows = list((await session.execute(stmt)).all())
        if args.max_signals and len(rows) > args.max_signals:
            rows = rows[-args.max_signals:]  # prendi i più recenti
            print(f"  (limitato a ultimi {args.max_signals} segnali con --max-signals)")
        print(f"\nSegnali trovati nel periodo: {len(rows)}")
        if not rows:
            print("Nessun segnale — prova ad aumentare --days o verificare la pipeline.")
            return

        # Carica candele per serie
        series_keys = {(p.exchange, p.symbol, p.timeframe) for p, _, _, _ in rows}
        or_parts = [
            and_(Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf)
            for ex, sym, tf in series_keys
        ]
        c_stmt = (
            select(Candle)
            .where(or_(*or_parts))
            .order_by(Candle.exchange, Candle.symbol, Candle.timeframe, Candle.timestamp.asc())
        )
        all_candles = list((await session.execute(c_stmt)).scalars().all())
        by_series: dict = defaultdict(list)
        for c in all_candles:
            by_series[(c.exchange, c.symbol, c.timeframe)].append(c)
        id_to_idx: dict = {}
        for key, clist in by_series.items():
            id_to_idx[key] = {c.id: i for i, c in enumerate(clist)}

        # Quality lookup
        pq_lookup = await pattern_quality_lookup_by_name_tf(
            session, symbol=None, exchange=None,
            provider=args.provider, asset_type=None, timeframe=args.timeframe,
        )

        # Regime filter
        regime_filter = await load_regime_filter(
            session, provider=args.provider,
            variant=normalize_regime_variant("ema50"),
        )

        # ── Passata 1: costruisci feature dicts (veloce) ──────────────────────
        try:
            from tqdm import tqdm as _tqdm
            _progress = _tqdm
        except ImportError:
            def _progress(it, **kw):  # type: ignore[misc]
                total = kw.get("total", "?")
                print(f"  (installa tqdm per la progress bar: pip install tqdm)")
                return it

        print("Passata 1/3 — build feature dicts…")
        partial_results = []
        feat_dicts = []
        for pat, candle, ctx, ind in _progress(rows, total=len(rows), desc="features"):
            ts_utc = pat.timestamp if pat.timestamp.tzinfo else pat.timestamp.replace(tzinfo=timezone.utc)
            feat = _build_feature_dict(pat, ind, ctx, candle, regime_filter)
            feat_dicts.append(feat)
            partial_results.append({
                "_pat": pat, "_candle": candle, "_ctx": ctx,
                "_key": (pat.exchange, pat.symbol, pat.timeframe),
                "signal_id": pat.id,
                "symbol": pat.symbol,
                "pattern_name": pat.pattern_name,
                "direction": pat.direction,
                "timestamp": ts_utc.isoformat(),
                "strength": float(pat.pattern_strength),
                "ml_score": None,
                "ml_above_threshold": False,
                "outcome": None,
                "ibkr_fill": None,
            })

        # ── Passata 2: batch ML scoring (una sola predict_proba) ──────────────
        print(f"Passata 2/3 — batch ML scoring ({len(feat_dicts)} segnali in una sola chiamata)…")
        ml_scores = _score_batch(model, features, feat_dicts)
        for i, score in enumerate(ml_scores):
            partial_results[i]["ml_score"] = score
            partial_results[i]["ml_above_threshold"] = (score is not None and score >= args.threshold)

        # ── Passata 3: outcome forward simulation ─────────────────────────────
        print("Passata 3/3 — simulazione outcome forward…")
        results = []
        for rec in _progress(partial_results, total=len(partial_results), desc="outcomes"):
            pat, candle, ctx = rec.pop("_pat"), rec.pop("_candle"), rec.pop("_ctx")
            key = rec.pop("_key")
            clist = by_series.get(key, [])
            idx = (id_to_idx.get(key) or {}).get(candle.id)

            if clist and idx is not None:
                rec["outcome"] = _compute_outcome(pat, candle, ctx, pq_lookup, clist, idx)

            ts_utc_obj = datetime.fromisoformat(rec["timestamp"])
            rec["ibkr_fill"] = (
                _match_fill_to_signal(ibkr_fills, pat.symbol, ts_utc_obj)
                if ibkr_fills else None
            )
            results.append(rec)

    # ── Report ───────────────────────────────────────────────────────────────
    n_total = len(results)
    has_outcome = [r for r in results if r["outcome"] is not None]
    has_ml = [r for r in results if r["ml_score"] is not None]

    print(f"\n{'='*60}")
    print(f"REPORT PERFORMANCE LIVE — {args.days} giorni")
    print(f"{'='*60}")
    print(f"Segnali totali:        {n_total}")
    print(f"Con outcome forward:   {len(has_outcome)}")
    print(f"Con ML score:          {len(has_ml)}")
    if ibkr_fills:
        matched = sum(1 for r in results if r["ibkr_fill"])
        print(f"Matched con IBKR fill: {matched}")

    if has_outcome:
        # Baseline
        wins_all = sum(1 for r in has_outcome if r["outcome"].get("tp1_hit"))
        wr_baseline = wins_all / len(has_outcome) * 100
        print(f"\nBaseline WR (tutti):   {wr_baseline:.1f}%  [{wins_all}/{len(has_outcome)}]")

    if has_ml and has_outcome:
        above = [r for r in results if r["ml_above_threshold"] and r["outcome"]]
        below = [r for r in results if not r["ml_above_threshold"] and r["ml_score"] is not None and r["outcome"]]

        print(f"\n{'─'*60}")
        print(f"ML score >= {args.threshold}:  {len(above)} segnali")
        if above:
            wins_a = sum(1 for r in above if r["outcome"].get("tp1_hit"))
            wr_a = wins_a / len(above) * 100
            avg_pnl = sum(r["outcome"]["pnl_r"] or 0 for r in above) / len(above)
            print(f"  WR tp1:  {wr_a:.1f}%  [{wins_a}/{len(above)}]")
            print(f"  Avg PnL: {avg_pnl:+.2f}R")

        print(f"\nML score <  {args.threshold}:  {len(below)} segnali  (filtrati)")
        if below:
            wins_b = sum(1 for r in below if r["outcome"].get("tp1_hit"))
            wr_b = wins_b / len(below) * 100
            avg_pnl_b = sum(r["outcome"]["pnl_r"] or 0 for r in below) / len(below)
            print(f"  WR tp1:  {wr_b:.1f}%  [{wins_b}/{len(below)}]")
            print(f"  Avg PnL: {avg_pnl_b:+.2f}R")

        # Calibrazione ML
        print(f"\n{'─'*60}")
        print("Calibrazione ML (WR per bucket di score):")
        buckets = [(0.0, 0.45), (0.45, 0.50), (0.50, 0.54), (0.54, 0.58), (0.58, 0.62), (0.62, 1.01)]
        for lo, hi in buckets:
            grp = [r for r in results if r["ml_score"] is not None and r["outcome"]
                   and lo <= r["ml_score"] < hi]
            if grp:
                wr = sum(1 for r in grp if r["outcome"].get("tp1_hit")) / len(grp) * 100
                avg_p = sum(r["outcome"]["pnl_r"] or 0 for r in grp) / len(grp)
                bar = "#" * int(wr / 5)
                print(f"  [{lo:.2f}-{hi:.2f}):  {bar:<20}  WR={wr:5.1f}%  n={len(grp):3d}  avg={avg_p:+.2f}R")

    # Fill IBKR reali
    if ibkr_fills:
        matched_results = [r for r in results if r["ibkr_fill"]]
        if matched_results:
            print(f"\n{'─'*60}")
            print(f"FILL IBKR REALI ({len(matched_results)} trade matchati):")
            for r in sorted(matched_results, key=lambda x: x["timestamp"])[-10:]:
                fill = r["ibkr_fill"]
                out = r["outcome"]
                ml = f"ML={r['ml_score']:.2f}" if r["ml_score"] else "ML=n/a"
                side = fill.get("side", "?")
                price = fill.get("price") or fill.get("avg_price") or "?"
                result_str = ""
                if out:
                    result_str = f"  {'WIN' if out.get('tp1_hit') else 'LOSS'}  {out.get('pnl_r', 0):+.2f}R"
                print(f"  {r['symbol']:<6} {r['timestamp'][:10]}  {side}@{price}  {ml}{result_str}")

    # Top segnali per ML score
    if has_ml:
        top = sorted([r for r in results if r["ml_score"]], key=lambda x: -x["ml_score"])[:10]
        print(f"\n{'─'*60}")
        print("Top 10 segnali per ML score:")
        for r in top:
            out = r["outcome"]
            result_str = ""
            if out:
                label = "WIN " if out.get("tp1_hit") else "LOSS"
                result_str = f"  {label}  {out.get('pnl_r', 0):+.2f}R"
            print(f"  {r['symbol']:<6} {r['timestamp'][:16]}  {r['pattern_name']:<35}  ML={r['ml_score']:.3f}{result_str}")

    print(f"\n{'='*60}")

    # Salva JSON
    _OUTPUT_JSON.parent.mkdir(exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days_analyzed": args.days,
        "threshold": args.threshold,
        "n_signals": n_total,
        "n_with_outcome": len(has_outcome),
        "n_with_ml_score": len(has_ml),
        "ibkr_fills_found": len(ibkr_fills),
        "results": results,
    }
    with open(_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"Report JSON: {_OUTPUT_JSON}")


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
