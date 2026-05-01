"""
Auto-esecuzione ordini via TWS (ib_insync).

Bracket order completo: entry LMT + TP LMT + SL STP (GTC).
Chiamato dopo pipeline refresh se TWS_ENABLED=true e IBKR_AUTO_EXECUTE=true.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.trade_plan_variant_constants import (
    MIN_FILL_RATIO,
    RISK_SIZE_5M_BY_HOUR_ET,
    TRAIL_STEPS,
    _SLIPPAGE_R_THRESHOLD,
)
from app.models.executed_signal import ExecutedSignal
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.alert_notifications import send_system_alert
from app.services.ibkr_error_codes import is_critical_ibkr_error
from app.services.opportunities import list_opportunities

logger = logging.getLogger(__name__)

# ── Slot registry (Strategy E+: slot separation bidirezionale 1h/5m) ────────
# Mappa symbol.upper() -> {timeframe, slot_type, opened_at}.
# Logica E+ (bidirezionale con sfratto):
#   - 3 slot 1h_prio: prioritari per 1h, ma 5m li usa temporaneamente quando liberi.
#   - 2 slot 5m: prioritari per 5m, ma 1h li usa quando liberi (come E).
#   - 1h arriva e trova 3 slot 1h_prio occupati da 5m? → sfratta il 5m piu' vecchio.
#   - 5m NON chiude mai un 1h per fare spazio.
# Il registry si sincronizza con le posizioni TWS ad ogni chiamata execute_signal().
_slot_registry: dict[str, dict] = {}
# Struttura entry: {"timeframe": "1h"|"5m", "slot_type": "1h_prio"|"5m", "opened_at": datetime}
_slot_lock = asyncio.Lock()

# ── Trailing stop Config D tracking ───────────────────────────────────────────
# Config D (OOS-confermata 2026, +0.29R/trade vs C, MC mediana +46% vs C):
#   Trail progressivo step 0.5R — vedi TRAIL_STEPS in risk.py.
#   Logica salto-step: se MFE arriva direttamente a +2.5R, lock +2.0R subito.
#
# Dict {rec.id: max_step_index_applied}. Al restart si resetta in
# sync_slot_registry_on_startup — lo stop TWS rimane dov'è (one-way), quindi
# il restart fa solo il recheck senza rischiare di peggiorare lo stop.
_trail_max_step: dict[int, int] = {}  # rec.id -> max step index (0..len(TRAIL_STEPS)-1) applicato

async def sync_slot_registry_on_startup() -> None:
    """
    Ricostruisce _slot_registry dal DB dopo un restart del backend.

    Al restart _slot_registry = {} — le posizioni ancora aperte in TWS non vengono
    conteggiate finché execute_signal() non viene chiamato. Senza questa sync il cap
    di slot simultanei può essere superato accettando nuovi segnali prima che la prima
    chiamata TWS ripopoli il registry.

    Usa close_outcome IS NULL come proxy per "posizione ancora aperta"; la sync TWS
    successiva all'interno di execute_signal() rimuoverà eventuali falsi positivi
    (posizioni già chiuse in TWS ma non ancora aggiornate nel DB).
    """
    _trail_max_step.clear()

    try:
        import datetime as _dt  # noqa: PLC0415

        from app.db.session import AsyncSessionLocal  # noqa: PLC0415
        from sqlalchemy import select as _select  # noqa: PLC0415

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)

        async with AsyncSessionLocal() as _session:
            _result = await _session.execute(
                _select(
                    ExecutedSignal.symbol,
                    ExecutedSignal.timeframe,
                    ExecutedSignal.executed_at,
                ).where(
                    ExecutedSignal.close_outcome.is_(None),
                    ExecutedSignal.tws_status.not_in(["skipped", "error", "cancelled"]),
                    ExecutedSignal.executed_at >= cutoff,
                )
            )
            rows = _result.all()

        if not rows:
            logger.info("auto_execute: slot registry startup sync — nessuna posizione aperta nel DB")
            return

        async with _slot_lock:
            for sym_raw, tf_raw, opened_at in rows:
                sym = (sym_raw or "").upper()
                tf = (tf_raw or "1h").lower()
                if sym and sym not in _slot_registry:
                    _slot_registry[sym] = {
                        "timeframe": tf,
                        "slot_type": "1h_prio" if tf == "1h" else "5m",
                        "opened_at": opened_at or _dt.datetime.now(_dt.timezone.utc),
                    }

        logger.info(
            "auto_execute: slot registry ricostruito da DB — %d posizioni: %s",
            len(_slot_registry),
            list(_slot_registry.keys()),
        )
    except Exception:
        logger.exception("auto_execute: slot registry startup sync fallita (non bloccante)")

# Mantiene riferimenti forti ai background task asyncio per prevenire la GC prematura.
# I task vengono rimossi automaticamente al completamento via add_done_callback.
_bg_tasks: set[asyncio.Task] = set()

# ── Safety caps esecuzione ─────────────────────────────────────────────────
# Limitano il numero di ordini inviabili per singola invocation / ciclo.
# Evitano runaway in caso di bug o regime improvvisamente favorevole su molti simboli.
# Il limite su posizioni contemporanee aperte è stato rimosso: vengono eseguiti
# tutti i segnali 'execute' indipendentemente dal numero di posizioni aperte.
MAX_ORDERS_PER_HOOK_INVOCATION: int = 5   # per maybe_ibkr_auto_execute_after_pipeline
MAX_ORDERS_PER_SCAN: int = 10             # per run_auto_execute_scan (globale per ciclo)

# Timeout (secondi) per il polling del fill post-bracket
_FILL_POLL_TIMEOUT_S: float = 60.0
_FILL_POLL_INTERVAL_S: float = 1.5


def compute_realized_r(
    entry_price: float,
    stop_price: float,
    fill_price: float,
    direction: str,
) -> float:
    """
    Calcola il realized_R dato il fill price reale dal broker.

    Long  (bullish): R = (fill − entry) / risk
    Short (bearish): R = (entry − fill) / risk
    risk  = abs(entry − stop)
    """
    risk = abs(entry_price - stop_price)
    if risk < 1e-10:
        return -1.0
    direction_lower = (direction or "").lower()
    if direction_lower == "bullish":
        return (fill_price - entry_price) / risk
    if direction_lower == "bearish":
        return (entry_price - fill_price) / risk
    return 0.0


def _is_overnight_close(executed_at: datetime, closed_at: datetime) -> bool:
    """True se la chiusura è avvenuta in un giorno di calendario diverso dall'apertura."""
    # Normalizza a UTC per confronto robusto anche con tz-aware datetimes
    def _date(dt: datetime):  # type: ignore[return]
        if dt.tzinfo is None:
            return dt.date()
        return dt.astimezone(timezone.utc).date()

    return _date(closed_at) > _date(executed_at)


def log_stop_close(
    *,
    symbol: str,
    entry_price: float,
    stop_price: float,
    fill_price: float,
    direction: str,
    executed_at: datetime,
    closed_at: datetime,
) -> tuple[float, float, str]:
    """
    Calcola e logga il realized_R quando un trade viene chiuso da stop.

    Restituisce (realized_r, slippage_r, cause).
    cause = "overnight_gap" se realized_R < _SLIPPAGE_R_THRESHOLD E la chiusura
    è avvenuta in un giorno di calendario diverso dall'apertura; altrimenti "normal".
    """
    realized_r = compute_realized_r(entry_price, stop_price, fill_price, direction)
    nominal_r = -1.0
    slippage_r = round(realized_r - nominal_r, 4)
    cause = (
        "overnight_gap"
        if realized_r < _SLIPPAGE_R_THRESHOLD and _is_overnight_close(executed_at, closed_at)
        else "normal"
    )
    logger.info(
        "Trade closed: symbol=%s, outcome=stop, nominal_R=%.2f, realized_R=%.4f, "
        "slippage_R=%.4f, cause=%s",
        symbol, nominal_r, realized_r, slippage_r, cause,
    )
    return realized_r, slippage_r, cause


