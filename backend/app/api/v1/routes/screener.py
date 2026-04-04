from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.context import LatestContextSnapshot, LatestScreenerResponse
from app.schemas.opportunities import OpportunitiesResponse
from app.schemas.screener import RankedScreenerResponse, RankedScreenerRow
from app.services.context_query import list_latest_context_per_series
from app.services.opportunities import list_opportunities
from app.services.screener_scoring import SnapshotForScoring, score_snapshot

router = APIRouter(prefix="/screener", tags=["screener"])


@router.get("/latest", response_model=LatestScreenerResponse)
async def get_latest_screener_snapshots(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by exchange. Omit for all exchanges.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> LatestScreenerResponse:
    rows = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
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
        description="Filter by exchange. Omit for all exchanges.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> RankedScreenerResponse:
    rows = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    )
    ranked: list[RankedScreenerRow] = []
    for row in rows:
        snap = SnapshotForScoring(
            exchange=row.exchange,
            symbol=row.symbol,
            timeframe=row.timeframe,
            timestamp=row.timestamp,
            market_regime=row.market_regime,
            volatility_regime=row.volatility_regime,
            candle_expansion=row.candle_expansion,
            direction_bias=row.direction_bias,
        )
        points, label = score_snapshot(snap)
        ranked.append(
            RankedScreenerRow(
                exchange=row.exchange,
                symbol=row.symbol,
                timeframe=row.timeframe,
                timestamp=row.timestamp,
                market_regime=row.market_regime,
                volatility_regime=row.volatility_regime,
                candle_expansion=row.candle_expansion,
                direction_bias=row.direction_bias,
                screener_score=points,
                score_label=label,
            )
        )
    ranked.sort(key=lambda r: r.screener_score, reverse=True)
    ranked = ranked[:limit]
    return RankedScreenerResponse(ranked=ranked, count=len(ranked))


@router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by exchange. Omit for all exchanges.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunitiesResponse:
    rows = await list_opportunities(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        limit=limit,
    )
    return OpportunitiesResponse(opportunities=rows, count=len(rows))
