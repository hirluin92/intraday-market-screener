"""
Simulazione equity deterministica: trade plan reale (stesso motore di GET /backtest/trade-plans).

- Raggruppamento per timestamp (barra): più segnali sulla stessa barra condividono il rischio
  totale ``risk_per_trade_pct%`` del capitale (diviso tra i fill della barra), max N simultanei
  (``max_simultaneous``), scelti per ``pattern_strength`` decrescente se in eccesso.
- Compounding tra barre: stesso capitale iniziale di barra per tutti i fill della barra.
- R da ``compute_trade_plan_pnl_from_pattern_row`` (costi già in R).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import MAX_SIMULTANEOUS_TRADES
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import (
    BacktestSimulationResponse,
    PatternBacktestAggregateRow,
    SimulationEquityPoint,
    SimulationTradeRow,
)
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_quality import (
    binomial_test_vs_50pct,
    significance_label,
    ttest_expectancy_vs_zero,
)
from app.services.regime_filter_service import load_regime_filter
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    MAX_BARS_ENTRY_SCAN,
    compute_trade_plan_pnl_from_pattern_row,
)

logger = logging.getLogger(__name__)

PATTERN_ROWS_CAP = 50_000

EQUITY_FLOOR = 1.0


def _utc_wall(ts: datetime) -> datetime:
    """Clock UTC coerente per confronti su timestamp naive/aware."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# Durata barra in secondi (cooldown anti-overlap per serie).
_TIMEFRAME_TO_SECONDS: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1800.0,
    "1h": 3600.0,
    "4h": 14400.0,
    "1d": 86400.0,
}


def _seconds_per_bar(timeframe: str) -> float | None:
    return _TIMEFRAME_TO_SECONDS.get((timeframe or "").strip().lower())


def _elapsed_bars_between(
    earlier: datetime,
    later: datetime,
    timeframe: str,
) -> float | None:
    """Barre tra due timestamp; None se TF non mappato (cooldown disattivato per quel TF)."""
    sec = _seconds_per_bar(timeframe)
    if sec is None or sec <= 0:
        return None
    a = _utc_wall(earlier)
    b = _utc_wall(later)
    return (b - a).total_seconds() / sec


def _bar_hours_utc_for_filter(
    ts: datetime,
    *,
    provider: str,
    timeframe: str,
) -> frozenset[int]:
    """
    Ore UTC 0–23 associate alla barra per exclude/include.

    Per Yahoo 1h il timestamp in DB è l'open della barra (tipicamente …:30 UTC dopo
    conversione NY→UTC): l'ora «solare» di chiusura è open+1h (es. 20:30→21:30 → 21).
    Senza includere anche l'ora di fine, exclude_hours=21 non matcha mai (nessun open
    a EXTRACT(hour)=21 nel DB) anche con centinaia di pattern nella finestra che tocca le 21 UTC.
    Altri timeframe Yahoo: solo l'ora UTC dell'istante timestamp. Binance: insieme vuoto (nessun filtro).
    """
    if provider == "binance":
        return frozenset()
    t = _utc_wall(ts)
    if provider == "yahoo_finance" and timeframe == "1h":
        close_t = t + timedelta(hours=1)
        return frozenset({t.hour, close_t.hour})
    return frozenset({t.hour})


