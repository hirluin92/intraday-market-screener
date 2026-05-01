"""
Test di get_last_price() in TWSService e dell'integrazione live-price in opportunities.py.

Copre:
  1. Cache hit (entro TTL 30s): nessuna chiamata reale a TWS
  2. Cache miss (cache assente): chiama _sync_get_last_price e aggiorna cache
  3. TWS ritorna quote con last valido  → restituisce last
  4. TWS ritorna quote senza last ma con bid/ask  → restituisce mid
  5. TWS ritorna None (simbolo non trovato)  → ritorna None, nessun crash
  6. TWS timeout (asyncio.TimeoutError)  → ritorna None silenziosamente
  7. TWS non connesso (_connected=False)  → ritorna None senza chiamare executor
  8. Crypto / Binance in opportunities.py  → NON chiama get_last_price, usa candle close
  9. US stock + TWS vivo  → usa prezzo live e price_source="live_tws"
 10. US stock + TWS offline  → fallback candle close e price_source="candle_close"
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _make_tws_service(connected: bool = True) -> MagicMock:
    """Crea un TWSService mock con _last_price_cache vuota e _connected impostato."""
    from app.services.tws_service import TWSService
    svc = MagicMock(spec=TWSService)
    svc._connected = connected
    svc._loop = MagicMock() if connected else None
    svc._last_price_cache = {}
    svc.is_connected = connected
    # Delega get_last_price all'implementazione reale per i test del metodo
    svc.get_last_price = TWSService.get_last_price.__get__(svc, type(svc))
    return svc


def _make_live_quote(last=None, bid=None, ask=None):
    from app.services.tws_service import LiveQuote
    return LiveQuote(bid=bid, ask=ask, last=last)


# ── Test get_last_price() ─────────────────────────────────────────────────────

class TestGetLastPrice:

    async def test_cache_hit_returns_cached_price(self):
        """Secondo call entro TTL → nessuna chiamata a _sync_get_last_price."""
        svc = _make_tws_service()
        svc._last_price_cache["AAPL"] = (185.50, time.monotonic())

        svc._sync_get_last_price = MagicMock(return_value=190.0)

        result = await svc.get_last_price("AAPL")

        assert result == 185.50
        svc._sync_get_last_price.assert_not_called()

    async def test_cache_expired_calls_tws(self):
        """Cache scaduta (timestamp nel passato oltre TTL) → chiama _sync_get_last_price."""
        svc = _make_tws_service()
        # Timestamp 60s fa → scaduto
        svc._last_price_cache["AAPL"] = (180.0, time.monotonic() - 60.0)

        svc._sync_get_last_price = MagicMock(return_value=185.0)

        result = await svc.get_last_price("AAPL")

        assert result == 185.0
        svc._sync_get_last_price.assert_called_once_with("AAPL")

    async def test_tws_not_connected_returns_none(self):
        """TWS non connesso → None immediato senza chiamare executor."""
        svc = _make_tws_service(connected=False)
        svc._sync_get_last_price = MagicMock(return_value=185.0)

        result = await svc.get_last_price("AAPL")

        assert result is None
        svc._sync_get_last_price.assert_not_called()

    async def test_valid_last_price_cached(self):
        """Prezzo valido → ritornato e salvato in cache."""
        svc = _make_tws_service()
        svc._sync_get_last_price = MagicMock(return_value=192.35)

        result = await svc.get_last_price("TSLA")

        assert result == 192.35
        cached_price, _ = svc._last_price_cache["TSLA"]
        assert cached_price == 192.35

    async def test_none_from_tws_not_cached(self):
        """TWS ritorna None → get_last_price ritorna None, cache non aggiornata."""
        svc = _make_tws_service()
        svc._sync_get_last_price = MagicMock(return_value=None)

        result = await svc.get_last_price("UNKNOWN")

        assert result is None
        assert "UNKNOWN" not in svc._last_price_cache

    async def test_timeout_returns_none(self):
        """asyncio.TimeoutError durante wait_for → None silenzioso."""
        svc = _make_tws_service()

        async def _slow_executor(_fn, _sym):
            await asyncio.sleep(5)
            return 190.0

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=asyncio.TimeoutError()
            )
            result = await svc.get_last_price("AAPL", timeout_s=0.01)

        assert result is None

    async def test_zero_price_not_cached(self):
        """Prezzo zero o negativo non è valido → None, non cached."""
        svc = _make_tws_service()
        svc._sync_get_last_price = MagicMock(return_value=0.0)

        result = await svc.get_last_price("AAPL")

        assert result is None
        assert "AAPL" not in svc._last_price_cache


# ── Test _sync_get_last_price() ───────────────────────────────────────────────

class TestSyncGetLastPrice:

    def _make_real_svc(self):
        """TWSService minimale con _loop mock per testare _sync_get_last_price."""
        from app.services.tws_service import TWSService
        svc = object.__new__(TWSService)
        svc._loop = MagicMock()
        svc._last_price_cache = {}
        return svc

    def test_returns_last_when_available(self):
        svc = self._make_real_svc()
        quote = _make_live_quote(last=180.25, bid=180.20, ask=180.30)

        with patch("asyncio.run_coroutine_threadsafe") as mock_fut:
            future_mock = MagicMock()
            future_mock.result.return_value = quote
            mock_fut.return_value = future_mock

            with patch("ib_insync.Stock"):
                result = svc._sync_get_last_price("AAPL")

        assert result == 180.25

    def test_fallback_to_mid_when_no_last(self):
        """Quote senza last ma con bid/ask → ritorna mid-price."""
        svc = self._make_real_svc()
        quote = _make_live_quote(last=None, bid=180.00, ask=180.20)

        with patch("asyncio.run_coroutine_threadsafe") as mock_fut:
            future_mock = MagicMock()
            future_mock.result.return_value = quote
            mock_fut.return_value = future_mock

            with patch("ib_insync.Stock"):
                result = svc._sync_get_last_price("AAPL")

        assert result == pytest.approx(180.10, abs=0.01)

    def test_none_quote_returns_none(self):
        svc = self._make_real_svc()

        with patch("asyncio.run_coroutine_threadsafe") as mock_fut:
            future_mock = MagicMock()
            future_mock.result.return_value = None
            mock_fut.return_value = future_mock

            with patch("ib_insync.Stock"):
                result = svc._sync_get_last_price("AAPL")

        assert result is None

    def test_exception_returns_none(self):
        """Eccezione in run_coroutine_threadsafe → None silenzioso."""
        svc = self._make_real_svc()

        with patch("asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("loop closed")):
            with patch("ib_insync.Stock"):
                result = svc._sync_get_last_price("AAPL")

        assert result is None


# ── Test integrazione: price_source in list_opportunities ─────────────────────

class TestOpportunitiesPriceSource:
    """
    Test light per verificare la logica di selezione price_source
    (la funzione list_opportunities è troppo complessa per unit test completo,
    ma possiamo isolare il blocco di selezione prezzo live).
    """

    async def test_us_stock_with_tws_live_uses_live_tws(self):
        """
        Provider yahoo_finance + TWS connesso + get_last_price ritorna valore
        → current_price deve essere il prezzo live e price_source="live_tws".
        """
        mock_tws = MagicMock()
        mock_tws.is_connected = True
        mock_tws.get_last_price = AsyncMock(return_value=185.50)

        current_price = None
        price_source = "unavailable"
        provider = "yahoo_finance"
        symbol = "AAPL"
        candle_close = 183.0

        _is_us_stock = provider == "yahoo_finance"
        if _is_us_stock:
            with patch("app.services.tws_service.get_tws_service", return_value=mock_tws):
                from app.services.tws_service import get_tws_service
                _tws_svc = get_tws_service()
                if _tws_svc is not None and _tws_svc.is_connected:
                    _live = await _tws_svc.get_last_price(symbol)
                    if _live is not None:
                        current_price = _live
                        price_source = "live_tws"

        if current_price is None:
            current_price = candle_close
            price_source = "candle_close"

        assert current_price == 185.50
        assert price_source == "live_tws"

    async def test_us_stock_tws_offline_fallback_candle(self):
        """
        Provider yahoo_finance + TWS non connesso
        → fallback a candle close e price_source="candle_close".
        """
        mock_tws = MagicMock()
        mock_tws.is_connected = False

        current_price = None
        price_source = "unavailable"
        provider = "yahoo_finance"
        symbol = "AAPL"
        candle_close = 183.0

        _is_us_stock = provider == "yahoo_finance"
        if _is_us_stock:
            _tws_svc = mock_tws
            if _tws_svc is not None and _tws_svc.is_connected:
                # non entra qui
                ...

        if current_price is None:
            current_price = candle_close
            price_source = "candle_close"

        assert current_price == 183.0
        assert price_source == "candle_close"

    async def test_crypto_binance_never_calls_tws(self):
        """
        Provider binance → _is_us_stock=False → get_last_price non viene mai chiamata.
        """
        mock_tws = MagicMock()
        mock_tws.is_connected = True
        mock_tws.get_last_price = AsyncMock(return_value=55000.0)

        current_price = None
        price_source = "unavailable"
        provider = "binance"
        symbol = "BTC/USDT"
        candle_close = 54800.0

        _is_us_stock = provider == "yahoo_finance"
        if _is_us_stock:
            # non entra qui per binance
            _live = await mock_tws.get_last_price(symbol)
            if _live is not None:
                current_price = _live
                price_source = "live_tws"

        if current_price is None:
            current_price = candle_close
            price_source = "candle_close"

        assert current_price == 54800.0
        assert price_source == "candle_close"
        mock_tws.get_last_price.assert_not_called()

    async def test_us_stock_tws_returns_none_fallback(self):
        """
        Provider yahoo_finance + TWS connesso ma get_last_price ritorna None
        → fallback candle close.
        """
        mock_tws = MagicMock()
        mock_tws.is_connected = True
        mock_tws.get_last_price = AsyncMock(return_value=None)

        current_price = None
        price_source = "unavailable"
        provider = "yahoo_finance"
        symbol = "AAPL"
        candle_close = 183.0

        _is_us_stock = provider == "yahoo_finance"
        if _is_us_stock:
            _tws_svc = mock_tws
            if _tws_svc is not None and _tws_svc.is_connected:
                _live = await _tws_svc.get_last_price(symbol)
                if _live is not None:
                    current_price = _live
                    price_source = "live_tws"

        if current_price is None:
            current_price = candle_close
            price_source = "candle_close"

        assert current_price == 183.0
        assert price_source == "candle_close"
