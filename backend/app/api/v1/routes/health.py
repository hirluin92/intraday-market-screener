import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    """Liveness/readiness: verifies PostgreSQL connectivity."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("database health check failed")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "database": "ok"}
