from fastapi import APIRouter

from app.api.v1.routes.alerts import router as alerts_router
from app.api.v1.routes.analysis import router as analysis_router
from app.api.v1.routes.backtest import router as backtest_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.ibkr import router as ibkr_router
from app.api.v1.routes.market_data import router as market_data_router
from app.api.v1.routes.monitoring import router as monitoring_router
from app.api.v1.routes.performance import router as performance_router
from app.api.v1.routes.pipeline import router as pipeline_router
from app.api.v1.routes.screener import (
    opportunities_alias_router,
    router as screener_router,
)

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(ibkr_router)
api_router.include_router(market_data_router)
api_router.include_router(pipeline_router)
api_router.include_router(screener_router)
api_router.include_router(opportunities_alias_router)
api_router.include_router(backtest_router)
api_router.include_router(alerts_router)
api_router.include_router(monitoring_router)
api_router.include_router(performance_router)
api_router.include_router(analysis_router)