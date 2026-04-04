from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.backtest import (
    PatternBacktestResponse,
    TradePlanBacktestResponse,
    TradePlanVariantBacktestResponse,
    TradePlanVariantBestResponse,
)
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.services.pattern_backtest import run_pattern_backtest
from app.services.trade_plan_backtest import run_trade_plan_backtest
from app.services.trade_plan_variant_backtest import run_trade_plan_variant_backtest
from app.services.trade_plan_variant_best import run_trade_plan_variant_best

router = APIRouter(prefix="/backtest", tags=["backtest"])


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
        le=2000,
        description="Max pattern rows valutate prima dell’aggregazione best (costo ~27×).",
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
        le=2000,
        description="Max pattern rows (ognuna simula 27 varianti — costo ~27×).",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> TradePlanVariantBacktestResponse:
    """
    Confronta 27 varianti di esecuzione (entry × stop × TP) per gli stessi bucket storici.
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
    )