async def _handle_partial_fill_after_bracket(
    *,
    rec_id: int,
    entry_order_id: int,
    sl_order_id: int | None,
    tp_order_id: int | None,
    ordered_qty: float,
    symbol: str,
    action: str,
    stop_price: float,
    take_profit_price: float,
    exchange: str = "SMART",
    currency: str = "USD",
) -> None:
    """
    Task background: polling fill dell'entry order per max _FILL_POLL_TIMEOUT_S.

    Scenari gestiti:
    - Fill completo       → aggiorna DB, nessun resize
    - Fill parziale       → cancella SL/TP originali, reinvia dimensionati sul fill reale
    - Fill < MIN_FILL_RATIO → chiude posizione con MKT order, cancella SL/TP
    - Rejected/Cancelled  → cancella SL/TP pendenti, logga errore
    - NotFound / error    → log warning, nessuna azione

    Gestisce la propria sessione DB (AsyncSessionLocal) per essere indipendente
    dal ciclo di request del chiamante.
    """
    from app.db.session import AsyncSessionLocal  # noqa: PLC0415
    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        logger.warning(
            "_handle_partial_fill_after_bracket: TWS non connesso — skip polling (symbol=%s, rec_id=%s)",
            symbol, rec_id,
        )
        return

    # ── 1. Poll fill status ────────────────────────────────────────────────
    fill = await tws.poll_entry_fill(
        order_id=entry_order_id,
        timeout_s=_FILL_POLL_TIMEOUT_S,
        poll_interval_s=_FILL_POLL_INTERVAL_S,
    )
    status = fill.get("status", "")
    filled_qty = float(fill.get("filled_qty", 0) or 0)
    ordered_qty_actual = float(fill.get("ordered_qty", ordered_qty) or ordered_qty)
    avg_fill_price = float(fill.get("avg_fill_price", 0) or 0)

    logger.info(
        "_handle_partial_fill: symbol=%s rec_id=%s status=%s filled=%.1f ordered=%.1f",
        symbol, rec_id, status, filled_qty, ordered_qty_actual,
    )

    # ── 2. Classify ───────────────────────────────────────────────────────
    _TERMINAL = {"Filled", "Cancelled", "Rejected", "Inactive", "ApiCancelled", "Timeout"}
    if status not in _TERMINAL and status not in ("NotFound", "error"):
        logger.warning(
            "_handle_partial_fill: symbol=%s status inatteso '%s' — nessuna azione",
            symbol, status,
        )
        return

    fill_ratio = filled_qty / ordered_qty_actual if ordered_qty_actual > 0 else 0.0
    is_full_fill = status == "Filled" and fill_ratio >= 0.999
    is_rejected = status in ("Cancelled", "Rejected", "Inactive", "ApiCancelled") and filled_qty < 0.01
    is_partial = filled_qty > 0 and not is_full_fill

    # ── 3. Aggiorna DB ────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        rec: ExecutedSignal | None = await session.get(ExecutedSignal, rec_id)
        if rec is None:
            logger.warning(
                "_handle_partial_fill: ExecutedSignal id=%s non trovato nel DB", rec_id
            )
            return

        rec.ordered_qty = Decimal(str(ordered_qty_actual))
        rec.filled_qty = Decimal(str(filled_qty)) if filled_qty > 0 else None
        rec.partial_fill = is_partial

        if is_full_fill:
            logger.info(
                "Full fill: symbol=%s, ordered=%.1f, filled=%.1f — nessun resize",
                symbol, ordered_qty_actual, filled_qty,
            )
            await session.commit()
            return

        if status in ("NotFound", "error"):
            logger.warning(
                "_handle_partial_fill: symbol=%s — poll fallito (status=%s), DB aggiornato senza resize",
                symbol, status,
            )
            await session.commit()
            return

        if is_rejected:
            logger.warning(
                "Order rejected/cancelled: symbol=%s, status=%s — cancello SL/TP pendenti",
                symbol, status,
            )
            rec.tws_status = f"rejected:{status}"
            for oid in [sl_order_id, tp_order_id]:
                if oid is not None:
                    await tws.cancel_order_by_id(oid)
            await session.commit()
            return

        # ── Fill parziale ─────────────────────────────────────────────────
        if is_partial:
            if fill_ratio < MIN_FILL_RATIO:
                logger.warning(
                    "Fill ratio too low (%.0f%%), closing position immediately: "
                    "symbol=%s, ordered=%.1f, filled=%.1f",
                    fill_ratio * 100, symbol, ordered_qty_actual, filled_qty,
                )
                # Cancella SL/TP originali
                for oid in [sl_order_id, tp_order_id]:
                    if oid is not None:
                        await tws.cancel_order_by_id(oid)
                # Chiudi la posizione parziale con un market order
                close_action = "SELL" if action == "BUY" else "BUY"
                close_result = await tws.place_market_close_order(
                    symbol=symbol,
                    action=close_action,
                    quantity=filled_qty,
                    exchange=exchange,
                    currency=currency,
                )
                rec.tws_status = "partial_fill_closed"
                logger.info(
                    "Partial fill closed: symbol=%s, close MKT order result=%s",
                    symbol, close_result,
                )
            else:
                logger.warning(
                    "Partial fill: symbol=%s, ordered=%.1f, filled=%.1f (%.0f%%) — "
                    "resize SL/TP to %.1f shares",
                    symbol, ordered_qty_actual, filled_qty,
                    fill_ratio * 100, filled_qty,
                )
                # Cancella SL/TP originali (dimensionati su ordered_qty)
                for oid in [sl_order_id, tp_order_id]:
                    if oid is not None:
                        await tws.cancel_order_by_id(oid)
                # Reinvia SL/TP standalone dimensionati sul fill effettivo
                close_action = "SELL" if action == "BUY" else "BUY"
                resize_result = await tws.place_tp_sl_standalone(
                    symbol=symbol,
                    close_action=close_action,
                    quantity=filled_qty,
                    stop_price=stop_price,
                    take_profit_price=take_profit_price,
                    exchange=exchange,
                    currency=currency,
                )
                rec.tws_status = "partial_fill_resized"
                logger.info(
                    "Partial fill resized: symbol=%s new SL/TP result=%s",
                    symbol, resize_result,
                )

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "_handle_partial_fill_after_bracket: errore commit DB (symbol=%s rec_id=%s)",
                symbol, rec_id,
            )


async def check_and_apply_trailing_stops(session: AsyncSession) -> None:
    """
    Config D trailing stop — trail progressivo step 0.5R con salto-step.
      Vedi TRAIL_STEPS in risk.py per la lista (mfe_trigger_R, dest_R).
      Se MFE corrente è a +2.5R, applica direttamente lock +2.0R (non step-by-step).

    Poll-based: chiamato ogni ciclo pipeline. Usa ib_insync modify (stesso orderId,
    nuovo auxPrice) per preservare il gruppo OCA. Tracking idempotente via
    _trail_max_step[rec.id] = indice ultimo step applicato.
    """
    if not getattr(settings, "tws_enabled", False):
        return

    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await session.execute(
        select(ExecutedSignal).where(
            ExecutedSignal.closed_at.is_(None),
            ExecutedSignal.sl_order_id.is_not(None),
            ExecutedSignal.executed_at >= cutoff,
            ExecutedSignal.tws_status.not_in(["skipped", "error", "cancelled"]),
        )
    )
    open_signals: list[ExecutedSignal] = list(result.scalars())

    for rec in open_signals:
        entry = float(rec.entry_price)
        stop  = float(rec.stop_price)
        risk  = abs(entry - stop)
        if risk < 1e-9:
            continue

        is_long = (rec.direction or "").lower() == "bullish"

        quote = await tws.get_last_price(rec.symbol, exchange=rec.exchange or "SMART", currency="USD")
        if quote is None:
            continue

        # MFE corrente in R-multipli (positivo se in profitto)
        current_mfe_r = (quote - entry) / risk if is_long else (entry - quote) / risk

        # Trova lo step più alto raggiunto (salto-step: se MFE=+2.5R, applica step 4 direttamente)
        max_step = -1
        for i, (mfe_trigger, _dest) in enumerate(TRAIL_STEPS):
            if current_mfe_r >= mfe_trigger:
                max_step = i

        if max_step < 0:
            # MFE sotto soglia +0.5R, niente da fare
            continue

        applied_step = _trail_max_step.get(rec.id, -1)
        if max_step <= applied_step:
            # Già applicato (o uno step più alto è già stato applicato — one-way)
            continue

        # Calcola nuovo stop dal dest_R dello step massimo raggiunto
        _, dest_r = TRAIL_STEPS[max_step]
        new_stop = entry + dest_r * risk if is_long else entry - dest_r * risk

        ok = await tws.modify_stop_price(rec.sl_order_id, new_stop, rec.symbol)
        if rec.sl2_order_id is not None:
            await tws.modify_stop_price(rec.sl2_order_id, new_stop, rec.symbol)

        if ok:
            _trail_max_step[rec.id] = max_step
            logger.info(
                "TRAIL D step%d: %s %s  stop→+%.2fR(%.4f)  mfe=%.2fR  quote=%.4f  entry=%.4f  sl_id=%s  sl2_id=%s",
                max_step + 1, rec.symbol, rec.direction, dest_r, new_stop, current_mfe_r,
                quote, entry, rec.sl_order_id, rec.sl2_order_id,
            )
        else:
            logger.warning(
                "TRAIL D step%d fallito: %s sl_id=%s mfe=%.2fR",
                max_step + 1, rec.symbol, rec.sl_order_id, current_mfe_r,
            )


