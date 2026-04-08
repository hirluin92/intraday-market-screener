"""
Out-of-sample validation: split train/test per data di cutoff.
Train = dati fino al giorno prima del cutoff; test = dal giorno di cutoff in poi (UTC).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.backtest import (
    OOSSetMetrics,
    OOSTestSetMetrics,
    OOSValidationResponse,
)
from app.services.backtest_simulation import run_backtest_simulation
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf

OOSVerdict = Literal["robusto", "degradazione_moderata", "possibile_overfitting"]


def _split_cutoff_utc(cutoff_date: str) -> tuple[datetime | None, datetime]:
    """
    cutoff_date YYYY-MM-DD: primo istante del test (inizio giorno UTC) e ultimo istante del train.
    """
    raw = cutoff_date.strip()[:10]
    d = date.fromisoformat(raw)
    test_start = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)
    prev = d - timedelta(days=1)
    train_end = datetime(
        prev.year,
        prev.month,
        prev.day,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    )
    return train_end, test_start


async def run_oos_validation(
    session: AsyncSession,
    *,
    provider: str,
    timeframe: str,
    pattern_names: list[str],
    cutoff_date: str,
    initial_capital: float,
    risk_per_trade_pct: float,
    cost_rate: float,
    max_simultaneous: int,
    include_trades: bool,
    use_regime_filter: bool = False,
    exclude_hours: list[int] | None = None,
    include_hours: list[int] | None = None,
    track_capital: bool = True,
    use_temporal_quality: bool = True,
    min_confluence_patterns: int = 1,
) -> OOSValidationResponse:
    train_end, test_start = _split_cutoff_utc(cutoff_date)

    # Quality lookup solo su pattern ≤ train_end — stesse "regole" per train e test (no leakage).
    train_quality_lookup = await pattern_quality_lookup_by_name_tf(
        session,
        symbol=None,
        exchange=None,
        provider=provider,
        asset_type=None,
        timeframe=timeframe,
        dt_to=train_end,
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
        dt_from=None,
        dt_to=train_end,
        use_regime_filter=use_regime_filter,
        exclude_hours=exclude_hours,
        include_hours=include_hours,
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
        include_trades=include_trades,
        dt_from=test_start,
        dt_to=None,
        use_regime_filter=use_regime_filter,
        exclude_hours=exclude_hours,
        include_hours=include_hours,
        quality_lookup_override=train_quality_lookup,
        track_capital=track_capital,
        use_temporal_quality=use_temporal_quality,
        min_confluence_patterns=min_confluence_patterns,
    )

    train_exp = train_result.expectancy_r
    test_exp = test_result.expectancy_r
    if train_exp is not None and abs(train_exp) > 1e-12:
        degradation_pct = (train_exp - (test_exp or 0.0)) / abs(train_exp) * 100.0
    else:
        degradation_pct = 0.0

    if degradation_pct < 20:
        verdict: OOSVerdict = "robusto"
    elif degradation_pct < 50:
        verdict = "degradazione_moderata"
    else:
        verdict = "possibile_overfitting"

    train_period_end = train_end.date().isoformat()

    train_set = OOSSetMetrics(
        period=f"inizio → {train_period_end}",
        total_trades=train_result.total_trades,
        total_return_pct=train_result.total_return_pct,
        win_rate=train_result.win_rate,
        expectancy_r=train_result.expectancy_r,
        max_drawdown_pct=train_result.max_drawdown_pct,
        sharpe_ratio=train_result.sharpe_ratio,
        profit_factor=train_result.profit_factor,
    )

    test_set = OOSTestSetMetrics(
        period=f"{cutoff_date.strip()[:10]} → oggi",
        total_trades=test_result.total_trades,
        total_return_pct=test_result.total_return_pct,
        win_rate=test_result.win_rate,
        expectancy_r=test_result.expectancy_r,
        max_drawdown_pct=test_result.max_drawdown_pct,
        sharpe_ratio=test_result.sharpe_ratio,
        profit_factor=test_result.profit_factor,
        equity_curve=test_result.equity_curve,
        trades=test_result.trades or [],
    )

    note_oos = (
        "Test set simulato con quality lookup calcolato solo su dati pre-cutoff "
        "(stesso dizionario del train; nessun leakage da pattern futuri)."
    )
    if track_capital:
        note_oos += (
            " Simulazione train/test con track_capital=true (capitale impegnato fino all'uscita, "
            "PnL alla chiusura)."
        )
    else:
        note_oos += (
            " Simulazione con track_capital=false (comportamento storico: PnL alla barra del segnale)."
        )

    return OOSValidationResponse(
        cutoff_date=cutoff_date.strip()[:10],
        train_set=train_set,
        test_set=test_set,
        performance_degradation_pct=round(degradation_pct, 2),
        oos_verdict=verdict,
        pattern_names_used=test_result.pattern_names_used,
        leakage_prevented=True,
        train_quality_lookup_size=len(train_quality_lookup),
        note_oos=note_oos,
        track_capital=track_capital,
    )
