"""MVP database bootstrap without Alembic.

Uses ``Base.metadata.create_all`` inside the FastAPI lifespan so tables exist before
handling traffic. This is **non-destructive**: existing tables are left unchanged;
``checkfirst=True`` skips creation when a table already exists.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base

logger = logging.getLogger(__name__)


def _import_models() -> None:
    """Import model packages so all tables are registered on ``Base.metadata``."""
    import app.models  # noqa: F401


def _create_all_tables(sync_conn) -> None:
    Base.metadata.create_all(sync_conn, checkfirst=True)


async def create_tables(engine: AsyncEngine) -> None:
    """Ensure all ORM tables exist (MVP DDL). Safe to call on every startup."""
    _import_models()
    async with engine.begin() as conn:
        await conn.run_sync(_create_all_tables)
    logger.info("database tables ensured (create_all, checkfirst=True)")
