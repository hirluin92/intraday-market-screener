"""
Database bootstrap: crea le tabelle mancanti via SQLAlchemy metadata se necessario.

In DEVELOPMENT e TEST usa ``create_all`` (no-op se le tabelle esistono gia').
In PRODUCTION e' preferibile affidarsi ad Alembic (``alembic upgrade head``) prima
dell'avvio del server; ``create_all`` resta come fallback di sicurezza ma emette
un WARNING per ricordare che lo schema deve essere governato da migrazioni.

Workflow Alembic:
    # Prima migrazione (baseline gia' generata in alembic/versions/)
    alembic upgrade head

    # Dopo ogni modifica ai model ORM
    alembic revision --autogenerate -m "descrizione_cambiamento"
    alembic upgrade head
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.db.base import Base

logger = logging.getLogger(__name__)


def _import_models() -> None:
    """Import model packages so all tables are registered on ``Base.metadata``."""
    import app.models  # noqa: F401


def _create_all_tables(sync_conn) -> None:
    Base.metadata.create_all(sync_conn, checkfirst=True)


async def create_tables(engine: AsyncEngine) -> None:
    """
    Ensure all ORM tables exist.

    In production, run ``alembic upgrade head`` before starting the server instead
    of relying on this function to apply schema changes.
    """
    _import_models()
    if settings.environment == "production":
        logger.warning(
            "bootstrap: create_all attivo in PRODUCTION — "
            "preferire 'alembic upgrade head' per gestire migrazioni in modo controllato"
        )
    async with engine.begin() as conn:
        await conn.run_sync(_create_all_tables)
    logger.info("database tables ensured (create_all, checkfirst=True)")