async def poll_and_record_stop_fills(session: AsyncSession) -> None:
    """
    Interroga TWS per gli ordini STP eseguiti nella sessione corrente.

    Per ogni fill trovato:
    - cerca il ExecutedSignal corrispondente via sl_order_id
    - se closed_at è già popolato, lo salta (idempotente)
    - calcola realized_R, logga con log_stop_close(), aggiorna il DB

    Viene chiamato dal pipeline_scheduler post-ciclo.
    TWS deve essere connesso; se non lo è, la funzione esce silenziosamente.
    """
    if not getattr(settings, "tws_enabled", False):
        return

    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        return

    filled = await tws.get_filled_stop_trades()
    if not filled:
        return

    _stop_notify_data: list[dict] = []

    for fill in filled:
        order_id: int | None = fill.get("order_id")
        if order_id is None:
            continue

        # Cerca il record corrispondente; salta se già chiuso (idempotente)
        result = await session.execute(
            select(ExecutedSignal).where(
                ExecutedSignal.sl_order_id == order_id,
                ExecutedSignal.closed_at.is_(None),
            )
        )
        rec: ExecutedSignal | None = result.scalar_one_or_none()
        if rec is None:
            continue

        fill_price: float | None = fill.get("fill_price")
        fill_time: datetime | None = fill.get("fill_time")
        if fill_price is None or fill_time is None:
            continue

        entry = float(rec.entry_price)
        stop  = float(rec.stop_price)
        now   = fill_time if fill_time.tzinfo else fill_time.replace(tzinfo=timezone.utc)
        exec_at = rec.executed_at if rec.executed_at.tzinfo else rec.executed_at.replace(tzinfo=timezone.utc)

        realized_r, _slippage_r, cause = log_stop_close(
            symbol=rec.symbol,
            entry_price=entry,
            stop_price=stop,
            fill_price=fill_price,
            direction=rec.direction,
            executed_at=exec_at,
            closed_at=now,
        )

        rec.closed_at = now
        rec.close_fill_price = Decimal(str(fill_price))
        rec.realized_r = realized_r
        rec.close_outcome = "stop"
        rec.close_cause = cause

        _stop_notify_data.append({
            "symbol": rec.symbol,
            "direction": rec.direction or "bullish",
            "entry_price": entry,
            "stop_price": stop,
            "close_fill_price": fill_price,
            "realized_r": realized_r,
            "close_outcome": "stop",
            "close_cause": cause,
            "executed_at": exec_at,
            "closed_at": now,
            "qty": float(rec.ordered_qty or rec.quantity_tp1 or 0),
        })

    try:
        await session.commit()
        if settings.notify_order_events_enabled and _stop_notify_data:
            from app.services.alert_notifications import send_trade_closed_notification  # noqa: PLC0415
            for _nd in _stop_notify_data:
                _t = asyncio.create_task(send_trade_closed_notification(**_nd))
                _bg_tasks.add(_t)
                _t.add_done_callback(_bg_tasks.discard)
    except Exception:
        await session.rollback()
        logger.exception("poll_and_record_stop_fills: errore commit DB")


async def poll_and_record_tp_fills(session: AsyncSession) -> None:
    """
    Interroga TWS per gli ordini LMT (take profit) eseguiti nella sessione corrente.

    Per ogni fill trovato che corrisponde a un tp_order_id o tp2_order_id:
    - se closed_at è già popolato, lo salta (idempotente)
    - calcola realized_R in base al fill price reale
    - aggiorna close_outcome = "tp1" o "tp2", close_fill_price, realized_r, closed_at

    Viene chiamato dal pipeline_scheduler post-ciclo insieme a poll_and_record_stop_fills.
    """
    if not getattr(settings, "tws_enabled", False):
        return

    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        return

    filled_lmt = await tws.get_filled_lmt_trades()
    if not filled_lmt:
        return

    # Indicizza i fill LMT per order_id per accesso rapido
    fill_by_order_id: dict[int, dict] = {f["order_id"]: f for f in filled_lmt}
    if not fill_by_order_id:
        return

    # Carica tutti i record aperti che hanno tp_order_id o tp2_order_id noti
    result = await session.execute(
        select(ExecutedSignal).where(
            ExecutedSignal.closed_at.is_(None),
            ExecutedSignal.tws_status.in_(["Filled", "PreSubmitted", "Submitted", "partial_fill_resized"]),
        )
    )
    open_records: list[ExecutedSignal] = list(result.scalars().all())

    _tp_notify_data: list[dict] = []

    for rec in open_records:
        tp1_id = rec.tp_order_id
        tp2_id = rec.tp2_order_id

        outcome: str | None = None
        fill_data: dict | None = None

        if tp1_id is not None and tp1_id in fill_by_order_id:
            outcome = "tp1"
            fill_data = fill_by_order_id[tp1_id]
        elif tp2_id is not None and tp2_id in fill_by_order_id:
            outcome = "tp2"
            fill_data = fill_by_order_id[tp2_id]

        if outcome is None or fill_data is None:
            continue

        fill_price: float | None = fill_data.get("fill_price")
        fill_time = fill_data.get("fill_time")
        if fill_price is None or fill_time is None:
            continue

        entry = float(rec.entry_price)
        stop  = float(rec.stop_price)
        now   = fill_time if fill_time.tzinfo else fill_time.replace(tzinfo=timezone.utc)
        exec_at = rec.executed_at if rec.executed_at.tzinfo else rec.executed_at.replace(tzinfo=timezone.utc)

        realized_r = compute_realized_r(entry, stop, fill_price, rec.direction or "bullish")
        cause = "normal"

        logger.info(
            "Trade closed via %s: symbol=%s, outcome=%s, fill_price=%.4f, realized_R=%.4f",
            outcome, rec.symbol, outcome, fill_price, realized_r,
        )

        rec.closed_at = now
        rec.close_fill_price = Decimal(str(fill_price))
        rec.realized_r = realized_r
        rec.close_outcome = outcome
        rec.close_cause = cause

        _tp_notify_data.append({
            "symbol": rec.symbol,
            "direction": rec.direction or "bullish",
            "entry_price": entry,
            "stop_price": stop,
            "close_fill_price": fill_price,
            "realized_r": realized_r,
            "close_outcome": outcome,
            "close_cause": cause,
            "executed_at": exec_at,
            "closed_at": now,
            "qty": float(rec.ordered_qty or rec.quantity_tp1 or 0),
        })

    try:
        await session.commit()
        if settings.notify_order_events_enabled and _tp_notify_data:
            from app.services.alert_notifications import send_trade_closed_notification  # noqa: PLC0415
            for _nd in _tp_notify_data:
                _t = asyncio.create_task(send_trade_closed_notification(**_nd))
                _bg_tasks.add(_t)
                _t.add_done_callback(_bg_tasks.discard)
    except Exception:
        await session.rollback()
        logger.exception("poll_and_record_tp_fills: errore commit DB")


