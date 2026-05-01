from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.services.auto_execute_service import execute_signal
from app.services.tws_service import get_tws_service

router = APIRouter(prefix="/ibkr", tags=["ibkr"])


@router.get("/status")
async def ibkr_status() -> dict:
    """Configurazione IBKR (capital, risk, slots) e flag operativi."""
    return {
        "enabled": settings.ibkr_enabled,
        "paper_trading": settings.ibkr_paper_trading,
        "auto_execute": settings.ibkr_auto_execute,
        "max_capital": settings.ibkr_max_capital,
        "risk_per_trade_pct": settings.ibkr_max_risk_per_trade_pct,
        "max_simultaneous_positions": settings.ibkr_max_simultaneous_positions,
        "slots_1h": settings.ibkr_slots_1h,
        "slots_5m": settings.ibkr_slots_5m,
    }


@router.get("/tws/status")
async def tws_status() -> dict:
    """Stato connessione TWS (ib_insync socket API). Forza la connessione se non ancora avviata."""
    enabled = getattr(settings, "tws_enabled", False)
    if not enabled:
        return {
            "enabled": False,
            "authenticated": False,
            "message": "TWS_ENABLED=false nel .env",
        }

    tws = get_tws_service()
    if tws is None:
        return {
            "enabled": True,
            "authenticated": False,
            "message": "TWSService non inizializzato (ib_insync non installato o errore init)",
        }

    # _ensure_started() è bloccante (attende fino a 12s) — lo eseguiamo in executor
    import asyncio
    connected = await asyncio.get_running_loop().run_in_executor(None, tws._ensure_started)

    # Con TWS, connesso = autenticato (il login è gestito direttamente da TWS)
    accounts: list[str] = []
    if connected and tws._ib is not None:
        try:
            accounts = list(tws._ib.managedAccounts())
        except Exception:
            pass

    return {
        "enabled": True,
        "authenticated": connected,   # connesso a TWS ≡ autenticato
        "connected": connected,
        "accounts": accounts,
        "host": getattr(settings, "tws_host", "?"),
        "port": getattr(settings, "tws_port", "?"),
        "client_id": getattr(settings, "tws_client_id", "?"),
        "paper_trading": settings.ibkr_paper_trading,
        "auto_execute": settings.ibkr_auto_execute,
        "message": (
            f"TWS connesso e autenticato — account: {', '.join(accounts)}"
            if connected else
            "TWS non connesso (controlla che sia aperto con API socket abilitata su porta 7497)"
        ),
    }


@router.get("/tws/quote/{symbol}")
async def tws_quote(symbol: str) -> dict:
    """Quote live bid/ask/last per un simbolo via TWS (ib_insync)."""
    enabled = getattr(settings, "tws_enabled", False)
    if not enabled:
        return {"error": "TWS_ENABLED=false nel .env"}

    tws = get_tws_service()
    if tws is None:
        return {"error": "TWSService non disponibile"}

    sym = symbol.strip().upper()
    quote = await tws.get_live_quote(sym)
    if quote is None:
        return {
            "symbol": sym,
            "error": "Nessuna quota ricevuta (abbonamento market data API richiesto su IBKR)",
        }
    return {"symbol": sym, **quote.to_dict()}


@router.get("/tws/portfolio")
async def tws_portfolio() -> dict:
    """Posizioni aperte dal portfolio TWS."""
    tws = get_tws_service()
    if tws is None:
        return {"error": "TWSService non disponibile"}
    positions = await tws.get_portfolio()
    if positions is None:
        return {"error": "TWS non connesso"}
    return {"positions": positions, "count": len(positions)}


@router.post("/tws/test-order")
async def tws_test_order(
    symbol: str = Query(..., description="Ticker (es. IWDA, SXR8, AAPL)"),
    action: str = Query("BUY", description="BUY o SELL"),
    quantity: float = Query(1, description="Numero di azioni"),
    order_type: str = Query("MKT", description="MKT, LMT, STP"),
    limit_price: float | None = Query(None, description="Prezzo limite (solo LMT)"),
    exchange: str = Query("SMART", description="Exchange (SMART, AEB, IBIS2, ...)"),
    currency: str = Query("USD", description="Valuta (USD, EUR, ...)"),
    what_if: bool = Query(True, description="True = solo simulazione, NON invia al mercato"),
) -> dict:
    """
    Test ordine via TWS. Per default what_if=True: simula senza inviare.
    Imposta what_if=false solo se vuoi eseguire realmente (paper o live).
    """
    tws = get_tws_service()
    if tws is None:
        return {"error": "TWSService non disponibile"}

    sym = symbol.strip().upper()
    act = action.strip().upper()
    if act not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action deve essere BUY o SELL")

    result = await tws.place_order(
        symbol=sym,
        action=act,
        quantity=quantity,
        order_type=order_type.upper(),
        limit_price=limit_price,
        what_if=what_if,
        exchange=exchange,
        currency=currency,
    )
    return result


