import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.bootstrap import create_tables
from app.db.session import AsyncSessionLocal, engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: create missing tables via SQLAlchemy metadata (no Alembic migrations yet).
    await create_tables(engine)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        logger.info("database startup check passed")
    except Exception:
        logger.exception("database startup check failed")
        raise
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="intraday-market-screener API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
