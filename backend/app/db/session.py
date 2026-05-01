from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url_effective,
    echo=settings.sqlalchemy_echo,
    pool_pre_ping=True,
    # Picco connessioni con parallelismo=12:
    # 12 job × 3 sessioni (main + indicators_parallel + context_parallel) = 36 pipeline
    # + 5 per list_opportunities/prewarm/warmup = 41 totale.
    # pool_size=30 persistenti + max_overflow=15 overflow = 45 max.
    # Postgres max_connections=100 → margine ampio.
    pool_size=30,
    max_overflow=15,
    pool_timeout=30,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
