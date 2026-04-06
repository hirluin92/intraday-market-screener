from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.context import LatestContextSnapshot, LatestScreenerResponse
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.schemas.opportunities import OpportunitiesResponse
from app.schemas.screener import RankedScreenerResponse
from app.services.context_query import list_latest_context_per_series
from app.services.opportunities import list_opportunities, list_ranked_screener

router = APIRouter(prefix="/screener", tags=["screener"])
# Stesso contratto di GET /screener/opportunities, path breve per client e script.
opportunities_alias_router = APIRouter(tags=["screener"])


async def _opportunities_response(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None,
    asset_type: str | None,
    timeframe: OptionalAllMarketsTimeframe,
    limit: int,
    decision: str | None,
) -> OpportunitiesResponse:
    rows = await list_opportunities(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
        decision=decision,
    )
    return OpportunitiesResponse(opportunities=rows, count=len(rows))


@router.get("/latest", response_model=LatestScreenerResponse)
async def get_latest_screener_snapshots(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue (e.g. binance, YAHOO_US). Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> LatestScreenerResponse:
    rows = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    snapshots = [LatestContextSnapshot.model_validate(r) for r in rows]
    return LatestScreenerResponse(snapshots=snapshots, count=len(snapshots))


@router.get("/ranked", response_model=RankedScreenerResponse)
async def get_ranked_screener(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> RankedScreenerResponse:
    ranked = await list_ranked_screener(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
    )
    return RankedScreenerResponse(ranked=ranked, count=len(ranked))


@router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    decision: str | None = Query(
        default=None,
        description=(
            "Filtro semaforo: execute | monitor | discard, oppure IT "
            "(operabile, da_monitorare, scartare). Alias: operable → execute."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunitiesResponse:
    return await _opportunities_response(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
        decision=decision,
    )


@opportunities_alias_router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities_short_path(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    decision: str | None = Query(
        default=None,
        description=(
            "Filtro semaforo: execute | monitor | discard, oppure IT "
            "(operabile, da_monitorare, scartare). Alias: operable → execute."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunitiesResponse:
    return await _opportunities_response(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
        decision=decision,
    )
