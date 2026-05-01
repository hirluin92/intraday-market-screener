"""
Outbound alert notifications v1 (MVP).

Dopo un pipeline refresh:

- **Mirato** (exchange + symbol + timeframe): idoneità con
  ``INCLUDE_MEDIA_PRIORITA`` (env ``ALERT_INCLUDE_MEDIA_PRIORITA``).
- **Globale** (nessun symbol e nessun timeframe nel body): elenca le opportunità per tutte le
  serie rilevanti e invia solo per ``alta_priorita`` (nessun media test).

Dedupe per (exchange, symbol, timeframe, context_timestamp) invariato.

Canali: Discord webhook e/o Telegram (variabili d'ambiente). Dedupe su DB per
(exchange, symbol, timeframe, context_timestamp).
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alert_channels import (
    _channels_configured,
    _discord_configured,
    _telegram_configured,
    send_discord as _send_discord,
    send_telegram as _send_telegram,
)
from app.core.config import settings
from app.models.alert_notification_sent import AlertNotificationSent

INCLUDE_MEDIA_PRIORITA = settings.alert_include_media_priorita
from app.schemas.opportunities import OpportunityRow
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.opportunity_final_score import compute_signal_alignment
from app.services.opportunities import list_opportunities

logger = logging.getLogger(__name__)

HIGH_ALERT_LEVEL = "alta_priorita"
MEDIA_ALERT_LEVEL = "media_priorita"

# Max righe opportunità considerate in un refresh globale (post-ordinamento score).
GLOBAL_NOTIFY_OPPORTUNITIES_LIMIT = 1000

def _notification_eligible_for_outbound(opp: OpportunityRow) -> bool:
    """Solo gating invio: alta_priorita e opzionalmente media_priorita (env)."""
    if not opp.alert_candidate:
        return False
    if opp.alert_level == HIGH_ALERT_LEVEL:
        return True
    if INCLUDE_MEDIA_PRIORITA and opp.alert_level == MEDIA_ALERT_LEVEL:
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
        "insufficient": "insufficiente",
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


async def _try_claim_notification(
    session: AsyncSession,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    context_timestamp,
) -> bool:
    """
    Tenta di registrare l'alert in modo atomico: INSERT ... ON CONFLICT DO NOTHING RETURNING id.
    Ritorna True se la riga è stata inserita (= questo worker invia).
    Ritorna False se era già presente (= alert già inviato, skip).

    Sostituisce il pattern non-atomico SELECT + INSERT separati che esponeva a race condition
    tra pipeline concorrenti o richieste HTTP simultanee sulla stessa serie.
    In caso di errore DB fa fail-open (True) per non perdere alert.
    """
    try:
        stmt = (
            pg_insert(AlertNotificationSent)
            .values(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                context_timestamp=context_timestamp,
            )
            .on_conflict_do_nothing(constraint="uq_alert_notification_sent_series_context")
            .returning(AlertNotificationSent.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.scalar_one_or_none() is not None
    except Exception as exc:
        logger.warning(
            "alert_notifications: dedupe DB claim failed — allow send (fail-open): %s", exc
        )
        return True


async def send_system_alert(message: str) -> None:
    """
    Invia un alert di sistema (non di mercato) su tutti i canali configurati.

    Aggiunge il prefisso ``🚨 SYSTEM:`` per distinguerlo visivamente dai segnali di trading.
    Non richiede una sessione DB, non ha dedupe, non rispetta ``alert_notifications_enabled``
    (i problemi di sistema vanno notificati anche se le alert di mercato sono disabilitate).

    Uso tipico: skip operativi critici in auto_execute_service (es. NetLiquidation non disponibile).
    """
    if not _channels_configured():
        logger.warning("send_system_alert: nessun canale configurato — messaggio non inviato: %s", message)
        return

    text = f"🚨 SYSTEM: {message}"
    logger.warning("send_system_alert: %s", message)
    ok_discord = await _send_discord(text)
    ok_telegram = await _send_telegram(text)
    if not ok_discord or not ok_telegram:
        logger.error(
            "send_system_alert: invio fallito su uno o più canali discord_ok=%s telegram_ok=%s",
            ok_discord,
            ok_telegram,
        )


async def maybe_notify_after_pipeline_refresh(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """
    Chiamato in coda da ``execute_pipeline_refresh`` dopo ingest/features/indicators/context/patterns:
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
        provider=body.provider,
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
        "ALERT_INCLUDE_MEDIA_PRIORITA=%s discord_configured=%s",
        alert_candidates_count,
        high_priority_candidates_count,
        media_priority_candidates_count,
        notification_eligible_count,
        INCLUDE_MEDIA_PRIORITA,
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
            "(alta_priorita, or media_priorita when ALERT_INCLUDE_MEDIA_PRIORITA=true) "
            "alert_candidate=%s alert_level=%s final_opportunity_score=%.2f",
            opp.alert_candidate,
            opp.alert_level,
            opp.final_opportunity_score,
        )
        return

    if INCLUDE_MEDIA_PRIORITA and opp.alert_level == MEDIA_ALERT_LEVEL:
        logger.info(
            "alert_notifications: media priority notification allowed "
            "(ALERT_INCLUDE_MEDIA_PRIORITA=true; set false for alta-only)",
        )

    claimed = await _try_claim_notification(
        session,
        exchange=opp.exchange,
        symbol=opp.symbol,
        timeframe=opp.timeframe,
        context_timestamp=opp.context_timestamp,
    )
    if not claimed:
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
            "telegram_ok=%s",
            ok_discord,
            ok_tg,
        )
        return

    logger.info(
        "alert_notifications: notification sent successfully (all channels ok, dedupe recorded) "
        "tier=%s media_tier_test=%s exchange=%s symbol=%s timeframe=%s context_timestamp=%s",
        opp.alert_level,
        opp.alert_level == MEDIA_ALERT_LEVEL and INCLUDE_MEDIA_PRIORITA,
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
        claimed = await _try_claim_notification(
            session,
            exchange=opp.exchange,
            symbol=opp.symbol,
            timeframe=opp.timeframe,
            context_timestamp=opp.context_timestamp,
        )
        if not claimed:
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
                "exchange=%s symbol=%s timeframe=%s",
                ok_discord,
                ok_tg,
                opp.exchange,
                opp.symbol,
                opp.timeframe,
            )
            continue

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


