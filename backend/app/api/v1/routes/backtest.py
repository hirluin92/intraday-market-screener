from datetime import date, datetime, timedelta, timezone

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    MAX_SIMULTANEOUS_TRADES,
)
from app.schemas.backtest import (
    BacktestSimulationResponse,
    DailySessionStats,
    MonteCarloDrawdownStats,
    MonteCarloProbabilitaStats,
    MonteCarloRendimentoStats,
    MonteCarloResponse,
    OOSValidationResponse,
    PatternBacktestResponse,
    TradePlanBacktestResponse,
    TradePlanVariantBacktestResponse,
    TradePlanVariantBestResponse,
    WalkForwardFoldResponse,
    WalkForwardResponse,
)
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.services.backtest_simulation import run_backtest_simulation
from app.services.pattern_backtest import run_pattern_backtest
from app.services.trade_plan_backtest import run_trade_plan_backtest
from app.services.trade_plan_variant_backtest import run_trade_plan_variant_backtest
from app.services.trade_plan_variant_best import run_trade_plan_variant_best
from app.services.oos_validation_service import run_oos_validation
from app.services.walk_forward_service import run_walk_forward
from app.services.monte_carlo_service import run_monte_carlo

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
        default=True,
        description=(
            "Se true (default), attiva il regime gate SPY 1d per Yahoo Finance: "
            "i PATTERNS_BEAR_REGIME_ONLY scattano solo in regime bearish, "
            "i pattern universali rimangono attivi in tutti i regimi. "
            "Per Binance il parametro è ignorato."
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
    cooldown_bars: int = Query(
        default=0,
        ge=0,
        le=20,
        description=(
            "Barre di cooldown per serie dopo un trade. "
            "0 = nessun cooldown (comportamento storico). "
            "3 = skip segnali nella stessa serie per 3 barre dopo un trade."
        ),
    ),
    min_strength: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Opzionale: esclude pattern con pattern_strength sotto questa soglia (0–1). "
            "Utile per testare filtri tipo RS (strength penalizzata)."
        ),
    ),
    track_capital: bool = Query(
        default=True,
        description=(
            "Se true (default), il capitale rischiato resta impegnato fino alla chiusura del trade (barra di uscita); "
            "PnL realizzato alla chiusura; slot e disponibilità riducono nuovi ingressi. "
            "false = comportamento storico (PnL accreditato alla barra del segnale)."
        ),
    ),
    use_temporal_quality: bool = Query(
        default=True,
        description=(
            "Se true (default) e senza quality_lookup_override, il lookup qualità pattern usa solo dati fino al timestamp "
            "del primo segnale nella simulazione (anti-leakage IS)."
        ),
    ),
    regime_variant: str = Query(
        default="ema50",
        description=(
            "Variante filtro regime SPY 1d (solo Yahoo con use_regime_filter=true): "
            "ema50 | ema9_20 | momentum5d | ema50_rsi."
        ),
    ),
    allowed_hours_utc: list[int] | None = Query(
        default=None,
        description=(
            "Whitelist ore UTC (0-23) sulla sola barra di segnale (timestamp pattern); ripetere il parametro. "
            "Non filtra per ora di uscita né per ore in cui il trade resta aperto (track_capital). "
            "Metriche e WR possono discostare da un'analisi statica per fascia oraria. "
            "Default None = disattivo (nessun filtro)."
        ),
    ),
    include_pattern_audit: bool = Query(
        default=False,
        description=(
            "Se true, la risposta include pattern_simulation_audit: uno stato per ogni CandlePattern "
            "processato (eseguito o motivo skip). Payload più grande."
        ),
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
        cooldown_bars=cooldown_bars,
        exclude_hours=exclude_hours if exclude_hours else None,
        include_hours=include_hours if include_hours else None,
        exclude_symbols=exclude_symbols if exclude_symbols else None,
        include_symbols=include_symbols if include_symbols else None,
        min_strength=min_strength,
        track_capital=track_capital,
        use_temporal_quality=use_temporal_quality,
        regime_variant=regime_variant,
        allowed_hours_utc=allowed_hours_utc if allowed_hours_utc else None,
        include_pattern_audit=include_pattern_audit,
    )