@router.post("/tws/test-bracket")
async def tws_test_bracket(
    symbol: str = Query(..., description="Ticker (es. IWDA)"),
    action: str = Query("BUY", description="BUY o SELL"),
    quantity: float = Query(1, description="Numero azioni"),
    entry_price: float = Query(..., description="Prezzo entry (LMT)"),
    stop_price: float = Query(..., description="Prezzo stop loss (STP)"),
    take_profit_price: float = Query(..., description="Prezzo take profit (LMT)"),
    exchange: str = Query("SMART", description="Exchange"),
    currency: str = Query("USD", description="Valuta"),
) -> dict:
    """
    Test bracket order reale via TWS: entry LMT + TP LMT + SL STP (GTC).
    Usa prezzi realistici — questi ordini vengono REALMENTE inviati al mercato.
    """
    tws = get_tws_service()
    if tws is None:
        return {"error": "TWSService non disponibile"}

    act = action.strip().upper()
    if act not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action deve essere BUY o SELL")

    result = await tws.place_bracket_order(
        symbol=symbol.strip().upper(),
        action=act,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        exchange=exchange,
        currency=currency,
    )
    return result


@router.post("/tws/cancel-all-orders")
async def tws_cancel_all_orders() -> dict:
    """Cancella tutti gli ordini aperti visibili al backend (clientId=10)."""
    tws = get_tws_service()
    if tws is None:
        return {"error": "TWSService non disponibile"}

    import asyncio  # noqa: PLC0415

    def _sync_cancel() -> dict:
        if tws._loop is None or not tws._connected:
            return {"error": "TWS non connesso"}
        future = asyncio.run_coroutine_threadsafe(_async_cancel(), tws._loop)
        return future.result(timeout=15)

    async def _async_cancel() -> dict:
        trades = tws._ib.trades()
        open_trades = [
            t for t in trades
            if t.orderStatus.status not in
            ("Filled", "Cancelled", "Inactive", "ApiCancelled")
        ]
        cancelled = []
        for t in open_trades:
            tws._ib.cancelOrder(t.order)
            await asyncio.sleep(0.5)
            cancelled.append({
                "order_id": t.order.orderId,
                "symbol": t.contract.symbol,
                "action": t.order.action,
                "status": t.orderStatus.status,
            })
        await asyncio.sleep(1)
        return {"cancelled": cancelled, "count": len(cancelled)}

    return await asyncio.get_running_loop().run_in_executor(None, _sync_cancel)


@router.post("/test-order")
async def ibkr_test_order(
    symbol: str = Query(..., description="Ticker US (es. NVDA)"),
    direction: str = Query(..., description="bullish o bearish"),
    price: float | None = Query(None, description="Prezzo override (opzionale). Se omesso tenta il quote live da TWS."),
) -> dict:
    """
    Test execute_signal() via TWS.
    Rispetta tutti i guard rails (auto_execute, slot, capital cap).
    Verifica nei log: 'TWS auto-execute: capitale=min(NetLiq=..., MaxCap=...)=...'

    Se TWS non ha market data (paper/no subscription), passa price= manualmente:
      curl -X POST ".../test-order?symbol=TSLA&direction=bullish&price=250.00"
    """
    if not getattr(settings, "tws_enabled", False):
        return {"status": "skipped", "reason": "TWS_ENABLED=false"}

    sym = (symbol or "").strip().upper()
    d = (direction or "").strip().lower()
    if d not in ("bullish", "bearish"):
        raise HTTPException(status_code=400, detail="direction deve essere bullish o bearish")

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        return {"status": "error", "reason": "TWS non connesso"}

    last_price: float | None = price
    if last_price is None:
        quote = await tws.get_live_quote(sym)
        if quote is not None:
            last_price = quote.last or quote.ask or quote.bid
    if not last_price:
        return {
            "status": "error",
            "reason": (
                f"Prezzo non disponibile per {sym} — mercato chiuso o nessun abbonamento market data. "
                "Usa il parametro price= per forzare un prezzo di test."
            ),
        }

    if d == "bearish":
        entry = round(last_price * 0.999, 2)
        stop  = round(last_price * 1.015, 2)
        tp    = round(last_price * 0.985, 2)
    else:
        entry = round(last_price * 1.001, 2)
        stop  = round(last_price * 0.985, 2)
        tp    = round(last_price * 1.015, 2)

    result = await execute_signal(
        symbol=sym,
        direction=d,
        entry_price=entry,
        stop_price=stop,
        take_profit_price=tp,
        pattern_name="test",
        strength=0.75,
    )
    if isinstance(result, dict):
        result["market_price"] = last_price
        result["entry"] = entry
        result["stop"] = stop
        result["tp"] = tp
    return result
