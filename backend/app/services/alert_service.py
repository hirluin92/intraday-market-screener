"""
Alert service — invia notifiche Telegram e Discord quando vengono rilevati pattern di qualità.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.trade_plan_variant_constants import SIGNAL_MIN_STRENGTH
from app.core.hour_filters import EXCLUDED_HOURS_UTC_YAHOO, hour_utc
from app.db.session import AsyncSessionLocal
from app.models.alert_sent import AlertSent

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
    if strength >= SIGNAL_MIN_STRENGTH:
        return "✅ BUONO"
    return "⚠️ MARGINALE"


def build_opportunities_deep_link(
    symbol: str,
    timeframe: str,
    provider: str,
    exchange: str | None = None,
) -> str:
    """URL `/opportunities` con query per espandere la card nel frontend."""
    base = (settings.alert_frontend_base_url or "").strip().rstrip("/") or "http://localhost:3000"
    q: dict[str, str] = {
        "symbol": symbol.strip(),
        "timeframe": timeframe.strip(),
        "expand": "true",
        "provider": provider.strip(),
    }
    ex = (exchange or "").strip()
    if ex:
        q["exchange"] = ex

    def _q_part(s: str) -> str:
        # quote() non codifica mai `_` (RFC “safe”); Telegram Markdown interpreta `_` come corsivo.
        return quote(s, safe="").replace("_", "%5F")

    pairs = [f"{_q_part(str(k))}={_q_part(str(v))}" for k, v in q.items()]
    return f"{base}/opportunities?{'&'.join(pairs)}"


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


def _bar_hour_key(timestamp: datetime) -> str:
    """Chiave ora-barra UTC per deduplicazione (stesso bucket del vecchio _alert_key)."""
    ts = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(
        tzinfo=timezone.utc,
    )
    return ts.strftime("%Y%m%d%H")


async def _try_claim_alert(
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str,
    direction: str,
    timestamp: datetime,
) -> bool:
    """
    Gate atomico anti-duplicato: tenta un INSERT ... ON CONFLICT DO NOTHING RETURNING id.

    Ritorna True  se la riga e' stata inserita (= questo worker ha acquisito il diritto di inviare).
    Ritorna False se era gia' presente (= alert gia' inviato da un altro worker/chiamata).

    Non esiste una SELECT separata: la lettura e la scrittura avvengono in un'unica operazione
    atomica DB, eliminando la race condition read-then-write.

    In caso di errore DB logga un warning e ritorna True (fail-open: meglio un duplicato
    occasionale che nessun alert).
    """
    bar_key = _bar_hour_key(timestamp)
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                pg_insert(AlertSent)
                .values(
                    symbol=symbol,
                    timeframe=timeframe,
                    provider=provider,
                    pattern_name=pattern_name,
                    direction=direction,
                    bar_hour_utc=bar_key,
                    telegram_ok=False,
                    discord_ok=False,
                )
                .on_conflict_do_nothing(constraint="uq_alert_sent_dedup")
                .returning(AlertSent.id)
            )
            result = await session.execute(stmt)
            await session.commit()
            inserted_id = result.scalar_one_or_none()
            return inserted_id is not None
    except Exception as exc:
        logger.warning("alert dedupe DB claim failed — allow send (fail-open): %s", exc)
        return True


async def cleanup_old_alerts(days_to_keep: int = 7) -> int:
    """
    Rimuove righe più vecchie di N giorni (sent_at).
    Ritorna il numero di righe eliminate.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    try:
        async with AsyncSessionLocal() as session:
            stmt = delete(AlertSent).where(AlertSent.sent_at < cutoff)
            result = await session.execute(stmt)
            await session.commit()
            deleted = int(result.rowcount or 0)
            if deleted > 0:
                logger.info(
                    "Cleanup alerts_sent: eliminati %d record più vecchi di %d giorni",
                    deleted,
                    days_to_keep,
                )
            return deleted
    except Exception as exc:
        logger.warning("cleanup_old_alerts failed: %s", exc)
        return 0


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
    *,
    exchange: str | None = None,
) -> str:
    dir_emoji = DIRECTION_EMOJI.get(direction, "⚪")
    regime_em = REGIME_EMOJI.get(regime_label, "➡️")
    strength_lbl = _strength_label(strength)

    if provider == "binance":
        regime_aligned = True
        regime_em = "ℹ️"
        regime_status = "filtro regime non applicato (crypto)"
    else:
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

    if provider == "binance":
        msg += "\n\n📌 Crypto — regime filter non applicato (edge indipendente da BTC)"

    deep_link = build_opportunities_deep_link(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        exchange=exchange,
    )
    # URL su riga propria (Telegram lo rende cliccabile). Evitare [testo](url): con Markdown
    # i `_` nei query param (es. yahoo_finance) spezzano il parsing se non sono percent-encoded.
    msg += f"\n\n📊 Vedi opportunità:\n{deep_link}"

    return msg


def build_alert_message_telegram_plain(
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
    *,
    exchange: str | None = None,
) -> str:
    """
    Testo senza parse_mode (né Markdown né HTML): Telegram rileva gli URL http/https come link.
    Evita errori «can't parse entities» e href su localhost che con HTML possono far fallire l'invio.
    """
    dir_emoji = DIRECTION_EMOJI.get(direction, "⚪")
    regime_em = REGIME_EMOJI.get(regime_label, "➡️")
    strength_lbl = _strength_label(strength)

    if provider == "binance":
        regime_aligned = True
        regime_em = "ℹ️"
        regime_status = "filtro regime non applicato (crypto)"
    else:
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

    msg = f"""{dir_emoji} {direction.upper()} — {symbol} {timeframe}
📊 Pattern: {pattern_display}
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
        msg += "\n\n⚠️ Segnale contro il trend di mercato — usare con cautela"

    if provider == "binance":
        msg += "\n\n📌 Crypto — regime filter non applicato (edge indipendente da BTC)"

    deep_link = build_opportunities_deep_link(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        exchange=exchange,
    )
    msg += f"\n\n📊 Apri opportunità (tap sull'URL):\n{deep_link}"

    return msg


async def send_telegram(message_plain: str) -> bool:
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
                    "text": message_plain,
                    "disable_web_page_preview": True,
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
    exchange: str | None = None,
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

    if settings.alert_regime_filter and provider != "binance":
        regime_aligned = (
            (direction == "bullish" and regime_label == "bullish")
            or (direction == "bearish" and regime_label == "bearish")
            or regime_label == "neutral"
        )
        if not regime_aligned:
            return

    message_md = build_alert_message(
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
        exchange=exchange,
    )
    message_telegram = build_alert_message_telegram_plain(
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
        exchange=exchange,
    )

    results = await asyncio.gather(
        send_telegram(message_telegram),
        send_discord(message_md),
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
    exchange: str | None = None,
) -> bool:
    """
    Invia alert con deduplicazione persistente su DB.
    Ritorna True se non era un duplicato e la pipeline è stata eseguita (invio o early-return in send_alert).
    False se già in DB per questa barra.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    claimed = await _try_claim_alert(
        symbol,
        timeframe,
        provider,
        pattern_name,
        direction,
        timestamp,
    )
    if not claimed:
        logger.debug(
            "Alert gia' inviato (DB gate atomico): %s %s %s %s",
            symbol,
            timeframe,
            pattern_name,
            direction,
        )
        return False

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
        exchange=exchange,
    )
    return True