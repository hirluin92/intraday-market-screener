from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.services.alert_service import (
    build_opportunities_deep_link,
    pattern_alert_channels_configured,
    send_alert,
    send_alert_deduped,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/test")
async def test_alert(
    symbol: str = Query(default="SPY"),
    timeframe: str = Query(default="1h"),
    pattern_name: str = Query(default="compression_to_expansion_transition"),
    direction: str = Query(default="bearish"),
    exchange: str | None = Query(default=None, description="Venue opzionale per deep link (Yahoo: es. YAHOO_US)"),
    force: bool = Query(
        default=False,
        description="Se true, invia sempre senza dedup (ripetere test / vedere di nuovo Telegram).",
    ),
) -> dict[str, object]:
    """Invia un alert di test su tutti i canali configurati."""
    deep_link = build_opportunities_deep_link(
        symbol=symbol,
        timeframe=timeframe,
        provider="yahoo_finance",
        exchange=exchange,
    )
    link_meta = {
        "deep_link": deep_link,
        "message": f"Deep link opportunita: {deep_link}",
        "message_includes_opportunities_link": "/opportunities" in deep_link,
    }
    if not pattern_alert_channels_configured():
        return {
            "status": "nessun canale configurato (TELEGRAM_* e/o DISCORD_WEBHOOK_URL)",
            "channels": [],
            **link_meta,
        }
    ts = datetime.now(timezone.utc)

    if force:
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
            timestamp=ts,
            exchange=exchange,
        )
        return {
            "status": "alert inviato (force, senza dedup)",
            "deduplicated": False,
            "forced": True,
            "channels": ["telegram", "discord"],
            **link_meta,
        }

    sent = await send_alert_deduped(
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
        timestamp=ts,
        exchange=exchange,
    )
    if not sent:
        return {
            "status": "già inviato (dedup)",
            "deduplicated": True,
            "channels": [],
            **link_meta,
        }
    return {
        "status": "alert inviato",
        "deduplicated": False,
        "channels": ["telegram", "discord"],
        **link_meta,
    }
