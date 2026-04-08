"""
Walk-forward validation con N fold.
Divide il dataset cronologicamente in N+1 parti uguali.
Per ogni fold i: train = parti 1..i, test = parte i+1 (no leakage sul quality lookup).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_pattern import CandlePattern
from app.services.backtest_simulation import run_backtest_simulation
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf

FoldVerdict = Literal["robusto", "degradazione_moderata", "possibile_overfitting"]
OverallVerdict = Literal[
    "robusto",
    "prevalentemente_robusto",
    "degradazione_moderata",
    "possibile_overfitting",
]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class WalkForwardFold:
    fold_number: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_trades: int
    test_trades: int
    train_return_pct: float
    test_return_pct: float
    train_win_rate: float
    test_win_rate: float
    train_max_dd: float
    test_max_dd: float
    train_expectancy_r: float | None
    test_expectancy_r: float | None
    degradation_pct: float
    verdict: FoldVerdict


@dataclass
class WalkForwardResult:
    n_folds: int
    folds: list[WalkForwardFold]
    avg_test_return_pct: float
    avg_test_win_rate: float
    avg_degradation_pct: float
    pct_folds_positive: float
    overall_verdict: OverallVerdict
    date_range_start: str
    date_range_end: str
    track_capital: bool


async def run_walk_forward(
    session: AsyncSession,
    *,
    provider: str,
    timeframe: str,
    pattern_names: list[str],
    n_folds: int,
    initial_capital: float,
    risk_per_trade_pct: float,
    cost_rate: float,
    max_simultaneous: int,
    use_regime_filter: bool,
    exclude_hours: list[int] | None = None,
    include_hours: list[int] | None = None,
    exclude_symbols: list[str] | None = None,
    include_symbols: list[str] | None = None,
    track_capital: bool = True,
    use_temporal_quality: bool = True,
    min_confluence_patterns: int = 1,
) -> WalkForwardResult:
    """
    Walk-forward validation con n_folds fold.

    Il timeline [min_ts, max_ts] dei pattern filtrati è diviso in n_folds+1 segmenti
    uguali. Per fold k (0-based): train = segmenti 0..k, test = segmento k+1.
    Il quality lookup è calcolato solo sul train (dt_to = fine train) e riusato sul test.
    """
    conditions: list = []
    if provider:
        conditions.append(CandlePattern.provider == provider)
    if timeframe:
        conditions.append(CandlePattern.timeframe == timeframe)
    if pattern_names:
        conditions.append(CandlePattern.pattern_name.in_(pattern_names))

    where_clause = and_(*conditions) if conditions else True

    stmt_range = select(
        func.min(CandlePattern.timestamp),
        func.max(CandlePattern.timestamp),
    ).where(where_clause)

    result = await session.execute(stmt_range)
    row = result.one()
    date_start_raw, date_end_raw = row[0], row[1]

    if date_start_raw is None or date_end_raw is None:
        raise ValueError("Nessun pattern trovato per i parametri specificati")

    date_start = _ensure_utc(date_start_raw)
    date_end = _ensure_utc(date_end_raw)

    total_seconds = (date_end - date_start).total_seconds()
    if total_seconds <= 0:
        raise ValueError("Range temporale dei pattern non valido")

    n_parts = n_folds + 1
    boundaries: list[datetime] = []
    for i in range(n_parts + 1):
        boundaries.append(
            date_start + timedelta(seconds=total_seconds * i / n_parts),
        )

    folds: list[WalkForwardFold] = []

    for fold_idx in range(n_folds):
        train_cut = boundaries[fold_idx + 1]
        test_start = train_cut
        test_end = boundaries[fold_idx + 2]

        train_end_inclusive = train_cut - timedelta(microseconds=1)
        if train_end_inclusive < date_start:
            train_end_inclusive = date_start

        train_quality_lookup = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=None,
            exchange=None,
            provider=provider,
            asset_type=None,
            timeframe=timeframe,
            dt_from=date_start,
            dt_to=train_end_inclusive,
        )

        train_result = await run_backtest_simulation(
            session,
            provider=provider,
            timeframe=timeframe,
            pattern_names=pattern_names,
            initial_capital=initial_capital,
            risk_per_trade_pct=risk_per_trade_pct,
            cost_rate=cost_rate,
            max_simultaneous=max_simultaneous,
            include_trades=False,
            dt_from=date_start,
            dt_to=train_end_inclusive,
            use_regime_filter=use_regime_filter,
            exclude_hours=exclude_hours,
            include_hours=include_hours,
            exclude_symbols=exclude_symbols,
            include_symbols=include_symbols,
            quality_lookup_override=train_quality_lookup,
            track_capital=track_capital,
            use_temporal_quality=use_temporal_quality,
            min_confluence_patterns=min_confluence_patterns,
        )

        test_result = await run_backtest_simulation(
            session,
            provider=provider,
            timeframe=timeframe,
            pattern_names=pattern_names,
            initial_capital=initial_capital,
            risk_per_trade_pct=risk_per_trade_pct,
            cost_rate=cost_rate,
            max_simultaneous=max_simultaneous,
            include_trades=False,
            dt_from=test_start,
            dt_to=test_end,
            use_regime_filter=use_regime_filter,
            exclude_hours=exclude_hours,
            include_hours=include_hours,
            exclude_symbols=exclude_symbols,
            include_symbols=include_symbols,
            quality_lookup_override=train_quality_lookup,
            track_capital=track_capital,
            use_temporal_quality=use_temporal_quality,
            min_confluence_patterns=min_confluence_patterns,
        )

        train_exp = train_result.expectancy_r
        test_exp = test_result.expectancy_r
        if train_exp is not None and abs(train_exp) > 1e-12:
            degradation = (train_exp - (test_exp or 0.0)) / abs(train_exp) * 100.0
        else:
            degradation = 0.0

        if degradation < 20:
            verdict: FoldVerdict = "robusto"
        elif degradation < 50:
            verdict = "degradazione_moderata"
        else:
            verdict = "possibile_overfitting"

        folds.append(
            WalkForwardFold(
                fold_number=fold_idx + 1,
                train_start=date_start.isoformat(),
                train_end=train_end_inclusive.isoformat(),
                test_start=test_start.isoformat(),
                test_end=test_end.isoformat(),
                train_trades=train_result.total_trades,
                test_trades=test_result.total_trades,
                train_return_pct=train_result.total_return_pct,
                test_return_pct=test_result.total_return_pct,
                train_win_rate=train_result.win_rate,
                test_win_rate=test_result.win_rate,
                train_max_dd=train_result.max_drawdown_pct,
                test_max_dd=test_result.max_drawdown_pct,
                train_expectancy_r=train_exp,
                test_expectancy_r=test_exp,
                degradation_pct=round(degradation, 2),
                verdict=verdict,
            ),
        )

    avg_test_ret = sum(f.test_return_pct for f in folds) / n_folds
    avg_test_wr = sum(f.test_win_rate for f in folds) / n_folds
    avg_deg = sum(f.degradation_pct for f in folds) / n_folds
    pct_positive = sum(1 for f in folds if f.test_return_pct > 0) / n_folds * 100

    robust_count = sum(1 for f in folds if f.verdict == "robusto")
    # Confronto intero: evita il problema floating-point con n_folds * 0.67.
    # Es. n_folds=3: 2/3 fold robusti → 2*3 >= 3*2 → True → "prevalentemente_robusto".
    if robust_count == n_folds:
        overall: OverallVerdict = "robusto"
    elif robust_count * 3 >= n_folds * 2:  # >= 67% dei fold
        overall = "prevalentemente_robusto"
    elif robust_count * 3 >= n_folds:  # >= 33% dei fold
        overall = "degradazione_moderata"
    else:
        overall = "possibile_overfitting"

    return WalkForwardResult(
        n_folds=n_folds,
        folds=folds,
        avg_test_return_pct=round(avg_test_ret, 2),
        avg_test_win_rate=round(avg_test_wr, 2),
        avg_degradation_pct=round(avg_deg, 2),
        pct_folds_positive=round(pct_positive, 1),
        overall_verdict=overall,
        date_range_start=date_start.isoformat(),
        date_range_end=date_end.isoformat(),
        track_capital=track_capital,
    )
