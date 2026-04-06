from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    MAX_SIMULTANEOUS_TRADES,
)
from app.schemas.backtest import (
    BacktestSimulationResponse,
    OOSValidationResponse,
    PatternBacktestResponse,
    TradePlanBacktestResponse,
    TradePlanVariantBacktestResponse,
    TradePlanVariantBestResponse,
)
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.services.backtest_simulation import run_backtest_simulation
from app.services.pattern_backtest import run_pattern_backtest
from app.services.trade_plan_backtest import run_trade_plan_backtest
from app.services.trade_plan_variant_backtest import run_trade_plan_variant_backtest
from app.services.trade_plan_variant_best import run_trade_plan_variant_best
from app.services.oos_validation_service import run_oos_validation

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _parse_ymd_utc(s: str, *, end_of_day: bool) -> datetime:
    """Primi 10 caratteri YYYY-MM-DD → inizio o fine giornata UTC."""
    raw = s.strip()[:10]
    d = date.fromisoformat(raw)
    if end_of_day:
        return datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)


def _resolve_date_range(
    period: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[datetime | None, datetime | None]:
    """
    Priorità: coppia date_from+date_to; altrimenti ``period`` (es. 1m, 1y);
    altrimenti nessun filtro (tutto lo storico).
    """
    now = datetime.now(timezone.utc)
    if date_from and date_to:
        dt_a = _parse_ymd_utc(date_from, end_of_day=False)
        dt_b = _parse_ymd_utc(date_to, end_of_day=True)
        if dt_a > dt_b:
            dt_a, dt_b = dt_b, dt_a
        return (dt_a, dt_b)
    if period and period.lower() != "all":
        delta_map = {
            "1m": timedelta(days=30),
            "3m": timedelta(days=90),
            "6m": timedelta(days=180),
            "1y": timedelta(days=365),
            "2y": timedelta(days=730),
            "3y": timedelta(days=1095),
        }
        delta = delta_map.get(period.lower().strip())
        if delta:
            return (now - delta, now)
    return (None, None)


@router.get("/simulation", response_model=BacktestSimulationResponse)
async def get_backtest_simulation(
    provider: str = Query(
        ...,
        description="Provider dati (es. yahoo_finance, binance).",
    ),
    timeframe: str = Query(
        ...,
        description="Timeframe (es. 1h, 1d).",
    ),
    pattern_names: list[str] = Query(
        default=[],
        description="Nomi pattern (ripetere parametro). Vuoto = tutti i pattern promoted per provider×TF.",
    ),
    initial_capital: float = Query(
        default=10_000.0,
        gt=0,
        description="Capitale iniziale della simulazione.",
    ),
    risk_per_trade_pct: float = Query(
        default=1.0,
        gt=0,
        le=100,
        description="Percentuale di equity allocata per trade (notional ~ equity × risk%).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description="Costo round-trip sul notional (fee + slippage).",
    ),
    symbol: str | None = Query(
        default=None,
        description="Opzionale: filtra per simbolo.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Opzionale: filtra per exchange.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Opzionale: filtra per asset_type.",
    ),
    pattern_row_limit: int = Query(
        default=50_000,
        ge=1,
        le=100_000,
        description="Massimo righe pattern considerate (ordine cronologico).",
    ),
    seed: int = Query(
        default=42,
        ge=0,
        description="Riservato compatibilità API; la simulazione è deterministica e non usa RNG.",
    ),
    include_trades: bool = Query(
        default=False,
        description="Se true, include l'elenco trade con pnl_r, outcome, capital_after (payload più grande).",
    ),
    max_simultaneous: int = Query(
        default=MAX_SIMULTANEOUS_TRADES,
        ge=1,
        le=10,
        description="Massimo trade per stessa barra (timestamp); il rischio % si divide tra i fill della barra.",
    ),
    date_from: str | None = Query(
        default=None,
        description="Data inizio (YYYY-MM-DD), opzionale; con date_to ha priorità su period.",
    ),
    date_to: str | None = Query(
        default=None,
        description="Data fine (YYYY-MM-DD), opzionale.",
    ),
    period: str | None = Query(
        default=None,
        description="Periodo relativo: 1m, 3m, 6m, 1y, 2y, 3y, all (nessun filtro data).",
    ),
    use_regime_filter: bool = Query(
        default=False,
        description=(
            "Se true, applica moltiplicatore di rischio per barra da regime SPY 1d (EMA50/RSI). "
            "Senza dati SPY nel DB il filtro è disattivato silenziosamente."
        ),
    ),
    exclude_hours: list[int] = Query(
        default=[],
        description=(
            "Ore UTC da escludere (ripetere il parametro). Vuoto = nessun filtro orario. "
            "Solo Yahoo; Binance ignora."
        ),
    ),
    include_hours: list[int] = Query(
        default=[],
        description=(
            "Solo queste ore UTC. Vuoto = tutte le ore. "
            "Se include ed exclude sono entrambi valorizzati, ha priorità include_hours."
        ),
    ),
    exclude_symbols: list[str] = Query(
        default=[],
        description="Simboli da escludere",
    ),
    include_symbols: list[str] = Query(
        default=[],
        description="Solo questi simboli",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> BacktestSimulationResponse:
    """
    Simulazione equity in-sample (solo DB): per ogni segnale pattern, forward return reale da close
    storici (stessa logica di ``GET /backtest/patterns``), compounding su risk% e costi sul notional a rischio.
    """
    dt_from, dt_to = _resolve_date_range(period, date_from, date_to)
    return await run_backtest_simulation(
        session,
        provider=provider,
        timeframe=timeframe,
        pattern_names=pattern_names,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        cost_rate=cost_rate,
        symbol=symbol,
        exchange=exchange,
        asset_type=asset_type,
        pattern_row_limit=pattern_row_limit,
        seed=seed,
        include_trades=include_trades,
        max_simultaneous=max_simultaneous,
        dt_from=dt_from,
        dt_to=dt_to,
        use_regime_filter=use_regime_filter,
        exclude_hours=exclude_hours if exclude_hours else None,
        include_hours=include_hours if include_hours else None,
        exclude_symbols=exclude_symbols if exclude_symbols else None,
        include_symbols=include_symbols if include_symbols else None,
    )


@router.get("/out-of-sample", response_model=OOSValidationResponse)
async def get_out_of_sample(
    provider: str = Query(
        ...,
        description="Provider dati (es. yahoo_finance, binance).",
    ),
    timeframe: str = Query(
        ...,
        description="Timeframe (es. 1h, 5m).",
    ),
    pattern_names: list[str] = Query(
        default=[],
        description="Nomi pattern (ripetere parametro). Vuoto = tutti i pattern promoted per provider×TF.",
    ),
    cutoff_date: str = Query(
        default="2025-01-01",
        description="Data di separazione train/test (YYYY-MM-DD); il test inizia a mezzanotte UTC di questo giorno.",
    ),
    initial_capital: float = Query(
        default=10_000.0,
        gt=0,
        description="Capitale iniziale per entrambe le simulazioni.",
    ),
    risk_per_trade_pct: float = Query(
        default=1.0,
        gt=0,
        le=100,
        description="Percentuale di equity allocata per trade.",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description="Costo round-trip sul notional.",
    ),
    max_simultaneous: int = Query(
        default=MAX_SIMULTANEOUS_TRADES,
        ge=1,
        le=10,
        description="Massimo trade simultanei per barra.",
    ),
    include_trades: bool = Query(
        default=False,
        description="Se true, include i trade nel test set (payload più grande).",
    ),
    use_regime_filter: bool = Query(
        default=False,
        description="Se true, filtra le direzioni in base al regime SPY 1d (EMA50).",
    ),
    exclude_hours: list[int] = Query(
        default=[],
        description=(
            "Ore UTC da escludere (stessa semantica di GET /backtest/simulation). "
            "Vuoto = nessun filtro."
        ),
    ),
    include_hours: list[int] = Query(
        default=[],
        description="Solo queste ore UTC (stessa semantica di GET /backtest/simulation).",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> OOSValidationResponse:
    """
    Validazione out-of-sample: metriche sul train (fino al giorno prima del cutoff) e simulazione sul test.
    """
    names = [n.strip() for n in pattern_names if n and n.strip()]
    return await run_oos_validation(
        session,
        provider=provider.strip(),
        timeframe=timeframe.strip(),
        pattern_names=names,
        cutoff_date=cutoff_date,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        cost_rate=cost_rate,
        max_simultaneous=max_simultaneous,
        include_trades=include_trades,
        use_regime_filter=use_regime_filter,
        exclude_hours=exclude_hours if exclude_hours else None,
        include_hours=include_hours if include_hours else None,
    )


@router.get("/patterns", response_model=PatternBacktestResponse)
async def get_pattern_backtest(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (exact).",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance).",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index).",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (includes 1d for Yahoo).",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name.",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Max stored pattern rows to evaluate (newest first).",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PatternBacktestResponse:
    """
    Forward return stats after detected patterns (+1/+3/+5/+10 candles), aggregated by
    pattern_name and timeframe. Computed on demand from stored candles and patterns.
    """
    return await run_pattern_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
    )


@router.get("/trade-plans", response_model=TradePlanBacktestResponse)
async def get_trade_plan_backtest(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (exact).",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance).",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index).",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (includes 1d for Yahoo).",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name.",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Max stored pattern rows to evaluate (newest first).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description=(
            "Costo round-trip stimato (fee + slippage) come frazione del notional "
            "(es. 0.0015 = 0.15%). Default: 0.15% (fee 0.10% + slippage 0.05%)."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> TradePlanBacktestResponse:
    """
    Simula i trade plan prodotti dal **Trade Plan Engine v1.1** (entry/stop/TP1/TP2, direzione,
    strategia di ingresso) sulle candele dopo il segnale; aggregati per pattern, timeframe,
    provider e asset_type.
    """
    return await run_trade_plan_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
        cost_rate=cost_rate,
    )


@router.get("/trade-plan-variants/best", response_model=TradePlanVariantBestResponse)
async def get_trade_plan_variant_best(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (exact).",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance).",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index).",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (includes 1d for Yahoo).",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name.",
    ),
    status_scope: str = Query(
        default="promoted_watchlist",
        description=(
            "promoted_watchlist (default, esclude rejected) | all | promoted | watchlist | rejected"
        ),
    ),
    operational_status: str | None = Query(
        default=None,
        description="Singolo stato (promoted|watchlist|rejected); se valorizzato ha priorità su status_scope.",
    ),
    limit: int = Query(
        default=300,
        ge=1,
        le=10_000,
        description="Max pattern rows valutate prima dell’aggregazione best (costo ~45×).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description=(
            "Costo round-trip stimato (fee + slippage) come frazione del notional "
            "(es. 0.0015 = 0.15%). Default: 0.15% (fee 0.10% + slippage 0.05%)."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> TradePlanVariantBestResponse:
    """
    Sintesi operativa: migliore variante di esecuzione per ogni bucket (pattern×TF×provider×asset),
    con stato promoted / watchlist / rejected.
    """
    return await run_trade_plan_variant_best(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
        status_scope=status_scope,
        operational_status=operational_status,
        cost_rate=cost_rate,
    )


@router.get("/trade-plan-variants", response_model=TradePlanVariantBacktestResponse)
async def get_trade_plan_variant_backtest(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (exact).",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance).",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index).",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (includes 1d for Yahoo).",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name.",
    ),
    limit: int = Query(
        default=300,
        ge=1,
        le=10_000,
        description="Max pattern rows (ognuna simula 27 varianti — costo ~27×).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description=(
            "Costo round-trip stimato (fee + slippage) come frazione del notional "
            "(es. 0.0015 = 0.15%). Default: 0.15% (fee 0.10% + slippage 0.05%)."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> TradePlanVariantBacktestResponse:
    """
    Confronta 45 varianti di esecuzione (entry × stop × TP) per gli stessi bucket storici.
    Analisi only; non influenza lo screener live.
    """
    return await run_trade_plan_variant_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
        cost_rate=cost_rate,
    )
