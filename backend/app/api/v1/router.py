from fastapi import APIRouter

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.market_data import router as market_data_router
from app.api.v1.routes.screener import router as screener_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(market_data_router)
api_router.include_router(screener_router)