def _build_entry_context_json(opp_row: object) -> str | None:
    """
    Serializza il contesto operativo dell'OpportunityRow in JSON.

    Cattura: regime, score, confluence, ML, backtest expectancy, rationale,
    SPY, spread/volume IBKR, pattern quality, decision flags.
    Usato per l'autopsia post-trade (perché SL invece di TP?).
    """
    import json  # noqa: PLC0415

    def _safe(v: object) -> object:
        """Converte tipi non JSON-serializzabili."""
        from decimal import Decimal as _D  # noqa: PLC0415
        from datetime import datetime as _dt  # noqa: PLC0415
        if isinstance(v, _D):
            return float(v)
        if isinstance(v, _dt):
            return v.isoformat()
        return v

    try:
        r = opp_row  # type: ignore[assignment]
        ctx = {
            # Regime e contesto di mercato
            "market_regime":        getattr(r, "market_regime", None),
            "volatility_regime":    getattr(r, "volatility_regime", None),
            "candle_expansion":     getattr(r, "candle_expansion", None),
            "direction_bias":       getattr(r, "direction_bias", None),
            "screener_score":       getattr(r, "screener_score", None),
            "score_label":          getattr(r, "score_label", None),
            "score_direction":      getattr(r, "score_direction", None),
            # Pattern
            "pattern_age_bars":               getattr(r, "pattern_age_bars", None),
            "pattern_stale":                  getattr(r, "pattern_stale", None),
            "pattern_quality_score":          _safe(getattr(r, "pattern_quality_score", None)),
            "pattern_quality_label":          getattr(r, "pattern_quality_label", None),
            "pattern_timeframe_quality_ok":   getattr(r, "pattern_timeframe_quality_ok", None),
            "pattern_timeframe_gate_label":   getattr(r, "pattern_timeframe_gate_label", None),
            "pattern_is_validated":           getattr(r, "pattern_is_validated", None),
            "pattern_operational_status":     getattr(r, "pattern_operational_status", None),
            # Score operativo
            "final_opportunity_score":                         _safe(getattr(r, "final_opportunity_score", None)),
            "final_opportunity_label":                         getattr(r, "final_opportunity_label", None),
            "final_opportunity_score_before_tpb":              _safe(getattr(r, "final_opportunity_score_before_trade_plan_backtest", None)),
            "trade_plan_backtest_score_delta":                 _safe(getattr(r, "trade_plan_backtest_score_delta", None)),
            "trade_plan_backtest_adjustment_label":            getattr(r, "trade_plan_backtest_adjustment_label", None),
            "operational_confidence":                          getattr(r, "operational_confidence", None),
            "trade_plan_backtest_expectancy_r":                _safe(getattr(r, "trade_plan_backtest_expectancy_r", None)),
            "trade_plan_backtest_sample_size":                 getattr(r, "trade_plan_backtest_sample_size", None),
            # Variant
            "selected_trade_plan_variant":              getattr(r, "selected_trade_plan_variant", None),
            "selected_trade_plan_variant_status":       getattr(r, "selected_trade_plan_variant_status", None),
            "selected_trade_plan_variant_sample_size":  getattr(r, "selected_trade_plan_variant_sample_size", None),
            "selected_trade_plan_variant_expectancy_r": _safe(getattr(r, "selected_trade_plan_variant_expectancy_r", None)),
            "trade_plan_source":                        getattr(r, "trade_plan_source", None),
            "trade_plan_fallback_reason":               getattr(r, "trade_plan_fallback_reason", None),
            # Confluenza e segnali
            "confluence_count":    getattr(r, "confluence_count", None),
            "alert_level":         getattr(r, "alert_level", None),
            # ML
            "ml_score":            _safe(getattr(r, "ml_score", None)),
            "ml_filter_active":    getattr(r, "ml_filter_active", None),
            # Prezzo al momento dell'entry
            "current_price":       _safe(getattr(r, "current_price", None)),
            "price_source":        getattr(r, "price_source", None),
            "price_distance_pct":  _safe(getattr(r, "price_distance_pct", None)),
            "price_stale":         getattr(r, "price_stale", None),
            "price_stale_reason":  getattr(r, "price_stale_reason", None),
            # Regime SPY
            "regime_spy":          getattr(r, "regime_spy", None),
            "regime_direction_ok": getattr(r, "regime_direction_ok", None),
            # IBKR spread/volume
            "bid_ask_spread_pct":      _safe(getattr(r, "bid_ask_spread_pct", None)),
            "live_volume_ratio":       _safe(getattr(r, "live_volume_ratio", None)),
            "ibkr_spread_filter_active": getattr(r, "ibkr_spread_filter_active", None),
            # Rationale testuale (le motivazioni della decisione)
            "decision_rationale": getattr(r, "decision_rationale", []),
        }
        return json.dumps(ctx, ensure_ascii=False)
    except Exception as exc:
        logger.warning("_build_entry_context_json: errore serializzazione — %s", exc)
        return None


async def _build_entry_indicators_json(
    session: AsyncSession,
    *,
    symbol: str,
    exchange: str,
    provider: str,
    timeframe: str,
) -> str | None:
    """
    Recupera e serializza l'ultimo CandleIndicator per il simbolo/timeframe.

    Cattura: RSI, EMA, ATR, volume, VWAP, swing levels, FVG, Order Block,
    CVD, funding rate, RS vs SPY.
    Usato per l'autopsia post-trade.
    """
    import json  # noqa: PLC0415
    from app.services.indicator_query import list_stored_indicators  # noqa: PLC0415

    try:
        rows = await list_stored_indicators(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            timeframe=timeframe,
            limit=1,
        )
        if not rows:
            return None

        ind = rows[0]

        def _f(v: object) -> float | None:
            from decimal import Decimal as _D  # noqa: PLC0415
            if v is None:
                return None
            try:
                return float(v) if isinstance(v, _D) else float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        snapshot = {
            "timestamp":    ind.timestamp.isoformat() if ind.timestamp else None,
            # EMA
            "ema_9":        _f(ind.ema_9),
            "ema_20":       _f(ind.ema_20),
            "ema_50":       _f(ind.ema_50),
            # Momentum
            "rsi_14":       _f(ind.rsi_14),
            # Volatilità
            "atr_14":       _f(ind.atr_14),
            # Volume
            "volume_ratio_vs_ma20": _f(ind.volume_ratio_vs_ma20),
            # Distanza dalle EMA
            "price_vs_ema20_pct":   _f(ind.price_vs_ema20_pct),
            "price_vs_ema50_pct":   _f(ind.price_vs_ema50_pct),
            # VWAP
            "vwap":                 _f(ind.vwap),
            "price_vs_vwap_pct":    _f(ind.price_vs_vwap_pct),
            "session_high":         _f(ind.session_high),
            "session_low":          _f(ind.session_low),
            "opening_range_high":   _f(ind.opening_range_high),
            "opening_range_low":    _f(ind.opening_range_low),
            # Swing structure
            "is_swing_high":              ind.is_swing_high,
            "is_swing_low":               ind.is_swing_low,
            "last_swing_high":            _f(ind.last_swing_high),
            "last_swing_low":             _f(ind.last_swing_low),
            "dist_to_swing_high_pct":     _f(ind.dist_to_swing_high_pct),
            "dist_to_swing_low_pct":      _f(ind.dist_to_swing_low_pct),
            "structural_range_pct":       _f(ind.structural_range_pct),
            "price_position_in_range":    _f(ind.price_position_in_range),
            # Fibonacci
            "fib_382":                    _f(ind.fib_382),
            "fib_500":                    _f(ind.fib_500),
            "fib_618":                    _f(ind.fib_618),
            "dist_to_fib_382_pct":        _f(ind.dist_to_fib_382_pct),
            "dist_to_fib_500_pct":        _f(ind.dist_to_fib_500_pct),
            "dist_to_fib_618_pct":        _f(ind.dist_to_fib_618_pct),
            # FVG (Fair Value Gap)
            "in_fvg_bullish":    ind.in_fvg_bullish,
            "in_fvg_bearish":    ind.in_fvg_bearish,
            "fvg_high":          _f(ind.fvg_high),
            "fvg_low":           _f(ind.fvg_low),
            "dist_to_fvg_pct":   _f(ind.dist_to_fvg_pct),
            "fvg_direction":     ind.fvg_direction,
            "fvg_filled":        ind.fvg_filled,
            # Order Block
            "in_ob_bullish":     ind.in_ob_bullish,
            "in_ob_bearish":     ind.in_ob_bearish,
            "ob_high":           _f(ind.ob_high),
            "ob_low":            _f(ind.ob_low),
            "ob_direction":      ind.ob_direction,
            "ob_strength":       _f(ind.ob_strength),
            "ob_filled":         ind.ob_filled,
            "dist_to_ob_pct":    _f(ind.dist_to_ob_pct),
            # CVD (Cumulative Volume Delta)
            "volume_delta":          _f(ind.volume_delta),
            "cvd":                   _f(ind.cvd),
            "cvd_normalized":        _f(ind.cvd_normalized),
            "cvd_trend":             ind.cvd_trend,
            "cvd_5":                 _f(ind.cvd_5),
            # Funding rate (crypto)
            "funding_rate":                  _f(ind.funding_rate),
            "funding_rate_annualized_pct":   _f(ind.funding_rate_annualized_pct),
            "funding_bias":                  ind.funding_bias,
            # RS vs SPY (stock)
            "rs_vs_spy":    _f(ind.rs_vs_spy),
            "rs_vs_spy_5":  _f(ind.rs_vs_spy_5),
            "rs_signal":    ind.rs_signal,
        }
        return json.dumps(snapshot, ensure_ascii=False)
    except Exception as exc:
        logger.warning("_build_entry_indicators_json: errore — %s", exc)
        return None


