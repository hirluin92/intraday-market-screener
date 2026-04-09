"""
Auto-esecuzione ordini via TWS (ib_insync).

Bracket order completo: entry LMT + TP LMT + SL STP (GTC).
Chiamato dopo pipeline refresh se TWS_ENABLED=true e IBKR_AUTO_EXECUTE=true.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.executed_signal import ExecutedSignal
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.opportunities import list_opportunities

logger = logging.getLogger(__name__)


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
    Arrotonda per difetto al decimale.
    """
    risk_amount = capital * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance < 1e-12:
        return 0.0
    size = risk_amount / stop_distance
    return math.floor(size * 10.0) / 10.0


async def execute_signal(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    take_profit_price: float,
    pattern_name: str,
    strength: float,
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

    # ── Controllo posizioni aperte ─────────────────────────────────────────
    open_positions = await tws.get_open_positions()
    if len(open_positions) >= settings.ibkr_max_simultaneous_positions:
        return {
            "status": "skipped",
            "reason": (
                f"Già {len(open_positions)} posizioni aperte "
                f"(max {settings.ibkr_max_simultaneous_positions})"
            ),
        }

    sym_u = symbol.upper()
    for pos in open_positions:
        if pos.get("symbol", "").upper() == sym_u:
            return {
                "status": "skipped",
                "reason": f"Posizione già aperta su {symbol}",
            }

    # ── Sizing ────────────────────────────────────────────────────────────
    # Legge il saldo reale dal conto TWS; fallback a IBKR_MAX_CAPITAL se non disponibile.
    net_liq = await tws.get_net_liquidation(currency="USD")
    if net_liq is not None and net_liq > 0:
        capital = net_liq
        logger.info("TWS auto-execute: capitale da NetLiquidation=%.2f USD", capital)
    else:
        capital = settings.ibkr_max_capital
        logger.warning(
            "TWS auto-execute: NetLiquidation non disponibile, uso IBKR_MAX_CAPITAL=%.2f",
            capital,
        )

    size = calculate_position_size(
        capital=capital,
        risk_pct=settings.ibkr_max_risk_per_trade_pct,
        entry_price=entry_price,
        stop_price=stop_price,
    )
    if size < 1:
        return {
            "status": "skipped",
            "reason": f"Size troppo piccola ({size}) — distanza stop troppo ampia rispetto al capitale (capital={capital:.0f})",
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
            exchange="SMART",
            currency="USD",
        )
    except Exception as exc:
        logger.exception("TWS place_bracket_order failed: %s", exc)
        return {"status": "error", "reason": str(exc)}

    if result.get("errors"):
        logger.warning("TWS bracket order errors: %s", result["errors"])

    logger.info("TWS bracket result: entry=%s  tp=%s  sl=%s",
                result.get("entry", {}).get("status"),
                result.get("take_profit", {}).get("status"),
                result.get("stop_loss", {}).get("status"))

    return {
        "status": "executed",
        "symbol": symbol,
        "action": action,
        "size": size,
        "entry": entry_price,
        "stop": stop_price,
        "tp": take_profit_price,
        "tws_result": result,
    }


async def maybe_ibkr_auto_execute_after_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """
    Hook post-pipeline: se c'è un segnale 'execute', invia il bracket order via TWS.
    """
    if not getattr(settings, "tws_enabled", False) or not settings.ibkr_auto_execute:
        return
    if body.provider != "yahoo_finance":
        return
    sym = (body.symbol or "").strip()
    tf = (body.timeframe or "").strip()
    if not sym or not tf:
        return

    try:
        rows = await list_opportunities(
            session,
            symbol=sym,
            exchange=body.exchange,
            provider=body.provider,
            asset_type=None,
            timeframe=tf,
            limit=5,
            decision="execute",
        )
    except Exception:
        logger.exception("TWS auto-execute hook: list_opportunities failed")
        return

    for opp in rows:
        if opp.operational_decision != "execute":
            continue
        plan = opp.trade_plan
        if plan is None:
            continue
        entry = _float_price(plan.entry_price)
        stop  = _float_price(plan.stop_loss)
        tp    = _float_price(plan.take_profit_1)
        tp2   = _float_price(plan.take_profit_2)
        if entry is None or stop is None or tp is None:
            continue
        direction = opp.latest_pattern_direction or "bullish"
        strength  = float(opp.latest_pattern_strength or 0.0)
        result = await execute_signal(
            symbol=opp.symbol,
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=tp,
            pattern_name=opp.latest_pattern_name or "",
            strength=strength,
        )
        logger.info("TWS auto-execute hook result: %s", result)

        # ── Salva nel DB registro eseguiti ────────────────────────────────
        tws_res = result.get("tws_result", {}) if isinstance(result, dict) else {}
        entry_order = tws_res.get("entry", {})
        tp_order    = tws_res.get("take_profit", {})
        sl_order    = tws_res.get("stop_loss", {})
        errors      = tws_res.get("errors", [])
        status_str  = entry_order.get("status", "unknown") if entry_order else result.get("status", "unknown")
        size_val    = result.get("size") if isinstance(result, dict) else None

        rec = ExecutedSignal(
            symbol=opp.symbol,
            timeframe=opp.timeframe,
            provider=opp.provider or "",
            exchange=opp.exchange or "",
            direction=direction,
            pattern_name=opp.latest_pattern_name or "",
            pattern_strength=strength or None,
            opportunity_score=opp.final_opportunity_score,
            entry_price=_to_decimal(entry),
            stop_price=_to_decimal(stop),
            take_profit_1=_to_decimal(tp),
            take_profit_2=_to_decimal(tp2),
            quantity_tp1=size_val,
            entry_order_id=entry_order.get("order_id") if entry_order else None,
            tp_order_id=tp_order.get("order_id") if tp_order else None,
            sl_order_id=sl_order.get("order_id") if sl_order else None,
            tws_status=status_str,
            error="; ".join(str(e) for e in errors) if errors else None,
        )
        session.add(rec)
        try:
            await session.commit()
            logger.info("ExecutedSignal salvato nel DB: %s %s id=%s", opp.symbol, opp.timeframe, rec.id)
        except Exception:
            await session.rollback()
            logger.exception("Errore salvataggio ExecutedSignal nel DB")

        break  # un solo ordine per ciclo
