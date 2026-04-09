import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging_config import configure_application_logging
from app.db.bootstrap import create_tables
from app.db.session import AsyncSessionLocal, engine
from app.scheduler.pipeline_scheduler import (
    shutdown_pipeline_scheduler,
    start_pipeline_scheduler,
)

logger = logging.getLogger(__name__)


async def _warmup_caches() -> None:
    """
    Pre-calcola le cache principali in background subito dopo lo startup,
    così la prima richiesta del frontend trova già tutto pronto (~7s invece di ~68s).
    """
    try:
        logger.info("Cache warmup: avvio in background...")
        from app.core.cache import (
            opportunity_lookup_key,
            pattern_quality_cache,
            trade_plan_backtest_cache,
            variant_best_cache,
        )
        from app.core.trade_plan_variant_constants import BACKTEST_TOTAL_COST_RATE_DEFAULT
        from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
        from app.services.trade_plan_backtest import trade_plan_backtest_lookup_by_bucket
        from app.services.trade_plan_live_variant import (
            LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
            load_best_variant_lookup_for_live,
        )

        pq_key = opportunity_lookup_key("pq", symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None)
        tpb_key = opportunity_lookup_key("tpb", symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None, cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT)
        var_key = opportunity_lookup_key("var", symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None, cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT, limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT)

        async def _pq():
            async with AsyncSessionLocal() as s:
                return await pattern_quality_lookup_by_name_tf(s, symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None)

        async def _tpb():
            async with AsyncSessionLocal() as s:
                return await trade_plan_backtest_lookup_by_bucket(s, symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None, cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT)

        async def _var():
            async with AsyncSessionLocal() as s:
                return await load_best_variant_lookup_for_live(s, symbol=None, exchange=None, provider=None, asset_type=None, timeframe=None, limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT, cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT)

        await asyncio.gather(
            pattern_quality_cache.get_or_compute(pq_key, _pq),
            trade_plan_backtest_cache.get_or_compute(tpb_key, _tpb),
            variant_best_cache.get_or_compute(var_key, _var),
            return_exceptions=True,
        )
        logger.info("Cache warmup: pq, tpb, var pre-calcolate")

        # Pre-scarica VIX history (evita download lento alla prima richiesta frontend)
        try:
            from app.services.opportunities import _get_vix_history  # noqa: PLC0415
            await _get_vix_history()
            logger.info("Cache warmup: VIX history pre-caricata")
        except Exception:
            logger.debug("Cache warmup: VIX skip")

        logger.info("Cache warmup: completato")
    except Exception:
        logger.exception("Cache warmup: fallito (non bloccante)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_application_logging()
    logger.info("application startup begin")

    # MVP: create missing tables via SQLAlchemy metadata (no Alembic migrations yet).
    await create_tables(engine)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        logger.info("database startup check passed")
    except Exception:
        logger.exception("database startup check failed")
        raise

    logger.info("scheduler startup invoked")
    start_pipeline_scheduler()

    # Avvia warm-up cache in background senza bloccare lo startup
    asyncio.create_task(_warmup_caches())

    yield

    shutdown_pipeline_scheduler()
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="intraday-market-screener API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
