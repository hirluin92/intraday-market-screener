"""
Simulazione equity deterministica: trade plan reale (stesso motore di GET /backtest/trade-plans).

- Raggruppamento per timestamp (barra): più segnali sulla stessa barra condividono il rischio
  totale ``risk_per_trade_pct%`` del capitale (diviso tra i fill della barra), max N simultanei
  (``max_simultaneous``), scelti per ``pattern_strength`` decrescente se in eccesso.
- Compounding tra barre: stesso capitale iniziale di barra per tutti i fill della barra.
- R da ``compute_trade_plan_pnl_from_pattern_row`` (costi già in R).
- Con ``track_capital=true``: capitale rischiato impegnato fino alla barra di uscita simulata;
  PnL realizzato alla chiusura; slot e disponibilità limitano nuovi ingressi.
  In questo modo la **equity_curve** registra solo punti agli **exit_timestamp** (chiusura trade);
  il **max_drawdown** è calcolato su quella stessa sequenza. Con ``track_capital=false`` la curva
  aggiorna l'equity alla barra del **segnale** (PnL immediato come nello storico).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import groupby
from typing import Literal

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    MAX_SIMULTANEOUS_TRADES,
    PATTERNS_BEAR_REGIME_ONLY,
    PATTERNS_BLOCKED,
    PATTERNS_BLOCKED_BY_SCOPE,
)
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import (
    BacktestSimulationResponse,
    DailySessionStats,
    PatternBacktestAggregateRow,
    PatternSimulationAuditRow,
    SimulationEquityPoint,
    SimulationTradeRow,
)
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_quality import (
    binomial_test_vs_50pct,
    significance_label,
    ttest_expectancy_vs_zero,
)
from app.services.regime_filter_service import load_regime_filter, normalize_regime_variant
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    MAX_BARS_ENTRY_SCAN,
    TradePlanExecutionResult,
    compute_trade_plan_execution_from_pattern_row,
    compute_trade_plan_pnl_from_pattern_row,
)

logger = logging.getLogger(__name__)

PATTERN_ROWS_CAP = 50_000
# Con pattern_row_limit<=0 nella simulazione: massimo righe lette (protezione memoria).
SIMULATION_PATTERN_HARD_CAP = 500_000

EQUITY_FLOOR = 1.0


@dataclass
class OpenPosition:
    """Posizione aperta: capitale rischiato impegnato fino a exit_timestamp."""

    symbol: str
    timeframe: str
    provider: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    capital_at_risk: float
    pnl_r: float
    outcome: str


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


def _trade_session_date_utc(t: SimulationTradeRow) -> str:
    """Giorno calendario UTC per sessione (uscita se presente, altrimenti barra segnale)."""
    ts = t.exit_timestamp if t.exit_timestamp is not None else t.timestamp
    if not isinstance(ts, datetime):
        ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return _utc_wall(ts).date().isoformat()


def _compute_daily_stats(trades: list[SimulationTradeRow]) -> DailySessionStats | None:
    """
    Somma R netti per giorno UTC (data di exit_timestamp, o timestamp se uscita assente).
    Peggior/miglior giorno in R; rolling 5 giorni di calendario consecutivi nella serie ordinata.
    """
    if not trades:
        return None

    by_date: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        dk = _trade_session_date_utc(t)
        by_date[dk].append(float(t.pnl_r_net))

    if not by_date:
        return None

    daily_rows: list[tuple[str, float]] = []
    for date in sorted(by_date.keys()):
        daily_rows.append((date, sum(by_date[date])))

    worst = min(daily_rows, key=lambda x: x[1])
    best = max(daily_rows, key=lambda x: x[1])
    positive_days = [d for d in daily_rows if d[1] > 0]
    negative_days = [d for d in daily_rows if d[1] < 0]
    n = len(daily_rows)
    pct_pos = round(len(positive_days) / n * 100, 1) if n else 0.0

    max_rolling_5d_loss = 0.0
    if len(daily_rows) >= 5:
        for i in range(len(daily_rows) - 4):
            window = sum(daily_rows[j][1] for j in range(i, i + 5))
            if window < max_rolling_5d_loss:
                max_rolling_5d_loss = window

    return DailySessionStats(
        n_giorni_trading=n,
        n_giorni_positivi=len(positive_days),
        n_giorni_negativi=len(negative_days),
        pct_giorni_positivi=pct_pos,
        peggior_giorno_r=round(worst[1], 4),
        peggior_giorno_data=worst[0],
        miglior_giorno_r=round(best[1], 4),
        miglior_giorno_data=best[0],
        avg_giorno_r=round(sum(x[1] for x in daily_rows) / n, 4),
        max_perdita_rolling_5d_r=round(max_rolling_5d_loss, 4),
    )


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
    regime_variant: str = "ema50",
    allowed_hours_utc: list[int] | None = None,
    exclude_hours: list[int] | None = None,
    include_hours: list[int] | None = None,
    exclude_symbols: list[str] | None = None,
    include_symbols: list[str] | None = None,
    quality_lookup_override: dict[tuple[str, str], PatternBacktestAggregateRow]
    | None = None,
    cooldown_bars: int = 0,
    min_strength: float | None = None,
    track_capital: bool = True,
    use_temporal_quality: bool = True,
    include_pattern_audit: bool = False,
    pattern_timestamp_order: Literal["asc", "desc"] = "asc",
    min_confluence_patterns: int = 1,
    only_regime: str | None = None,
) -> BacktestSimulationResponse:
    """
    only_regime: se fornito ('bull'|'bear'|'neutral'), esclude le barre in cui il regime SPY
    non corrisponde. Richiede use_regime_filter=True e provider in (yahoo_finance, alpaca).
    Utile per testare l'edge di un pattern in un regime specifico.
    """
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

    _regime_vf = normalize_regime_variant(regime_variant)
    regime_variant_used: str | None = (
        _regime_vf
        if (use_regime_filter and (provider or "").strip().lower() in ("yahoo_finance", "alpaca"))
        else None
    )

    _allowed_hours_resolved: list[int] | None = None
    _allowed_hours_frozen: frozenset[int] | None = None
    if allowed_hours_utc:
        for h in allowed_hours_utc:
            hi = int(h)
            if not (0 <= hi <= 23):
                raise ValueError("allowed_hours_utc: ogni valore deve essere intero in [0, 23]")
        uniq = sorted({int(x) for x in allowed_hours_utc})
        if uniq:
            _allowed_hours_resolved = uniq
            _allowed_hours_frozen = frozenset(uniq)

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
        trades_skipped_by_hour=0,
    )

    pattern_audit_dict: dict[int, PatternSimulationAuditRow] = {}

    def _audit(
        pat: CandlePattern,
        *,
        executed: bool,
        skip_reason: str | None,
        pnl_r_val: float | None,
        open_pos: int,
        cap_pct: float,
    ) -> None:
        if not include_pattern_audit:
            return
        pattern_audit_dict[pat.id] = PatternSimulationAuditRow(
            candle_pattern_id=pat.id,
            executed=executed,
            skip_reason=skip_reason,
            pnl_r=pnl_r_val,
            open_positions_at_signal=open_pos,
            capital_available_pct=cap_pct,
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
            use_temporal_quality=use_temporal_quality,
            quality_lookup_dt_to=None,
            regime_variant_used=regime_variant_used,
            allowed_hours_utc=_allowed_hours_resolved,
            pattern_simulation_audit=[],
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
    if _sym_in:
        stmt = stmt.where(CandlePattern.symbol.in_(_sym_in))
    # min_strength applicato in SQL prima del LIMIT: il LIMIT si applica sull'universo
    # filtrato per strength, non sull'intero DB. Coerente con build_trade_dataset.py.
    if min_strength is not None and min_strength > 0:
        stmt = stmt.where(CandlePattern.pattern_strength >= min_strength)

    if pattern_timestamp_order == "desc":
        stmt = stmt.order_by(CandlePattern.timestamp.desc(), CandlePattern.id.desc())
    else:
        stmt = stmt.order_by(CandlePattern.timestamp.asc(), CandlePattern.id.asc())

    if pattern_row_limit <= 0:
        eff_lim = SIMULATION_PATTERN_HARD_CAP
    else:
        eff_lim = min(pattern_row_limit, SIMULATION_PATTERN_HARD_CAP)
    stmt = stmt.limit(eff_lim)

    result = await session.execute(stmt)
    rows = list(result.all())

    # Sempre cronologico crescente per groupby/compounding (anche se la query usava DESC per
    # selezionare gli ultimi N pattern nel tempo).
    rows.sort(key=lambda r: (_utc_wall(r[0].timestamp), r[0].id))

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
            use_temporal_quality=use_temporal_quality,
            quality_lookup_dt_to=None,
            regime_variant_used=regime_variant_used,
            allowed_hours_utc=_allowed_hours_resolved,
            pattern_simulation_audit=[],
            **empty_metrics,
        )

    quality_lookup_dt_to_str: str | None = None

    # --- Quality lookup temporale -------------------------------------------------
    # Strategia: un bucket per ogni ANNO-MESE presente nei pattern.
    # dt_to del bucket = primo istante del mese (qualita' calcolata con soli pattern
    # PRECEDENTI a quel mese). Numero query = N mesi ~ 12-24 per simulazioni tipiche,
    # molto piu' accurato del singolo min_ts e molto piu' veloce del per-segnale.
    # In questo modo segnali di mesi diversi non condividono la stessa quality lookup.
    #
    # Quando quality_lookup_override e' passato (es. OOS) si usa quello senza toccare
    # nulla — comportamento identico a prima.

    # Dict ym_key -> pq_lookup per il monthly-bucket approach.
    _monthly_pq: dict[str, dict] = {}

    if quality_lookup_override is not None:
        _global_pq = quality_lookup_override
        quality_lookup_dt_to_str = "override"
    elif use_temporal_quality:
        # Estrai i bucket unici anno-mese dai timestamp dei pattern.
        unique_ym: list[str] = sorted({
            _utc_wall(
                r[0].timestamp if isinstance(r[0].timestamp, datetime)
                else datetime.fromisoformat(str(r[0].timestamp))
            ).strftime("%Y-%m")
            for r in rows
        })
        for ym in unique_ym:
            year, month = int(ym[:4]), int(ym[5:7])
            # dt_to esclusivo: quality calcolata con pattern strettamente PRIMA di
            # questo mese (uguale semantica al per-segnale del dataset).
            month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            _monthly_pq[ym] = await pattern_quality_lookup_by_name_tf(
                session,
                symbol=symbol,
                exchange=exchange,
                provider=provider,
                asset_type=asset_type,
                timeframe=timeframe,
                dt_to=month_start,
            )
        quality_lookup_dt_to_str = f"monthly_buckets ({len(unique_ym)} mesi)"
        # Fallback globale (nessun bucket disponibile, non dovrebbe accadere).
        _global_pq = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
        )
        logger.info(
            "Quality lookup temporale (monthly bucket): %d mesi, chiavi primo bucket=%d",
            len(unique_ym),
            len(next(iter(_monthly_pq.values()), {})),
        )
    else:
        _global_pq = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
        )

    def _pq_for_bar(bar_ts: datetime) -> dict:
        """Ritorna il quality lookup corretto per la barra bar_ts."""
        if _monthly_pq:
            ym = _utc_wall(bar_ts).strftime("%Y-%m")
            return _monthly_pq.get(ym, _global_pq)
        return _global_pq

    # Alias per compatibilita' con le parti del codice successive al loop che
    # usano ancora pq_lookup (es. statistiche aggregate post-sim).
    pq_lookup = _global_pq

    # Blocklist provider+timeframe specifica (es. Alpaca 5m) sovrascrive quella globale.
    # Contiene già PATTERNS_BLOCKED unito alla lista specifica del contesto.
    _prov_key = ((provider or "").strip().lower(), (timeframe or "").strip().lower())
    _patterns_blocked_effective = PATTERNS_BLOCKED_BY_SCOPE.get(_prov_key, PATTERNS_BLOCKED)

    regime_filter = None
    regime_filter_active = False
    # Filtro regime SPY 1d: Yahoo (nativo) e Alpaca US stocks (riutilizza dati SPY Yahoo 1d).
    # Binance: ignorato — edge crypto indipendente da SPY.
    _prov_lower = (provider or "").strip().lower()
    if use_regime_filter and _prov_lower in ("yahoo_finance", "alpaca"):
        regime_filter = await load_regime_filter(
            session,
            dt_from=dt_from,
            dt_to=dt_to,
            provider="yahoo_finance",
            variant=_regime_vf,
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
    trades_skipped_by_hour = 0
    hour_skip_counts: dict[int, int] = defaultdict(int)
    hour_filter_logged_once = False

    last_entry_bar: dict[tuple[str, str, str], datetime] = {}

    open_positions: list[OpenPosition] = []
    trades_skipped_by_capital = 0
    max_concurrent_positions_obs = 0
    capital_utilization_samples: list[float] = []

    # rows: Row (CandlePattern, Candle, CandleContext). groupby sulla chiave di barra
    # (CandlePattern.timestamp — verificato identico a Candle.timestamp nel DB).
    for _ts_key, group_iter in groupby(rows, key=lambda r: r[0].timestamp):
        group_rows = list(group_iter)
        group_rows.sort(key=lambda r: _pattern_strength_sort_key(r[0]))
        series_used_this_bar: set[tuple[str, str, str]] = set()
        candidates_legacy: list[tuple[CandlePattern, Candle, CandleContext, float, str]] = []
        candidates_capital: list[tuple[CandlePattern, Candle, CandleContext, TradePlanExecutionResult]] = []

        ts_bar = (
            _ts_key
            if isinstance(_ts_key, datetime)
            else datetime.fromisoformat(str(_ts_key))
        )
        ts_wall = _utc_wall(ts_bar)

        if track_capital:
            # Equity curve: un punto per ogni chiusura, timestamp = uscita (non barra segnale).
            still_open: list[OpenPosition] = []
            for p in open_positions:
                if _utc_wall(p.exit_timestamp) <= ts_wall:
                    net_close = p.capital_at_risk * p.pnl_r
                    equity += net_close
                    equity = max(equity, EQUITY_FLOOR)
                    curve.append(
                        SimulationEquityPoint(timestamp=p.exit_timestamp, equity=equity),
                    )
                else:
                    still_open.append(p)
            open_positions = still_open
            committed_now = sum(p.capital_at_risk for p in open_positions)
            if equity > EQUITY_FLOOR:
                capital_utilization_samples.append(committed_now / equity)
            slots_available = max_simultaneous - len(open_positions)
            max_concurrent_positions_obs = max(max_concurrent_positions_obs, len(open_positions))
            available_for_new = equity - committed_now
        else:
            slots_available = max_simultaneous
            available_for_new = equity

        bar_open_n = len(open_positions)
        bar_cap_pct = (available_for_new / equity * 100.0) if equity > EQUITY_FLOOR else 0.0

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

        # Filtro only_regime: salta le barre dove il regime SPY non corrisponde al target.
        if only_regime and regime_filter is not None:
            _bar_regime = regime_filter.get_regime_label(ts_bar)
            _only_low = only_regime.strip().lower()
            if _only_low in ("bull", "bullish"):
                if _bar_regime not in ("bull", "bullish"):
                    skipped += len(group_rows)
                    trades_skipped_by_regime += len(group_rows)
                    continue
            elif _only_low in ("bear", "bearish"):
                if _bar_regime not in ("bear", "bearish"):
                    skipped += len(group_rows)
                    trades_skipped_by_regime += len(group_rows)
                    continue
            elif _only_low in ("neutral", "sideways"):
                if _bar_regime not in ("neutral", "sideways", "ranging"):
                    skipped += len(group_rows)
                    trades_skipped_by_regime += len(group_rows)
                    continue

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
            if include_pattern_audit:
                for pat, _, _ in group_rows:
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="hour_filter",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            continue

        # Solo ora UTC della barra segnale — non ora di TP/SL né holding intragiornaliero.
        if _allowed_hours_frozen is not None and ts_wall.hour not in _allowed_hours_frozen:
            n_ah = len(group_rows)
            skipped += n_ah
            trades_skipped_by_hour += n_ah
            if include_pattern_audit:
                for pat, _, _ in group_rows:
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="allowed_hours_utc",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            continue

        if track_capital and (
            available_for_new <= EQUITY_FLOOR or slots_available <= 0
        ):
            skipped += len(group_rows)
            trades_skipped_by_capital += len(group_rows)
            if include_pattern_audit:
                for pat, _, _ in group_rows:
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="capital_constraint",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            continue

        # Confluence filter: solo simboli con >= min_confluence_patterns pattern distinti
        # nella stessa barra (conferma multi-segnale). min_confluence_patterns=1 = nessun filtro.
        if min_confluence_patterns > 1:
            sym_pat_count: dict[str, set[str]] = {}
            for p, _, _ in group_rows:
                sym_pat_count.setdefault(p.symbol, set()).add(p.pattern_name)
            group_rows = [
                (p, c, ctx_r)
                for p, c, ctx_r in group_rows
                if len(sym_pat_count.get(p.symbol, set())) >= min_confluence_patterns
            ]
            if not group_rows:
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
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="cooldown",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
                    continue
                le_ts = last_entry_bar.get(series_key)
                if le_ts is not None:
                    elapsed_b = _elapsed_bars_between(le_ts, ts_bar, pat.timeframe)
                    if elapsed_b is not None and elapsed_b < float(cooldown_bars):
                        trades_skipped_by_cooldown += 1
                        skipped += 1
                        _audit(
                            pat,
                            executed=False,
                            skip_reason="cooldown",
                            pnl_r_val=None,
                            open_pos=bar_open_n,
                            cap_pct=bar_cap_pct,
                        )
                        continue

            # ── Filtri per-pattern: stessa logica dell'opportunity_validator live ──

            # Pattern bloccati: usa lista specifica provider+timeframe se disponibile.
            if pat.pattern_name in _patterns_blocked_effective:
                skipped += 1
                _audit(
                    pat,
                    executed=False,
                    skip_reason="pattern_blocked",
                    pnl_r_val=None,
                    open_pos=bar_open_n,
                    cap_pct=bar_cap_pct,
                )
                continue

            # Pattern regime-condizionali: sono counter-trend intenzionali.
            # Bypassano il filtro direzione standard (allowed_dirs) e vengono
            # invece valutati esclusivamente sul label del regime SPY.
            # Es: engulfing_bullish è bullish ma valido SOLO in bear market →
            # il filtro direzione (allowed_dirs=bearish) lo bloccerebbe per errore.
            _regime_label_now = (
                regime_filter.get_regime_label(ts_bar)
                if regime_filter is not None
                else "neutral"
            )

            # PATTERNS_BEAR_REGIME_ONLY: applicare il filtro SOLO se il regime filter è
            # caricato (yahoo_finance o alpaca con use_regime_filter=True). Per binance
            # regime_filter=None → skip non applicato.
            if pat.pattern_name in PATTERNS_BEAR_REGIME_ONLY and regime_filter is not None:
                if _regime_label_now not in ("bear", "bearish"):
                    trades_skipped_by_regime += 1
                    skipped += 1
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="regime_bear_only",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
                    continue
                # Regime bear confermato: il pattern bear-only è attivabile.
                # NON applicare il filtro direzione standard (allowed_dirs):
                # i pattern bear-only sono counter-trend intenzionali (es. engulfing_bullish
                # in bear market), il filtro direzione li bloccherebbe per errore.
            # Pattern universali: edge validato in tutti i regimi → nessun filtro direzione.
            # La designazione «universale» implica che il pattern funziona indipendentemente
            # dal regime SPY (es. double_bottom bullish in bear market = mean reversion valido,
            # macd_divergence_bear short in bull market = divergenza con edge positivo confermato
            # da backtest). Applicare allowed_dirs qui causerebbe falsi blocchi e abbassa EV.

            if _sym_ex and pat.symbol in _sym_ex:
                skipped += 1
                _audit(
                    pat,
                    executed=False,
                    skip_reason="symbol_filter",
                    pnl_r_val=None,
                    open_pos=bar_open_n,
                    cap_pct=bar_cap_pct,
                )
                continue
            if _sym_in and pat.symbol not in _sym_in:
                skipped += 1
                _audit(
                    pat,
                    executed=False,
                    skip_reason="symbol_filter",
                    pnl_r_val=None,
                    open_pos=bar_open_n,
                    cap_pct=bar_cap_pct,
                )
                continue

            key_s = (pat.exchange, pat.symbol, pat.timeframe)
            clist = by_series.get(key_s)
            idx_map = id_to_index.get(key_s)
            if not clist or not idx_map:
                skipped += 1
                _audit(
                    pat,
                    executed=False,
                    skip_reason="no_ohlc_data",
                    pnl_r_val=None,
                    open_pos=bar_open_n,
                    cap_pct=bar_cap_pct,
                )
                continue
            idx = idx_map.get(candle.id)
            if idx is None:
                skipped += 1
                _audit(
                    pat,
                    executed=False,
                    skip_reason="no_ohlc_data",
                    pnl_r_val=None,
                    open_pos=bar_open_n,
                    cap_pct=bar_cap_pct,
                )
                continue

            pq_bar = _pq_for_bar(ts_bar)
            if track_capital:
                ex = compute_trade_plan_execution_from_pattern_row(
                    pat,
                    candle,
                    ctx,
                    clist,
                    idx,
                    pq_bar,
                    cost_rate,
                )
                if ex is None:
                    skipped += 1
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="trade_plan_not_triggered",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
                    continue
                candidates_capital.append((pat, candle, ctx, ex))
            else:
                tp_result = compute_trade_plan_pnl_from_pattern_row(
                    pat,
                    candle,
                    ctx,
                    clist,
                    idx,
                    pq_bar,
                    cost_rate,
                )
                if tp_result is None:
                    skipped += 1
                    _audit(
                        pat,
                        executed=False,
                        skip_reason="trade_plan_not_triggered",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
                    continue
                pnl_r, engine_outcome = tp_result
                candidates_legacy.append((pat, candle, ctx, pnl_r, engine_outcome))
            series_used_this_bar.add(series_key)

        if track_capital:
            candidates_src = candidates_capital
        else:
            candidates_src = candidates_legacy

        if not candidates_src:
            continue

        max_take = min(len(candidates_src), max_simultaneous)
        if track_capital:
            max_take = min(max_take, slots_available)
        if len(candidates_src) > max_take:
            dropped = len(candidates_src) - max_take
            skipped += dropped
            if track_capital:
                trades_skipped_by_capital += dropped
            drop_slice = candidates_src[max_take:]
            if include_pattern_audit:
                for item in drop_slice:
                    pat_drop = item[0]
                    _audit(
                        pat_drop,
                        executed=False,
                        skip_reason="capital_constraint",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            del candidates_src[max_take:]

        n = len(candidates_src)
        equity_before_bar = equity
        if not track_capital and equity_before_bar <= EQUITY_FLOOR:
            skipped += n
            if include_pattern_audit:
                for item in candidates_src:
                    pat_eq = item[0]
                    _audit(
                        pat_eq,
                        executed=False,
                        skip_reason="equity_floor",
                        pnl_r_val=None,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            continue

        risk_per_single_pct = risk_per_trade_pct / float(n)
        bar_pnl = 0.0
        ts_point: datetime | None = None
        fills: list[
            tuple[
                CandlePattern,
                float,
                float,
                float,
                datetime,
                Literal["win", "loss", "flat"],
                datetime | None,
            ]
        ] = []

        if not track_capital:
            for pat, _candle, _ctx, pnl_r, engine_outcome in candidates_legacy:
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
                fills.append((pat, pnl_r, risk_amount, net, ts_point, row_outcome, None))

            if fills and ts_point is not None:
                for pat, _, _, _, _, _, _ in fills:
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

            if include_pattern_audit and fills:
                for pat, pnl_r, _, _, _, _, _ in fills:
                    _audit(
                        pat,
                        executed=True,
                        skip_reason=None,
                        pnl_r_val=pnl_r,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            if include_trades:
                for pat, pnl_r, risk_amount, net, ts_pt, row_outcome, _exit_ts in fills:
                    pnl_r_net = net / risk_amount if risk_amount > 1e-18 else 0.0
                    strength = _pattern_strength_float(pat)
                    trade_rows.append(
                        SimulationTradeRow(
                            timestamp=ts_pt,
                            exit_timestamp=None,
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
                            candle_pattern_id=pat.id,
                        )
                    )
        else:
            committed_before_fills = sum(p.capital_at_risk for p in open_positions)
            available_for_sizing = max(0.0, equity - committed_before_fills)
            for pat, _candle, _ctx, ex in candidates_capital:
                pnl_r = ex.pnl_r
                engine_outcome = ex.outcome
                risk_amount = available_for_sizing * (risk_per_single_pct / 100.0)
                net = risk_amount * pnl_r

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
                    net / available_for_sizing if available_for_sizing > 1e-18 else 0.0,
                )

                ts = pat.timestamp
                ts_point = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
                row_outcome = _map_engine_outcome_to_row(engine_outcome)
                fills.append(
                    (pat, pnl_r, risk_amount, net, ts_point, row_outcome, ex.exit_timestamp),
                )

                open_positions.append(
                    OpenPosition(
                        symbol=pat.symbol,
                        timeframe=pat.timeframe,
                        provider=pat.provider,
                        entry_timestamp=ex.entry_timestamp,
                        exit_timestamp=ex.exit_timestamp,
                        capital_at_risk=risk_amount,
                        pnl_r=pnl_r,
                        outcome=engine_outcome,
                    )
                )
                max_concurrent_positions_obs = max(
                    max_concurrent_positions_obs,
                    len(open_positions),
                )

            if fills and ts_point is not None:
                for pat, _, _, _, _, _, _ in fills:
                    sk = (pat.symbol, pat.timeframe, pat.provider)
                    last_entry_bar[sk] = ts_point

            bars_with_trades += 1
            sum_trades_per_bar += n
            if n > max_sim_obs:
                max_sim_obs = n

            if include_pattern_audit and fills:
                for pat, pnl_r, _, _, _, _, _ in fills:
                    _audit(
                        pat,
                        executed=True,
                        skip_reason=None,
                        pnl_r_val=pnl_r,
                        open_pos=bar_open_n,
                        cap_pct=bar_cap_pct,
                    )
            if include_trades:
                for pat, pnl_r, risk_amount, net, ts_pt, row_outcome, exit_ts in fills:
                    pnl_r_net = net / risk_amount if risk_amount > 1e-18 else 0.0
                    strength = _pattern_strength_float(pat)
                    trade_rows.append(
                        SimulationTradeRow(
                            timestamp=ts_pt,
                            exit_timestamp=exit_ts,
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
                            candle_pattern_id=pat.id,
                        )
                    )

    if track_capital and open_positions:
        for p in sorted(open_positions, key=lambda x: _utc_wall(x.exit_timestamp)):
            equity += p.capital_at_risk * p.pnl_r
            equity = max(equity, EQUITY_FLOOR)
            curve.append(
                SimulationEquityPoint(timestamp=p.exit_timestamp, equity=equity),
            )
        open_positions.clear()

    avg_cap_util: float | None = None
    if track_capital and capital_utilization_samples:
        avg_cap_util = sum(capital_utilization_samples) / len(capital_utilization_samples)

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
            track_capital=track_capital,
            max_concurrent_positions=max_concurrent_positions_obs,
            avg_capital_utilization=avg_cap_util,
            trades_skipped_by_capital=trades_skipped_by_capital,
            use_temporal_quality=use_temporal_quality,
            quality_lookup_dt_to=quality_lookup_dt_to_str,
            regime_variant_used=regime_variant_used,
            trades_skipped_by_hour=trades_skipped_by_hour,
            allowed_hours_utc=_allowed_hours_resolved,
            pattern_simulation_audit=sorted(
                pattern_audit_dict.values(),
                key=lambda x: x.candle_pattern_id,
            ),
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
            f" Filtro direzione SPY (1d, variante {regime_variant_used}): segnali esclusi per direzione: "
            f"{trades_skipped_by_regime}."
        )
    elif use_regime_filter and (provider or "").strip().lower() == "binance":
        note += (
            " use_regime_filter=true ignorato per Binance (filtro regime non applicato alle crypto)."
        )
    if track_capital:
        note += (
            " track_capital=true: capitale impegnato fino all'uscita; PnL accreditato alla chiusura del trade; "
            "equity_curve con punti agli exit_timestamp (non alla barra del segnale); "
            f"max posizioni contemporanee osservate={max_concurrent_positions_obs}, "
            f"saltati per capitale/slot={trades_skipped_by_capital}."
        )
    if quality_lookup_dt_to_str is not None:
        note += (
            f" Quality lookup anti-leakage: solo pattern con timestamp ≤ {quality_lookup_dt_to_str}."
        )
    if _allowed_hours_resolved:
        note += (
            f" Filtro allowed_hours_utc={_allowed_hours_resolved}: "
            f"{trades_skipped_by_hour} segnali esclusi (ora UTC barra non in whitelist)."
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

    daily_stats_value: DailySessionStats | None = None
    if include_trades and track_capital and trade_rows:
        daily_stats_value = _compute_daily_stats(trade_rows)

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
        track_capital=track_capital,
        max_concurrent_positions=max_concurrent_positions_obs,
        avg_capital_utilization=round(avg_cap_util, 4) if avg_cap_util is not None else None,
        trades_skipped_by_capital=trades_skipped_by_capital,
        use_temporal_quality=use_temporal_quality,
        quality_lookup_dt_to=quality_lookup_dt_to_str,
        regime_variant_used=regime_variant_used,
        trades_skipped_by_hour=trades_skipped_by_hour,
        allowed_hours_utc=_allowed_hours_resolved,
        daily_stats=daily_stats_value,
        pattern_simulation_audit=sorted(
            pattern_audit_dict.values(),
            key=lambda x: x.candle_pattern_id,
        ),
    )


run_backtest_simulation = run_simulation
