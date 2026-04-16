import logging
from datetime import datetime, timezone

import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.candle_pattern import CandlePattern
from app.schemas.pipeline import PipelineRefreshRequest, PipelineRefreshResponse
from app.services.pipeline_refresh import execute_pipeline_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/status")
async def pipeline_status(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Stato ultimo run della pipeline.

    Deriva l'ultimo run dal timestamp più recente in candle_patterns:
    se esistono pattern creati da meno di 10 minuti → pipeline "recente".
    Ritorna:
    - last_run_at: ISO timestamp ultimo run (null se nessun pattern in DB)
    - status: "ok" | "stale" | "unknown"
    - age_minutes: minuti trascorsi dall'ultimo run (null se sconosciuto)
    - in_progress: sempre False (APScheduler non espone stato sincrono via API)
    """
    stmt = select(func.max(CandlePattern.created_at))
    last_run_at: datetime | None = (await session.execute(stmt)).scalar_one_or_none()

    if last_run_at is None:
        return {"last_run_at": None, "status": "unknown", "age_minutes": None, "in_progress": False}

    # Assicura timezone-aware
    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - last_run_at).total_seconds()
    age_minutes = round(age_seconds / 60, 1)
    status = "ok" if age_minutes <= 10 else "stale"

    return {
        "last_run_at": last_run_at.isoformat(),
        "status": status,
        "age_minutes": age_minutes,
        "in_progress": False,
    }


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
