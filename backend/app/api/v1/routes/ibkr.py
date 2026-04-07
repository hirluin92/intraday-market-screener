from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.services.auto_execute_service import execute_signal
from app.services.ibkr_service import get_ibkr_service

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
