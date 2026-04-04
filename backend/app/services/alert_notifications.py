"""
Outbound alert notifications v1 (MVP).

Dopo un pipeline refresh:

- **Mirato** (exchange + symbol + timeframe): come prima; idoneità con
  ``NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA`` per i test.
- **Globale** (nessun symbol e nessun timeframe nel body): elenca le opportunità per tutte le
  serie rilevanti e invia solo per ``alta_priorita`` (nessun media test).

Dedupe per (exchange, symbol, timeframe, context_timestamp) invariato.

Canali: Discord webhook e/o Telegram (variabili d'ambiente). Dedupe su DB per
(exchange, symbol, timeframe, context_timestamp).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.alert_notification_sent import AlertNotificationSent
from app.schemas.opportunities import OpportunityRow
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.opportunity_final_score import compute_signal_alignment
from app.services.opportunities import list_opportunities

logger = logging.getLogger(__name__)

HIGH_ALERT_LEVEL = "alta_priorita"
MEDIA_ALERT_LEVEL = "media_priorita"

# ---------------------------------------------------------------------------
# TEST NOTIFICHE — RIMUOVERE / METTERE False PER RIPRISTINARE SOLO alta_priorita
# Non tocca lo scoring delle opportunità, solo il gating di invio Discord/Telegram.
# ---------------------------------------------------------------------------
NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA = True

# Max righe opportunità considerate in un refresh globale (post-ordinamento score).
GLOBAL_NOTIFY_OPPORTUNITIES_LIMIT = 1000

DISCORD_CONTENT_MAX = 1900
TELEGRAM_TEXT_MAX = 4000


def _notification_eligible_for_outbound(opp: OpportunityRow) -> bool:
    """Solo gating invio: alta_priorita (produzione) e opzionalmente media_priorita (test)."""
    if not opp.alert_candidate:
        return False
    if opp.alert_level == HIGH_ALERT_LEVEL:
        return True
    if NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA and opp.alert_level == MEDIA_ALERT_LEVEL:
        return True
    return False


def _is_targeted_notify_request(body: PipelineRefreshRequest) -> bool:
    return bool(
        (body.exchange or "").strip()
        and (body.symbol or "").strip()
        and (body.timeframe or "").strip()
    )


def _is_global_notify_request(body: PipelineRefreshRequest) -> bool:
    """Refresh globale: nessun filtro symbol/timeframe (exchange opzionale)."""
    return not (body.symbol or "").strip() and not (body.timeframe or "").strip()


def _direction_it(v: str | None) -> str:
    if not v:
        return "—"
    m = {
        "bullish": "rialzista",
        "bearish": "ribassista",
        "neutral": "neutrale",
    }
    return m.get(v.lower().strip(), v)


def _alignment_it(score_direction: str, pattern_direction: str | None) -> str:
    a = compute_signal_alignment(score_direction, pattern_direction)
    return {
        "aligned": "allineato",
        "mixed": "misto",
        "conflicting": "conflittuale",
    }.get(a, a)


def _final_band_it(label: str) -> str:
    return {
        "strong": "eccellente",
        "moderate": "buono",
        "weak": "debole",
        "minimal": "minimo",
    }.get(label, label)


def _quality_band_it(label: str) -> str:
    return {
        "high": "alta",
        "medium": "media",
        "low": "bassa",
        "unknown": "sconosciuta",
    }.get(label, label)


def _detail_url(exchange: str, symbol: str, timeframe: str) -> str | None:
    base = (settings.alert_frontend_base_url or "").strip().rstrip("/")
    if not base:
        return None
    sym = quote(symbol, safe="")
    tf = quote(timeframe, safe="")
    ex = quote(exchange, safe="")
    return f"{base}/opportunities/{sym}/{tf}?exchange={ex}"


def _format_message(opp: OpportunityRow) -> str:
    pq = opp.pattern_quality_score
    pq_txt = f"{pq:.1f}" if pq is not None else "—"
    pat = opp.latest_pattern_name or "—"
    strength = opp.latest_pattern_strength
    if strength is not None:
        st_txt = f"{float(strength):.4f}" if isinstance(strength, Decimal) else str(strength)
    else:
        st_txt = "—"

    lines = [
        "🔔 Alert priorità alta — intraday screener",
        "",
        f"Simbolo: {opp.symbol}",
        f"Timeframe: {opp.timeframe}",
        f"Exchange: {opp.exchange}",
        "",
        f"Score finale: {opp.final_opportunity_score:.1f} ({_final_band_it(opp.final_opportunity_label)})",
        f"Etichetta score: {opp.score_label}",
        f"Direzione score: {_direction_it(opp.score_direction)}",
        "",
        f"Pattern: {pat}",
        f"Direzione pattern: {_direction_it(opp.latest_pattern_direction)}",
        f"Allineamento: {_alignment_it(opp.score_direction, opp.latest_pattern_direction)}",
        f"Qualità pattern: {_quality_band_it(opp.pattern_quality_label)} (score {pq_txt})",
        f"Forza pattern: {st_txt}",
    ]
    url = _detail_url(opp.exchange, opp.symbol, opp.timeframe)
    if url:
        lines.extend(["", f"Dettaglio: {url}"])
    else:
        lines.extend(
            [
                "",
                "Dettaglio: imposta ALERT_FRONTEND_BASE_URL per il link alla pagina serie.",
            ]
        )
    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n… (troncato)"


def _channels_configured() -> bool:
    return bool(settings.discord_webhook_url.strip()) or (
        bool(settings.telegram_bot_token.strip()) and bool(settings.telegram_chat_id.strip())
    )


def _discord_configured() -> bool:
    return bool(settings.discord_webhook_url.strip())


def _telegram_configured() -> bool:
    return bool(settings.telegram_bot_token.strip()) and bool(settings.telegram_chat_id.strip())


async def _already_sent(
    session: AsyncSession,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    context_timestamp,
) -> bool:
    stmt = (
        select(AlertNotificationSent.id)
        .where(
            AlertNotificationSent.exchange == exchange,
            AlertNotificationSent.symbol == symbol,
            AlertNotificationSent.timeframe == timeframe,
            AlertNotificationSent.context_timestamp == context_timestamp,
        )
        .limit(1)
    )
    r = await session.execute(stmt)
    return r.scalar_one_or_none() is not None


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


async def _send_discord(text: str) -> bool:
    url = settings.discord_webhook_url.strip()
    if not url:
        logger.info("alert_notifications: notification attempt skipped (Discord webhook not configured)")
        return True
    payload = {"content": _truncate(text, DISCORD_CONTENT_MAX)}
    logger.info("alert_notifications: notification attempt (Discord webhook)")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        logger.info(
            "alert_notifications: notification success (Discord) http_status=%s",
            r.status_code,
        )
        return True
    except httpx.HTTPStatusError as e:
        snippet = _response_body_snippet(e.response)
        logger.error(
            "alert_notifications: notification failed (Discord) http_status=%s body=%s",
            e.response.status_code,
            snippet or "(empty)",
        )
        return False
    except httpx.RequestError as e:
        logger.error("alert_notifications: notification failed (Discord) request_error=%s", e)
        return False


async def _send_telegram(text: str) -> bool:
    token = settings.telegram_bot_token.strip()
    chat = settings.telegram_chat_id.strip()
    if not token or not chat:
        logger.info(
            "alert_notifications: notification attempt skipped (Telegram bot token or chat id not configured)",
        )
        return True
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": _truncate(text, TELEGRAM_TEXT_MAX)}
    logger.info("alert_notifications: notification attempt (Telegram sendMessage)")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(api, json=payload)
            r.raise_for_status()
        logger.info(
            "alert_notifications: notification success (Telegram) http_status=%s",
            r.status_code,
        )
        return True
    except httpx.HTTPStatusError as e:
        snippet = _response_body_snippet(e.response)
        logger.error(
            "alert_notifications: notification failed (Telegram) http_status=%s body=%s",
            e.response.status_code,
            snippet or "(empty)",
        )
        return False
    except httpx.RequestError as e:
        logger.error("alert_notifications: notification failed (Telegram) request_error=%s", e)
        return False


async def maybe_notify_after_pipeline_refresh(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """
    Chiamato in coda da ``execute_pipeline_refresh`` dopo ingest/features/context/patterns:
    stesso percorso per ``POST /api/v1/pipeline/refresh`` e per il ciclo scheduler.
    """
    if _is_targeted_notify_request(body):
        await _notify_targeted_pipeline(session, body)
        return
    if _is_global_notify_request(body):
        await _notify_global_pipeline(session, body)
        return

    logger.info(
        "alert_notifications: notification flow not entered (use targeted: exchange+symbol+timeframe, "
        "or global: omit both symbol and timeframe); got exchange=%r symbol=%r timeframe=%r",
        body.exchange,
        body.symbol,
        body.timeframe,
    )


async def _notify_targeted_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """Una serie: invariato rispetto al comportamento precedente (include test media)."""
    discord_cfg = "yes" if _discord_configured() else "no"
    telegram_cfg = "yes" if _telegram_configured() else "no"
    enabled = settings.alert_notifications_enabled

    logger.info(
        "alert_notifications: targeted notification flow entered exchange=%s symbol=%s timeframe=%s "
        "enabled=%s discord_configured=%s telegram_configured=%s",
        body.exchange,
        body.symbol,
        body.timeframe,
        enabled,
        discord_cfg,
        telegram_cfg,
    )

    if not enabled:
        logger.info(
            "alert_notifications: disabled (ALERT_NOTIFICATIONS_ENABLED=false), skipping evaluation",
        )
        return

    if not _channels_configured():
        logger.warning(
            "alert_notifications: enabled but no outbound channel configured "
            "(set DISCORD_WEBHOOK_URL and/or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID); skipping",
        )
        return

    rows = await list_opportunities(
        session,
        symbol=body.symbol,
        exchange=body.exchange,
        timeframe=body.timeframe,
        limit=1,
    )
    logger.info(
        "alert_notifications: opportunities computed for notification (after pipeline refresh) "
        "row_count=%d exchange=%s symbol=%s timeframe=%s",
        len(rows),
        body.exchange,
        body.symbol,
        body.timeframe,
    )

    alert_candidates_count = sum(1 for r in rows if r.alert_candidate)
    high_priority_candidates_count = sum(1 for r in rows if r.alert_level == HIGH_ALERT_LEVEL)
    media_priority_candidates_count = sum(1 for r in rows if r.alert_level == MEDIA_ALERT_LEVEL)
    notification_eligible_count = sum(1 for r in rows if _notification_eligible_for_outbound(r))
    logger.info(
        "alert_notifications: alert_candidates_count=%d high_priority_candidates_count=%d "
        "media_priority_candidates_count=%d notification_eligible_count=%d "
        "NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA=%s discord_configured=%s",
        alert_candidates_count,
        high_priority_candidates_count,
        media_priority_candidates_count,
        notification_eligible_count,
        NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA,
        discord_cfg,
    )

    if not rows:
        logger.info(
            "alert_notifications: no notification-eligible row "
            "(no opportunity row for this series after refresh)",
        )
        return

    opp = rows[0]

    if not _notification_eligible_for_outbound(opp):
        logger.info(
            "alert_notifications: no notification eligible for outbound "
            "(alta_priorita, or media_priorita when NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA=True) "
            "alert_candidate=%s alert_level=%s final_opportunity_score=%.2f",
            opp.alert_candidate,
            opp.alert_level,
            opp.final_opportunity_score,
        )
        return

    if (
        NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA
        and opp.alert_level == MEDIA_ALERT_LEVEL
    ):
        logger.info(
            "alert_notifications: media priority notification allowed for test "
            "(NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA=True; set False to restore alta-only)",
        )

    if await _already_sent(
        session,
        exchange=opp.exchange,
        symbol=opp.symbol,
        timeframe=opp.timeframe,
        context_timestamp=opp.context_timestamp,
    ):
        logger.info(
            "alert_notifications: notification skipped due to dedupe (already sent for this "
            "context) exchange=%s symbol=%s timeframe=%s context_timestamp=%s",
            opp.exchange,
            opp.symbol,
            opp.timeframe,
            opp.context_timestamp,
        )
        return

    text = _format_message(opp)
    ok_discord = await _send_discord(text)
    ok_tg = await _send_telegram(text)
    if not ok_discord or not ok_tg:
        logger.warning(
            "alert_notifications: notification failed (one or more channels) discord_ok=%s "
            "telegram_ok=%s; dedupe not recorded",
            ok_discord,
            ok_tg,
        )
        return

    session.add(
        AlertNotificationSent(
            exchange=opp.exchange,
            symbol=opp.symbol,
            timeframe=opp.timeframe,
            context_timestamp=opp.context_timestamp,
        )
    )
    await session.commit()
    logger.info(
        "alert_notifications: notification sent successfully (all channels ok, dedupe recorded) "
        "tier=%s media_tier_test=%s exchange=%s symbol=%s timeframe=%s context_timestamp=%s",
        opp.alert_level,
        opp.alert_level == MEDIA_ALERT_LEVEL and NOTIFICATION_TEST_INCLUDE_MEDIA_PRIORITA,
        opp.exchange,
        opp.symbol,
        opp.timeframe,
        opp.context_timestamp,
    )


def _global_alta_candidates(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Solo alta_priorita per il batch globale (nessun test media)."""
    return [
        r
        for r in rows
        if r.alert_candidate and r.alert_level == HIGH_ALERT_LEVEL
    ]