# ── Order execution and trade close notifications ─────────────────────────────

def _format_trade_duration(executed_at: datetime, closed_at: datetime) -> str:
    try:
        delta = closed_at - executed_at
        total_s = int(delta.total_seconds())
        if total_s < 0:
            return "—"
        d, rem = divmod(total_s, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d > 0:
            return f"{d}d {h}h {m}m"
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "—"


async def send_order_executed_notification(
    *,
    symbol: str,
    timeframe: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    take_profit_price: float,
    size: float,
    capital: float,
) -> None:
    """
    Invia notifica su tutti i canali configurati quando un bracket order
    viene confermato da TWS (tws_status=submitted).
    Chiamato da auto_execute_service._execute_and_save() solo quando executed_ok=True.
    """
    if not _channels_configured():
        return

    dir_arrow = "▲" if (direction or "").lower() == "bullish" else "▼"
    dir_label = "LONG" if (direction or "").lower() == "bullish" else "SHORT"
    stop_dist = abs(entry_price - stop_price)
    tp_dist   = abs(take_profit_price - entry_price)
    rr        = round(tp_dist / stop_dist, 2) if stop_dist > 1e-10 else 0.0
    risk_usd  = round(size * stop_dist, 2) if size > 0 else 0.0
    risk_pct  = round(risk_usd / capital * 100, 2) if capital > 0 else 0.0

    from datetime import datetime as _dt, timezone  # noqa: PLC0415
    ts_str = _dt.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    text = "\n".join([
        f"🟢 ORDINE ESEGUITO — {symbol} {timeframe}",
        f"{dir_arrow} {dir_label}  (entry LIMIT)",
        "",
        f"Entry:    ${entry_price:.2f}",
        f"Stop:     ${stop_price:.2f}  (−${stop_dist:.2f}/az)",
        f"TP1:      ${take_profit_price:.2f}  (+${tp_dist:.2f}/az)",
        f"Qty:      {size:.1f} az  |  R/R 1:{rr}",
        f"Rischio:  ${risk_usd:.2f}  ({risk_pct:.2f}% cap)",
        f"Capitale: ${capital:,.0f}",
        "",
        f"⏰ {ts_str}",
    ])

    logger.info(
        "send_order_executed_notification: symbol=%s tf=%s dir=%s size=%.1f",
        symbol, timeframe, direction, size,
    )
    await _send_discord(text)
    await _send_telegram(text)


async def send_trade_closed_notification(
    *,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    close_fill_price: float,
    realized_r: float,
    close_outcome: str,
    close_cause: str,
    executed_at: datetime,
    closed_at: datetime,
    qty: float = 0.0,
) -> None:
    """
    Invia notifica su tutti i canali configurati quando un trade si chiude
    (stop loss, take profit, timeout).
    Chiamato da poll_and_record_stop_fills() e poll_and_record_tp_fills()
    solo dopo commit DB riuscito.
    """
    if not _channels_configured():
        return

    dir_arrow = "▲" if (direction or "").lower() == "bullish" else "▼"
    dir_label = "LONG" if (direction or "").lower() == "bullish" else "SHORT"
    is_win    = realized_r > 0
    emoji     = "🟢" if is_win else "🔴"

    outcome_labels = {"tp1": "TP1 ✓", "tp2": "TP2 ✓", "stop": "SL ✗", "timeout": "Timeout"}
    outcome_label  = outcome_labels.get(close_outcome, close_outcome)
    gap_note = "  (gap notturno ⚠)" if close_cause == "overnight_gap" else ""

    risk = abs(entry_price - stop_price)
    if qty > 0 and risk > 1e-10:
        pnl_val = realized_r * risk * qty
        sign = "+" if pnl_val >= 0 else ""
        rsign = "+" if realized_r >= 0 else ""
        pnl_str = f"{sign}${pnl_val:,.2f}  ({rsign}{realized_r:.2f}R)"
    else:
        rsign = "+" if realized_r >= 0 else ""
        pnl_str = f"{rsign}{realized_r:.2f}R"

    duration = _format_trade_duration(executed_at, closed_at)
    ts_str   = closed_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    text = "\n".join([
        f"{emoji} TRADE CHIUSO — {symbol}",
        f"{dir_arrow} {dir_label} → {outcome_label}{gap_note}",
        "",
        f"Entry:   ${entry_price:.2f}  →  Exit: ${close_fill_price:.2f}",
        f"P&L:     {pnl_str}",
        f"Durata:  {duration}",
        "",
        f"⏰ {ts_str}",
    ])

    logger.info(
        "send_trade_closed_notification: symbol=%s outcome=%s realized_r=%.2f cause=%s",
        symbol, close_outcome, realized_r, close_cause,
    )
    await _send_discord(text)
    await _send_telegram(text)
