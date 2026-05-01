#!/usr/bin/env python3
"""
Chiusura posizioni aperte — da eseguire prima dell'apertura di lunedì (9:29 ET).

Uso:
    # dry-run (default): mostra cosa verrebbe chiuso, non invia ordini
    docker exec intraday-backend python /app/data/close_positions_monday.py

    # esecuzione reale: cancella ordini GTC pendenti + chiude posizioni con MKT DAY
    docker exec intraday-backend python /app/data/close_positions_monday.py --execute

    # forza connessione anche se backend è già connesso con lo stesso client_id
    docker exec intraday-backend python /app/data/close_positions_monday.py --execute --client-id 12

Quando eseguire:
    - Idealmente alle 9:29 ET se il mercato USA è aperto (chiusura a open)
    - O manualmente dopo verifica in TWS: Activity → Positions
    - Gli ordini MKT TIF=DAY scadono a fine giornata se non fillati (es. mercato chiuso)
"""
import sys
import asyncio
import argparse
import datetime
import logging

# ─── args ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Chiude tutte le posizioni TWS aperte")
parser.add_argument("--execute", action="store_true",
                    help="Invia ordini reali (default: dry-run)")
parser.add_argument("--client-id", type=int, default=12,
                    help="TWS client_id da usare (default: 12, diverso da backend=11)")
parser.add_argument("--host", default="host.docker.internal",
                    help="TWS host (default: host.docker.internal)")
parser.add_argument("--port", type=int, default=7497,
                    help="TWS port (default: 7497 paper, 7496 live)")
args = parser.parse_args()

DRY_RUN = not args.execute
TWS_HOST = args.host
TWS_PORT = args.port
CLIENT_ID = args.client_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("close_positions")

SEP  = "═" * 80
SEP2 = "─" * 80


