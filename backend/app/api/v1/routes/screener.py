from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.executed_signal import ExecutedSignal
from app.schemas.context import LatestContextSnapshot, LatestScreenerResponse
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.schemas.opportunities import OpportunitiesResponse
from app.schemas.screener import RankedScreenerResponse
from app.services.context_query import list_latest_context_per_series
from app.services.opportunities import list_opportunities, list_ranked_screener

router = APIRouter(prefix="/screener", tags=["screener"])
# Stesso contratto di GET /screener/opportunities, path breve per client e script.
opportunities_alias_router = APIRouter(tags=["screener"])


@dataclass
class OpportunityQueryParams:
    """Parametri condivisi tra /screener/opportunities e /opportunities (alias).

    Usato come Depends() per evitare la duplicazione dei 13 parametri Query
    nei due handler. FastAPI espone correttamente i parametri nello schema OpenAPI.
    """

    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair. Omit for all series.",
    )
    exchange: str | None = Query(
        default=None,
        description="Filter by venue (e.g. binance, YAHOO_US). Omit for all venues.",
    )
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    )
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    )
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe. Omit for all timeframes.",
    )
    limit: int = Query(default=100, ge=1, le=1000)
    decision: str | None = Query(
        default=None,
        description=(
            "Filtro semaforo: execute | monitor | discard, oppure IT "
            "(operabile, da_monitorare, scartare). Alias: operable → execute."
        ),
    )
    min_confluence: int | None = Query(
        default=None,
        ge=1,
        le=10,
        description=(
            "Override soglia confluenza: numero minimo di pattern validati distinti "
            "nella stessa barra per promuovere il segnale a 'execute'. "
            "Default: valore globale SIGNAL_MIN_CONFLUENCE (attualmente 2). "
            "Usa 1 per disabilitare il filtro."
        ),
    )


async def _opportunities_response(
    session: AsyncSession,
    params: OpportunityQueryParams,
) -> OpportunitiesResponse:
    rows = await list_opportunities(
        session,
        symbol=params.symbol,
        exchange=params.exchange,
        provider=params.provider,
        asset_type=params.asset_type,
        timeframe=params.timeframe,
        limit=params.limit,
        decision=params.decision,
        min_confluence_patterns=params.min_confluence,
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
    params: OpportunityQueryParams = Depends(),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunitiesResponse:
    return await _opportunities_response(session, params)


@opportunities_alias_router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities_short_path(
    params: OpportunityQueryParams = Depends(),
    session: AsyncSession = Depends(get_db_session),
) -> OpportunitiesResponse:
    return await _opportunities_response(session, params)

# ── Executed signals ──────────────────────────────────────────────────────────

class ExecutedSignalRow(BaseModel):
    id: int
    symbol: str
    timeframe: str
    provider: str
    exchange: str
    direction: str
    pattern_name: str
    pattern_strength: Optional[float]
    opportunity_score: Optional[float]
    entry_price: float
    stop_price: float
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    quantity_tp1: Optional[float]
    entry_order_id: Optional[int]
    tp_order_id: Optional[int]
    sl_order_id: Optional[int]
    tws_status: str
    error: Optional[str]
    executed_at: datetime

    class Config:
        from_attributes = True


class ExecutedSignalsResponse(BaseModel):
    signals: list[ExecutedSignalRow]
    count: int


@router.get("/executed-signals", response_model=ExecutedSignalsResponse)
async def get_executed_signals(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutedSignalsResponse:
    stmt = select(ExecutedSignal).order_by(desc(ExecutedSignal.executed_at)).limit(limit)
    if symbol:
        stmt = stmt.where(ExecutedSignal.symbol == symbol.strip().upper())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return ExecutedSignalsResponse(
        signals=[ExecutedSignalRow.model_validate(r) for r in rows],
        count=len(rows),
    )