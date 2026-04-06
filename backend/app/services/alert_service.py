"""
Alert service — invia notifiche Telegram e Discord quando vengono rilevati pattern di qualità.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.hour_filters import EXCLUDED_HOURS_UTC_YAHOO, hour_utc

# Universo Yahoo validato (top 6): `VALIDATED_SYMBOLS_YAHOO` in
# `trade_plan_variant_constants.py` — usato da `opportunity_validator` sulle opportunità.

logger = logging.getLogger(__name__)

DIRECTION_EMOJI = {"bullish": "🟢", "bearish": "🔴"}
REGIME_EMOJI = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}


def _strength_label(strength: float) -> str:
    if strength >= 0.80:
        return "⭐ ECCELLENTE"
    if strength >= 0.70:
        return "🔥 ALTO"
    if strength >= 0.60:
        return "✅ BUONO"
    return "⚠️ MARGINALE"


def _format_price(price: float | None) -> str:
    if price is None:
        return "N/A"
    if price > 1000:
        return f"${price:,.2f}"
    if price > 10:
        return f"${price:.2f}"
    return f"${price:.4f}"


def _channels_configured() -> bool:
    return bool(
        (settings.telegram_bot_token and settings.telegram_chat_id)
        or settings.discord_webhook_url
    )


def pattern_alert_channels_configured() -> bool:
    """True se almeno Telegram o Discord è configurato per gli alert outbound."""
    return _channels_configured()


_sent_alerts: set[str] = set()


def _alert_key(symbol: str, timeframe: str, pattern_name: str, ts: datetime) -> str:
    hour = ts.astimezone(timezone.utc).strftime("%Y%m%d%H")
    return f"{symbol}:{timeframe}:{pattern_name}:{hour}"


def build_alert_message(
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str,
    direction: str,
    strength: float,
    quality_score: float | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit_1: float | None,
    take_profit_2: float | None,
    regime_label: str,
    cvd_trend: str | None,
    funding_bias: str | None,
    timestamp: datetime,
) -> str:
    dir_emoji = DIRECTION_EMOJI.get(direction, "⚪")
    regime_em = REGIME_EMOJI.get(regime_label, "➡️")
    strength_lbl = _strength_label(strength)

    regime_aligned = (
        (direction == "bullish" and regime_label == "bullish")
        or (direction == "bearish" and regime_label == "bearish")
        or regime_label == "neutral"
    )
    regime_status = "✅ allineato" if regime_aligned else "⚠️ contro-trend"

    rr_text = ""
    if entry_price and stop_loss and take_profit_1:
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit_1 - entry_price)
        if risk > 0:
            rr = reward / risk
            rr_text = f"R/R: {rr:.1f}:1"

    context_parts: list[str] = []
    if cvd_trend:
        context_parts.append(f"CVD: {cvd_trend}")
    if funding_bias and provider == "binance":
        context_parts.append(f"Funding: {funding_bias}")
    context_str = " | ".join(context_parts) if context_parts else ""

    pattern_display = pattern_name.replace("_", " ").title()
    ts_utc = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    ts_str = ts_utc.strftime("%d/%m/%Y %H:%M UTC")

    msg = f"""{dir_emoji} **{direction.upper()} — {symbol} {timeframe}**
📊 Pattern: `{pattern_display}`
{strength_lbl} | Strength: {strength:.2f}
{regime_em} Regime: {regime_status}
🕐 {ts_str}

💰 Entry:  {_format_price(entry_price)}
🛑 Stop:   {_format_price(stop_loss)}
🎯 TP1:    {_format_price(take_profit_1)}
🎯 TP2:    {_format_price(take_profit_2)}
{rr_text}"""

    if context_str:
        msg += f"\n📈 {context_str}"

    if quality_score is not None:
        msg += f"\n🏆 Qualità: {quality_score:.1f}/100"

    if not regime_aligned:
        msg += "\n\n⚠️ _Segnale contro il trend di mercato — usare con cautela_"

    return msg


async def send_telegram(message: str) -> bool:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                },
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Telegram alert failed: %s", exc)
        return False


async def send_discord(message: str) -> bool:
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        return False

    discord_msg = message
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                webhook_url,
                json={
                    "content": discord_msg,
                    "username": "IntraDay Screener",
                    "avatar_url": "https://cdn-icons-png.flaticon.com/512/2942/2942289.png",
                },
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Discord alert failed: %s", exc)
        return False


async def send_alert(
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str,
    direction: str,
    strength: float,
    quality_score: float | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit_1: float | None,
    take_profit_2: float | None,
    regime_label: str = "neutral",
    cvd_trend: str | None = None,
    funding_bias: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    if not _channels_configured():
        return

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    if provider == "yahoo_finance" and hour_utc(timestamp) in EXCLUDED_HOURS_UTC_YAHOO:
        logger.info(
            "Alert soppresso — ora %d UTC non operativa (Yahoo)",
            hour_utc(timestamp),
        )
        return

    if strength < settings.alert_min_strength:
        return

    if quality_score is not None and quality_score < settings.alert_min_quality_score:
        return

    if settings.alert_regime_filter:
        regime_aligned = (
            (direction == "bullish" and regime_label == "bullish")
            or (direction == "bearish" and regime_label == "bearish")
            or regime_label == "neutral"
        )
        if not regime_aligned:
            return

    message = build_alert_message(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        pattern_name=pattern_name,
        direction=direction,
        strength=strength,
        quality_score=quality_score,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        regime_label=regime_label,
        cvd_trend=cvd_trend,
        funding_bias=funding_bias,
        timestamp=timestamp,
    )

    results = await asyncio.gather(
        send_telegram(message),
        send_discord(message),
        return_exceptions=True,
    )

    channels_sent = sum(1 for r in results if r is True)
    if channels_sent > 0:
        logger.info(
            "Alert inviato su %d canali: %s %s %s",
            channels_sent,
            symbol,
            timeframe,
            pattern_name,
        )


async def send_alert_deduped(
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str,
    direction: str,
    strength: float,
    quality_score: float | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit_1: float | None,
    take_profit_2: float | None,
    regime_label: str = "neutral",
    cvd_trend: str | None = None,
    funding_bias: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    key = _alert_key(symbol, timeframe, pattern_name, timestamp)
    if key in _sent_alerts:
        return
    _sent_alerts.add(key)
    if len(_sent_alerts) > 1000:
        _sent_alerts.clear()

    await send_alert(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        pattern_name=pattern_name,
        direction=direction,
        strength=strength,
        quality_score=quality_score,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        regime_label=regime_label,
        cvd_trend=cvd_trend,
        funding_bias=funding_bias,
        timestamp=timestamp,
    )
