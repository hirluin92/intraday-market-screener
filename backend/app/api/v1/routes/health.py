import logging
from datetime import datetime, timezone

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
from app.core.hour_filters import EXCLUDED_HOURS_UTC_LSE
from app.core.trade_plan_variant_constants import (
    DATA_COLLECTION_SYMBOLS_UK,
    SCHEDULER_SYMBOLS_BINANCE_1D_REGIME,
    SCHEDULER_SYMBOLS_BINANCE_1H,
    SCHEDULER_SYMBOLS_YAHOO_1H,
    SIGNAL_MIN_STRENGTH,
    VALIDATED_SYMBOLS_UK,
)
from app.schemas.settings_public import PublicSettingsResponse
from app.services.tws_service import get_tws_service

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
        alert_min_strength=settings.alert_min_strength,
        signal_min_strength=SIGNAL_MIN_STRENGTH,
    )


@router.get("/health/ibkr")
async def ibkr_health() -> dict:
    """
    Stato della connessione IBKR/TWS (ib_insync).

    Returns:
        - status        : "connected" | "disconnected" | "error" | "disabled"
        - last_heartbeat: ISO timestamp — ora corrente se connesso, None altrimenti
        - account_id    : account IBKR attivo se connesso, None altrimenti
        - error_message : dettaglio se non connesso
    """
    tws = get_tws_service()
    if tws is None:
        return {
            "status": "disabled",
            "last_heartbeat": None,
            "account_id": None,
            "error_message": "TWS service non abilitato (TWS_ENABLED=false o ib_insync non installato)",
        }
    try:
        info = tws.connection_status()
        last_heartbeat = (
            datetime.now(timezone.utc).isoformat() if info["status"] == "connected" else None
        )
        return {
            "status": info["status"],
            "last_heartbeat": last_heartbeat,
            "account_id": info["account_id"],
            "error_message": info["error_message"],
        }
    except Exception as exc:
        logger.exception("ibkr_health check error")
        return {
            "status": "error",
            "last_heartbeat": None,
            "account_id": None,
            "error_message": str(exc),
        }


@router.post("/cache/invalidate")
async def invalidate_opportunity_lookup_caches() -> dict[str, str]:
    """Svuota le cache dei lookup backtest usati da GET opportunities (dopo modifiche al DB o test)."""
    await pattern_quality_cache.invalidate_all()
    await trade_plan_backtest_cache.invalidate_all()
    await variant_best_cache.invalidate_all()
    return {"status": "ok", "message": "Cache lookup opportunità svuotate"}


