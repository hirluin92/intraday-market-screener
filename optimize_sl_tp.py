#!/usr/bin/env python3
"""
MAE/MFE Analysis + Grid Search Walk-Forward per ottimizzazione SL/TP per-pattern.

Metodo utilizzato dai quant professionisti:
  MAE (Maximum Adverse Excursion): quanto il prezzo va CONTRO di te prima della chiusura.
      → indica il SL ottimale (metti lo stop dove il 90-95% dei trade vincenti non arriva mai)
  MFE (Maximum Favorable Excursion): quanto il prezzo va A FAVORE prima della chiusura.
      → indica il TP ottimale (metti il TP dove il 40-60% dei trade arriva)

Pipeline:
  1. Fetch pattern + candele successive dal DB
  2. Per ogni trade: calcola MAE/MFE bar-by-bar (in multipli di R)
  3. Analisi distribuzione MAE/MFE per pattern
  4. Grid search: testa combinazioni SL_MULT × TP1_R × TP2_R
  5. Walk-forward: train 60% / val 20% / test 20% cronologico
  6. Output: tabella raccomandazioni per-pattern

Eseguire da root repo (PowerShell):
  $env:PYTHONPATH="c:\\Lavoro\\Trading\\intraday-market-screener\\backend"
  $env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/intraday_market_screener"
  python optimize_sl_tp.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import and_, select
from tqdm import tqdm

from app.db.session import AsyncSessionLocal
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_indicator import CandleIndicator
from app.models.candle_pattern import CandlePattern
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    MAX_BARS_ENTRY_SCAN,
    _d,
    _entry_scan_start_idx,
    _find_entry_bar,
    build_trade_plan_v1_for_stored_pattern,
)
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf

# ---------------------------------------------------------------------------
# Parametri analisi
# ---------------------------------------------------------------------------

# Pattern da analizzare — solo quelli con campione sufficiente
TARGET_PATTERNS: list[str] = [
    "compression_to_expansion_transition",
    "rsi_momentum_continuation",
    "double_bottom",
    "double_top",
    "macd_divergence_bull",
    "rsi_divergence_bull",
    "rsi_divergence_bear",
    "macd_divergence_bear",
    "engulfing_bullish",
]

# Grid search: moltiplicatori sul buffer SL calcolato dall'engine
SL_MULTS: list[float] = [0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5]

# Grid search: livelli TP in multipli di R
TP1_OPTIONS: list[float] = [1.0, 1.2, 1.5, 1.8, 2.0]
TP2_OPTIONS: list[float] = [1.8, 2.0, 2.5, 3.0, 3.5]

COST_RATE = 0.0015  # 0.15% round-trip (commissioni + slippage)
MIN_SAMPLES_FOR_ANALYSIS = 50  # Minimo per considerare affidabile il risultato

# ---------------------------------------------------------------------------

Outcome = Literal["stop", "tp1", "tp2", "timeout"]


@dataclass
class TradeRecord:
    pattern_name: str
    direction: str
    timestamp: datetime
    entry: float
    risk_r: float        # distanza assoluta entry-stop (R)
    mae_r: float         # Maximum Adverse Excursion in R multipli
    mfe_r: float         # Maximum Favorable Excursion in R multipli
    outcome_base: Outcome
    pnl_base_r: float    # P&L con parametri base (engine default)


@dataclass
class GridResult:
    sl_mult: float
    tp1_r: float
    tp2_r: float
    n_trades: int
    n_executed: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    ev_r: float          # Expected Value in R
    profit_factor: float


def _d_safe(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _compute_mae_mfe_long(
    candles: list[Candle],
    entry_idx: int,
    entry: Decimal,
    risk: Decimal,
    max_bars: int,
) -> tuple[float, float]:
    """
    Calcola MAE e MFE in multipli di R per un trade LONG.
    MAE: quanto è sceso al massimo (avversità max)
    MFE: quanto è salito al massimo (favorevole max)
    """
    if risk <= 0:
        return 0.0, 0.0
    mae = Decimal("0")
    mfe = Decimal("0")
    end = min(entry_idx + max_bars, len(candles))
    for k in range(entry_idx, end):
        c = candles[k]
        lo = _d_safe(c.low)
        hi = _d_safe(c.high)
        adverse = entry - lo
        favorable = hi - entry
        if adverse > mae:
            mae = adverse
        if favorable > mfe:
            mfe = favorable
    return float(mae / risk), float(mfe / risk)


def _compute_mae_mfe_short(
    candles: list[Candle],
    entry_idx: int,
    entry: Decimal,
    risk: Decimal,
    max_bars: int,
) -> tuple[float, float]:
    """Calcola MAE e MFE in multipli di R per un trade SHORT."""
    if risk <= 0:
        return 0.0, 0.0
    mae = Decimal("0")
    mfe = Decimal("0")
    end = min(entry_idx + max_bars, len(candles))
    for k in range(entry_idx, end):
        c = candles[k]
        lo = _d_safe(c.low)
        hi = _d_safe(c.high)
        adverse = hi - entry
        favorable = entry - lo
        if adverse > mae:
            mae = adverse
        if favorable > mfe:
            mfe = favorable
    return float(mae / risk), float(mfe / risk)


def _simulate_with_custom_params(
    candles: list[Candle],
    entry_idx: int,
    direction: str,
    entry: Decimal,
    original_stop: Decimal,
    sl_mult: float,
    tp1_r: float,
    tp2_r: float,
    entry_strategy: str,
    cost_rate: float,
) -> tuple[Outcome, float]:
    """
    Simula il trade con SL/TP personalizzati.
    SL: original_buffer * sl_mult
    TP1/TP2: entry ± risk * tp1_r/tp2_r
    """
    if direction == "long":
        original_risk = entry - original_stop
        if original_risk <= 0:
            return "stop", -(1.0 + cost_rate)
        new_risk = original_risk * Decimal(str(sl_mult))
        new_stop = entry - new_risk
        tp1 = entry + new_risk * Decimal(str(tp1_r))
        tp2 = entry + new_risk * Decimal(str(tp2_r))
        cr = float(cost_rate) * float(entry / new_risk) if new_risk > 0 else 0
        scan_from = _entry_scan_start_idx(entry_idx, entry_strategy)
        actual_entry_bar = _find_entry_bar(candles, scan_from, entry, MAX_BARS_ENTRY_SCAN)
        if actual_entry_bar is None:
            return "stop", -(1.0 + cr)
        end = min(actual_entry_bar + MAX_BARS_AFTER_ENTRY, len(candles))
        for k in range(actual_entry_bar, end):
            c = candles[k]
            lo, hi = _d_safe(c.low), _d_safe(c.high)
            if lo <= new_stop:
                return "stop", -(1.0 + cr)
            if hi >= tp1:
                return "tp1", float((tp1 - entry) / new_risk) - cr
            if hi >= tp2:
                return "tp2", float((tp2 - entry) / new_risk) - cr
        return "timeout", -cr
    else:  # short
        original_risk = original_stop - entry
        if original_risk <= 0:
            return "stop", -(1.0 + cost_rate)
        new_risk = original_risk * Decimal(str(sl_mult))
        new_stop = entry + new_risk
        tp1 = entry - new_risk * Decimal(str(tp1_r))
        tp2 = entry - new_risk * Decimal(str(tp2_r))
        cr = float(cost_rate) * float(entry / new_risk) if new_risk > 0 else 0
        scan_from = _entry_scan_start_idx(entry_idx, entry_strategy)
        actual_entry_bar = _find_entry_bar(candles, scan_from, entry, MAX_BARS_ENTRY_SCAN)
        if actual_entry_bar is None:
            return "stop", -(1.0 + cr)
        end = min(actual_entry_bar + MAX_BARS_AFTER_ENTRY, len(candles))
        for k in range(actual_entry_bar, end):
            c = candles[k]
            lo, hi = _d_safe(c.low), _d_safe(c.high)
            if hi >= new_stop:
                return "stop", -(1.0 + cr)
            if lo <= tp1:
                return "tp1", float((entry - tp1) / new_risk) - cr
            if lo <= tp2:
                return "tp2", float((entry - tp2) / new_risk) - cr
        return "timeout", -cr


def _grid_search(records: list[TradeRecord], candles_map: dict) -> list[GridResult]:
    """
    Testa ogni combinazione SL_MULT × TP1_R × TP2_R sui record forniti.
    Usa i dati MAE/MFE già calcolati per velocità (senza re-fetch DB).
    
    Strategia veloce: usa MAE/MFE per simulare senza ri-accedere alle candele.
    - Il trade viene stoppato se MAE > sl_mult * 1.0R (cioè il prezzo ha toccato il nuovo SL)
    - Il trade raggiunge TP1 se MFE >= tp1_r
    - Il trade raggiunge TP2 se MFE >= tp2_r
    
    Questo è un'approssimazione conservativa (non considera l'ordine temporale MAE vs MFE
    nella stessa candela), ma è statisticamente stabile su campioni grandi.
    """
    results = []
    for sl_mult in SL_MULTS:
        for tp1_r in TP1_OPTIONS:
            for tp2_r in TP2_OPTIONS:
                if tp2_r <= tp1_r:
                    continue
                n_exec = 0
                wins = []
                losses = []
                for rec in records:
                    n_exec += 1
                    cr = COST_RATE * (1.0 / sl_mult) if sl_mult > 0 else COST_RATE
                    # Se MAE ha superato il nuovo SL → stop
                    if rec.mae_r >= sl_mult:
                        losses.append(-(sl_mult + cr))
                    # TP2 raggiunto (priorità se non stoppato)
                    elif rec.mfe_r >= tp2_r:
                        wins.append(tp2_r - cr)
                    # TP1 raggiunto
                    elif rec.mfe_r >= tp1_r:
                        wins.append(tp1_r - cr)
                    # Timeout (timeout piccola perdita / pareggio)
                    else:
                        # Timeout: uscita al prezzo finale ≈ 0 (stima conservativa)
                        losses.append(-cr)

                if n_exec < MIN_SAMPLES_FOR_ANALYSIS:
                    continue
                n_wins = len(wins)
                n_loss = len(losses)
                wr = n_wins / n_exec if n_exec > 0 else 0
                avg_win = sum(wins) / n_wins if n_wins > 0 else 0
                avg_loss = sum(losses) / n_loss if n_loss > 0 else 0
                ev = wr * avg_win + (1 - wr) * avg_loss
                gross_win = sum(wins) if wins else 0
                gross_loss = abs(sum(losses)) if losses else 1e-9
                pf = gross_win / gross_loss if gross_loss > 0 else 0

                results.append(GridResult(
                    sl_mult=sl_mult,
                    tp1_r=tp1_r,
                    tp2_r=tp2_r,
                    n_trades=len(records),
                    n_executed=n_exec,
                    win_rate=wr,
                    avg_win_r=avg_win,
                    avg_loss_r=avg_loss,
                    ev_r=ev,
                    profit_factor=pf,
                ))
    return sorted(results, key=lambda r: r.ev_r, reverse=True)


def _print_mae_mfe_summary(pattern_name: str, records: list[TradeRecord]) -> None:
    """Stampa statistiche descrittive MAE/MFE."""
    import statistics

    maes = [r.mae_r for r in records]
    mfes = [r.mfe_r for r in records]
    wins = [r for r in records if r.pnl_base_r > 0]
    losses = [r for r in records if r.pnl_base_r <= 0]

    print(f"\n{'─'*60}")
    print(f"  {pattern_name}  (n={len(records)}, vincenti={len(wins)}, perdenti={len(losses)})")
    print(f"{'─'*60}")

    if maes:
        mae_sorted = sorted(maes)
        p50 = mae_sorted[int(0.50 * len(mae_sorted))]
        p75 = mae_sorted[int(0.75 * len(mae_sorted))]
        p90 = mae_sorted[int(0.90 * len(mae_sorted))]
        p95 = mae_sorted[int(0.95 * len(mae_sorted))]
        print(f"  MAE (avversità max in R): p50={p50:.2f}R  p75={p75:.2f}R  p90={p90:.2f}R  p95={p95:.2f}R")
        if wins:
            mae_wins = sorted([r.mae_r for r in wins])
            pw90 = mae_wins[int(0.90 * len(mae_wins))]
            pw95 = mae_wins[int(0.95 * len(mae_wins))]
            print(f"  MAE sui VINCENTI:        p90={pw90:.2f}R  p95={pw95:.2f}R  → stop ideale > {pw95:.2f}R")

    if mfes:
        mfe_sorted = sorted(mfes)
        p40 = mfe_sorted[int(0.40 * len(mfe_sorted))]
        p50 = mfe_sorted[int(0.50 * len(mfe_sorted))]
        p60 = mfe_sorted[int(0.60 * len(mfe_sorted))]
        p75 = mfe_sorted[int(0.75 * len(mfe_sorted))]
        print(f"  MFE (favorevole max in R): p40={p40:.2f}R  p50={p50:.2f}R  p60={p60:.2f}R  p75={p75:.2f}R")
        print(f"  → TP1 ideale ≈ {p50:.1f}R (50% dei trade ci arriva)")
        print(f"  → TP2 ideale ≈ {p60:.1f}R-{p75:.1f}R (40-25% dei trade ci arriva)")

    # WR e EV con parametri attuali
    wr_base = len(wins) / len(records) if records else 0
    ev_base = sum(r.pnl_base_r for r in records) / len(records) if records else 0
    print(f"  Parametri ATTUALI:  WR={wr_base:.1%}  EV={ev_base:+.3f}R")


def _walk_forward_best(
    records: list[TradeRecord],
    top_k: int = 5,
) -> dict:
    """
    Walk-forward 60/20/20.
    Trova i top_k parametri su TRAIN, verifica su VAL, riporta TEST.
    """
    n = len(records)
    if n < MIN_SAMPLES_FOR_ANALYSIS * 3:
        return {"error": f"Campione troppo piccolo per walk-forward (n={n}, serve {MIN_SAMPLES_FOR_ANALYSIS*3}+)"}

    # Ordina per timestamp (già ordinati, ma per sicurezza)
    recs_sorted = sorted(records, key=lambda r: r.timestamp)
    train_end = int(n * 0.60)
    val_end = int(n * 0.80)

    train = recs_sorted[:train_end]
    val = recs_sorted[train_end:val_end]
    test = recs_sorted[val_end:]

    # Grid search su TRAIN
    train_results = _grid_search(train, {})
    if not train_results:
        return {"error": "Nessun risultato dal grid search su TRAIN"}

    top_train = train_results[:top_k]

    # Valida su VAL — prendi il migliore che tiene
    best_val: GridResult | None = None
    best_val_ev = -999.0
    for candidate in top_train:
        val_results = _grid_search(val, {})
        # Cerca la stessa combinazione nel val
        match = next(
            (r for r in val_results
             if r.sl_mult == candidate.sl_mult
             and r.tp1_r == candidate.tp1_r
             and r.tp2_r == candidate.tp2_r),
            None,
        )
        if match and match.ev_r > best_val_ev:
            best_val_ev = match.ev_r
            best_val = candidate

    if best_val is None:
        best_val = top_train[0]

    # Valuta su TEST
    test_results = _grid_search(test, {})
    test_match = next(
        (r for r in test_results
         if r.sl_mult == best_val.sl_mult
         and r.tp1_r == best_val.tp1_r
         and r.tp2_r == best_val.tp2_r),
        None,
    )

    # Baseline su TEST (parametri attuali: sl_mult=1.0, tp1=1.5, tp2=2.5)
    baseline_test = next(
        (r for r in test_results
         if r.sl_mult == 1.0
         and r.tp1_r == 1.5
         and r.tp2_r == 2.5),
        None,
    )

    return {
        "best_params": {
            "sl_mult": best_val.sl_mult,
            "tp1_r": best_val.tp1_r,
            "tp2_r": best_val.tp2_r,
        },
        "train": {"ev_r": best_val.ev_r, "wr": best_val.win_rate, "n": best_val.n_executed},
        "val": {"ev_r": best_val_ev},
        "test": {
            "ev_r": test_match.ev_r if test_match else None,
            "wr": test_match.win_rate if test_match else None,
            "n": test_match.n_executed if test_match else None,
        },
        "test_baseline": {
            "ev_r": baseline_test.ev_r if baseline_test else None,
            "wr": baseline_test.win_rate if baseline_test else None,
        },
        "n_total": n,
        "n_train": len(train),
        "n_val": len(val),
        "n_test": len(test),
    }


async def _fetch_patterns_and_candles(
    session,
    pattern_names: list[str],
    min_strength: float = 0.70,
    symbols: list[str] | None = None,
) -> dict[str, list[tuple[CandlePattern, list[Candle], str]]]:
    """
    Fetch pattern + candele forward per ogni pattern.
    Ritorna dict: pattern_name → [(pattern, candles_after, entry_strategy)]
    """
    conditions = [
        CandlePattern.pattern_name.in_(pattern_names),
        CandlePattern.pattern_strength >= Decimal(str(min_strength)),
        CandlePattern.timeframe == "1h",
        CandlePattern.provider == "yahoo_finance",
    ]
    if symbols:
        conditions.append(CandlePattern.symbol.in_(symbols))

    stmt = (
        select(CandlePattern)
        .where(and_(*conditions))
        .order_by(CandlePattern.symbol, CandlePattern.timestamp)
    )
    result = await session.execute(stmt)
    patterns: list[CandlePattern] = list(result.scalars().all())

    print(f"  Trovati {len(patterns)} pattern totali per {len(pattern_names)} tipi")

    # Raggruppa per (symbol, timeframe) per fetch candele efficienti
    by_series: dict[tuple[str, str], list[CandlePattern]] = defaultdict(list)
    for p in patterns:
        by_series[(p.symbol, p.timeframe)].append(p)

    # Fetch candles per serie (una query per serie)
    series_candles: dict[tuple[str, str], list[Candle]] = {}
    for (sym, tf), pats in tqdm(by_series.items(), desc="  Fetch candele per serie", leave=False):
        ts_min = min(p.timestamp for p in pats)
        stmt_c = (
            select(Candle)
            .where(
                and_(
                    Candle.symbol == sym,
                    Candle.timeframe == tf,
                    Candle.timestamp >= ts_min,
                )
            )
            .order_by(Candle.timestamp)
        )
        res_c = await session.execute(stmt_c)
        series_candles[(sym, tf)] = list(res_c.scalars().all())

    # Relazioni: CandlePattern → candle_feature_id → CandleFeature → candle_id → CandleIndicator
    #            CandlePattern → candle_context_id → CandleContext
    feat_ids = list({p.candle_feature_id for p in patterns})
    ctx_ids = list({p.candle_context_id for p in patterns if p.candle_context_id is not None})

    # Batch helper: evita il limite di 32767 parametri in .in_()
    async def _fetch_in_batches(model, col_attr, ids, batch=5000):
        result_map = {}
        for i in range(0, len(ids), batch):
            chunk = ids[i: i + batch]
            res = await session.execute(select(model).where(col_attr.in_(chunk)))
            for row in res.scalars().all():
                result_map[getattr(row, col_attr.key)] = row
        return result_map

    # Fetch features (per volume_ratio e candle_id)
    feat_by_id: dict[int, CandleFeature] = await _fetch_in_batches(
        CandleFeature, CandleFeature.id, feat_ids
    )

    # Fetch contexts (market_regime, volatility_regime, candle_expansion)
    ctx_by_id: dict[int, CandleContext] = await _fetch_in_batches(
        CandleContext, CandleContext.id, ctx_ids
    )

    # Fetch indicators tramite candle_id delle features
    candle_ids = list({f.candle_id for f in feat_by_id.values()})
    ind_by_candle_id: dict[int, CandleIndicator] = await _fetch_in_batches(
        CandleIndicator, CandleIndicator.candle_id, candle_ids
    )

    # Costruisci mappe per-pattern_id
    ctx_map: dict[int, CandleContext] = {}
    feat_map: dict[int, CandleFeature] = {}
    ind_map: dict[int, CandleIndicator] = {}
    for p in patterns:
        feat = feat_by_id.get(p.candle_feature_id)
        if feat:
            feat_map[p.id] = feat
            ind = ind_by_candle_id.get(feat.candle_id)
            if ind:
                ind_map[p.id] = ind
        if p.candle_context_id:
            ctx = ctx_by_id.get(p.candle_context_id)
            if ctx:
                ctx_map[p.id] = ctx

    # Costruisci risultati per pattern
    output: dict[str, list[tuple[CandlePattern, list[Candle], str, str]]] = defaultdict(list)
    for p in patterns:
        candles_all = series_candles.get((p.symbol, p.timeframe), [])
        # Trova indice del pattern nella serie
        pat_idx = next(
            (i for i, c in enumerate(candles_all) if c.timestamp >= p.timestamp),
            None,
        )
        if pat_idx is None:
            continue
        # Candele dal pattern in poi (incluso il bar del pattern stesso)
        candles_forward = candles_all[pat_idx: pat_idx + MAX_BARS_ENTRY_SCAN + MAX_BARS_AFTER_ENTRY + 5]
        if len(candles_forward) < 3:
            continue

        ctx = ctx_map.get(p.id)
        feat = feat_map.get(p.id)
        ind = ind_map.get(p.id)
        direction = (p.direction or "bullish").strip().lower()

        output[p.pattern_name].append((p, candles_forward, direction, ctx, feat, ind))

    return dict(output)


def _build_trade_records(
    pattern_name: str,
    items: list[tuple],
    pq_lookup: dict,
) -> list[TradeRecord]:
    """
    Costruisce i TradeRecord con MAE/MFE per ogni trade.
    Usa build_trade_plan_v1_for_stored_pattern (identica a produzione).
    """
    records: list[TradeRecord] = []

    for (pat, candles, direction, ctx, feat, ind) in items:
        candle_bar = candles[0] if candles else None
        if candle_bar is None:
            continue

        # Contesto sintetico di fallback se non disponibile nel DB
        if ctx is None:
            from app.models.candle_context import CandleContext as _CC
            ctx_obj = object.__new__(_CC)
            ctx_obj.__dict__.update({
                "exchange": pat.exchange,
                "symbol": pat.symbol,
                "timeframe": pat.timeframe,
                "timestamp": pat.timestamp,
                "market_regime": "trend",
                "volatility_regime": "normal",
                "candle_expansion": "normal",
                "direction_bias": direction,
            })
            ctx = ctx_obj

        plan = build_trade_plan_v1_for_stored_pattern(pat, candle_bar, ctx, pq_lookup)

        if plan.trade_direction not in ("long", "short"):
            continue
        if plan.entry_price is None or plan.stop_loss is None:
            continue

        entry = _d(plan.entry_price)
        stop = _d(plan.stop_loss)
        entry_strat = plan.entry_strategy or "close"

        scan_from = _entry_scan_start_idx(0, entry_strat)
        actual_entry_bar = _find_entry_bar(candles, scan_from, entry, MAX_BARS_ENTRY_SCAN)
        if actual_entry_bar is None:
            continue

        if plan.trade_direction == "long":
            risk = entry - stop
            if risk <= 0:
                continue
            mae_r, mfe_r = _compute_mae_mfe_long(candles, actual_entry_bar, entry, risk, MAX_BARS_AFTER_ENTRY)
        else:
            risk = stop - entry
            if risk <= 0:
                continue
            mae_r, mfe_r = _compute_mae_mfe_short(candles, actual_entry_bar, entry, risk, MAX_BARS_AFTER_ENTRY)

        # P&L con parametri engine attuali (SL×1.0, TP1=1.5R, TP2=2.5R)
        cr = float(COST_RATE) * float(entry / risk) if risk > 0 else 0.0
        outcome: Outcome
        if mae_r >= 1.0:
            outcome, pnl = "stop", -(1.0 + cr)
        elif mfe_r >= 2.5:
            outcome, pnl = "tp2", 2.5 - cr
        elif mfe_r >= 1.5:
            outcome, pnl = "tp1", 1.5 - cr
        else:
            outcome, pnl = "timeout", -cr

        ts = pat.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        records.append(TradeRecord(
            pattern_name=pattern_name,
            direction=plan.trade_direction,
            timestamp=ts,
            entry=float(entry),
            risk_r=float(risk),
            mae_r=mae_r,
            mfe_r=mfe_r,
            outcome_base=outcome,
            pnl_base_r=pnl,
        ))

    return records


async def main(args) -> None:
    print("\n" + "="*70)
    print("  MAE/MFE ANALYSIS + SL/TP GRID SEARCH WALK-FORWARD")
    print("="*70)
    print(f"  Pattern analizzati: {len(TARGET_PATTERNS)}")
    print(f"  Grid: {len(SL_MULTS)} SL × {len(TP1_OPTIONS)} TP1 × {len(TP2_OPTIONS)} TP2 = "
          f"{len(SL_MULTS)*len(TP1_OPTIONS)*len(TP2_OPTIONS)} combinazioni per pattern")
    print(f"  Walk-forward: 60% TRAIN / 20% VAL / 20% TEST (cronologico)\n")

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    async with AsyncSessionLocal() as session:
        print("Fetch pattern e candele dal DB...")
        data = await _fetch_patterns_and_candles(
            session,
            TARGET_PATTERNS,
            min_strength=args.min_strength,
            symbols=symbols,
        )
        print("Carico pattern quality lookup...")
        pq_lookup = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=None,
            exchange=None,
            provider="yahoo_finance",
            timeframe="1h",
        )

    # ---------------------------------------------------------------------------
    # Analisi per pattern
    # ---------------------------------------------------------------------------
    recommendations: dict[str, dict] = {}

    for pn in TARGET_PATTERNS:
        items = data.get(pn, [])
        if not items:
            print(f"\n  {pn}: nessun dato nel DB, skip.")
            continue

        print(f"\nAnalisi {pn} ({len(items)} segnali)...")
        records = _build_trade_records(pn, items, pq_lookup)

        if len(records) < MIN_SAMPLES_FOR_ANALYSIS:
            print(f"  Campione insufficiente: {len(records)} < {MIN_SAMPLES_FOR_ANALYSIS}, skip.")
            continue

        # MAE/MFE summary
        _print_mae_mfe_summary(pn, records)

        # Walk-forward
        print(f"\n  Walk-forward grid search (n={len(records)})...")
        wf = _walk_forward_best(records)

        if "error" in wf:
            print(f"  {wf['error']}")
            # Mostra solo il grid search completo senza walk-forward
            all_results = _grid_search(records, {})
            if all_results:
                best = all_results[0]
                print(f"  Best (no WF): SL×{best.sl_mult}  TP1={best.tp1_r}R  TP2={best.tp2_r}R  "
                      f"EV={best.ev_r:+.3f}R  WR={best.win_rate:.1%}")
            continue

        bp = wf["best_params"]
        print(f"\n  ┌─ RISULTATO WALK-FORWARD ─────────────────────────────────┐")
        print(f"  │  Parametri ottimali: SL×{bp['sl_mult']}  TP1={bp['tp1_r']}R  TP2={bp['tp2_r']}R")
        print(f"  │  TRAIN (n={wf['n_train']}):  EV={wf['train']['ev_r']:+.3f}R  WR={wf['train']['wr']:.1%}")
        print(f"  │  VAL:                  EV={wf['val']['ev_r']:+.3f}R")
        if wf['test']['ev_r'] is not None:
            print(f"  │  TEST  (n={wf['n_test']}):  EV={wf['test']['ev_r']:+.3f}R  WR={wf['test']['wr']:.1%}")
            if wf['test_baseline']['ev_r'] is not None:
                delta = wf['test']['ev_r'] - wf['test_baseline']['ev_r']
                sign = "+" if delta >= 0 else ""
                print(f"  │  vs BASELINE (1.0×SL 1.5R/2.5R): {sign}{delta:+.3f}R per trade")
        consistent = (
            wf['train']['ev_r'] > 0 and
            wf['val']['ev_r'] > 0 and
            (wf['test']['ev_r'] or 0) > 0
        )
        verdict = "✅ ROBUSTO — parametri stabili su tutti i blocchi" if consistent else "⚠️  INSTABILE — non adottare (overfitting)"
        print(f"  │  Verdetto: {verdict}")
        print(f"  └──────────────────────────────────────────────────────────┘")

        recommendations[pn] = {
            "sl_mult": bp["sl_mult"],
            "tp1_r": bp["tp1_r"],
            "tp2_r": bp["tp2_r"],
            "robust": consistent,
            "ev_test": wf["test"]["ev_r"],
            "wr_test": wf["test"]["wr"],
            "ev_baseline_test": wf["test_baseline"]["ev_r"],
            "n": len(records),
        }

    # ---------------------------------------------------------------------------
    # Riepilogo finale
    # ---------------------------------------------------------------------------
    print("\n\n" + "="*70)
    print("  RIEPILOGO RACCOMANDAZIONI PER-PATTERN")
    print("="*70)
    print(f"  {'Pattern':<42} {'SL×':>5} {'TP1':>5} {'TP2':>5} {'EV test':>9} {'WR test':>8} {'Note'}")
    print(f"  {'-'*42} {'-'*5} {'-'*5} {'-'*5} {'-'*9} {'-'*8} {'-'*20}")

    robust_patterns = {}
    for pn, rec in sorted(recommendations.items(), key=lambda x: (not x[1]["robust"], -(x[1]["ev_test"] or 0))):
        ev = rec["ev_test"]
        wr = rec["wr_test"]
        note = "✅ adotta" if rec["robust"] else "⚠️  skip"
        ev_str = f"{ev:+.3f}R" if ev is not None else "  n/a "
        wr_str = f"{wr:.1%}" if wr is not None else "  n/a "
        print(f"  {pn:<42} {rec['sl_mult']:>5.2f} {rec['tp1_r']:>5.1f} {rec['tp2_r']:>5.1f} {ev_str:>9} {wr_str:>8}  {note}")
        if rec["robust"]:
            robust_patterns[pn] = rec

    if robust_patterns:
        print(f"\n\n  CONFIGURAZIONE PER trade_plan_engine.py (copia-incolla):")
        print(f"  ─────────────────────────────────────────────────────────")
        print(f"  PATTERN_SL_TP_CONFIG: dict[str, tuple[float, float, float]] = {{")
        print(f"      # (sl_mult, tp1_r, tp2_r) — ottimizzati con MAE/MFE walk-forward")
        for pn, rec in robust_patterns.items():
            ev_str = f"{rec['ev_test']:+.3f}R" if rec['ev_test'] else "n/a"
            print(f"      \"{pn}\": ({rec['sl_mult']}, {rec['tp1_r']}, {rec['tp2_r']}),  # EV test={ev_str} WR={rec['wr_test']:.1%}")
        print(f"  }}")
        print(f"\n  Se vuoi aggiornare l'engine, riesegui con --apply per applicare automaticamente.")

    print()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MAE/MFE SL/TP Optimizer")
    p.add_argument("--min-strength", type=float, default=0.70,
                   help="Filtro pattern_strength minimo (default 0.70)")
    p.add_argument("--symbols", type=str, default=None,
                   help="Lista simboli separati da virgola (default: universo v4.2)")
    p.add_argument("--apply", action="store_true",
                   help="Applica automaticamente i parametri robusti all'engine (non implementato — output solo testuale)")
    return p.parse_args()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    args = _parse_args()
    asyncio.run(main(args))
