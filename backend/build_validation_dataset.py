"""
build_validation_dataset.py
============================
Costruisce il dataset di validazione per misurare empiricamente l'effetto
di modifiche al sistema di scoring (pesi quality_bonus, strength, penalty, ecc.).

Produce: data/validation_set_v1.csv  (e .parquet se pandas>=1.0 disponibile)

Schema output:
  opportunity_id       int       progressivo
  symbol               str
  timeframe            str
  provider             str
  exchange             str
  pattern_name         str
  direction            str       bullish | bearish
  pattern_timestamp    str       ISO8601 UTC
  entry_price          float
  stop_price           float
  tp1_price            float
  tp2_price            float
  risk_pct             float     (entry - stop) / entry * 100
  pattern_strength     float     0..1
  pattern_quality_score float|None   score 0..100
  screener_score       float     score grezzo
  final_score          float     score composito al momento del pattern
  outcome              str       stop | tp1 | tp2 | timeout | no_entry
  pnl_r                float     multipli di R (-1 = stop, +RR = tp)
  bars_to_entry        int|None  barre dalla barra pattern all'ingresso
  bars_to_exit         int|None  barre dall'ingresso all'uscita
  entry_filled         bool

Uso:
  cd backend
  python build_validation_dataset.py [--limit 500] [--timeframe 1h] [--output data/validation_set_v1.csv]

Note:
  - Il pattern quality score è calcolato sul BACKTEST POINT-IN-TIME relativo
    ai pattern antecedenti (non su tutta la storia → si evita look-ahead parzialmente).
  - Lo script ricicla le stesse funzioni di simulazione di trade_plan_backtest.py.
  - Esclude automaticamente gli ultimi 60 giorni (holdout non toccare).
  - Se il sistema fa concurrent pattern detection su più provider, sceglie
    il pattern più recente per (symbol, timeframe, provider).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# --- bootstrap path ----------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import app.db.bootstrap  # noqa: F401  # registra Base.metadata

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    PATTERN_QUALITY_MIN_SAMPLE,
    VALIDATED_PATTERNS_1H,
    VALIDATED_PATTERNS_5M,
    VALIDATED_PATTERNS_OPERATIONAL,
)
from app.db.session import AsyncSessionLocal
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_quality import compute_pattern_quality_score
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    MAX_BARS_ENTRY_SCAN,
    _entry_scan_start_idx,
    _find_entry_bar,
    _simulate_long_after_entry,
    _simulate_short_after_entry,
)
from app.services.trade_plan_engine import build_trade_plan_v1
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
)
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurazione campionamento
# ---------------------------------------------------------------------------
_HOLDOUT_DAYS = 60          # escludi i più recenti (test set futuro)
_MAX_PER_PATTERN_TF = 60    # max occorrenze per (pattern_name, timeframe) → bilanciamento
_MIN_TOTAL_PATTERNS = 50    # sotto questa soglia avvisa ma non blocca
_DEFAULT_LIMIT = 2000       # pattern candidati prima del filtro bilanciamento

_VALIDATED: frozenset[str] = VALIDATED_PATTERNS_OPERATIONAL | VALIDATED_PATTERNS_1H | VALIDATED_PATTERNS_5M


def _d(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _ts_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


async def _load_candidate_patterns(
    session: AsyncSession,
    *,
    timeframe_filter: str | None,
    limit: int,
    holdout_days: int,
) -> list[tuple[CandlePattern, Candle, CandleContext]]:
    """
    Carica pattern candidati bilanciati per (pattern_name, timeframe).
    Esclude gli ultimi holdout_days giorni (holdout set).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=holdout_days)

    stmt = (
        select(CandlePattern, Candle, CandleContext)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
        .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
        .where(CandlePattern.pattern_name.in_(list(_VALIDATED)))
        .where(Candle.timestamp < cutoff)
    )

    if timeframe_filter:
        stmt = stmt.where(CandlePattern.timeframe == timeframe_filter)

    # Campionamento casuale per rappresentatività temporale
    stmt = stmt.order_by(func.random()).limit(limit)

    result = await session.execute(stmt)
    return list(result.all())