@router.get("/health/uk-status")
async def uk_market_status(session: AsyncSession = Depends(get_db_session)) -> dict:
    """
    Stato del mercato UK (London Stock Exchange) e verifica connessione IBKR/TWS.

    Ritorna:
      - enable_uk_market: flag config (ENABLE_UK_MARKET)
      - uk_auto_execute_enabled: flag auto-execute UK (default False)
      - uk_symbols_count: totale simboli FTSE100 nell'universo configurato
      - uk_validated_symbols_count: simboli UK con edge OOS validato (ora 0)
      - lse_excluded_hours_utc: ore UTC escluse dalla sessione LSE
      - tws_uk_test: test live prezzo AZN su LSE via TWS
        - ok: True se TWS risponde e AZN restituisce un prezzo
        - last_price: prezzo live (in pence, es. 12450 = £124.50)
        - error: messaggio errore se ok=False (es. "subscription required")
    """
    from app.core.uk_universe import UK_SYMBOLS_FTSE100_TOP30  # noqa: PLC0415

    tws = get_tws_service()
    tws_test: dict = {
        "symbol": "AZN",
        "exchange": "LSE",
        "currency": "GBP",
        "last_price": None,
        "ok": False,
        "error": None,
    }

    if tws is None or not tws._connected:
        tws_test["error"] = (
            "TWS non connesso (TWS_ENABLED=false o gateway non raggiungibile). "
            "Abilitare TWS e verificare connessione prima di testare UK."
        )
    elif not settings.enable_uk_market:
        tws_test["error"] = "ENABLE_UK_MARKET=false — attivare prima di testare UK."
    else:
        try:
            price = await tws.get_last_price(
                symbol="AZN",
                timeout_s=4.0,
                exchange="LSE",
                currency="GBP",
            )
            if price is not None and price > 0:
                tws_test["last_price"] = price
                tws_test["ok"] = True
            else:
                tws_test["error"] = (
                    "TWS connesso ma AZN/LSE ha restituito prezzo None. "
                    "Probabile causa: abbonamento 'London Stock Exchange UK Bundle' non attivo "
                    "o mercato chiuso (nessun dato delayed). Verificare IBKR → Market Data Subscriptions."
                )
        except Exception as exc:
            tws_test["error"] = f"Errore durante il test TWS: {exc}"

    # Regime UK: legge snapshot ISF.L 1d da DB (fail-safe: nessuna eccezione propagata)
    uk_regime: dict = {"current": "no_data"}
    try:
        from app.services.uk_regime import get_uk_regime_snapshot  # noqa: PLC0415
        uk_regime = await get_uk_regime_snapshot(session)
    except Exception:
        logger.exception("uk_market_status: get_uk_regime_snapshot failed")
        uk_regime = {"current": "error", "anchor_symbol": "ISF.L"}

    return {
        "enable_uk_market": settings.enable_uk_market,
        "uk_auto_execute_enabled": getattr(settings, "uk_auto_execute_enabled", False),
        "uk_symbols_count": len(UK_SYMBOLS_FTSE100_TOP30),
        "uk_validated_symbols_count": len(VALIDATED_SYMBOLS_UK),
        "uk_data_collection_symbols_count": len(DATA_COLLECTION_SYMBOLS_UK),
        "lse_excluded_hours_utc": sorted(EXCLUDED_HOURS_UTC_LSE),
        "lse_operative_hours_utc": sorted(set(range(24)) - EXCLUDED_HOURS_UTC_LSE),
        "tws_uk_test": tws_test,
        "uk_regime": uk_regime,
    }


@router.get("/health/ibkr-historical")
async def test_ibkr_historical(
    symbol: str = "AAPL",
    timeframe: str = "1h",
    limit: int = 10,
) -> dict:
    """
    Test manuale: verifica che IBKR risponda a una richiesta di dati storici.

    Chiama tws_service.get_historical_candles e ritorna il numero di candele
    ricevute + timestamp prima/ultima. Usare prima di abilitare EQUITY_PROVIDER_1H=ibkr.

    Parametri:
      symbol:    ticker US (default AAPL)
      timeframe: 1h | 1d | 5m | 15m (default 1h)
      limit:     numero di barre da richiedere (default 10)
    """
    tws = get_tws_service()
    if not tws._connected:
        return {
            "status": "error",
            "message": "TWS non connesso — verificare TWS Gateway e TWS_ENABLED=true",
            "symbol": symbol,
            "timeframe": timeframe,
            "candles_received": 0,
        }

    try:
        bars = await tws.get_historical_candles(symbol=symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "symbol": symbol,
            "timeframe": timeframe,
            "candles_received": 0,
        }

    if not bars:
        return {
            "status": "empty",
            "message": "TWS ha risposto ma ha restituito 0 barre — verificare abbonamenti e simbolo",
            "symbol": symbol,
            "timeframe": timeframe,
            "candles_received": 0,
        }

    first_ts = bars[0].get("timestamp")
    last_ts = bars[-1].get("timestamp")
    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_received": len(bars),
        "first_timestamp": first_ts.isoformat() if hasattr(first_ts, "isoformat") else str(first_ts),
        "last_timestamp": last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts),
        "sample_close": bars[-1].get("close"),
    }