async def main() -> None:
    try:
        import ib_insync as ibi  # noqa: PLC0415
    except ImportError:
        log.error("ib_insync non installato — pip install ib_insync")
        sys.exit(1)

    mode_label = "🔴 ESECUZIONE REALE" if not DRY_RUN else "🔵 DRY-RUN (no ordini)"
    print(SEP)
    print(f"CLOSE POSITIONS MONDAY — {mode_label}")
    print(f"Connessione: {TWS_HOST}:{TWS_PORT} clientId={CLIENT_ID}")
    print(f"Timestamp:   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    ib = ibi.IB()
    try:
        await ib.connectAsync(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=10)
        log.info("TWS connesso: %s:%d clientId=%d", TWS_HOST, TWS_PORT, CLIENT_ID)
    except Exception as exc:
        log.error("Connessione TWS fallita: %s", exc)
        log.error("Verifica che TWS sia aperto e API abilitata (porta %d).", TWS_PORT)
        log.error("Se il backend è in esecuzione usa --client-id 12 per evitare conflitti.")
        sys.exit(1)

    try:
        await _close_all(ib)
    finally:
        ib.disconnect()
        log.info("TWS disconnesso.")


async def _close_all(ib) -> None:
    import ib_insync as ibi  # noqa: PLC0415

    # ── 1. Stato ordini aperti ─────────────────────────────────────────────────
    TERMINAL = {"Filled", "Cancelled", "Inactive", "ApiCancelled"}
    open_trades = [t for t in ib.openTrades() if t.orderStatus.status not in TERMINAL]
    pending_entries = [
        t for t in open_trades
        if getattr(t.order, "orderType", "") == "LMT"
        and getattr(t.order, "parentId", 0) == 0
    ]
    gtc_orders = [
        t for t in open_trades
        if getattr(t.order, "tif", "") == "GTC"
    ]

    print()
    print(SEP2)
    print(f"ORDINI APERTI: {len(open_trades)} totali | "
          f"{len(pending_entries)} entry LMT | {len(gtc_orders)} GTC (TP/SL)")
    print(SEP2)
    for t in open_trades:
        sym = getattr(t.contract, "symbol", "?")
        oid = t.order.orderId
        otype = getattr(t.order, "orderType", "?")
        action = getattr(t.order, "action", "?")
        qty = getattr(t.order, "totalQuantity", 0)
        tif = getattr(t.order, "tif", "?")
        status = t.orderStatus.status
        lmt = f" @ {t.order.lmtPrice:.2f}" if hasattr(t.order, "lmtPrice") and t.order.lmtPrice else ""
        aux = f" aux={t.order.auxPrice:.2f}" if hasattr(t.order, "auxPrice") and t.order.auxPrice else ""
        print(f"  #{oid:>8} {sym:<6} {action:<5} {qty:>8.0f}  {otype:<5}{lmt}{aux}  TIF={tif}  [{status}]")

    # ── 2. Posizioni aperte ────────────────────────────────────────────────────
    positions = await ib.reqPositionsAsync()
    open_positions = [p for p in positions if abs(p.position) > 1e-6]

    print()
    print(SEP2)
    print(f"POSIZIONI APERTE: {len(open_positions)}")
    print(SEP2)
    for p in open_positions:
        sym = p.contract.symbol
        qty = p.position
        avg = p.avgCost
        side = "LONG" if qty > 0 else "SHORT"
        print(f"  {sym:<8} {side:<6} {abs(qty):>8.0f} az  avg_cost={avg:.4f}")

    if not open_positions and not open_trades:
        print()
        print("✅ Nessuna posizione aperta e nessun ordine pendente. Niente da fare.")
        return

    print()
    if DRY_RUN:
        print("🔵 DRY-RUN — nessun ordine inviato.")
        print("   Riesegui con --execute per procedere.")
        return

    # ── 3. Cancella tutti gli ordini entry LMT pendenti ───────────────────────
    if pending_entries:
        print(f"Cancellazione {len(pending_entries)} ordini entry LMT pendenti...")
        for t in pending_entries:
            ib.cancelOrder(t.order)
            log.info("Cancellato ordine entry #%d %s", t.order.orderId, t.contract.symbol)
        await asyncio.sleep(2.0)
        print(f"  ✅ {len(pending_entries)} entry cancellati.")

    # ── 4. Cancella tutti gli ordini GTC (TP/SL) ─────────────────────────────
    if gtc_orders:
        print(f"Cancellazione {len(gtc_orders)} ordini GTC (TP/SL)...")
        for t in gtc_orders:
            ib.cancelOrder(t.order)
            log.info("Cancellato GTC #%d %s", t.order.orderId, t.contract.symbol)
        await asyncio.sleep(2.0)
        print(f"  ✅ {len(gtc_orders)} GTC cancellati.")

    # ── 5. Chiudi ogni posizione aperta con MKT DAY ────────────────────────────
    if open_positions:
        print(f"Invio ordini MKT DAY per {len(open_positions)} posizioni...")
        accounts = ib.managedAccounts()
        account = accounts[0] if accounts else ""

        for p in open_positions:
            sym = p.contract.symbol
            qty = p.position
            exchange = getattr(p.contract, "primaryExchange", None) or p.contract.exchange or "SMART"
            currency = p.contract.currency or "USD"
            action = "SELL" if qty > 0 else "BUY"

            contract = ibi.Stock(sym, exchange, currency)
            order = ibi.MarketOrder(action=action, totalQuantity=abs(qty))
            order.tif = "DAY"
            order.account = account

            trade = ib.placeOrder(contract, order)
            log.info("Inviato MKT %s %s %.0f az (ordine #%d)", action, sym, abs(qty), trade.order.orderId)

        await asyncio.sleep(3.0)

        # Verifica stato ordini appena piazzati
        fresh_trades = ib.openTrades()
        print()
        print(f"  Stato ordini MKT dopo 3s:")
        for t in fresh_trades:
            if getattr(t.order, "orderType", "") == "MKT":
                sym = t.contract.symbol
                status = t.orderStatus.status
                filled = t.orderStatus.filled
                remaining = t.orderStatus.remaining
                avg_fill = t.orderStatus.avgFillPrice
                fill_str = f" fillato={filled:.0f} avg={avg_fill:.2f}" if filled else ""
                print(f"    {sym:<8} [{status}]{fill_str} rimanente={remaining:.0f}")

    print()
    print(SEP)
    print("OPERAZIONE COMPLETATA")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