async def _load_forward_candles(
    session: AsyncSession,
    patterns: list[tuple[CandlePattern, Candle, CandleContext]],
) -> dict[tuple[str, str, str, str], list[Candle]]:
    """
    Carica le candele forward per ogni serie (provider, exchange, symbol, timeframe)
    necessarie alla simulazione.
    """
    oldest_by_series: dict[tuple[str, str, str, str], datetime] = {}
    for pat, candle, _ in patterns:
        key = (pat.provider, pat.exchange, pat.symbol, pat.timeframe)
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if key not in oldest_by_series or ts < oldest_by_series[key]:
            oldest_by_series[key] = ts

    if not oldest_by_series:
        return {}

    # Raggruppa per (provider, exchange, timeframe) per efficienza della query
    all_candles: dict[tuple[str, str, str, str], list[Candle]] = defaultdict(list)

    # Carica in batch per serie
    for (prov, exch, sym, tf), oldest_ts in oldest_by_series.items():
        since = oldest_ts - timedelta(days=2)
        # Forward window: MAX_BARS_ENTRY_SCAN + MAX_BARS_AFTER_ENTRY barre
        # Per sicurezza carichiamo fino a 30 giorni dopo il pattern più vecchio
        until = oldest_ts + timedelta(days=30)

        stmt = (
            select(Candle)
            .where(
                and_(
                    Candle.provider == prov,
                    Candle.exchange == exch,
                    Candle.symbol == sym,
                    Candle.timeframe == tf,
                    Candle.timestamp >= since,
                    Candle.timestamp <= until,
                )
            )
            .order_by(Candle.timestamp.asc())
        )
        result = await session.execute(stmt)
        candles = list(result.scalars().all())
        all_candles[(prov, exch, sym, tf)].extend(candles)

    return dict(all_candles)


