"""
IBKR Client Portal API (REST locale via gateway).

Documentazione: https://www.interactivebrokers.com/api/doc.html
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

IBKR_VERIFY_SSL = False


def _parse_ibkr_numeric(val: Any) -> float | None:
    """Converte valori snapshot IBKR (stringhe con virgole, ecc.) in float."""
    if val is None or val == "":
        return None
    try:
        s = str(val).replace(",", "").strip()
        if not s:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


class IBKRService:
    """Client async per IBKR Client Portal API."""

    def __init__(self, base_url: str, host_header: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] | None = None
        h = (host_header or "").strip()
        if h:
            headers = {"Host": h}
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=IBKR_VERIFY_SSL,
            timeout=30.0,
            headers=headers,
        )

    async def auth_status_raw(self) -> dict[str, Any]:
        """Risposta grezza GET /iserver/auth/status (per debug)."""
        try:
            r = await self._client.get("/iserver/auth/status")
            body: Any
            try:
                body = r.json()
            except Exception:
                body = r.text
            return {
                "http_status": r.status_code,
                "body": body,
            }
        except Exception as e:
            return {"http_status": None, "error": str(e), "body": None}

    async def is_authenticated(self) -> bool:
        try:
            r = await self._client.get("/iserver/auth/status")
            r.raise_for_status()
            data = r.json()
            return bool(data.get("authenticated", False))
        except Exception as e:
            logger.warning("IBKR auth check failed: %s", e)
            return False

    async def get_accounts(self) -> list[dict[str, Any]]:
        r = await self._client.get("/portfolio/accounts")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []

    async def search_contract(
        self,
        symbol: str,
        *,
        name_search: bool = False,
    ) -> list[dict[str, Any]]:
        """Ricerca STK via /iserver/secdef/search.

        Per ticker (es. NVDA) usare name_search=False (default): name=true tende a
        risultati vuoti o diversi rispetto alla ricerca per simbolo.
        """
        r = await self._client.get(
            "/iserver/secdef/search",
            params={
                "symbol": symbol.strip(),
                "name": "true" if name_search else "false",
                "secType": "STK",
            },
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def secdef_search_stk_raw(self, symbol: str) -> dict[str, Any]:
        """Risposta grezza secdef/search STK (stessi parametri di get_conid)."""
        try:
            r = await self._client.get(
                "/iserver/secdef/search",
                params={
                    "symbol": symbol.strip(),
                    "name": "false",
                    "secType": "STK",
                },
            )
            body: Any
            try:
                body = r.json()
            except Exception:
                body = r.text
            return {
                "http_status": r.status_code,
                "body": body,
                "ok": r.status_code < 400,
            }
        except Exception as e:
            logger.warning("IBKR secdef_search_stk_raw %s: %s", symbol, e)
            return {"http_status": None, "body": None, "ok": False, "error": str(e)}

    async def get_conid(self, symbol: str, exchange: str = "SMART") -> int | None:
        """Contract ID per uno stock US (STK); None se non trovato."""
        sym_u = symbol.strip().upper()
        if not sym_u:
            return None
        try:
            results = await self.search_contract(sym_u, name_search=False)
        except Exception as e:
            logger.error("IBKR get_conid search failed per %s: %s", sym_u, e)
            return None

        logger.info("IBKR secdef/search %s: %s risultati", sym_u, len(results))

        if not results:
            return None

        ex_u = exchange.upper()
        preferred_exchanges = {ex_u, "SMART", "NASDAQ", "NYSE", "AMEX"}

        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("symbol", "")).upper() == sym_u and item.get("conid") is not None:
                try:
                    return int(item["conid"])
                except (TypeError, ValueError):
                    continue

        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("conid") is not None:
                try:
                    return int(item["conid"])
                except (TypeError, ValueError):
                    continue
            for sec in item.get("sections", []) or []:
                if not isinstance(sec, dict):
                    continue
                st = (sec.get("secType") or "").upper()
                ex = (sec.get("exchange") or "").upper()
                if st == "STK" and sec.get("conid") is not None:
                    if ex and ex in preferred_exchanges:
                        try:
                            return int(sec["conid"])
                        except (TypeError, ValueError):
                            continue
            for sec in item.get("sections", []) or []:
                if not isinstance(sec, dict):
                    continue
                if (sec.get("secType") or "").upper() == "STK" and sec.get("conid") is not None:
                    try:
                        return int(sec["conid"])
                    except (TypeError, ValueError):
                        continue

        first = results[0]
        if isinstance(first, dict) and first.get("conid") is not None:
            try:
                return int(first["conid"])
            except (TypeError, ValueError):
                pass
        return None

    async def get_snapshot_last_price(self, conid: int) -> float | None:
        """Ultimo prezzo da marketdata snapshot: last (31), altrimenti bid (84) / ask (86)."""
        try:
            r = await self._client.get(
                "/iserver/marketdata/snapshot",
                params={
                    "conids": str(conid),
                    "fields": "31,84,86",
                },
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("IBKR marketdata/snapshot conid=%s: %s", conid, e)
            return None

        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = [data]
        else:
            return None
        if not rows:
            return None
        item = rows[0]
        if not isinstance(item, dict):
            return None
        for key in ("31", "84", "86"):
            p = _parse_ibkr_numeric(item.get(key))
            if p is not None and p > 0:
                return p
        return None

    async def _confirm_all(
        self,
        initial_response: Any,
        max_confirmations: int = 10,
    ) -> dict[str, Any]:
        """
        Conferma automaticamente tutti i messaggi IBKR in sequenza (id + message).
        Normalizza lista/dict così ogni round trova il prompt anche se la risposta è un solo dict.
        """
        result: Any = initial_response

        for i in range(max_confirmations):
            items = result if isinstance(result, list) else [result]

            reply_id = None
            for item in items:
                if isinstance(item, dict) and "id" in item and "message" in item:
                    reply_id = item["id"]
                    logger.info(
                        "IBKR conferma %d richiesta (id=%s): %s",
                        i + 1,
                        reply_id,
                        item.get("message", ""),
                    )
                    break

            if not reply_id:
                break

            r = await self._client.post(
                f"/iserver/reply/{str(reply_id).strip()}",
                json={"confirmed": True},
            )
            r.raise_for_status()
            result = r.json()
            logger.info("IBKR risposta conferma %d: %s", i + 1, result)

        if isinstance(result, list):
            orders: list[dict[str, Any]] = []
            for item in result:
                if isinstance(item, dict) and (
                    "order_id" in item or "orderId" in item
                ):
                    orders.append(item)
            if orders:
                return {"orders": orders} if len(orders) > 1 else orders[0]
            if len(result) == 1:
                return result[0] if isinstance(result[0], dict) else {"raw": result}
            return {"raw": result}

        if isinstance(result, dict):
            return result
        return {"raw": result}

    @staticmethod
    def _extract_order_id_from_place_result(entry_result: dict[str, Any]) -> str | None:
        """Estrae id ordine dalla risposta place_order / _confirm_all."""
        for k in ("order_id", "orderId", "id"):
            v = entry_result.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        subs = entry_result.get("orders")
        if isinstance(subs, list) and subs and isinstance(subs[0], dict):
            return IBKRService._extract_order_id_from_place_result(subs[0])
        return None

    async def place_order(
        self,
        account_id: str,
        conid: int,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None = None,
        aux_price: float | None = None,
        tif: str = "DAY",
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        sec = f"{conid}:STK"
        ot = (order_type or "").upper()
        order: dict[str, Any] = {
            "conid": conid,
            "secType": sec,
            "side": side,
            "quantity": quantity,
            "orderType": order_type,
            "tif": tif,
            "outsideRTH": False,
        }
        if ot == "STP":
            stop_px = aux_price if aux_price is not None else price
            if stop_px is not None:
                order["price"] = stop_px
        else:
            if price is not None:
                order["price"] = price

        if parent_id is not None and str(parent_id).strip() != "":
            pid = str(parent_id).strip()
            try:
                order["parentId"] = int(pid)
            except ValueError:
                order["parentId"] = pid

        r = await self._client.post(
            f"/iserver/account/{account_id}/orders",
            json={"orders": [order]},
        )
        r.raise_for_status()
        result = r.json()
        logger.info("IBKR place_order raw: %s", result)
        return await self._confirm_all(result)

    async def place_bracket_order(
        self,
        account_id: str,
        conid: int,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        tif: str = "DAY",
    ) -> dict[str, Any]:
        """
        Bracket in un solo POST: parent/child collegati via cOID stringa e parentId
        (stesso valore del cOID del parent), non order_id numerico.
        """
        is_long = side == "BUY"
        stop_side = "SELL" if is_long else "BUY"
        tp_side = "SELL" if is_long else "BUY"

        ts = int(time.time())
        parent_coid = f"BRACKET_{conid}_{ts}"

        orders: list[dict[str, Any]] = [
            {
                "cOID": parent_coid,
                "conid": conid,
                "orderType": "LMT",
                "side": side,
                "price": entry_price,
                "tif": tif,
                "quantity": quantity,
            },
            {
                "parentId": parent_coid,
                "cOID": f"{parent_coid}-SL",
                "conid": conid,
                "orderType": "STP",
                "side": stop_side,
                "price": stop_price,
                "tif": "GTC",
                "quantity": quantity,
            },
            {
                "parentId": parent_coid,
                "cOID": f"{parent_coid}-TP",
                "conid": conid,
                "orderType": "LMT",
                "side": tp_side,
                "price": take_profit_price,
                "tif": "GTC",
                "quantity": quantity,
            },
        ]

        r = await self._client.post(
            f"/iserver/account/{account_id}/orders",
            json={"orders": orders},
        )
        r.raise_for_status()
        result = r.json()
        logger.info("IBKR bracket raw: %s", result)
        return await self._confirm_all(result)

    async def get_open_orders(self, account_id: str) -> list[dict[str, Any]]:
        _ = account_id
        r = await self._client.get("/iserver/account/orders")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return list(data.get("orders", []) or [])
        if isinstance(data, list):
            return data
        return []

    async def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        r = await self._client.delete(
            f"/iserver/account/{account_id}/order/{order_id}",
        )
        r.raise_for_status()
        return r.json()

    async def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        r = await self._client.get(f"/portfolio/{account_id}/positions/0")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []

    async def aclose(self) -> None:
        await self._client.aclose()


_ibkr_service: IBKRService | None = None


def get_ibkr_service() -> IBKRService:
    global _ibkr_service
    if _ibkr_service is None:
        from app.core.config import settings

        url = (settings.ibkr_gateway_url or "").strip() or "https://localhost:5000/v1/api"
        host_h = (settings.ibkr_gateway_host_header or "").strip() or None
        _ibkr_service = IBKRService(base_url=url, host_header=host_h)
    return _ibkr_service
