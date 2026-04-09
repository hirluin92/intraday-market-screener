"""
Test connessione TWS via ib_insync.

Esegui dalla root del progetto (non dentro Docker):
    pip install ib-insync   # se non già installato nell'env locale
    python test_tws_connection.py

Assicurati che in TWS sia abilitata l'API socket:
    File → Global Configuration → API → Settings
    [x] Enable ActiveX and Socket Clients
    Socket port: 7497 (paper) / 7496 (live)
    Master API client ID: 0 (o lascia vuoto)
"""

import asyncio
import sys

HOST = "127.0.0.1"
PORT = 7497          # 7497 paper, 7496 live
CLIENT_ID = 99       # ID diverso da quello del backend (10)
TEST_SYMBOL = "SPY"  # Simbolo da quotare


async def main() -> None:
    try:
        import ib_insync as ibi
    except ImportError:
        print("ERRORE: ib_insync non installato. Esegui: pip install ib-insync")
        sys.exit(1)

    ib = ibi.IB()

    print(f"[1/4] Connessione a TWS {HOST}:{PORT} clientId={CLIENT_ID} ...")
    try:
        await ib.connectAsync(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"      FALLITO: {e}")
        print("\n  Verifica che TWS sia aperto e l'API socket sia abilitata.")
        print("  TWS → File → Global Configuration → API → Settings → Enable ActiveX and Socket Clients")
        sys.exit(1)

    print(f"      Connesso! Account(s): {ib.managedAccounts()}")

    # ── Test 2: quote live ────────────────────────────────────────────────────
    print(f"\n[2/4] Richiesta quote live per {TEST_SYMBOL} ...")
    import math
    contract = ibi.Stock(TEST_SYMBOL, "SMART", "USD")
    tickers = await ib.reqTickersAsync(contract)
    ask_price: float | None = None
    if tickers:
        t = tickers[0]
        bid = t.bid if t.bid and t.bid > 0 and not math.isnan(t.bid) else None
        ask = t.ask if t.ask and t.ask > 0 and not math.isnan(t.ask) else None
        last = t.last if t.last and t.last > 0 and not math.isnan(t.last) else None
        ask_price = ask
        print(f"      {TEST_SYMBOL}: bid={bid or 'N/D'}  ask={ask or 'N/D'}  last={last or 'N/D'}")
        if bid is None and ask is None:
            print("      (Dati in tempo reale non disponibili — abbonamento market data API richiesto;")
            print("       in modalità paper/delayed i prezzi potrebbero non arrivare via reqTickers)")
    else:
        print(f"      Nessun ticker ricevuto per {TEST_SYMBOL}")

    # ── Test 3: market depth (Level 2) ────────────────────────────────────────
    print(f"\n[3/4] Richiesta Market Depth (Level 2) per {TEST_SYMBOL} ...")
    ticker_depth = ib.reqMktDepth(contract, numRows=3)
    await asyncio.sleep(1.5)
    bids = [d for d in (ticker_depth.domBids or []) if d.price > 0]
    asks = [d for d in (ticker_depth.domAsks or []) if d.price > 0]
    if bids or asks:
        print(f"      Bid levels: {[(round(d.price,2), d.size) for d in bids[:3]]}")
        print(f"      Ask levels: {[(round(d.price,2), d.size) for d in asks[:3]]}")
    else:
        print("      Dati Level 2 non disponibili (normale senza abbonamento market depth)")
    ib.cancelMktDepth(contract)

    # ── Test 4: ordine simulato (whatIfOrder) ─────────────────────────────────
    print(f"\n[4/4] Simulazione ordine LIMIT BUY 1 {TEST_SYMBOL} (whatIfOrder — NON inviato al mercato) ...")
    accounts = ib.managedAccounts()
    account = accounts[0] if accounts else ""

    # Usa prezzo ask live se disponibile, altrimenti un prezzo di fallback realistico
    FALLBACK_PRICE = 560.0   # prezzo indicativo SPY — aggiorna se necessario
    limit_price = round(ask_price * 0.999, 2) if ask_price else FALLBACK_PRICE
    print(f"      Prezzo limite usato: {limit_price} {'(live ask)' if ask_price else '(fallback)'}")

    order = ibi.LimitOrder("BUY", 1, limit_price)
    order.account = account
    order.whatIf = True   # NON viene inviato al mercato

    trade = ib.placeOrder(contract, order)
    await asyncio.sleep(2)

    state = trade.orderStatus.status
    print(f"      Status ordine: {state}")

    # In ib_insync la commissione stimata è in trade.orderStatus.whyHeld o nei fills
    # Per whatIf, IBKR restituisce i dati via orderState nell'evento orderStatusEvent
    fills = trade.fills
    if fills:
        for f in fills:
            comm = getattr(f.commissionReport, "commission", None)
            if comm and comm > 0:
                print(f"      Commissione stimata: ${comm:.4f}")
    else:
        print("      Commissione stimata: non disponibile (normale per paper/whatIf senza fill)")

    # ── Disconnect ────────────────────────────────────────────────────────────
    ib.disconnect()
    print("\nTest completato con successo.")
    print(f"\nRIEPILOGO:")
    print(f"  - Connessione TWS:   OK  ({HOST}:{PORT})")
    print(f"  - Account:           {account}")
    print(f"  - Market data:       {'OK' if ask_price else 'non disponibile (abbonamento richiesto)'}")
    print(f"  - Level 2 depth:     {'OK' if (bids or asks) else 'non disponibile'}")
    print(f"  - Ordine simulato:   {state}")


if __name__ == "__main__":
    asyncio.run(main())