async def _notify_global_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """Tutte le serie con contesto: notifiche solo per alta_priorita."""
    discord_cfg = "yes" if _discord_configured() else "no"
    telegram_cfg = "yes" if _telegram_configured() else "no"
    enabled = settings.alert_notifications_enabled
    ex_filter = (body.exchange or "").strip() or None

    logger.info(
        "alert_notifications: global notification flow entered exchange_filter=%s "
        "enabled=%s discord_configured=%s telegram_configured=%s",
        ex_filter if ex_filter is not None else "(all)",
        enabled,
        discord_cfg,
        telegram_cfg,
    )

    if not enabled:
        logger.info(
            "alert_notifications: global — disabled (ALERT_NOTIFICATIONS_ENABLED=false), skipping",
        )
        return

    if not _channels_configured():
        logger.warning(
            "alert_notifications: global — enabled but no outbound channel configured; skipping",
        )
        return

    rows = await list_opportunities(
        session,
        symbol=None,
        exchange=ex_filter,
        timeframe=None,
        limit=GLOBAL_NOTIFY_OPPORTUNITIES_LIMIT,
    )
    series_checked = len(rows)
    alta_list = _global_alta_candidates(rows)
    high_priority_found = len(alta_list)

    logger.info(
        "alert_notifications: global opportunities computed series_checked=%d "
        "high_priority_candidates_found=%d (alta_priorita only; limit=%d) exchange_filter=%s",
        series_checked,
        high_priority_found,
        GLOBAL_NOTIFY_OPPORTUNITIES_LIMIT,
        ex_filter if ex_filter is not None else "(all)",
    )

    if high_priority_found == 0:
        logger.info(
            "alert_notifications: global — no alta_priorita candidates; "
            "notifications_sent=0 skipped_dedupe=0 failed_send=0",
        )
        return

    sent = 0
    skipped_dedupe = 0
    failed_send = 0

    for opp in alta_list:
        if await _already_sent(
            session,
            exchange=opp.exchange,
            symbol=opp.symbol,
            timeframe=opp.timeframe,
            context_timestamp=opp.context_timestamp,
        ):
            skipped_dedupe += 1
            logger.info(
                "alert_notifications: global notification skipped due to dedupe "
                "exchange=%s symbol=%s timeframe=%s context_timestamp=%s",
                opp.exchange,
                opp.symbol,
                opp.timeframe,
                opp.context_timestamp,
            )
            continue

        text = _format_message(opp)
        ok_discord = await _send_discord(text)
        ok_tg = await _send_telegram(text)
        if not ok_discord or not ok_tg:
            failed_send += 1
            logger.warning(
                "alert_notifications: global notification failed (channels) discord_ok=%s telegram_ok=%s "
                "exchange=%s symbol=%s timeframe=%s; dedupe not recorded for this series",
                ok_discord,
                ok_tg,
                opp.exchange,
                opp.symbol,
                opp.timeframe,
            )
            continue

        session.add(
            AlertNotificationSent(
                exchange=opp.exchange,
                symbol=opp.symbol,
                timeframe=opp.timeframe,
                context_timestamp=opp.context_timestamp,
            )
        )
        await session.commit()
        sent += 1
        logger.info(
            "alert_notifications: global notification sent successfully (dedupe recorded) "
            "tier=%s exchange=%s symbol=%s timeframe=%s context_timestamp=%s",
            opp.alert_level,
            opp.exchange,
            opp.symbol,
            opp.timeframe,
            opp.context_timestamp,
        )

    logger.info(
        "alert_notifications: global notification batch complete series_checked=%d "
        "high_priority_candidates_found=%d notifications_sent=%d skipped_dedupe=%d failed_send=%d",
        series_checked,
        high_priority_found,
        sent,
        skipped_dedupe,
        failed_send,
    )