def _max_drawdown_from_curve(
    initial: float,
    points: list[SimulationEquityPoint],
) -> float:
    peak = initial
    max_dd = 0.0
    for pt in points:
        peak = max(peak, pt.equity)
        if peak <= 0:
            continue
        dd = (peak - pt.equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _pattern_strength_float(pat: CandlePattern) -> float:
    try:
        return float(pat.pattern_strength)
    except (TypeError, ValueError):
        return 0.0


def _pattern_strength_sort_key(pat: CandlePattern) -> tuple[float, int]:
    """Ordinamento decrescente per forza pattern, poi id stabile."""
    s = _pattern_strength_float(pat)
    return (-s, -pat.id)


def _normalize_pattern_direction(direction: str | None) -> str:
    """Allinea a bullish/bearish per confronto con il regime (SPY 1d o BTC/USDT 1d)."""
    d = (direction or "").strip().lower()
    if d in ("bearish", "short", "sell", "bear"):
        return "bearish"
    return "bullish"


def _map_engine_outcome_to_row(
    engine_outcome: str,
) -> Literal["win", "loss", "flat"]:
    if engine_outcome in ("tp1", "tp2"):
        return "win"
    if engine_outcome == "stop":
        return "loss"
    return "flat"


async def _distinct_pattern_names(
    session: AsyncSession,
    *,
    provider: str,
    timeframe: str,
    symbol: str | None,
    exchange: str | None,
    asset_type: str | None,
) -> list[str]:
    stmt = select(CandlePattern.pattern_name).where(
        CandlePattern.provider == provider,
        CandlePattern.timeframe == timeframe,
    )
    if exchange is not None:
        stmt = stmt.where(CandlePattern.exchange == exchange)
    if symbol is not None:
        stmt = stmt.where(CandlePattern.symbol == symbol)
    if asset_type is not None:
        stmt = stmt.where(CandlePattern.asset_type == asset_type)
    stmt = stmt.distinct().order_by(CandlePattern.pattern_name.asc())
    r = await session.execute(stmt)
    return [row[0] for row in r.all()]


async def run_simulation(
    session: AsyncSession,
    *,
    provider: str,
    timeframe: str,
    pattern_names: list[str],
    initial_capital: float,
    risk_per_trade_pct: float,
    cost_rate: float,
    symbol: str | None = None,
    exchange: str | None = None,
    asset_type: str | None = None,
    pattern_row_limit: int = PATTERN_ROWS_CAP,
    seed: int = 42,
    include_trades: bool = False,
    max_simultaneous: int = MAX_SIMULTANEOUS_TRADES,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
    use_regime_filter: bool = False,
    exclude_hours: list[int] | None = None,
    include_hours: list[int] | None = None,
    exclude_symbols: list[str] | None = None,
    include_symbols: list[str] | None = None,
    quality_lookup_override: dict[tuple[str, str], PatternBacktestAggregateRow]
    | None = None,
    cooldown_bars: int = 0,
    min_strength: float | None = None,
) -> BacktestSimulationResponse:
    _ = seed  # compat API: simulazione deterministica, seed ignorato

    # Crypto 24/7: nessun filtro orario. Yahoo: nessun default implicito; solo
    # parametri espliciti applicano filtri.
    if provider == "binance":
        _exclude: set[int] = set()
        _include: set[int] = set()
    else:
        _exclude = set(exclude_hours) if exclude_hours is not None else set()
        _include = set(include_hours) if include_hours is not None else set()

    _sym_ex = {
        s.strip()
        for s in (exclude_symbols or [])
        if isinstance(s, str) and s.strip()
    }
    _sym_in = {
        s.strip()
        for s in (include_symbols or [])
        if isinstance(s, str) and s.strip()
    }

    if initial_capital <= 0:
        raise ValueError("initial_capital deve essere > 0")
    if not (0 < risk_per_trade_pct <= 100):
        raise ValueError("risk_per_trade_pct deve essere in (0, 100]")
    if not (0 <= cost_rate <= 0.05):
        raise ValueError("cost_rate deve essere in [0, 0.05]")
    if not (1 <= max_simultaneous <= 10):
        raise ValueError("max_simultaneous deve essere in [1, 10]")
    if not (0 <= cooldown_bars <= 20):
        raise ValueError("cooldown_bars deve essere in [0, 20]")
    if min_strength is not None and not (0.0 <= min_strength <= 1.0):
        raise ValueError("min_strength deve essere in [0, 1] o None")

    names_filter = [n.strip() for n in pattern_names if n and n.strip()]
    if not names_filter:
        names_filter = await _distinct_pattern_names(
            session,
            provider=provider,
            timeframe=timeframe,
            symbol=symbol,
            exchange=exchange,
            asset_type=asset_type,
        )

    forward_meta = (MAX_BARS_ENTRY_SCAN, MAX_BARS_AFTER_ENTRY)
    empty_metrics = dict(
        avg_simultaneous_trades=0.0,
        max_simultaneous_observed=0,
        bars_with_trades=0,
        trades_skipped_by_regime=0,
        regime_filter_active=False,
        cooldown_bars_used=cooldown_bars,
        trades_skipped_by_cooldown=0,
    )

    if not names_filter:
        return BacktestSimulationResponse(
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            skipped_trades=0,
            win_rate=0.0,
            sharpe_ratio=None,
            equity_curve=[
                SimulationEquityPoint(
                    timestamp=datetime.now(timezone.utc),
                    equity=initial_capital,
                )
            ],
            pattern_names_used=[],
            forward_horizons_used=forward_meta,
            note="Nessun pattern_name nel DB per i filtri; nessun trade simulato.",
            expectancy_r=None,
            win_rate_pvalue=None,
            win_rate_significance=None,
            expectancy_pvalue=None,
            expectancy_significance=None,
            profit_factor=None,
            **empty_metrics,
        )

    stmt = (
        select(CandlePattern, Candle, CandleContext)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
        .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
        .where(
            CandlePattern.provider == provider,
            CandlePattern.timeframe == timeframe,
            CandlePattern.pattern_name.in_(names_filter),
        )
    )
    if exchange is not None:
        stmt = stmt.where(CandlePattern.exchange == exchange)
    if symbol is not None:
        stmt = stmt.where(CandlePattern.symbol == symbol)
    if asset_type is not None:
        stmt = stmt.where(CandlePattern.asset_type == asset_type)
    if dt_from is not None:
        stmt = stmt.where(CandlePattern.timestamp >= dt_from)
    if dt_to is not None:
        stmt = stmt.where(CandlePattern.timestamp <= dt_to)

    stmt = stmt.order_by(CandlePattern.timestamp.asc(), CandlePattern.id.asc()).limit(
        min(pattern_row_limit, PATTERN_ROWS_CAP),
    )

    result = await session.execute(stmt)
    rows = list(result.all())

    if min_strength is not None and min_strength > 0:
        rows = [r for r in rows if _pattern_strength_float(r[0]) >= min_strength]

    if not rows:
        return BacktestSimulationResponse(
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            skipped_trades=0,
            win_rate=0.0,
            sharpe_ratio=None,
            equity_curve=[
                SimulationEquityPoint(
                    timestamp=datetime.now(timezone.utc),
                    equity=initial_capital,
                )
            ],
            pattern_names_used=names_filter,
            forward_horizons_used=forward_meta,
            note="Nessuna riga pattern+candle_context per i filtri selezionati.",
            expectancy_r=None,
            win_rate_pvalue=None,
            win_rate_significance=None,
            expectancy_pvalue=None,
            expectancy_significance=None,
            profit_factor=None,
            **empty_metrics,
        )

    if quality_lookup_override is not None:
        pq_lookup = quality_lookup_override
    else:
        pq_lookup = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
        )

    regime_filter = None
    regime_filter_active = False
    # Filtro regime solo Yahoo (SPY 1d). Binance: use_regime_filter ignorato — edge indipendente da BTC.
    if use_regime_filter and (provider or "").strip().lower() == "yahoo_finance":
        regime_filter = await load_regime_filter(
            session,
            dt_from=dt_from,
            dt_to=dt_to,
            provider="yahoo_finance",
        )
        regime_filter_active = bool(
            regime_filter is not None and regime_filter.has_data,
        )

    series_keys: set[tuple[str, str, str]] = set()
    for p, _, _ in rows:
        series_keys.add((p.exchange, p.symbol, p.timeframe))

    or_parts = [
        and_(Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf)
        for ex, sym, tf in series_keys
    ]
    c_stmt = select(Candle).where(or_(*or_parts)).order_by(
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.timestamp.asc(),
    )
    c_result = await session.execute(c_stmt)
    all_candles = list(c_result.scalars().all())

    by_series: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
    for c in all_candles:
        by_series[(c.exchange, c.symbol, c.timeframe)].append(c)

    id_to_index: dict[tuple[str, str, str], dict[int, int]] = {}
    for key, clist in by_series.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    equity = float(initial_capital)
    curve: list[SimulationEquityPoint] = []
    wins = 0
    total_trades = 0
    skipped = 0
    per_trade_returns: list[float] = []
    per_trade_pnl_r: list[float] = []
    trade_rows: list[SimulationTradeRow] = []

    sum_pnl_r = 0.0
    sum_pos_r = 0.0
    sum_neg_r_abs = 0.0

    sum_trades_per_bar = 0
    max_sim_obs = 0
    bars_with_trades = 0
    trades_skipped_by_regime = 0
    trades_skipped_by_cooldown = 0
    hour_skip_counts: dict[int, int] = defaultdict(int)
    hour_filter_logged_once = False

    last_entry_bar: dict[tuple[str, str, str], datetime] = {}

    # rows: Row (CandlePattern, Candle, CandleContext). groupby sulla chiave di barra
    # (CandlePattern.timestamp — verificato identico a Candle.timestamp nel DB).
    for _ts_key, group_iter in groupby(rows, key=lambda r: r[0].timestamp):
        group_rows = list(group_iter)
        group_rows.sort(key=lambda r: _pattern_strength_sort_key(r[0]))
        series_used_this_bar: set[tuple[str, str, str]] = set()
        candidates: list[tuple[CandlePattern, Candle, CandleContext, float, str]] = []

        ts_bar = (
            _ts_key
            if isinstance(_ts_key, datetime)
            else datetime.fromisoformat(str(_ts_key))
        )
        hours_set = _bar_hours_utc_for_filter(
            ts_bar,
            provider=provider,
            timeframe=timeframe,
        )
        if not hour_filter_logged_once:
            hour_filter_logged_once = True
            logger.info(
                "Filtro orario: exclude=%s include=%s | primo _ts_key=%s "
                "hours_set(UTC)=%s tzinfo=%s",
                sorted(_exclude) if _exclude else [],
                sorted(_include) if _include else [],
                ts_bar,
                sorted(hours_set),
                ts_bar.tzinfo,
            )

        skip_bar = False
        if _include:
            if not (hours_set & _include):
                skip_bar = True
        elif _exclude and (hours_set & _exclude):
            skip_bar = True
        if skip_bar:
            n_skip = len(group_rows)
            skipped += n_skip
            if _exclude and (hit := hours_set & _exclude):
                hour_skip_counts[min(hit)] += n_skip
            elif _include:
                hour_skip_counts[min(hours_set)] += n_skip
            continue

        allowed_dirs: frozenset[str] = frozenset({"bullish", "bearish"})
        if regime_filter is not None:
            allowed_dirs = regime_filter.get_allowed_directions(ts_bar)

        for pat, candle, ctx in group_rows:
            series_key = (pat.symbol, pat.timeframe, pat.provider)
            if cooldown_bars > 0:
                if series_key in series_used_this_bar:
                    trades_skipped_by_cooldown += 1
                    skipped += 1
                    continue
                le_ts = last_entry_bar.get(series_key)
                if le_ts is not None:
                    elapsed_b = _elapsed_bars_between(le_ts, ts_bar, pat.timeframe)
                    if elapsed_b is not None and elapsed_b < float(cooldown_bars):
                        trades_skipped_by_cooldown += 1
                        skipped += 1
                        continue

            pdir = _normalize_pattern_direction(pat.direction)
            if pdir not in allowed_dirs:
                trades_skipped_by_regime += 1
                skipped += 1
                continue

            if _sym_ex and pat.symbol in _sym_ex:
                skipped += 1
                continue
            if _sym_in and pat.symbol not in _sym_in:
                skipped += 1
                continue

            key_s = (pat.exchange, pat.symbol, pat.timeframe)
            clist = by_series.get(key_s)
            idx_map = id_to_index.get(key_s)
            if not clist or not idx_map:
                skipped += 1
                continue
            idx = idx_map.get(candle.id)
            if idx is None:
                skipped += 1
                continue

            tp_result = compute_trade_plan_pnl_from_pattern_row(
                pat,
                candle,
                ctx,
                clist,
                idx,
                pq_lookup,
                cost_rate,
            )
            if tp_result is None:
                skipped += 1
                continue

            pnl_r, engine_outcome = tp_result
            candidates.append((pat, candle, ctx, pnl_r, engine_outcome))
            series_used_this_bar.add(series_key)

        if not candidates:
            continue

        if len(candidates) > max_simultaneous:
            dropped = candidates[max_simultaneous:]
            candidates = candidates[:max_simultaneous]
            skipped += len(dropped)

        n = len(candidates)
        equity_before_bar = equity
        if equity_before_bar <= EQUITY_FLOOR:
            skipped += n
            continue

        risk_per_single_pct = risk_per_trade_pct / float(n)
        bar_pnl = 0.0
        ts_point: datetime | None = None
        fills: list[tuple[CandlePattern, float, float, float, datetime, Literal["win", "loss", "flat"]]] = []

        for pat, _candle, _ctx, pnl_r, engine_outcome in candidates:
            risk_amount = equity_before_bar * (risk_per_single_pct / 100.0)
            net = risk_amount * pnl_r
            bar_pnl += net

            if engine_outcome in ("tp1", "tp2"):
                wins += 1
            total_trades += 1
            sum_pnl_r += pnl_r
            per_trade_pnl_r.append(pnl_r)
            if pnl_r > 0:
                sum_pos_r += pnl_r
            elif pnl_r < 0:
                sum_neg_r_abs += abs(pnl_r)
            per_trade_returns.append(
                net / equity_before_bar if equity_before_bar > 0 else 0.0,
            )

            ts = pat.timestamp
            ts_point = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            row_outcome = _map_engine_outcome_to_row(engine_outcome)
            pnl_r_net = net / risk_amount if risk_amount > 1e-18 else 0.0
            fills.append((pat, pnl_r, risk_amount, net, ts_point, row_outcome))

        if fills and ts_point is not None:
            for pat, _, _, _, _, _ in fills:
                sk = (pat.symbol, pat.timeframe, pat.provider)
                last_entry_bar[sk] = ts_point

        equity = equity_before_bar + bar_pnl
        equity = max(equity, EQUITY_FLOOR)

        if ts_point is not None:
            curve.append(SimulationEquityPoint(timestamp=ts_point, equity=equity))
            bars_with_trades += 1
            sum_trades_per_bar += n
            if n > max_sim_obs:
                max_sim_obs = n

        if include_trades:
            for pat, pnl_r, risk_amount, net, ts_pt, row_outcome in fills:
                pnl_r_net = net / risk_amount if risk_amount > 1e-18 else 0.0
                strength = _pattern_strength_float(pat)
                trade_rows.append(
                    SimulationTradeRow(
                        timestamp=ts_pt,
                        symbol=pat.symbol,
                        pattern_name=pat.pattern_name,
                        direction=pat.direction,
                        strength=strength,
                        horizon_bars=MAX_BARS_AFTER_ENTRY,
                        signed_return_pct=0.0,
                        pnl_r=pnl_r,
                        pnl_r_net=pnl_r_net,
                        outcome=row_outcome,
                        capital_after=equity,
                    )
                )

    if hour_skip_counts and provider != "binance":
        logger.info(
            "Simulation hour filter: trade saltati per ora UTC (conteggio pattern)=%s total=%d",
            dict(sorted(hour_skip_counts.items())),
            sum(hour_skip_counts.values()),
        )

    if not curve:
        return BacktestSimulationResponse(
            initial_capital=initial_capital,
            final_capital=float(initial_capital),
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            skipped_trades=skipped,
            win_rate=0.0,
            sharpe_ratio=None,
            equity_curve=[
                SimulationEquityPoint(
                    timestamp=rows[0][0].timestamp,
                    equity=float(initial_capital),
                )
            ],
            pattern_names_used=names_filter,
            forward_horizons_used=forward_meta,
            note="Nessun trade plan simulabile per i pattern selezionati.",
            expectancy_r=None,
            win_rate_pvalue=None,
            win_rate_significance=None,
            expectancy_pvalue=None,
            expectancy_significance=None,
            profit_factor=None,
            avg_simultaneous_trades=0.0,
            max_simultaneous_observed=0,
            bars_with_trades=0,
            trades_skipped_by_regime=trades_skipped_by_regime,
            regime_filter_active=regime_filter_active,
            cooldown_bars_used=cooldown_bars,
            trades_skipped_by_cooldown=trades_skipped_by_cooldown,
        )

    curve.insert(
        0,
        SimulationEquityPoint(timestamp=curve[0].timestamp, equity=float(initial_capital)),
    )

    max_dd_pct = _max_drawdown_from_curve(float(initial_capital), curve)

    total_ret_pct = (equity / float(initial_capital) - 1.0) * 100.0
    win_rate_pct = (wins / total_trades * 100.0) if total_trades else 0.0

    sharpe: float | None = None
    if len(per_trade_returns) > 1:
        mret = sum(per_trade_returns) / len(per_trade_returns)
        var = sum((x - mret) ** 2 for x in per_trade_returns) / (len(per_trade_returns) - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        if sd > 1e-12:
            sharpe = mret / sd

    avg_sim = (sum_trades_per_bar / bars_with_trades) if bars_with_trades else 0.0

    expectancy_r: float | None = (
        (sum_pnl_r / total_trades) if total_trades else None
    )
    profit_factor: float | None = (
        (sum_pos_r / sum_neg_r_abs) if sum_neg_r_abs > 1e-12 else None
    )

    note = (
        f"Simulazione trade plan per barra (timestamp): rischio totale {risk_per_trade_pct:g}% equity per barra, "
        f"diviso tra i fill (max {max_simultaneous} per pattern_strength); compounding tra barre. "
        f"Stesso motore di GET /backtest/trade-plans."
    )
    if cooldown_bars > 0:
        note += (
            f" Cooldown {cooldown_bars} barre per serie: "
            f"{trades_skipped_by_cooldown} segnali esclusi (anti-overlap)."
        )
    if regime_filter_active:
        note += (
            " Filtro direzione SPY (1d, EMA50 ±2%): segnali esclusi per direzione: "
            f"{trades_skipped_by_regime}."
        )
    elif use_regime_filter and (provider or "").strip().lower() == "binance":
        note += (
            " use_regime_filter=true ignorato per Binance (filtro regime non applicato alle crypto)."
        )

    wr_pvalue: float | None = None
    wr_sig: str | None = None
    exp_pvalue: float | None = None
    exp_sig: str | None = None
    if total_trades > 0:
        wr_pvalue = binomial_test_vs_50pct(wins, total_trades)
        wr_sig = significance_label(wr_pvalue)
    if len(per_trade_pnl_r) >= 2:
        _, exp_pvalue = ttest_expectancy_vs_zero(per_trade_pnl_r)
        exp_sig = significance_label(exp_pvalue)

    return BacktestSimulationResponse(
        initial_capital=float(initial_capital),
        final_capital=equity,
        total_return_pct=total_ret_pct,
        max_drawdown_pct=max_dd_pct,
        total_trades=total_trades,
        skipped_trades=skipped,
        win_rate=win_rate_pct,
        sharpe_ratio=sharpe,
        equity_curve=curve,
        pattern_names_used=names_filter,
        forward_horizons_used=forward_meta,
        trades=trade_rows,
        avg_simultaneous_trades=round(avg_sim, 4),
        max_simultaneous_observed=max_sim_obs,
        bars_with_trades=bars_with_trades,
        expectancy_r=expectancy_r,
        win_rate_pvalue=wr_pvalue,
        win_rate_significance=wr_sig,
        expectancy_pvalue=exp_pvalue,
        expectancy_significance=exp_sig,
        profit_factor=profit_factor,
        trades_skipped_by_regime=trades_skipped_by_regime,
        regime_filter_active=regime_filter_active,
        cooldown_bars_used=cooldown_bars,
        trades_skipped_by_cooldown=trades_skipped_by_cooldown,
        note=note,
    )


run_backtest_simulation = run_simulation