@router.get("/monte-carlo", response_model=MonteCarloResponse)
async def get_monte_carlo(
    session: AsyncSession = Depends(get_db_session),
    provider: str = Query(
        default="yahoo_finance",
        description="Provider dati (es. yahoo_finance).",
    ),
    timeframe: str = Query(
        default="1h",
        description="Timeframe pattern.",
    ),
    pattern_names: list[str] = Query(
        default=[],
        description="Nomi pattern (ripetere parametro). Vuoto = tutti i pattern promoted per provider×TF.",
    ),
    min_strength: float = Query(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Soglia minima pattern_strength (stessa semantica di GET /backtest/simulation).",
    ),
    use_regime_filter: bool = Query(
        default=True,
        description="Filtro regime SPY 1d (solo Yahoo).",
    ),
    n_simulations: int = Query(
        default=1000,
        ge=1,
        le=50_000,
        description="Numero di simulazioni bootstrap.",
    ),
    initial_capital: float = Query(
        default=10_000.0,
        gt=0,
        description="Capitale iniziale (simulazione + Monte Carlo).",
    ),
    risk_per_trade_pct: float = Query(
        default=1.0,
        gt=0,
        le=100,
        description="Rischio % equity per trade (stesso della simulazione).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description="Costo round-trip (stesso della simulazione).",
    ),
    max_simultaneous: int = Query(
        default=MAX_SIMULTANEOUS_TRADES,
        ge=1,
        le=10,
    ),
    seed: int = Query(
        default=42,
        ge=0,
        description="Seed RNG Monte Carlo (riproducibilità).",
    ),
) -> MonteCarloResponse:
    """
    Bootstrap Monte Carlo sui ``pnl_r_net`` dei trade prodotti da una simulazione IS
    (stessi parametri operativi). Non preserva ordine temporale tra trade.
    """
    names = [n.strip() for n in pattern_names if n and n.strip()]
    sim_result = await run_backtest_simulation(
        session,
        provider=provider.strip(),
        timeframe=timeframe.strip(),
        pattern_names=names,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        cost_rate=cost_rate,
        max_simultaneous=max_simultaneous,
        include_trades=True,
        use_regime_filter=use_regime_filter,
        min_strength=min_strength,
        track_capital=True,
        use_temporal_quality=True,
    )
    pnl_r_list = [t.pnl_r_net for t in (sim_result.trades or [])]
    if not pnl_r_list:
        raise HTTPException(
            status_code=400,
            detail="Nessun trade disponibile per Monte Carlo (simulazione senza trade o trades mancanti).",
        )
    mc = run_monte_carlo(
        pnl_r_list,
        n_simulations=n_simulations,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        seed=seed,
    )
    return MonteCarloResponse(
        n_trades_storici=len(pnl_r_list),
        n_simulations=mc.n_simulations,
        n_trades_per_sim=mc.n_trades_per_sim,
        drawdown=MonteCarloDrawdownStats(
            median_pct=mc.dd_median_pct,
            p95_pct=mc.dd_p95_pct,
            p99_pct=mc.dd_p99_pct,
            max_ever_pct=mc.dd_max_ever_pct,
        ),
        rendimento=MonteCarloRendimentoStats(
            median_pct=mc.ret_median_pct,
            p5_pct=mc.ret_p5_pct,
            p95_pct=mc.ret_p95_pct,
        ),
        probabilita=MonteCarloProbabilitaStats(
            pct_positive=mc.pct_simulations_positive,
            pct_ruin_50pct_dd=mc.pct_simulations_ruin,
        ),
    )


@router.get("/daily-stats", response_model=DailySessionStats)
async def get_daily_session_stats(
    session: AsyncSession = Depends(get_db_session),
    provider: str = Query(
        default="yahoo_finance",
        description="Provider dati (es. yahoo_finance).",
    ),
    timeframe: str = Query(
        default="1h",
        description="Timeframe pattern.",
    ),
    pattern_names: list[str] = Query(
        default=[],
        description="Nomi pattern (ripetere parametro). Vuoto = tutti i pattern promoted per provider×TF.",
    ),
    min_strength: float = Query(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Soglia minima pattern_strength (stessa semantica di GET /backtest/simulation).",
    ),
    use_regime_filter: bool = Query(
        default=True,
        description="Filtro regime SPY 1d (solo Yahoo).",
    ),
    cost_rate: float = Query(
        default=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        ge=0.0,
        le=0.05,
        description="Costo round-trip (stesso della simulazione).",
    ),
    max_simultaneous: int = Query(
        default=MAX_SIMULTANEOUS_TRADES,
        ge=1,
        le=10,
    ),
    initial_capital: float = Query(
        default=10_000.0,
        gt=0,
        description="Capitale iniziale (coerente con simulazione).",
    ),
    risk_per_trade_pct: float = Query(
        default=1.0,
        gt=0,
        le=100,
        description="Rischio % equity per trade.",
    ),
) -> DailySessionStats:
    """
    Statistiche per sessione giornaliera (UTC): somma R netti per giorno di uscita,
    peggior/miglior giorno, rolling 5 giorni. Stessa simulazione di GET /backtest/simulation
    con ``include_trades=true`` e ``track_capital=true``.
    """
    names = [n.strip() for n in pattern_names if n and n.strip()]
    sim_result = await run_backtest_simulation(
        session,
        provider=provider.strip(),
        timeframe=timeframe.strip(),
        pattern_names=names,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        cost_rate=cost_rate,
        max_simultaneous=max_simultaneous,
        include_trades=True,
        track_capital=True,
        use_regime_filter=use_regime_filter,
        min_strength=min_strength,
        use_temporal_quality=True,
    )
    if sim_result.daily_stats is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Statistiche giornaliere non disponibili: nessun trade nella simulazione "
                "o dati insufficienti (serve track_capital=true e trade con uscita)."
            ),
        )
    return sim_result.daily_stats


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
        default=True,
        description=(
            "Se true (default), attiva il regime gate SPY 1d: PATTERNS_BEAR_REGIME_ONLY "
            "scattano solo in regime bearish; pattern universali attivi in tutti i regimi. "
            "Ignorato per Binance."
        ),
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
    track_capital: bool = Query(
        default=True,
        description=(
            "Se true (default OOS), stessa simulazione di GET /backtest/simulation con track_capital: "
            "capitale impegnato fino all'uscita, PnL alla chiusura. false = comportamento storico."
        ),
    ),
    use_temporal_quality: bool = Query(
        default=True,
        description=(
            "Se true (default), propagato a run_simulation; con quality_lookup_override OOS non ha effetto sul lookup."
        ),
    ),
    min_confluence_patterns: int = Query(
        default=1,
        ge=1,
        le=5,
        description=(
            "Numero minimo di pattern distinti sullo stesso simbolo nella stessa barra per eseguire il trade. "
            "1 = nessun filtro (default). 2 = confluenza richiesta (2+ pattern concordano)."
        ),
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
        track_capital=track_capital,
        use_temporal_quality=use_temporal_quality,
        min_confluence_patterns=min_confluence_patterns,
    )


