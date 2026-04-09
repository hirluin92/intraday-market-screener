from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.services.auto_execute_service import execute_signal
from app.services.ibkr_service import get_ibkr_service
from app.services.tws_service import get_tws_service

router = APIRouter(prefix="/ibkr", tags=["ibkr"])


@router.get("/status")
async def ibkr_status() -> dict:
    """Stato connessione IBKR Gateway e flag da config."""
    if not settings.ibkr_enabled:
        return {"enabled": False, "message": "IBKR disabled in config"}

    ibkr = get_ibkr_service()
    try:
        authenticated = await ibkr.is_authenticated()
    except Exception:
        authenticated = False

    gw = (settings.ibkr_gateway_url or "").lower()
    hint: str | None = None
    if (
        not authenticated
        and "host.docker.internal" in gw
    ):
        hint = (
            "Il gateway IBKR associa il login del browser alla sessione API tipicamente solo per "
            "connessioni da localhost. Da un container Docker spesso resta authenticated=false. "
            "Prova: (1) IBKR_GATEWAY_HOST_HEADER=localhost:5000 nel .env e riavvia il backend; "
            "(2) se non basta, avvia il backend sul PC (venv/uvicorn) senza Docker con "
            "IBKR_GATEWAY_URL=https://127.0.0.1:5000/v1/api."
        )

    out: dict = {
        "enabled": True,
        "paper_trading": settings.ibkr_paper_trading,
        "auto_execute": settings.ibkr_auto_execute,
        "authenticated": authenticated,
        "account_id": settings.ibkr_account_id,
        "max_capital": settings.ibkr_max_capital,
        "risk_per_trade_pct": settings.ibkr_max_risk_per_trade_pct,
        "max_simultaneous_positions": settings.ibkr_max_simultaneous_positions,
        "gateway_url": settings.ibkr_gateway_url,
    }
    if hint:
        out["hint"] = hint
    return out


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
    connected = await asyncio.get_event_loop().run_in_executor(None, tws._ensure_started)

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

    return await asyncio.get_event_loop().run_in_executor(None, _sync_cancel)


@router.get("/conid/{symbol}")
async def ibkr_conid_lookup(symbol: str) -> dict:
    """Debug: contract ID e risposta grezza secdef/search per un ticker STK."""
    if not settings.ibkr_enabled:
        return {"error": "IBKR disabled"}
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol mancante")
    ibkr = get_ibkr_service()
    raw = await ibkr.secdef_search_stk_raw(sym)
    conid = await ibkr.get_conid(sym)
    return {
        "symbol": sym,
        "conid": conid,
        "raw_response": raw.get("body"),
        "http_status": raw.get("http_status"),
        "search_ok": raw.get("ok"),
        "error": raw.get("error"),
    }


@router.get("/debug/auth")
async def ibkr_debug_auth() -> dict:
    """Risposta grezza da GET /iserver/auth/status (solo con IBKR_DEBUG=true)."""
    if not settings.ibkr_debug:
        raise HTTPException(status_code=404, detail="IBKR debug disabled")
    if not settings.ibkr_enabled:
        return {"error": "IBKR disabled"}
    ibkr = get_ibkr_service()
    return await ibkr.auth_status_raw()


@router.get("/positions")
async def ibkr_positions() -> dict:
    """Posizioni aperte (richiede gateway autenticato)."""
    if not settings.ibkr_enabled:
        return {"positions": [], "error": "IBKR disabled"}
    aid = (settings.ibkr_account_id or "").strip()
    if not aid:
        return {"positions": [], "error": "IBKR_ACCOUNT_ID mancante"}
    ibkr = get_ibkr_service()
    positions = await ibkr.get_positions(aid)
    return {"positions": positions}


@router.get("/orders")
async def ibkr_orders() -> dict:
    """Ordini aperti."""
    if not settings.ibkr_enabled:
        return {"orders": [], "error": "IBKR disabled"}
    ibkr = get_ibkr_service()
    orders = await ibkr.get_open_orders(settings.ibkr_account_id)
    return {"orders": orders}


@router.post("/test-order")
async def ibkr_test_order(
    symbol: str = Query(..., description="Ticker US (es. NVDA)"),
    direction: str = Query(..., description="bullish o bearish"),
) -> dict:
    """Test sizing + invio bracket con prezzi da snapshot mercato (rispetta auto_execute e paper)."""
    if not settings.ibkr_enabled:
        return {"status": "skipped", "reason": "IBKR disabled"}

    sym = (symbol or "").strip().upper()
    d = (direction or "").strip().lower()
    if d not in ("bullish", "bearish"):
        raise HTTPException(
            status_code=400,
            detail="direction deve essere bullish o bearish",
        )

    ibkr = get_ibkr_service()
    conid = await ibkr.get_conid(sym)
    if not conid:
        return {"status": "error", "reason": f"conid non trovato per {sym}"}

    last_price = await ibkr.get_snapshot_last_price(conid)
    if not last_price:
        return {
            "status": "error",
            "reason": "Impossibile ottenere prezzo corrente (marketdata snapshot)",
        }

    # ~1.5% stop / TP rispetto al last, entry leggermente dal lato del trade
    if d == "bearish":
        entry = round(last_price * 0.999, 2)
        stop = round(last_price * 1.015, 2)
        tp = round(last_price * 0.985, 2)
    else:
        entry = round(last_price * 1.001, 2)
        stop = round(last_price * 0.985, 2)
        tp = round(last_price * 1.015, 2)

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