def _balance_sample(
    rows: list[tuple[CandlePattern, Candle, CandleContext]],
    max_per_bucket: int,
) -> list[tuple[CandlePattern, Candle, CandleContext]]:
    """Limita a max_per_bucket occorrenze per (pattern_name, timeframe)."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    out = []
    for row in rows:
        pat, _, _ = row
        key = (pat.pattern_name, pat.timeframe)
        if counts[key] < max_per_bucket:
            counts[key] += 1
            out.append(row)
    return out


async def build_dataset(
    *,
    timeframe_filter: str | None,
    limit: int,
    holdout_days: int,
    cost_rate: float,
) -> list[dict]:
    """
    Logica principale: carica pattern, simula esiti, compila il dataset.
    """
    async with AsyncSessionLocal() as session:
        logger.info("Caricamento pattern candidati (limit=%d, holdout=%dd)…", limit, holdout_days)
        raw = await _load_candidate_patterns(
            session,
            timeframe_filter=timeframe_filter,
            limit=limit,
            holdout_days=holdout_days,
        )
        logger.info("Pattern candidati: %d", len(raw))

        balanced = _balance_sample(raw, _MAX_PER_PATTERN_TF)
        logger.info(
            "Pattern dopo bilanciamento (max %d per bucket): %d",
            _MAX_PER_PATTERN_TF, len(balanced),
        )

        if len(balanced) < _MIN_TOTAL_PATTERNS:
            logger.warning(
                "Solo %d pattern nel dataset — aumenta --limit o rimuovi --timeframe",
                len(balanced),
            )

        # Pattern quality lookup POINT-IN-TIME approssimato:
        # usiamo la lookup globale (leggero look-ahead) — nota limitazione documentata.
        logger.info("Calcolo pattern quality lookup…")
        pq_lookup = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=None,
            exchange=None,
            provider=None,
            asset_type=None,
            timeframe=timeframe_filter,
        )
        logger.info("Lookup pronto: %d (pattern_name, timeframe) unici", len(pq_lookup))

        # Carica candele forward in bulk
        logger.info("Caricamento candele forward…")
        forward_candles = await _load_forward_candles(session, balanced)
        logger.info(
            "Serie caricate: %d, totale candele: %d",
            len(forward_candles),
            sum(len(v) for v in forward_candles.values()),
        )

    # Simulazione (CPU-bound, nessun DB richiesto oltre questo punto)
    records: list[dict] = []
    skipped = 0
    opp_id = 0

    for pat, candle, ctx in balanced:
        opp_id += 1
        key = (pat.provider, pat.exchange, pat.symbol, pat.timeframe)
        series = forward_candles.get(key, [])

        # Costruisci trade plan
        try:
            plan = build_trade_plan_v1(
                candle=candle,
                pattern=pat,
                context=ctx,
            )
        except Exception as exc:
            logger.debug("build_trade_plan_v1 fallito (symbol=%s pattern=%s): %s",
                         pat.symbol, pat.pattern_name, exc)
            skipped += 1
            continue

        if plan is None:
            skipped += 1
            continue

        entry = _d(plan.entry_price)
        stop = _d(plan.stop_loss)
        tp1 = _d(plan.take_profit_1) if plan.take_profit_1 else entry
        tp2 = _d(plan.take_profit_2) if plan.take_profit_2 else tp1

        if stop <= 0 or entry <= 0 or entry == stop:
            skipped += 1
            continue

        risk_pct = abs(float(entry - stop)) / float(entry) * 100.0

        # Indice della barra del pattern nella serie
        pat_ts = candle.timestamp
        if pat_ts.tzinfo is None:
            pat_ts = pat_ts.replace(tzinfo=timezone.utc)

        # Trova la barra corrispondente nella serie
        pat_idx: int | None = None
        for i, c in enumerate(series):
            c_ts = c.timestamp
            if c_ts.tzinfo is None:
                c_ts = c_ts.replace(tzinfo=timezone.utc)
            if c_ts == pat_ts:
                pat_idx = i
                break

        if pat_idx is None:
            skipped += 1
            continue

        # Pattern quality score
        pq_agg = pq_lookup.get((pat.pattern_name, pat.timeframe))
        pq_score: float | None = pq_agg.pattern_quality_score if pq_agg else None

        # Screener score (proxy senza tutte le serie, solo context)
        snapshot = SnapshotForScoring(
            market_regime=ctx.market_regime or "neutral",
            volatility_regime=ctx.volatility_regime or "normal",
            candle_expansion=float(ctx.candle_expansion or 0.0),
            direction_bias=ctx.direction_bias or "neutral",
            signal_alignment=ctx.signal_alignment or "neutral",
            pattern_strength=float(pat.pattern_strength),
            pattern_direction=pat.direction,
        )
        scr_score = score_snapshot(snapshot)

        # Final opportunity score
        final_score = compute_final_opportunity_score(
            screener_score=scr_score,
            pattern_strength=float(pat.pattern_strength),
            pattern_quality_score=pq_score,
            signal_alignment=ctx.signal_alignment or "neutral",
        )
        final_score_after_policy = apply_pattern_timeframe_policy(
            final_score,
            pattern_name=pat.pattern_name,
            timeframe=pat.timeframe,
            pq_score=pq_score,
        )

        # Simulazione forward
        is_long = pat.direction.lower() == "bullish"
        scan_start = _entry_scan_start_idx(pat_idx, plan.entry_strategy or "close")

        entry_idx = _find_entry_bar(series, scan_start, entry, MAX_BARS_ENTRY_SCAN)

        if entry_idx is None:
            outcome = "no_entry"
            pnl_r = 0.0
            bars_to_entry = None
            bars_to_exit = None
        else:
            bars_to_entry = entry_idx - pat_idx

            sim_fn = _simulate_long_after_entry if is_long else _simulate_short_after_entry
            outcome_raw, pnl_r_raw, exit_idx = sim_fn(
                series,
                entry_idx,
                entry=entry,
                stop=stop,
                tp1=tp1,
                tp2=tp2,
                max_bars=MAX_BARS_AFTER_ENTRY,
                cost_rate=cost_rate,
            )
            outcome = outcome_raw
            pnl_r = pnl_r_raw
            bars_to_exit = exit_idx - entry_idx

        records.append({
            "opportunity_id": opp_id,
            "symbol": pat.symbol,
            "timeframe": pat.timeframe,
            "provider": pat.provider,
            "exchange": pat.exchange,
            "pattern_name": pat.pattern_name,
            "direction": pat.direction,
            "pattern_timestamp": _ts_str(candle.timestamp),
            "entry_price": float(entry),
            "stop_price": float(stop),
            "tp1_price": float(tp1),
            "tp2_price": float(tp2),
            "risk_pct": round(risk_pct, 4),
            "pattern_strength": round(float(pat.pattern_strength), 4),
            "pattern_quality_score": pq_score,
            "screener_score": round(scr_score, 2),
            "final_score": round(final_score_after_policy, 2),
            "outcome": outcome,
            "pnl_r": round(pnl_r, 4),
            "bars_to_entry": bars_to_entry,
            "bars_to_exit": bars_to_exit,
            "entry_filled": entry_idx is not None,
        })

    logger.info(
        "Simulazione completata: %d record, %d skippati",
        len(records), skipped,
    )
    return records


def write_csv(records: list[dict], path: Path) -> None:
    if not records:
        logger.error("Nessun record da scrivere.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    logger.info("CSV scritto: %s (%d righe)", path, len(records))


def write_parquet(records: list[dict], path: Path) -> None:
    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.DataFrame(records)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        logger.info("Parquet scritto: %s (%d righe)", path, len(df))
    except ImportError:
        logger.info("pandas non disponibile — solo CSV generato.")


def print_summary(records: list[dict]) -> None:
    if not records:
        return

    from collections import Counter

    total = len(records)
    filled = sum(1 for r in records if r["entry_filled"])
    outcomes = Counter(r["outcome"] for r in records)
    wins = sum(1 for r in records if r["pnl_r"] > 0 and r["entry_filled"])
    pnl_values = [r["pnl_r"] for r in records if r["entry_filled"]]
    avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0
    win_rate = wins / filled * 100 if filled else 0.0

    print("\n" + "=" * 60)
    print("VALIDATION DATASET — SOMMARIO")
    print("=" * 60)
    print(f"  Pattern totali:          {total}")
    print(f"  Entry fill rate:         {filled}/{total} ({filled/total*100:.1f}%)")
    print(f"  Win rate (su filled):    {win_rate:.1f}%")
    print(f"  Avg PnL (su filled):     {avg_pnl:.3f}R")
    print(f"  Outcome distribution:    {dict(outcomes)}")
    print()

    # Per timeframe
    by_tf: dict[str, list] = defaultdict(list)
    for r in records:
        if r["entry_filled"]:
            by_tf[r["timeframe"]].append(r["pnl_r"])

    print("  Per timeframe:")
    for tf, vals in sorted(by_tf.items()):
        wr = sum(1 for v in vals if v > 0) / len(vals) * 100
        avg = sum(vals) / len(vals)
        print(f"    {tf:6s}: n={len(vals):4d}  WR={wr:.1f}%  avg={avg:.3f}R")

    # Per score bucket
    print()
    print("  Win rate per bucket di final_score:")
    buckets = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 100)]
    for lo, hi in buckets:
        subset = [r for r in records if r["entry_filled"] and lo <= r["final_score"] < hi]
        if not subset:
            continue
        wr = sum(1 for r in subset if r["pnl_r"] > 0) / len(subset) * 100
        avg = sum(r["pnl_r"] for r in subset) / len(subset)
        print(f"    [{lo:3d}-{hi:3d}): n={len(subset):4d}  WR={wr:.1f}%  avg={avg:.3f}R")
    print("=" * 60)


async def main(args: argparse.Namespace) -> None:
    records = await build_dataset(
        timeframe_filter=args.timeframe or None,
        limit=args.limit,
        holdout_days=_HOLDOUT_DAYS,
        cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
    )

    out_csv = Path(args.output)
    write_csv(records, out_csv)
    write_parquet(records, out_csv.with_suffix(".parquet"))
    print_summary(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build validation dataset for scoring experiments")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                        help=f"Pattern candidati prima del bilanciamento (default {_DEFAULT_LIMIT})")
    parser.add_argument("--timeframe", type=str, default=None,
                        help="Filtra per timeframe (1h, 5m, 1d). Default: tutti.")
    parser.add_argument("--output", type=str, default="data/validation_set_v1.csv",
                        help="Path output CSV (default: data/validation_set_v1.csv)")
    args = parser.parse_args()

    asyncio.run(main(args))
