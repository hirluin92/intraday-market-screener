"""
Canonical alert channel helpers — single source of truth for Telegram and Discord sends.

Used by alert_service and alert_notifications. Do not duplicate these functions elsewhere.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DISCORD_CONTENT_MAX = 1900
TELEGRAM_TEXT_MAX = 4000


def _channels_configured() -> bool:
    return bool(settings.discord_webhook_url.strip()) or (
        bool(settings.telegram_bot_token.strip()) and bool(settings.telegram_chat_id.strip())
    )


def _discord_configured() -> bool:
    return bool(settings.discord_webhook_url.strip())


def _telegram_configured() -> bool:
    return bool(settings.telegram_bot_token.strip()) and bool(settings.telegram_chat_id.strip())


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n… (troncato)"


def _response_body_snippet(response: httpx.Response | None, max_len: int = 500) -> str:
    if response is None:
        return ""
    try:
        t = (response.text or "").strip()
    except Exception:
        return "(body unreadable)"
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


async def send_discord(text: str) -> bool:
    url = settings.discord_webhook_url.strip()
    if not url:
        logger.info("alert_channels: Discord send skipped (webhook not configured)")
        return True
    payload = {"content": _truncate(text, DISCORD_CONTENT_MAX)}
    logger.info("alert_channels: sending via Discord webhook")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        logger.info("alert_channels: Discord send success http_status=%s", r.status_code)
        return True
    except httpx.HTTPStatusError as e:
        snippet = _response_body_snippet(e.response)
        logger.error(
            "alert_channels: Discord send failed http_status=%s body=%s",
            e.response.status_code,
            snippet or "(empty)",
        )
        return False
    except httpx.RequestError as e:
        logger.error("alert_channels: Discord send failed request_error=%s", e)
        return False


async def send_telegram(text: str) -> bool:
    token = settings.telegram_bot_token.strip()
    chat = settings.telegram_chat_id.strip()
    if not token or not chat:
        logger.info(
            "alert_channels: Telegram send skipped (bot token or chat id not configured)",
        )
        return True
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": _truncate(text, TELEGRAM_TEXT_MAX)}
    logger.info("alert_channels: sending via Telegram sendMessage")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(api, json=payload)
            r.raise_for_status()
        logger.info("alert_channels: Telegram send success http_status=%s", r.status_code)
        return True
    except httpx.HTTPStatusError as e:
        snippet = _response_body_snippet(e.response)
        logger.error(
            "alert_channels: Telegram send failed http_status=%s body=%s",
            e.response.status_code,
            snippet or "(empty)",
        )
        return False
    except httpx.RequestError as e:
        logger.error("alert_channels: Telegram send failed request_error=%s", e)
        return False
