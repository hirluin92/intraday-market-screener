import logging

import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.pipeline import PipelineRefreshRequest, PipelineRefreshResponse
from app.services.pipeline_refresh import execute_pipeline_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/refresh", response_model=PipelineRefreshResponse)
async def pipeline_refresh(
    body: PipelineRefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PipelineRefreshResponse:
    """
    Synchronous MVP pipeline: ingest → features → indicators → context → patterns with shared filters.
    """
    try:
        return await execute_pipeline_refresh(session, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ccxt.BaseError as e:
        logger.exception("pipeline refresh: ccxt exchange error during ingest")
        raise HTTPException(status_code=502, detail=str(e)) from e
