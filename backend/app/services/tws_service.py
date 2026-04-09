"""
TWS Service — integrazione IBKR Trader Workstation via ib_insync.

Fornisce dati di mercato live e storici direttamente dal TWS installato
sul PC dell'utente, con qualità superiore rispetto al Client Portal REST.

Vantaggi rispetto al Client Portal:
  - Streaming real-time bid/ask (non solo snapshot)
  - Market depth Level 2 (5 livelli) senza abbonamento aggiuntivo
  - Dati storici bid/ask fino a 30 giorni (reqHistoricalData BID_ASK)
  - Latenza molto più bassa

Configurazione richiesta nel TWS (una sola volta):
  File → Global Configuration → API → Settings
    [x] Enable ActiveX and Socket Clients
    Socket port: 7497 (paper) / 7496 (live)
    [x] Allow connections from localhost only (o aggiungere 172.x.x.x per Docker)

Variabili .env:
  TWS_HOST=host.docker.internal   (Docker) o localhost (locale)
  TWS_PORT=7497                   (7497 paper, 7496 live)
  TWS_CLIENT_ID=10                (qualsiasi intero >= 1, diverso da TWS stesso)
  TWS_ENABLED=true

Il servizio è completamente opzionale e non-breaking:
  - Se TWS non è in esecuzione o API è disabilitata → tutti i metodi restituiscono None
  - Il backend continua a funzionare con Client Portal come fallback
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─── Strutture dati risultato ─────────────────────────────────────────────────

class LiveQuote:
    """Snapshot bid/ask/last/volume da TWS."""
    __slots__ = ("bid", "ask", "last", "bid_size", "ask_size", "volume", "spread_pct")

    def __init__(
        self,
        bid: float | None = None,
        ask: float | None = None,
        last: float | None = None,
        bid_size: float | None = None,
        ask_size: float | None = None,
        volume: float | None = None,
    ) -> None:
        self.bid = bid
        self.ask = ask
        self.last = last or bid or ask
        self.bid_size = bid_size
        self.ask_size = ask_size
        self.volume = volume
        if bid and ask and bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            self.spread_pct = round((ask - bid) / mid * 100.0, 4) if mid > 0 else None
        else:
            self.spread_pct = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "volume": self.volume,
            "spread_pct": self.spread_pct,
        }


class DepthLevel:
    """Un livello del book (bid o ask)."""
    __slots__ = ("price", "size", "orders")

    def __init__(self, price: float, size: float, orders: int = 1) -> None:
        self.price = price
        self.size = size
        self.orders = orders


class MarketDepth:
    """Order book Level 2: 5 livelli bid + 5 livelli ask."""

    def __init__(
        self,
        bids: list[DepthLevel],
        asks: list[DepthLevel],
    ) -> None:
        self.bids = bids   # ordinati per prezzo decrescente (migliore bid primo)
        self.asks = asks   # ordinati per prezzo crescente (migliore ask primo)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread_pct(self) -> float | None:
        if self.best_bid and self.best_ask and self.best_bid > 0:
            mid = (self.best_bid + self.best_ask) / 2.0
            return round((self.best_ask - self.best_bid) / mid * 100.0, 4)
        return None

    @property
    def bid_wall_size(self) -> float:
        """Volume totale lato buy nei 5 livelli."""
        return sum(l.size for l in self.bids)

    @property
    def ask_wall_size(self) -> float:
        """Volume totale lato sell nei 5 livelli."""
        return sum(l.size for l in self.asks)

    @property
    def imbalance(self) -> float | None:
        """
        Imbalance bid vs ask: > 1 = più pressione acquisto, < 1 = più pressione vendita.
        Valori tipici: 0.5 (forte pressione vendita) … 2.0 (forte pressione acquisto).
        """
        ask_tot = self.ask_wall_size
        if ask_tot <= 0:
            return None
        return round(self.bid_wall_size / ask_tot, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread_pct": self.spread_pct,
            "bid_wall_size": self.bid_wall_size,
            "ask_wall_size": self.ask_wall_size,
            "imbalance": self.imbalance,
            "bids": [{"price": l.price, "size": l.size} for l in self.bids],
            "asks": [{"price": l.price, "size": l.size} for l in self.asks],
        }


# ─── TWS Service (singleton thread-safe) ─────────────────────────────────────

class TWSService:
    """
    Wrapper asyncio-friendly per ib_insync.

    Usa un thread dedicato con il suo event loop per gestire la connessione
    persistente al TWS — evita conflitti con l'event loop principale di FastAPI.

    Tutti i metodi pubblici sono coroutine asyncio e non bloccano mai il server.
    """

    _instance: TWSService | None = None
    _lock = threading.Lock()

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib: Any = None          # ib_insync.IB instance
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._connected = False
        self._connect_failed = False

    # ── Connessione ──────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Entry point del thread dedicato TWS."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_async())
        self._loop.run_forever()

    async def _connect_async(self) -> None:
        try:
            import ib_insync as ibi  # noqa: PLC0415
            self._ib = ibi.IB()
            await self._ib.connectAsync(
                self._host, self._port, clientId=self._client_id,
                timeout=10,
            )
            # Richiedi dati delayed (tipo 3) se real-time non disponibile.
            # Evita il flood di Error 10089 per simboli US senza abbonamento API real-time.
            # Tipo 3 = delayed frozen: dati con 15-20 min di ritardo, sempre disponibili.
            self._ib.reqMarketDataType(3)
            self._connected = True
            logger.info(
                "TWS connesso: %s:%d clientId=%d (market data: delayed/frozen fallback attivo)",
                self._host, self._port, self._client_id,
            )
        except Exception as exc:
            self._connect_failed = True
            logger.warning("TWS non disponibile (%s:%d): %s", self._host, self._port, exc)
        finally:
            self._ready.set()

    def start(self) -> None:
        """Avvia il thread di connessione in background (non bloccante)."""
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="tws-loop")
        self._thread.start()

    def _ensure_started(self) -> bool:
        """Avvia se non ancora partito. Restituisce True se connesso."""
        if self._connect_failed:
            return False
        if not (self._thread and self._thread.is_alive()):
            self.start()
        self._ready.wait(timeout=12)
        return self._connected

    def _run_in_tws_loop(self, coro) -> Any:
        """Esegue una coroutine nel loop TWS e restituisce il risultato (bloccante)."""
        if self._loop is None or not self._connected:
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=8)
        except Exception as exc:
            logger.debug("TWS call failed: %s", exc)
            return None

    # ── API pubblica (coroutine asyncio) ──────────────────────────────────────

    async def get_live_quote(self, symbol: str) -> LiveQuote | None:
        """
        Ritorna bid/ask/last/volume correnti per un simbolo US Stock.
        Timeout 5s — restituisce None se TWS non disponibile.
        """
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_live_quote, symbol
        )

    def _sync_live_quote(self, symbol: str) -> LiveQuote | None:
        try:
            import ib_insync as ibi  # noqa: PLC0415

            contract = ibi.Stock(symbol, "SMART", "USD")
            future = asyncio.run_coroutine_threadsafe(
                self._async_live_quote(contract), self._loop
            )
            return future.result(timeout=6)
        except Exception as exc:
            logger.debug("TWS live_quote %s: %s", symbol, exc)
            return None

    async def _async_live_quote(self, contract) -> LiveQuote | None:
        import ib_insync as ibi  # noqa: PLC0415

        tickers = await self._ib.reqTickersAsync(contract)
        if not tickers:
            return None
        t = tickers[0]
        return LiveQuote(
            bid=t.bid if t.bid and t.bid > 0 else None,
            ask=t.ask if t.ask and t.ask > 0 else None,
            last=t.last if t.last and t.last > 0 else None,
            bid_size=t.bidSize if t.bidSize else None,
            ask_size=t.askSize if t.askSize else None,
            volume=t.volume if t.volume else None,
        )

    async def get_market_depth(self, symbol: str, levels: int = 5) -> MarketDepth | None:
        """
        Ritorna i primi N livelli del book (Level 2) per un simbolo.
        Richiede che TWS abbia i dati di mercato per quel simbolo.
        """
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_market_depth, symbol, levels
        )

    def _sync_market_depth(self, symbol: str, levels: int) -> MarketDepth | None:
        try:
            import ib_insync as ibi  # noqa: PLC0415

            contract = ibi.Stock(symbol, "SMART", "USD")
            future = asyncio.run_coroutine_threadsafe(
                self._async_market_depth(contract, levels), self._loop
            )
            return future.result(timeout=8)
        except Exception as exc:
            logger.debug("TWS market_depth %s: %s", symbol, exc)
            return None

    async def _async_market_depth(self, contract, levels: int) -> MarketDepth | None:
        import ib_insync as ibi  # noqa: PLC0415

        ticker = self._ib.reqMktDepth(contract, numRows=levels)
        await asyncio.sleep(1.5)   # attendi che arrivino i dati
        bids = sorted(
            [
                DepthLevel(d.price, d.size, d.marketMaker or 1)
                for d in (ticker.domBids or []) if d.price > 0
            ],
            key=lambda x: -x.price,
        )[:levels]
        asks = sorted(
            [
                DepthLevel(d.price, d.size, d.marketMaker or 1)
                for d in (ticker.domAsks or []) if d.price > 0
            ],
            key=lambda x: x.price,
        )[:levels]
        self._ib.cancelMktDepth(contract)
        if not bids and not asks:
            return None
        return MarketDepth(bids=bids, asks=asks)

    async def get_bid_ask_history(
        self,
        symbol: str,
        duration: str = "30 D",
        bar_size: str = "1 hour",
    ) -> list[dict] | None:
        """
        Ritorna barre storiche BID_ASK (open/high/low/close per bid e ask)
        per gli ultimi N giorni al bar_size indicato.

        Parametri duration: "30 D", "7 D", "1 M", ecc.
        Parametri bar_size: "1 hour", "30 mins", "15 mins", "5 mins", ecc.

        Ogni barra restituita contiene:
          {timestamp, bid_open, bid_high, bid_low, bid_close,
           ask_open, ask_high, ask_low, ask_close, avg_spread_pct}
        """
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_bid_ask_history, symbol, duration, bar_size
        )

    def _sync_bid_ask_history(
        self, symbol: str, duration: str, bar_size: str
    ) -> list[dict] | None:
        try:
            import ib_insync as ibi  # noqa: PLC0415

            contract = ibi.Stock(symbol, "SMART", "USD")
            future = asyncio.run_coroutine_threadsafe(
                self._async_bid_ask_history(contract, duration, bar_size), self._loop
            )
            return future.result(timeout=30)
        except Exception as exc:
            logger.debug("TWS bid_ask_history %s: %s", symbol, exc)
            return None

    async def _async_bid_ask_history(
        self, contract, duration: str, bar_size: str
    ) -> list[dict]:
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="BID_ASK",
            useRTH=True,
            formatDate=1,
        )
        result = []
        for b in bars:
            ts = b.date
            if hasattr(ts, "astimezone"):
                ts = ts.astimezone(timezone.utc)
            elif isinstance(ts, datetime):
                ts = ts.replace(tzinfo=timezone.utc)
            # BID_ASK bars: open=bid, high=ask, low=bid_low, close=ask_close
            bid_c = float(b.open) if b.open else None
            ask_c = float(b.high) if b.high else None
            spread_pct = None
            if bid_c and ask_c and bid_c > 0:
                mid = (bid_c + ask_c) / 2.0
                spread_pct = round((ask_c - bid_c) / mid * 100.0, 4)
            result.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "bid_close": bid_c,
                "ask_close": ask_c,
                "avg_spread_pct": spread_pct,
                "volume": float(b.volume) if b.volume else None,
            })
        return result

    async def get_historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 hour",
        use_rth: bool = True,
    ) -> list[dict] | None:
        """
        Ritorna barre OHLCV storiche + barra corrente in formazione per un simbolo US Stock.

        A differenza dell'ingestion Yahoo Finance, NON scarta l'ultima barra:
        la barra parziale corrente (ancora aperta) viene inclusa per aggiornamenti live.

        Parametri:
          duration: "1 D", "2 D", "1 W" ecc.
          bar_size: "1 hour", "30 mins", "5 mins" ecc.
          use_rth: True = solo Regular Trading Hours (09:30-16:00 ET)

        Ogni barra:
          {timestamp (datetime UTC), open, high, low, close, volume}
        """
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_historical_bars, symbol, duration, bar_size, use_rth
        )

    def _sync_historical_bars(
        self, symbol: str, duration: str, bar_size: str, use_rth: bool
    ) -> list[dict] | None:
        try:
            import ib_insync as ibi  # noqa: PLC0415

            contract = ibi.Stock(symbol, "SMART", "USD")
            future = asyncio.run_coroutine_threadsafe(
                self._async_historical_bars(contract, duration, bar_size, use_rth),
                self._loop,
            )
            return future.result(timeout=20)
        except Exception as exc:
            logger.debug("TWS historical_bars %s: %s", symbol, exc)
            return None

    async def _async_historical_bars(
        self, contract, duration: str, bar_size: str, use_rth: bool
    ) -> list[dict]:
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=use_rth,
            formatDate=1,
        )
        result = []
        for b in bars:
            ts = b.date
            if hasattr(ts, "astimezone"):
                ts = ts.astimezone(timezone.utc)
            elif isinstance(ts, datetime):
                ts = ts.replace(tzinfo=timezone.utc)
            result.append({
                "timestamp": ts,
                "open": float(b.open) if b.open else None,
                "high": float(b.high) if b.high else None,
                "low": float(b.low) if b.low else None,
                "close": float(b.close) if b.close else None,
                "volume": float(b.volume) if b.volume else 0.0,
            })
        return result

    async def get_portfolio(self) -> list[dict] | None:
        """Ritorna le posizioni aperte dal portfolio TWS."""
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_portfolio)

    def _sync_portfolio(self) -> list[dict] | None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_portfolio(), self._loop
            )
            return future.result(timeout=8)
        except Exception as exc:
            logger.debug("TWS portfolio: %s", exc)
            return None

    async def _async_portfolio(self) -> list[dict]:
        # reqPositionsAsync recupera le posizioni attive in tempo reale
        positions = await self._ib.reqPositionsAsync()
        result = []
        for pos in positions:
            c = pos.contract
            result.append({
                "symbol": c.symbol,
                "exchange": getattr(c, "primaryExchange", None) or c.exchange,
                "currency": c.currency,
                "position": pos.position,
                "avg_cost": pos.avgCost,
                "account": pos.account,
            })
        return result

    async def get_open_positions(self) -> list[dict]:
        """Posizioni attualmente aperte (position != 0)."""
        if not self._ensure_started():
            return []
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_open_positions)

    def _sync_open_positions(self) -> list[dict]:
        try:
            future = asyncio.run_coroutine_threadsafe(self._async_open_positions(), self._loop)
            return future.result(timeout=8)
        except Exception as exc:
            logger.debug("TWS open_positions: %s", exc)
            return []

    async def _async_open_positions(self) -> list[dict]:
        positions = await self._ib.reqPositionsAsync()
        return [
            {
                "symbol": p.contract.symbol,
                "exchange": getattr(p.contract, "primaryExchange", None) or p.contract.exchange,
                "currency": p.contract.currency,
                "position": p.position,
                "avg_cost": p.avgCost,
                "account": p.account,
            }
            for p in positions
            if abs(p.position) > 1e-6
        ]

    async def get_net_liquidation(self, currency: str = "USD") -> float | None:
        """Legge il valore netto del conto (NetLiquidation) da TWS.

        Restituisce il valore in `currency` (default USD) oppure None se non
        disponibile. Usa reqAccountSummaryAsync con un timeout di 8 secondi.
        """
        if not self._ensure_started():
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_net_liquidation, currency
        )

    def _sync_net_liquidation(self, currency: str) -> float | None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_net_liquidation(currency), self._loop
            )
            return future.result(timeout=8)
        except Exception as exc:
            logger.debug("TWS net_liquidation: %s", exc)
            return None

    async def _async_net_liquidation(self, currency: str) -> float | None:
        tags = "NetLiquidation"
        summaries = await self._ib.reqAccountSummaryAsync(group="All", tags=tags)
        for s in summaries:
            if s.tag == "NetLiquidation" and s.currency == currency:
                try:
                    return float(s.value)
                except (TypeError, ValueError):
                    return None
        return None

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> dict:
        """
        Bracket order completo: entry LMT + TP LMT + SL STP collegati.

        IBKR gestisce i tre ordini come gruppo: se l'entry viene eseguita,
        TP e SL diventano attivi; se uno dei due viene colpito, l'altro
        viene cancellato automaticamente (OCA).

        Restituisce lo stato dei tre ordini dopo 5 secondi.
        """
        if not self._ensure_started():
            return {"error": "TWS non connesso"}
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._sync_place_bracket,
            symbol, action, quantity,
            entry_price, stop_price, take_profit_price,
            exchange, currency,
        )

    def _sync_place_bracket(
        self,
        symbol: str,
        action: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        exchange: str,
        currency: str,
    ) -> dict:
        try:
            import asyncio as _asyncio
            future = _asyncio.run_coroutine_threadsafe(
                self._async_place_bracket(
                    symbol, action, quantity,
                    entry_price, stop_price, take_profit_price,
                    exchange, currency,
                ),
                self._loop,
            )
            return future.result(timeout=20)
        except Exception as exc:
            logger.error("TWS bracket_order %s: %s", symbol, exc)
            return {"error": str(exc)}

    async def _async_place_bracket(
        self,
        symbol: str,
        action: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        exchange: str,
        currency: str,
    ) -> dict:
        import ib_insync as ibi  # noqa: PLC0415

        contract = ibi.Stock(symbol, exchange, currency)
        accounts = self._ib.managedAccounts()
        account = accounts[0] if accounts else ""

        # Titoli US: tick minimo $0.01 → arrotondamento a 2 decimali obbligatorio.
        # Prezzi con 3+ decimali provocano Warning 110 e l'ordine rimane in PendingSubmit.
        def _tick(price: float) -> float:
            return round(round(price / 0.01) * 0.01, 2)

        # ib_insync crea i 3 ordini collegati (parent → OCA tra TP e SL)
        bracket = self._ib.bracketOrder(
            action=action.upper(),
            quantity=quantity,
            limitPrice=_tick(entry_price),
            takeProfitPrice=_tick(take_profit_price),
            stopLossPrice=_tick(stop_price),
        )
        parent_order, tp_order, sl_order = bracket

        for order in bracket:
            order.account = account
            order.tif = "GTC"

        # Strategia "parent-first":
        # 1) Invia il parent con transmit=True (va subito all'exchange come LMT aperto)
        # 2) Aspetta che TWS lo confermi (status Submitted/PreSubmitted), max 8s
        # 3) Solo dopo invia TP e SL come child — a questo punto il parent è nel book di TWS
        # Questo evita Error 135 "cannot find order" causato dalla race condition
        # in cui i child arrivano prima che TWS abbia registrato il parent.
        parent_order.transmit = True
        tp_order.transmit = True
        sl_order.transmit = True

        parent_trade = self._ib.placeOrder(contract, parent_order)
        # Attendi conferma parent (Submitted / PreSubmitted)
        for _ in range(40):
            await asyncio.sleep(0.25)
            st = parent_trade.orderStatus.status
            if st in ("Submitted", "PreSubmitted", "Filled"):
                logger.info("TWS bracket parent %s confermato: %s", parent_order.orderId, st)
                break
        else:
            logger.warning("TWS bracket parent %s non confermato in 10s, status=%s — invio child comunque", parent_order.orderId, parent_trade.orderStatus.status)

        tp_trade = self._ib.placeOrder(contract, tp_order)
        sl_trade = self._ib.placeOrder(contract, sl_order)
        trades = [parent_trade, tp_trade, sl_trade]
        await asyncio.sleep(5)

        def _trade_summary(t: Any) -> dict:
            return {
                "order_id": t.order.orderId,
                "type": t.order.orderType,
                "action": t.order.action,
                "qty": t.order.totalQuantity,
                "lmt_price": getattr(t.order, "lmtPrice", None),
                "aux_price": getattr(t.order, "auxPrice", None),
                "tif": t.order.tif,
                "status": t.orderStatus.status,
                "filled": t.orderStatus.filled,
                "avg_fill": t.orderStatus.avgFillPrice,
            }

        parent, tp, sl = trades[0], trades[1], trades[2]
        errors = [
            e.message for t in trades
            for e in t.log
            if e.errorCode and e.errorCode not in (0, 2104, 2106, 2158, 10349, 10167)
            and e.message
        ]
        return {
            "symbol": symbol,
            "action": action.upper(),
            "quantity": quantity,
            "entry_price": entry_price,
            "take_profit_price": take_profit_price,
            "stop_price": stop_price,
            "account": account,
            "entry": _trade_summary(parent),
            "take_profit": _trade_summary(tp),
            "stop_loss": _trade_summary(sl),
            "errors": errors,
        }

    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
        stop_price: float | None = None,
        what_if: bool = True,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> dict:
        """
        Invia un ordine via TWS.

        what_if=True (default): simula l'ordine senza inviarlo al mercato.
        Restituisce status, commissione stimata e dettagli.
        """
        if not self._ensure_started():
            return {"error": "TWS non connesso"}
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_place_order,
            symbol, action, quantity, order_type,
            limit_price, stop_price, what_if, exchange, currency,
        )

    def _sync_place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        stop_price: float | None,
        what_if: bool,
        exchange: str,
        currency: str,
    ) -> dict:
        try:
            import asyncio as _asyncio
            future = _asyncio.run_coroutine_threadsafe(
                self._async_place_order(
                    symbol, action, quantity, order_type,
                    limit_price, stop_price, what_if, exchange, currency,
                ),
                self._loop,
            )
            return future.result(timeout=15)
        except Exception as exc:
            logger.debug("TWS place_order %s: %s", symbol, exc)
            return {"error": str(exc)}

    async def _async_place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        stop_price: float | None,
        what_if: bool,
        exchange: str,
        currency: str,
    ) -> dict:
        import ib_insync as ibi  # noqa: PLC0415

        contract = ibi.Stock(symbol, exchange, currency)

        if order_type == "MKT":
            order = ibi.MarketOrder(action.upper(), quantity)
        elif order_type == "LMT" and limit_price:
            order = ibi.LimitOrder(action.upper(), quantity, limit_price)
        elif order_type == "STP" and stop_price:
            order = ibi.StopOrder(action.upper(), quantity, stop_price)
        else:
            order = ibi.MarketOrder(action.upper(), quantity)

        order.whatIf = what_if
        accounts = self._ib.managedAccounts()
        if accounts:
            order.account = accounts[0]

        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(3)

        errors = [e.message for e in trade.log if e.errorCode and e.errorCode not in (0, 2104, 2106, 2158, 10349)]
        fills_info = []
        for f in trade.fills:
            fills_info.append({
                "price": f.execution.price,
                "qty": f.execution.shares,
                "commission": getattr(f.commissionReport, "commission", None),
            })

        return {
            "what_if": what_if,
            "symbol": symbol,
            "action": action.upper(),
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "status": trade.orderStatus.status,
            "filled": trade.orderStatus.filled,
            "account": order.account if hasattr(order, "account") else None,
            "fills": fills_info,
            "errors": errors,
            "log": [e.message for e in trade.log if e.message],
        }

    async def disconnect(self) -> None:
        if self._connected and self._ib:
            try:
                self._run_in_tws_loop(self._ib.disconnectAsync())
            except Exception:
                pass
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


# ─── Singleton factory ────────────────────────────────────────────────────────

_tws_service: TWSService | None = None
_tws_lock = threading.Lock()


def get_tws_service() -> TWSService | None:
    """
    Restituisce il singleton TWSService se TWS_ENABLED=true nella config.
    Avvia la connessione in background al primo accesso.
    Restituisce None se disabilitato o ib_insync non installato.
    """
    global _tws_service
    with _tws_lock:
        if _tws_service is not None:
            return _tws_service
        try:
            from app.core.config import settings  # noqa: PLC0415
            if not getattr(settings, "tws_enabled", False):
                return None
            host = getattr(settings, "tws_host", "host.docker.internal")
            port = int(getattr(settings, "tws_port", 7497))
            client_id = int(getattr(settings, "tws_client_id", 10))
            import ib_insync  # noqa: F401, PLC0415  — verifica installazione
            _tws_service = TWSService(host=host, port=port, client_id=client_id)
            _tws_service.start()
            return _tws_service
        except ImportError:
            logger.warning("ib_insync non installato — TWS service disabilitato")
            return None
        except Exception as exc:
            logger.warning("TWS service init fallito: %s", exc)
            return None
