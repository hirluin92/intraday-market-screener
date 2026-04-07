import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.cache import (
    all_opportunity_lookup_cache_stats,
    pattern_quality_cache,
    trade_plan_backtest_cache,
    variant_best_cache,
)
from app.core.config import settings
from app.core.trade_plan_variant_constants import (
    SCHEDULER_SYMBOLS_BINANCE_1D_REGIME,
    SCHEDULER_SYMBOLS_BINANCE_1H,
    SCHEDULER_SYMBOLS_YAHOO_1H,
)
from app.schemas.settings_public import PublicSettingsResponse

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


@router.get("/settings", response_model=PublicSettingsResponse)
async def public_settings() -> PublicSettingsResponse:
    """
    Config non sensibile (nessun token/webhook) per verifica da script o health check esteso.
    """
    cache_stats = await all_opportunity_lookup_cache_stats()
    scheduler_universe = {
        "yahoo_1h_count": len(SCHEDULER_SYMBOLS_YAHOO_1H),
        "binance_1h_count": len(SCHEDULER_SYMBOLS_BINANCE_1H),
        "binance_1d_regime_count": len(SCHEDULER_SYMBOLS_BINANCE_1D_REGIME),
        "total_symbols": len(SCHEDULER_SYMBOLS_YAHOO_1H)
        + len(SCHEDULER_SYMBOLS_BINANCE_1H)
        + len(SCHEDULER_SYMBOLS_BINANCE_1D_REGIME),
    }
    base_fe = (settings.alert_frontend_base_url or "").strip() or "http://localhost:3000"
    return PublicSettingsResponse(
        environment=settings.environment,
        alert_notifications_enabled=settings.alert_notifications_enabled,
        alert_legacy_enabled=settings.alert_legacy_enabled,
        alert_include_media_priorita=settings.alert_include_media_priorita,
        pipeline_scheduler_enabled=settings.pipeline_scheduler_enabled,
        frontend_base_url=base_fe,
        scheduler_universe=scheduler_universe,
        cache_stats=cache_stats,
    )


@router.post("/cache/invalidate")
async def invalidate_opportunity_lookup_caches() -> dict[str, str]:
    """Svuota le cache dei lookup backtest usati da GET opportunities (dopo modifiche al DB o test)."""
    await pattern_quality_cache.invalidate_all()
    await trade_plan_backtest_cache.invalidate_all()
    await variant_best_cache.invalidate_all()
    return {"status": "ok", "message": "Cache lookup opportunità svuotate"}
