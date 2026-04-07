"""
Auto-esecuzione ordini via IBKR Client Portal (paper di default).

Chiamato opzionalmente dopo pipeline refresh se ``ibkr_auto_execute`` è true.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.ibkr_service import get_ibkr_service
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


def calculate_position_size(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
) -> float:
    risk_amount = capital * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance < 1e-12:
        return 0.0
    size = risk_amount / stop_distance
    return math.floor(size * 10.0) / 10.0


def _open_position_count(positions: list[dict]) -> int:
    n = 0
    for p in positions:
        try:
            pos = float(p.get("position", 0) or 0)
        except (TypeError, ValueError):
            pos = 0.0
        if abs(pos) > 1e-6:
            n += 1
    return n


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
    Esegue un segnale su IBKR se configurato e sicuro (paper, auth, limiti).
    """
    _ = (pattern_name, strength)

    if not settings.ibkr_enabled:
        return {"status": "skipped", "reason": "IBKR disabled"}

    if not settings.ibkr_auto_execute:
        return {"status": "skipped", "reason": "Auto-execute disabled"}

    if (
        (direction or "").lower() == "bearish"
        and not settings.ibkr_margin_account
        and not settings.ibkr_paper_trading
    ):
        return {
            "status": "skipped",
            "reason": "Short non disponibile su cash account — in attesa margin account",
        }

    if not settings.ibkr_paper_trading:
        logger.warning("IBKR auto-execute con conto REALE — verificare configurazione")

    ibkr = get_ibkr_service()

    if not await ibkr.is_authenticated():
        return {"status": "error", "reason": "IBKR gateway non autenticato"}

    account_id = (settings.ibkr_account_id or "").strip()
    if not account_id:
        return {"status": "error", "reason": "IBKR_ACCOUNT_ID non configurato"}

    positions = await ibkr.get_positions(account_id)
    if _open_position_count(positions) >= settings.ibkr_max_simultaneous_positions:
        return {
            "status": "skipped",
            "reason": f"Gia' {settings.ibkr_max_simultaneous_positions} posizioni aperte (max)",
        }

    sym_u = symbol.upper()
    for pos in positions:
        t = str(pos.get("ticker") or pos.get("contractDesc") or "").upper()
        if sym_u in t or t == sym_u:
            try:
                if abs(float(pos.get("position", 0) or 0)) > 1e-6:
                    return {
                        "status": "skipped",
                        "reason": f"Posizione gia' aperta su {symbol}",
                    }
            except (TypeError, ValueError):
                continue

    conid = await ibkr.get_conid(symbol)
    if not conid:
        return {"status": "error", "reason": f"Contratto non trovato per {symbol}"}

    size = calculate_position_size(
        capital=settings.ibkr_max_capital,
        risk_pct=settings.ibkr_max_risk_per_trade_pct,
        entry_price=entry_price,
        stop_price=stop_price,
    )

    if size < 1:
        return {
            "status": "skipped",
            "reason": f"Size troppo piccola ({size}) — distanza stop troppo ampia",
        }

    side = "BUY" if (direction or "").lower() == "bullish" else "SELL"

    logger.info(
        "IBKR auto-execute: %s %s x%s @ %.4f (stop=%.4f tp=%.4f)",
        side,
        symbol,
        size,
        entry_price,
        stop_price,
        take_profit_price,
    )

    try:
        result = await ibkr.place_bracket_order(
            account_id=account_id,
            conid=conid,
            side=side,
            quantity=size,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )
    except Exception as e:
        logger.exception("IBKR place_bracket_order failed: %s", e)
        return {"status": "error", "reason": str(e)}

    logger.info("IBKR order result: %s", result)
    return {
        "status": "executed",
        "symbol": symbol,
        "side": side,
        "size": size,
        "entry": entry_price,
        "stop": stop_price,
        "tp": take_profit_price,
        "ibkr_response": result,
    }


async def maybe_ibkr_auto_execute_after_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    """
    Dopo refresh pipeline: se Yahoo + simbolo noto, valuta opportunità ``execute`` e invia ordine.
    """
    if not settings.ibkr_enabled or not settings.ibkr_auto_execute:
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
        logger.exception("IBKR hook: list_opportunities failed")
        return

    for opp in rows:
        if opp.operational_decision != "execute":
            continue
        plan = opp.trade_plan
        if plan is None:
            continue
        entry = _float_price(plan.entry_price)
        stop = _float_price(plan.stop_loss)
        tp = _float_price(plan.take_profit_1)
        if entry is None or stop is None or tp is None:
            continue
        direction = opp.latest_pattern_direction or "bullish"
        strength = float(opp.latest_pattern_strength or 0.0)
        result = await execute_signal(
            symbol=opp.symbol,
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=tp,
            pattern_name=opp.latest_pattern_name or "",
            strength=strength,
        )
        logger.info("IBKR auto-execute hook result: %s", result)
        break
