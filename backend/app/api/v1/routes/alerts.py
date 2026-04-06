from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.services.alert_service import pattern_alert_channels_configured, send_alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/test")
async def test_alert(
    symbol: str = Query(default="SPY"),
    timeframe: str = Query(default="1h"),
    pattern_name: str = Query(default="compression_to_expansion_transition"),
    direction: str = Query(default="bearish"),
) -> dict[str, object]:
    """Invia un alert di test su tutti i canali configurati."""
    if not pattern_alert_channels_configured():
        return {
            "status": "nessun canale configurato (TELEGRAM_* e/o DISCORD_WEBHOOK_URL)",
            "channels": [],
        }
    await send_alert(
        symbol=symbol,
        timeframe=timeframe,
        provider="yahoo_finance",
        pattern_name=pattern_name,
        direction=direction,
        strength=0.75,
        quality_score=62.5,
        entry_price=655.20,
        stop_loss=651.80,
        take_profit_1=660.10,
        take_profit_2=665.00,
        regime_label="bearish",
        cvd_trend="bearish",
        funding_bias=None,
        timestamp=datetime.now(timezone.utc),
    )
    return {"status": "alert inviato", "channels": ["telegram", "discord"]}
