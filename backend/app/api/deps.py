from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.services.market_data_ingestion import MarketDataIngestionService


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_market_data_ingestion_service() -> MarketDataIngestionService:
    """New service instance per request (no module-level singleton)."""
    return MarketDataIngestionService()