@router.get("/walk-forward", response_model=WalkForwardResponse)
async def get_walk_forward(
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
    n_folds: int = Query(
        default=3,
        ge=2,
        le=6,
        description="Numero di fold: timeline divisa in n_folds+1 segmenti uguali.",
    ),
    initial_capital: float = Query(
        default=10_000.0,
        gt=0,
        description="Capitale iniziale per ogni simulazione.",
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
    use_regime_filter: bool = Query(
        default=True,
        description=(
            "Se true (default), attiva il regime gate SPY 1d per i pattern bear-only. "
            "Ignorato per Binance."
        ),
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
    exclude_symbols: list[str] = Query(
        default=[],
        description="Simboli da escludere (stessa semantica di GET /backtest/simulation).",
    ),
    include_symbols: list[str] = Query(
        default=[],
        description="Solo questi simboli (stessa semantica di GET /backtest/simulation).",
    ),
    track_capital: bool = Query(
        default=True,
        description=(
            "Se true (default walk-forward), stessa simulazione di GET /backtest/simulation con track_capital. "
            "false = comportamento storico (PnL alla barra del segnale)."
        ),
    ),
    use_temporal_quality: bool = Query(
        default=True,
        description=(
            "Se true (default), propagato a run_simulation per ogni fold; con quality_lookup_override train non ha effetto sul lookup."
        ),
    ),
    min_confluence_patterns: int = Query(
        default=1,
        ge=1,
        le=10,
        description=(
            "Numero minimo di pattern validati distinti attivi nella stessa barra per eseguire il trade. "
            "1 = nessun filtro (default storico). "
            "2 = stesso valore usato nel backtest OOS di validazione (apr 2026): "
            "EV +0.478R, WR 58.4%, PF 2.82, DD -19.8%."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> WalkForwardResponse:
    """
    Walk-forward: per ogni fold il quality lookup è calcolato solo sul train e riusato sul test (no leakage).
    """
    names = [n.strip() for n in pattern_names if n and n.strip()]
    try:
        result = await run_walk_forward(
            session,
            provider=provider.strip(),
            timeframe=timeframe.strip(),
            pattern_names=names,
            n_folds=n_folds,
            initial_capital=initial_capital,
            risk_per_trade_pct=risk_per_trade_pct,
            cost_rate=cost_rate,
            max_simultaneous=max_simultaneous,
            use_regime_filter=use_regime_filter,
            exclude_hours=exclude_hours if exclude_hours else None,
            include_hours=include_hours if include_hours else None,
            exclude_symbols=exclude_symbols if exclude_symbols else None,
            include_symbols=include_symbols if include_symbols else None,
            track_capital=track_capital,
            use_temporal_quality=use_temporal_quality,
            min_confluence_patterns=min_confluence_patterns,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return WalkForwardResponse(
        n_folds=result.n_folds,
        folds=[WalkForwardFoldResponse(**asdict(f)) for f in result.folds],
        avg_test_return_pct=result.avg_test_return_pct,
        avg_test_win_rate=result.avg_test_win_rate,
        avg_degradation_pct=result.avg_degradation_pct,
        pct_folds_positive=result.pct_folds_positive,
        overall_verdict=result.overall_verdict,
        date_range_start=result.date_range_start,
        date_range_end=result.date_range_end,
        track_capital=result.track_capital,
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
