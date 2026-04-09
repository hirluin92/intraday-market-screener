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
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
    compute_signal_alignment,
    final_opportunity_label_from_score,
)
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_quality import pattern_quality_label_from_score
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    MAX_BARS_ENTRY_SCAN,
    TradePlanExecutionResult,
    build_trade_plan_v1_for_stored_pattern,
    compute_trade_plan_execution_from_pattern_row,
    _entry_scan_start_idx,
    _find_entry_bar,
)

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


async def _load_series_candles(
    session: AsyncSession,
    patterns: list[tuple[CandlePattern, Candle, CandleContext]],
) -> dict[tuple[str, str, str, str], list[Candle]]:
    """
    Per ogni serie (provider, exchange, symbol, timeframe), carica le candele
    da [min_ts - buffer] a [max_ts + forward_window].

    Lo stesso approccio di run_trade_plan_backtest ma con chiave a 4 colonne
    (include provider dopo il fix A3).
    """
    oldest: dict[tuple[str, str, str, str], datetime] = {}
    newest: dict[tuple[str, str, str, str], datetime] = {}

    for _, candle, _ in patterns:
        key = (candle.provider, candle.exchange, candle.symbol, candle.timeframe)
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if key not in oldest or ts < oldest[key]:
            oldest[key] = ts
        if key not in newest or ts > newest[key]:
            newest[key] = ts

    if not oldest:
        return {}

    all_candles: dict[tuple[str, str, str, str], list[Candle]] = {}

    for key in oldest:
        prov, exch, sym, tf = key
        since = oldest[key] - timedelta(days=2)
        # forward: MAX_BARS_ENTRY_SCAN + MAX_BARS_AFTER_ENTRY barre su 1h = ~3 giorni; usiamo 5 per sicurezza
        until = newest[key] + timedelta(days=5)

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
        all_candles[key] = list(result.scalars().all())

    return all_candles


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

        # Carica candele per serie (include buffer backward + forward window)
        logger.info("Caricamento candele per serie…")
        forward_candles = await _load_series_candles(session, balanced)
        logger.info(
            "Serie caricate: %d, totale candele: %d",
            len(forward_candles),
            sum(len(v) for v in forward_candles.values()),
        )

    # Simulazione (CPU-bound, nessun DB richiesto oltre questo punto)
    records: list[dict] = []
    skipped = 0
    opp_id = 0

    # Pre-build id_to_index per serie — stessa logica di run_trade_plan_backtest
    id_to_index: dict[tuple[str, str, str, str], dict[int, int]] = {}
    for key, clist in forward_candles.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    for pat, candle, ctx in balanced:
        opp_id += 1
        key = (candle.provider, candle.exchange, candle.symbol, candle.timeframe)
        series = forward_candles.get(key, [])
        idx_map = id_to_index.get(key, {})

        # Posizione del candle del pattern nella serie
        pat_idx = idx_map.get(candle.id)
        if pat_idx is None:
            skipped += 1
            continue

        # Pattern quality score dal lookup
        pq_agg = pq_lookup.get((pat.pattern_name, pat.timeframe))
        pq_score: float | None = pq_agg.pattern_quality_score if pq_agg else None

        # Trade plan: usa la funzione già testata in produzione
        try:
            plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)
        except Exception as exc:
            logger.debug("build_trade_plan_v1_for_stored_pattern failed (symbol=%s pattern=%s): %s",
                         pat.symbol, pat.pattern_name, exc)
            skipped += 1
            continue

        # Screener score — stessa pipeline di build_trade_plan_v1_for_stored_pattern
        snap = SnapshotForScoring(
            exchange=ctx.exchange,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            timestamp=ctx.timestamp,
            market_regime=ctx.market_regime or "neutral",
            volatility_regime=ctx.volatility_regime or "normal",
            candle_expansion=ctx.candle_expansion or "normal",
            direction_bias=ctx.direction_bias or "neutral",
        )
        scored = score_snapshot(snap)

        # Final score — identica formula di production
        pq_label = pattern_quality_label_from_score(pq_score)
        base_final = compute_final_opportunity_score(
            screener_score=scored.screener_score,
            score_direction=scored.score_direction,
            latest_pattern_direction=pat.direction,
            pattern_quality_score=pq_score,
            pattern_quality_label=pq_label,
            latest_pattern_strength=pat.pattern_strength,
        )
        final_score_val, _tf_ok, tf_gate, _tf_f = apply_pattern_timeframe_policy(
            has_pattern=True,
            pattern_quality_score=pq_score,
            _pattern_quality_label=pq_label,
            base_final_opportunity_score=base_final,
        )
        signal_alignment = compute_signal_alignment(scored.score_direction, pat.direction)

        # Simulazione forward: riusa compute_trade_plan_execution_from_pattern_row
        exec_result: TradePlanExecutionResult | None = compute_trade_plan_execution_from_pattern_row(
            pat, candle, ctx, series, pat_idx, pq_lookup, cost_rate,
        )

        entry_px = plan.entry_price
        stop_px = plan.stop_loss
        tp1_px = plan.take_profit_1
        tp2_px = plan.take_profit_2

        if entry_px is None or stop_px is None:
            skipped += 1
            continue

        entry = _d(entry_px)
        stop = _d(stop_px)
        tp1 = _d(tp1_px) if tp1_px else entry
        tp2 = _d(tp2_px) if tp2_px else tp1

        risk_pct = abs(float(entry - stop)) / float(entry) * 100.0 if float(entry) > 0 else 0.0

        if exec_result is None:
            outcome = "no_entry"
            pnl_r = 0.0
            bars_to_entry = None
            bars_to_exit = None
            entry_filled = False
        else:
            outcome = exec_result.outcome
            pnl_r = exec_result.pnl_r
            bars_to_entry = exec_result.entry_bar_index - pat_idx
            bars_to_exit = exec_result.exit_bar_index - exec_result.entry_bar_index
            entry_filled = True

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
            "screener_score": scored.screener_score,
            "signal_alignment": signal_alignment,
            "final_score": round(final_score_val, 2),
            "outcome": outcome,
            "pnl_r": round(pnl_r, 4),
            "bars_to_entry": bars_to_entry,
            "bars_to_exit": bars_to_exit,
            "entry_filled": entry_filled,
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


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval 95%. Ritorna (lower%, upper%)."""
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    center = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margin = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / (1 + z**2 / n)
    return round(max(0.0, center - margin) * 100, 1), round(min(1.0, center + margin) * 100, 1)


def _bucket_row(subset: list[dict], label: str) -> str:
    if not subset:
        return f"  {label:14s}: {'—':>5} {'—':>7} {'—':>8} {'—':>14}"
    n = len(subset)
    wins = sum(1 for r in subset if r["pnl_r"] > 0)
    wr = wins / n * 100
    avg = sum(r["pnl_r"] for r in subset) / n
    lo, hi = _wilson_ci(wins, n)
    ci_str = f"[{lo:.1f}%-{hi:.1f}%]"
    return f"  {label:14s}: {n:>5}  {wr:>6.1f}%  {avg:>8.3f}R  {ci_str:>14}"


def print_summary(records: list[dict]) -> None:
    if not records:
        return

    from collections import Counter

    total = len(records)
    filled = [r for r in records if r["entry_filled"]]
    outcomes = Counter(r["outcome"] for r in records)
    wins = sum(1 for r in filled if r["pnl_r"] > 0)
    pnl_values = [r["pnl_r"] for r in filled]
    avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0
    win_rate = wins / len(filled) * 100 if filled else 0.0
    ci_lo, ci_hi = _wilson_ci(wins, len(filled))

    print("\n" + "=" * 72)
    print("VALIDATION DATASET — SOMMARIO")
    print("=" * 72)
    print(f"  Pattern totali:      {total}")
    print(f"  Entry fill rate:     {len(filled)}/{total} ({len(filled)/total*100:.1f}%)")
    print(f"  Win rate globale:    {win_rate:.1f}%  CI 95% [{ci_lo}%-{ci_hi}%]")
    print(f"  Avg PnL globale:     {avg_pnl:.3f}R")
    print(f"  Outcome:             {dict(outcomes)}")

    # ── Per timeframe ──────────────────────────────────────────────────────
    print()
    by_tf: dict[str, list] = defaultdict(list)
    for r in filled:
        by_tf[r["timeframe"]].append(r)
    print(f"  {'Timeframe':14s}  {'n':>5}  {'WR%':>7}  {'AvgR':>8}  {'CI 95%':>14}")
    print("  " + "-" * 55)
    for tf, rows in sorted(by_tf.items()):
        print(_bucket_row(rows, tf))

    # ── Per bucket final_score con CI ─────────────────────────────────────
    print()
    print(f"  {'Score bucket':14s}  {'n':>5}  {'WR%':>7}  {'AvgR':>8}  {'CI 95%':>14}")
    print("  " + "-" * 55)
    for lo, hi in [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 101)]:
        subset = [r for r in filled if lo <= r["final_score"] < hi]
        print(_bucket_row(subset, f"[{lo}-{hi})"))

    # ── Cliff analysis pq a step 5 ────────────────────────────────────────
    print()
    print("  Cliff analysis pattern_quality_score (step 5, solo entry filled)")
    print(f"  {'PQ bucket':14s}  {'n':>5}  {'WR%':>7}  {'AvgR':>8}  {'CI 95%':>14}")
    print("  " + "-" * 55)
    for lo in range(0, 100, 5):
        hi = lo + 5
        subset = [
            r for r in filled
            if r.get("pattern_quality_score") not in (None, "", "None")
            and lo <= float(r["pattern_quality_score"]) < hi
        ]
        marker = " ← cliff?" if lo == 30 else ""
        row = _bucket_row(subset, f"[{lo:2d}-{hi:2d})")
        print(row + marker)

    # ── Correlazione pq → WR (10 bin) ────────────────────────────────────
    print()
    print("  Correlazione pattern_quality_score → WR (bin da 10):")
    pq_rows = [r for r in filled if r.get("pattern_quality_score") not in (None, "", "None")]
    if pq_rows:
        pq_vals = [float(r["pattern_quality_score"]) for r in pq_rows]
        wr_vals = [1.0 if r["pnl_r"] > 0 else 0.0 for r in pq_rows]
        # Pearson r semplice (pq vs outcome binario)
        n_pq = len(pq_vals)
        mean_pq = sum(pq_vals) / n_pq
        mean_wr = sum(wr_vals) / n_pq
        cov = sum((p - mean_pq) * (w - mean_wr) for p, w in zip(pq_vals, wr_vals)) / n_pq
        std_pq = (sum((p - mean_pq) ** 2 for p in pq_vals) / n_pq) ** 0.5
        std_wr = (sum((w - mean_wr) ** 2 for w in wr_vals) / n_pq) ** 0.5
        r = cov / (std_pq * std_wr) if std_pq > 0 and std_wr > 0 else 0.0
        print(f"    Pearson r(pq, win) = {r:.3f}  (n={n_pq})")
        print(f"    Interpretazione: {'segnale forte (|r|>0.15)' if abs(r) > 0.15 else 'segnale debole — pq ha basso potere predittivo'}")

    print("=" * 72)


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