def _float_price(v: object | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_decimal(v: object | None) -> Decimal | None:
    """Converte float/str/Decimal in Decimal per i campi Numeric del modello."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def calculate_position_size(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
) -> float:
    """
    Sizing basato sul rischio: quante azioni comprare rischiando risk_pct% del capitale.
    Arrotonda per difetto all'unità intera — IBKR LMT richiede quantità intere per azioni US.
    """
    risk_amount = capital * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance < 1e-12:
        return 0.0
    size = risk_amount / stop_distance
    return float(math.floor(size))


async def execute_signal(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    take_profit_price: float,
    pattern_name: str,
    strength: float,
    timeframe: str = "1h",
    take_profit_2_price: float | None = None,
) -> dict:
    """
    Esegue un bracket order su TWS se configurato e sicuro.

    Guard rails:
    - TWS_ENABLED=true e IBKR_AUTO_EXECUTE=true
    - TWS connesso e autenticato
    - short solo se IBKR_MARGIN_ACCOUNT=true
    - max posizioni simultanee rispettato
    - nessuna posizione già aperta su quel simbolo
    - size >= 1 azione
    """
    _ = (pattern_name, strength)

    if not getattr(settings, "tws_enabled", False):
        return {"status": "skipped", "reason": "TWS_ENABLED=false"}

    if not settings.ibkr_auto_execute:
        return {"status": "skipped", "reason": "IBKR_AUTO_EXECUTE=false"}

    if (
        (direction or "").lower() == "bearish"
        and not settings.ibkr_margin_account
    ):
        return {
            "status": "skipped",
            "reason": "Short non disponibile: IBKR_MARGIN_ACCOUNT=false",
        }

    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        return {"status": "error", "reason": "TWS non connesso"}

    # ── Controllo posizioni duplicate e ordini pendenti ──────────────────
    open_positions = await tws.get_open_positions()

    sym_u = symbol.upper()
    for pos in open_positions:
        if pos.get("symbol", "").upper() == sym_u:
            return {
                "status": "skipped",
                "reason": f"Posizione già aperta su {symbol}",
            }

    # Controlla anche ordini entry LMT pendenti (PreSubmitted/Submitted, non ancora fillati).
    # get_open_positions() mostra solo position != 0, quindi non vede i pending entry.
    # Senza questo check, due cicli pipeline consecutivi invierebbero due bracket sullo stesso simbolo.
    if await tws.has_pending_entry_order(sym_u):
        return {
            "status": "skipped",
            "reason": f"Ordine entry già pendente su {symbol} (non ancora fillato)",
        }

    # ── Slot management + esecuzione: serializzati via _slot_lock ───────────
    # Il lock previene la race condition TOCTOU: due coroutine parallele (es.
    # pipeline hook + post-cycle scan) che leggono lo stesso slot libero e
    # procedono entrambe, superando il cap di posizioni simultanee.
    # Serializzare l'intera sezione (slot check → TWS call → registry write)
    # è corretto per un trading system: non vogliamo esecuzioni concorrenti.
    async with _slot_lock:

        # ── Slot management: Strategy E+ (slot separation bidirezionale 3+2) ──
        # Il 1h usa prima i 3 slot 1h_prio; se pieni di 5m → sfratta il piu' vecchio;
        # se tutti 1h_prio occupati da 1h → prende in prestito slot 5m liberi.
        # Il 5m usa prima i 2 slot 5m; se pieni → usa slot 1h_prio liberi.
        # Il 5m non chiude MAI un 1h per fare spazio.
        max_total = settings.ibkr_max_simultaneous_positions  # 5
        slots_1h  = getattr(settings, "ibkr_slots_1h", 3)
        slots_5m  = getattr(settings, "ibkr_slots_5m", 2)

        open_syms = {p.get("symbol", "").upper() for p in open_positions}

        # Sincronizza il registry: rimuovi simboli non piu' aperti
        for _s in list(_slot_registry):
            if _s not in open_syms:
                del _slot_registry[_s]

        # Conta per slot_type e timeframe
        known  = {s: info for s, info in _slot_registry.items() if s in open_syms}
        n_1h_in_1hprio = sum(1 for i in known.values() if i["timeframe"]=="1h" and i["slot_type"]=="1h_prio")
        n_5m_in_1hprio = sum(1 for i in known.values() if i["timeframe"]=="5m" and i["slot_type"]=="1h_prio")
        n_1h_in_5m     = sum(1 for i in known.values() if i["timeframe"]=="1h" and i["slot_type"]=="5m")
        n_5m_in_5m     = sum(1 for i in known.values() if i["timeframe"]=="5m" and i["slot_type"]=="5m")
        # Posizioni senza registry entry → conteggiate come 5m_in_5m (conservativo)
        n_unknown = len(open_syms) - len(known)
        n_5m_in_5m += n_unknown

        n_1hprio_free = slots_1h - n_1h_in_1hprio - n_5m_in_1hprio
        n_5m_free     = slots_5m - n_1h_in_5m - n_5m_in_5m

        # Normalizza il timeframe del segnale corrente
        tf = (timeframe or "5m").strip().lower()
        slot_type: str  # assegnato nel branch corretto

        if tf == "1h":
            if n_1hprio_free > 0:
                slot_type = "1h_prio"                   # slot 1h_prio libero
            elif n_5m_free > 0:
                slot_type = "5m"                        # prende in prestito slot 5m
            elif n_5m_in_1hprio > 0:
                # Tutti i 3 slot 1h_prio occupati da 5m → sfratta il piu' vecchio
                candidates = [
                    (s, info) for s, info in known.items()
                    if info["timeframe"] == "5m" and info["slot_type"] == "1h_prio"
                ]
                oldest_sym, oldest_info = min(candidates, key=lambda x: x[1]["opened_at"])
                oldest_pos = next(
                    (p for p in open_positions if p.get("symbol","").upper() == oldest_sym), None
                )
                if oldest_pos is None:
                    return {
                        "status": "skipped",
                        "reason": f"Sfratto {oldest_sym}: posizione non trovata in TWS",
                    }
                qty = float(oldest_pos.get("position", 0))
                # Determina azione: se position > 0 → long → chiudi con SELL, viceversa BUY
                close_action = "SELL" if qty > 0 else "BUY"
                close_res = await tws.place_market_close_order(
                    symbol=oldest_sym,
                    action=close_action,
                    quantity=abs(qty),
                )
                if "error" in close_res:
                    return {
                        "status": "skipped",
                        "reason": f"Sfratto 5m {oldest_sym} fallito: {close_res['error']}",
                    }
                logger.info(
                    "E+ Slot eviction: sfrattato 5m %s (slot 1h_prio) per 1h %s",
                    oldest_sym, symbol,
                )
                del _slot_registry[oldest_sym]
                slot_type = "1h_prio"
            else:
                # Tutti i 3 slot 1h_prio occupati da trade 1h
                return {
                    "status": "skipped",
                    "reason": (
                        f"Slot 1h pieni: {n_1h_in_1hprio}/{slots_1h} slot 1h_prio + "
                        f"0 slot 5m liberi (n_5m_in_5m={n_5m_in_5m})"
                    ),
                }
        else:  # "5m" o timeframe sconosciuto
            if n_5m_free > 0:
                slot_type = "5m"                        # slot 5m proprio libero
            elif n_1hprio_free > 0:
                slot_type = "1h_prio"                   # prende in prestito slot 1h_prio
            else:
                return {
                    "status": "skipped",
                    "reason": (
                        f"Slot 5m pieni: {n_5m_in_5m + n_1h_in_5m}/{slots_5m} usati, "
                        f"slot 1h_prio occupati ({n_1h_in_1hprio} da 1h, {n_5m_in_1hprio} da 5m)"
                    ),
                }

        # ── Sizing ──────────────────────────────────────────────────────────
        net_liq = await tws.get_net_liquidation(currency="USD")
        max_cap = getattr(settings, "ibkr_max_capital", 0.0)
        if net_liq is not None and net_liq > 0:
            # IBKR_MAX_CAPITAL cap: se impostato, limita il capitale usato per il sizing.
            # Utile quando il conto paper ha equity elevata ma si vuole operare su scala ridotta.
            if max_cap > 0:
                capital = min(net_liq, max_cap)
                logger.info(
                    "TWS auto-execute: capitale=min(NetLiq=%.2f, MaxCap=%.2f)=%.2f",
                    net_liq, max_cap, capital,
                )
            else:
                capital = net_liq
                logger.info("TWS auto-execute: capitale da NetLiquidation=%.2f", capital)
        else:
            fallback = max_cap
            if fallback > 0:
                capital = fallback
                logger.warning(
                    "TWS auto-execute: NetLiquidation non disponibile — "
                    "fallback a IBKR_MAX_CAPITAL=%.2f (symbol=%s, pattern=%s). "
                    "Verificare connessione TWS e permessi account.",
                    capital, symbol, pattern_name,
                )
            else:
                logger.error(
                    "TWS auto-execute: NetLiquidation non disponibile e IBKR_MAX_CAPITAL=0 "
                    "— ordine annullato (symbol=%s, pattern=%s).",
                    symbol, pattern_name,
                )
                await send_system_alert(
                    f"NetLiquidation non disponibile e IBKR_MAX_CAPITAL=0 "
                    f"— ordine annullato per {symbol} ({pattern_name}).\n"
                    "Impostare IBKR_MAX_CAPITAL nel .env oppure verificare connessione TWS."
                )
                return {
                    "status": "skipped",
                    "reason": (
                        "NetLiquidation non disponibile: impossibile calcolare il sizing "
                        "in modo sicuro. Ordine annullato per prevenire position size errata."
                    ),
                }

        # Risk % timeframe-specific.
        # 1h: ibkr_risk_pct_1h fisso (1.5% default).
        # 5m: differenziato per ora ET (RISK_SIZE_5M_BY_HOUR_ET) — OOS-confermato.
        #     0.30% alle 11/16 ET (edge basso), 0.50% alle 12-14 ET, 0.75% alle 15 ET (ALPHA).
        #     Fallback su ibkr_risk_pct_5m se ora non in dict.
        # In ogni caso, se il risk è 0 o non configurato, fallback su ibkr_max_risk_per_trade_pct.
        _tf = (timeframe or "1h").strip().lower()
        if _tf == "1h":
            _tf_risk = getattr(settings, "ibkr_risk_pct_1h", 0.0)
            _risk_source = "ibkr_risk_pct_1h"
        else:
            # 5m: lookup risk per ora ET corrente (datetime.now ET — preciso entro min)
            try:
                from zoneinfo import ZoneInfo  # noqa: PLC0415
                _hour_et = datetime.now(tz=ZoneInfo("America/New_York")).hour
            except Exception:
                _hour_et = (datetime.now(timezone.utc).hour - 4) % 24  # fallback EDT
            _tf_risk = RISK_SIZE_5M_BY_HOUR_ET.get(
                _hour_et, getattr(settings, "ibkr_risk_pct_5m", 0.0)
            )
            _risk_source = f"RISK_SIZE_5M_BY_HOUR_ET[hour_et={_hour_et:02d}]"
        _effective_risk_pct = _tf_risk if _tf_risk > 0 else settings.ibkr_max_risk_per_trade_pct
        logger.info(
            "TWS auto-execute sizing: tf=%s  risk_pct=%.2f%% (%s)  capital=%.0f",
            _tf, _effective_risk_pct, _risk_source, capital,
        )
        size = calculate_position_size(
            capital=capital,
            risk_pct=_effective_risk_pct,
            entry_price=entry_price,
            stop_price=stop_price,
        )
        if size < 1:
            return {
                "status": "skipped",
                "reason": f"Size troppo piccola ({size}) — distanza stop troppo ampia rispetto al capitale (capital={capital:.0f})",
            }

        # MAX_NOTIONAL safety: notional > 2× capital → stop troppo stretto, sizing esplose.
        # Anche con MIN_RISK_PCT sul validator, questo blocco garantisce un secondo livello
        # di protezione per qualsiasi path che bypassa il validator (es. ordini manuali via API).
        _notional = size * entry_price
        _max_notional = capital * 2.0
        if _notional > _max_notional:
            logger.error(
                "TWS auto-execute BLOCCATO: notional=%.0f > max_notional=%.0f "
                "(capital=%.0f, size=%.1f, entry=%.4f) — symbol=%s pattern=%s",
                _notional, _max_notional, capital, size, entry_price, symbol, pattern_name,
            )
            return {
                "status": "skipped",
                "reason": (
                    f"Notional {_notional:,.0f} USD > MAX ({_max_notional:,.0f} USD = capital×2) — "
                    f"stop troppo stretto (size={size:.0f} × entry={entry_price:.2f}). "
                    "Fix: aumentare MIN_RISK_PCT nel validator o verificare parametri stop."
                ),
            }

        action = "BUY" if (direction or "").lower() == "bullish" else "SELL"

        logger.info(
            "TWS auto-execute: %s %s x%.1f  entry=%.4f  stop=%.4f  tp=%.4f  pattern=%s  strength=%.2f",
            action, symbol, size, entry_price, stop_price, take_profit_price, pattern_name, strength,
        )

        try:
            result = await tws.place_bracket_order(
                symbol=sym_u,
                action=action,
                quantity=size,
                entry_price=entry_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                take_profit_2_price=take_profit_2_price,
                exchange="SMART",
                currency="USD",
            )
        except Exception as exc:
            logger.exception("TWS place_bracket_order raised exception: %s", exc)
            return {
                "status": "error",
                "reason": f"exception: {exc}",
                "tws_status": "exception",
            }

        # Caso 1: TWS ritorna {"error": ...} senza eccezione (disconnessione, timeout
        # nel sync wrapper, _ensure_started() fallito). Non catturato da try/except
        # perché è un dict normale, non un'eccezione Python.
        if result.get("error"):
            error_msg = result["error"]
            logger.error(
                "TWS place_bracket_order fallito (no exception): symbol=%s reason=%s",
                symbol, error_msg,
            )
            return {
                "status": "error",
                "reason": error_msg,
                "tws_status": "tws_unavailable",
            }

        # Caso 2: TWS ha risposto ma con errors nel log — distingui critici da informativi
        errors_list: list[str] = result.get("errors", []) or []
        if errors_list:
            critical_errors = [e for e in errors_list if is_critical_ibkr_error(e)]
            info_errors = [e for e in errors_list if not is_critical_ibkr_error(e)]

            if info_errors:
                logger.info(
                    "TWS bracket order info messages (non-critical): symbol=%s msgs=%s",
                    symbol, info_errors,
                )
            if critical_errors:
                logger.error(
                    "TWS bracket order rejected with critical errors: symbol=%s errors=%s",
                    symbol, critical_errors,
                )
                return {
                    "status": "error",
                    "reason": "; ".join(critical_errors),
                    "tws_status": "rejected",
                    "tws_errors": critical_errors,
                    "tws_result": result,
                }

        # Caso 3: risposta valida, ma senza orderId nell'entry — indica un problema
        # di conferma che renderebbe impossibile tracciare il fill successivo.
        entry_order_in_result = result.get("entry", {}) or {}
        if not entry_order_in_result.get("order_id"):
            logger.error(
                "TWS bracket order risposto senza entry order_id valido: symbol=%s result=%s",
                symbol, result,
            )
            return {
                "status": "error",
                "reason": "no entry order_id in TWS response",
                "tws_status": "no_order_id",
                "tws_result": result,
            }

        logger.info(
            "TWS bracket result: entry=%s  tp=%s  sl=%s",
            entry_order_in_result.get("status"),
            (result.get("take_profit") or {}).get("status"),
            (result.get("stop_loss") or {}).get("status"),
        )

        # Registra slot nel registry per E+ slot management
        _slot_registry[sym_u] = {
            "timeframe": tf,
            "slot_type": slot_type,
            "opened_at": datetime.now(timezone.utc),
        }

        return {
            "status": "executed",
            "tws_status": "submitted",
            "symbol": symbol,
            "action": action,
            "size": size,
            "entry": entry_price,
            "stop": stop_price,
            "tp": take_profit_price,
            "tp2": take_profit_2_price,
            "capital_used": capital,
            "tws_result": result,
        }


async def _execute_and_save(
    session: AsyncSession,
    opp: object,
    source_label: str = "hook",
) -> bool:
    """
    Esegue un bracket order per una singola opportunità e salva il risultato nel DB.

    Ritorna True se l'ordine è stato effettivamente inviato (status='executed').
    """
    opp_row = opp  # type: ignore[assignment]
    plan = opp_row.trade_plan
    if plan is None:
        return False
    entry = _float_price(plan.entry_price)
    stop  = _float_price(plan.stop_loss)
    tp    = _float_price(plan.take_profit_1)
    tp2   = _float_price(plan.take_profit_2)
    if entry is None or stop is None or tp is None:
        return False

    direction = opp_row.latest_pattern_direction or "bullish"
    strength  = float(opp_row.latest_pattern_strength or 0.0)

    result = await execute_signal(
        symbol=opp_row.symbol,
        direction=direction,
        entry_price=entry,
        stop_price=stop,
        take_profit_price=tp,
        pattern_name=opp_row.latest_pattern_name or "",
        strength=strength,
        timeframe=getattr(opp_row, "timeframe", "1h") or "1h",
        take_profit_2_price=tp2,
    )

    is_executed = isinstance(result, dict) and result.get("status") == "executed"
    log_level = logger.info if is_executed else logger.warning
    log_level(
        "TWS auto-execute [%s] %s %s → status=%s tws_status=%s reason=%s",
        source_label,
        opp_row.symbol,
        opp_row.timeframe,
        result.get("status") if isinstance(result, dict) else "?",
        result.get("tws_status") if isinstance(result, dict) else "?",
        result.get("reason") if isinstance(result, dict) else "?",
    )

    # Estrai campi dalla risposta — gestisce sia il path "executed" che "error"
    tws_res = (result.get("tws_result") or {}) if isinstance(result, dict) else {}
    entry_order  = tws_res.get("entry") or {}
    tp_order     = tws_res.get("take_profit") or {}
    sl_order     = tws_res.get("stop_loss") or {}
    tp2_order    = tws_res.get("take_profit_2") or {}
    sl2_order    = tws_res.get("stop_loss_2") or {}
    is_split     = bool(tws_res.get("split"))

    # tws_status: usa il campo esplicito introdotto nel nuovo schema; se assente
    # (es. vecchio path "skipped"), cade su result["status"].
    tws_status_str: str = (
        (result.get("tws_status") or result.get("status") or "unknown")
        if isinstance(result, dict)
        else "unknown"
    )
    size_val = result.get("size") if isinstance(result, dict) else None
    capital_used_val = result.get("capital_used") if isinstance(result, dict) else None

    # Order ID solo se l'ordine è stato effettivamente inviato
    entry_order_id_val: int | None  = entry_order.get("order_id")  if is_executed else None
    tp_order_id_val: int | None     = tp_order.get("order_id")     if is_executed else None
    sl_order_id_val: int | None     = sl_order.get("order_id")     if is_executed else None
    tp2_order_id_val: int | None    = tp2_order.get("order_id")    if is_executed else None
    sl2_order_id_val: int | None    = sl2_order.get("order_id")    if is_executed else None

    # Quantità per leg: split → qty_tp1 e qty_tp2 dal result; singolo → tutto su qty_tp1
    qty_tp1_val: float | None = (
        float(tws_res["qty_tp1"]) if is_executed and is_split and tws_res.get("qty_tp1") else size_val
    )
    qty_tp2_val: float | None = (
        float(tws_res["qty_tp2"]) if is_executed and is_split and tws_res.get("qty_tp2") else None
    )

    # Errori TWS (stringa sintetica per il campo error del DB)
    tws_errors_list: list[str] = (
        result.get("tws_errors")
        or tws_res.get("errors")
        or []
    ) if isinstance(result, dict) else []
    error_str: str | None = (
        result.get("reason")
        if not is_executed and isinstance(result, dict)
        else ("; ".join(str(e) for e in tws_errors_list) if tws_errors_list else None)
    )

    # ── Snapshot autopsia (context + indicatori) ──────────────────────────
    # Serializzati qui, quando l'opportunità è ancora fresca in memoria,
    # per consentire analisi retrospettiva: perché SL invece di TP?
    entry_context_json = _build_entry_context_json(opp_row)
    entry_indicators_json = await _build_entry_indicators_json(
        session,
        symbol=opp_row.symbol,
        exchange=opp_row.exchange or "",
        provider=opp_row.provider or "",
        timeframe=opp_row.timeframe,
    )

    rec = ExecutedSignal(
        symbol=opp_row.symbol,
        timeframe=opp_row.timeframe,
        provider=opp_row.provider or "",
        exchange=opp_row.exchange or "",
        direction=direction,
        pattern_name=opp_row.latest_pattern_name or "",
        pattern_strength=strength or None,
        opportunity_score=opp_row.final_opportunity_score,
        entry_price=_to_decimal(entry),
        stop_price=_to_decimal(stop),
        take_profit_1=_to_decimal(tp),
        take_profit_2=_to_decimal(tp2),
        quantity_tp1=qty_tp1_val if is_executed else None,
        quantity_tp2=qty_tp2_val if is_executed else None,
        entry_order_id=entry_order_id_val,
        tp_order_id=tp_order_id_val,
        sl_order_id=sl_order_id_val,
        tp2_order_id=tp2_order_id_val,
        sl2_order_id=sl2_order_id_val,
        tws_status=tws_status_str,
        error=error_str,
        ordered_qty=_to_decimal(size_val) if is_executed else None,
        entry_context_json=entry_context_json,
        entry_indicators_json=entry_indicators_json,
    )
    session.add(rec)
    executed_ok = False
    try:
        await session.commit()
        executed_ok = is_executed
        if is_executed:
            logger.info(
                "ExecutedSignal INVIATO [%s]: %s %s id=%s tws_status=%s",
                source_label, opp_row.symbol, opp_row.timeframe, rec.id, tws_status_str,
            )
            if settings.notify_order_events_enabled:
                from app.services.alert_notifications import send_order_executed_notification  # noqa: PLC0415
                _t = asyncio.create_task(send_order_executed_notification(
                    symbol=opp_row.symbol,
                    timeframe=opp_row.timeframe,
                    direction=direction,
                    entry_price=entry,
                    stop_price=stop,
                    take_profit_price=tp,
                    size=float(size_val or 0),
                    capital=float(capital_used_val or settings.ibkr_max_capital or 0),
                ))
                _bg_tasks.add(_t)
                _t.add_done_callback(_bg_tasks.discard)
        else:
            logger.warning(
                "ExecutedSignal FALLITO salvato [%s]: %s %s id=%s tws_status=%s error=%s",
                source_label, opp_row.symbol, opp_row.timeframe, rec.id,
                tws_status_str, error_str,
            )
    except Exception:
        await session.rollback()
        logger.exception("Errore salvataggio ExecutedSignal nel DB [%s]", source_label)
        return False

    # ── Avvia fill monitoring in background ──────────────────────────────
    # Lancia come asyncio task separato così non blocca il ciclo pipeline.
    # Il task gestisce la propria sessione DB via AsyncSessionLocal.
    if (
        executed_ok
        and rec.id is not None
        and entry_order_id_val is not None
        and getattr(settings, "tws_enabled", False)
    ):
        _close_action = "BUY" if (direction or "").lower() == "bullish" else "SELL"
        _t = asyncio.create_task(
            _handle_partial_fill_after_bracket(
                rec_id=rec.id,
                entry_order_id=entry_order_id_val,
                sl_order_id=sl_order_id_val,
                tp_order_id=tp_order_id_val,
                ordered_qty=float(qty_tp1_val or size_val or 0),
                symbol=opp_row.symbol,
                action=_close_action,
                stop_price=stop,
                take_profit_price=tp,
                exchange=opp_row.exchange or "SMART",
                currency="USD",
            )
        )
        _bg_tasks.add(_t)
        _t.add_done_callback(_bg_tasks.discard)

    return executed_ok


async def maybe_ibkr_auto_execute_after_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """
    Hook post-pipeline: per ogni segnale 'execute' del simbolo/timeframe appena
    refreshato, invia un bracket order via TWS.

    Filtra provider e timeframe contro le liste config-driven:
      - auto_execute_providers_list (default: yahoo_finance, binance)
      - auto_execute_timeframes_list (default: 1h — 5m escluso di default)

    Guard rail: MAX_ORDERS_PER_HOOK_INVOCATION (default 5) per singola invocation.
    """
    if not getattr(settings, "tws_enabled", False) or not settings.ibkr_auto_execute:
        return

    # Guard: se TWS non è connessa, non ha senso chiamare list_opportunities
    # (costosa: ~1-2s per simbolo con pq cache miss) solo per scoprire che non
    # si può fare nulla. Questo early-return elimina ~35 compute/min di per-symbol
    # pq cache che saturavano l'event loop quando TWS è in attesa di connessione.
    try:
        from app.services.tws_service import get_tws_service  # noqa: PLC0415
        _tws = get_tws_service()
        if _tws is None or not _tws.is_connected:
            return
    except Exception:
        return

    sym = (body.symbol or "").strip()
    tf = (body.timeframe or "").strip()
    if not sym or not tf:
        return

    if body.provider not in settings.auto_execute_providers_list:
        return
    if tf not in settings.auto_execute_timeframes_list:
        return

    # Usa la chiave globale (provider=None, timeframe=None) già warm dal startup warmup
    # invece di una chiave per-simbolo che non è in cache → genera miss costosi
    # (pq 1-7s, var 9-17s, tpb 78-80s per simbolo × 35 simboli per ciclo).
    # La chiave globale stale-while-revalidate è praticamente sempre disponibile.
    try:
        all_rows = await list_opportunities(
            session,
            symbol=None,
            exchange=None,
            provider=None,
            asset_type=None,
            timeframe=None,
            limit=500,
            decision="execute",
        )
    except Exception:
        logger.exception("TWS auto-execute hook: list_opportunities failed")
        return

    sym_upper = sym.upper()
    provider_norm = (body.provider or "").strip()
    rows = [
        r for r in all_rows
        if r.operational_decision == "execute"
        and (r.symbol or "").upper() == sym_upper
        and (r.provider or "") == provider_norm
        and (r.timeframe or "") == tf
    ][:MAX_ORDERS_PER_HOOK_INVOCATION + 1]

    executed_count = 0
    for opp in rows:
        if opp.operational_decision != "execute":
            continue
        if executed_count >= MAX_ORDERS_PER_HOOK_INVOCATION:
            logger.warning(
                "maybe_ibkr_auto_execute: cap %d raggiunto per %s/%s/%s — skip restanti",
                MAX_ORDERS_PER_HOOK_INVOCATION, body.provider, sym, tf,
            )
            break
        ok = await _execute_and_save(session, opp, source_label="pipeline-hook")
        if ok:
            executed_count += 1


async def run_auto_execute_scan(
    timeframes_override: list[str] | None = None,
) -> None:
    """
    Scan post-ciclo: riesamina TUTTE le opportunità con decision='execute' per
    catturare segnali che l'hook per-simbolo non ha rilevato.

    Itera su tutte le combinazioni (provider, timeframe) abilitate da config:
      - auto_execute_providers_enabled (default: yahoo_finance, binance)
      - auto_execute_timeframes_enabled (default: 1h — 5m escluso di default)

    Questo accade quando al momento del pipeline refresh individuale la decisione
    era 'monitor' (es. confluenza=1, prezzo stale, regime non ancora aggiornato),
    ma dopo il ricalcolo completo post-ciclo la decisione è diventata 'execute'.

    Guard rails:
      - MAX_ORDERS_PER_SCAN: cap globale per ciclo (evita runaway)
      - Un errore su una combinazione non blocca le altre (continua sul prossimo)

    Args:
        timeframes_override: se valorizzato, restringe la scansione a questi timeframe
                             invece di usare auto_execute_timeframes_list. Usato in split
                             mode per scopare ogni ciclo al proprio timeframe ed evitare
                             doppia esecuzione se 1h e 5m girano in sovrapposizione.

    Viene chiamato una volta per ciclo, dopo il prewarm.
    """
    if not getattr(settings, "tws_enabled", False):
        return
    if not settings.ibkr_auto_execute:
        return

    enabled_providers = settings.auto_execute_providers_list
    enabled_timeframes = timeframes_override if timeframes_override is not None else settings.auto_execute_timeframes_list

    if not enabled_providers or not enabled_timeframes:
        logger.debug("run_auto_execute_scan: nessuna combinazione abilitata da config, skip")
        return

    from app.db.session import AsyncSessionLocal  # noqa: PLC0415

    total_executed = 0
    total_errors = 0
    cap_reached = False

    # Una sola chiamata globale (provider=None, timeframe=None) invece di N×M chiamate
    # per ogni combinazione (provider, timeframe). La chiave cache globale è già warm
    # dal startup warmup e non viene invalidata dai job per-provider, quindi questa
    # chiamata è quasi istantanea (hit cache). Le N×M chiamate separate generavano
    # pq/tpb/var miss per ogni combo non prewarmed (alpaca/5m, yahoo/5m, …), bloccando
    # l'event loop per 15-30s per ciclo e rallentando il frontend a 14-34s.
    try:
        async with AsyncSessionLocal() as session:
            all_rows = await list_opportunities(
                session,
                symbol=None,
                exchange=None,
                provider=None,
                asset_type=None,
                timeframe=None,
                limit=500,
                decision="execute",
            )
    except Exception:
        logger.exception("run_auto_execute_scan: list_opportunities failed")
        all_rows = []

    enabled_providers_set = set(enabled_providers)
    enabled_timeframes_set = set(enabled_timeframes)

    execute_rows = [
        r for r in all_rows
        if r.operational_decision == "execute"
        and (r.provider or "") in enabled_providers_set
        and (r.timeframe or "") in enabled_timeframes_set
    ]

    if execute_rows:
        logger.info("run_auto_execute_scan: %d segnale/i execute trovati", len(execute_rows))
    else:
        logger.debug("run_auto_execute_scan: nessun segnale execute")

    for opp in execute_rows:
        if total_executed >= MAX_ORDERS_PER_SCAN:
            logger.warning(
                "run_auto_execute_scan: cap globale %d raggiunto — stop scan.",
                MAX_ORDERS_PER_SCAN,
            )
            cap_reached = True
            break
        async with AsyncSessionLocal() as session:
            ok = await _execute_and_save(session, opp, source_label="post-cycle-scan")
        if ok:
            total_executed += 1
        else:
            total_errors += 1

    logger.info(
        "run_auto_execute_scan completato: executed=%d errors=%d cap_reached=%s "
        "(providers=%s timeframes=%s)",
        total_executed, total_errors, cap_reached, enabled_providers, enabled_timeframes,
    )
