"""Bootstrap path: scripts/utils/ → backend root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from app.services.tws_service import get_tws_service

async def main():
    tws = get_tws_service()
    if not tws or not tws.is_connected:
        print("TWS non connesso!")
        return

    # Prima verifica prezzo corrente
    quote = await tws.get_live_quote("MDB")
    if quote:
        print("MDB quote: bid=" + str(quote.bid) + " ask=" + str(quote.ask) + " last=" + str(quote.last))
    else:
        print("MDB: nessun quote disponibile, procedo comunque")

    # Parametri dal piano di trade
    # SHORT: SELL entry a 256.775, TP1 a 252.532, SL a 259.132
    # Quantita' 4 (arrotondata da 4.089)
    result = await tws.place_bracket_order(
        symbol="MDB",
        action="SELL",       # SHORT entry
        quantity=4,
        entry_price=256.775,
        stop_price=259.132,       # stop loss (sopra entry per short)
        take_profit_price=252.532, # take profit (sotto entry per short)
        exchange="SMART",
        currency="USD",
    )

    print("\n=== RISULTATO ORDINE MDB SHORT ===")
    print("Simbolo: " + result.get("symbol", "?"))
    print("Azione: " + result.get("action", "?"))
    print("Qty: " + str(result.get("quantity", "?")))
    print("Entry: " + str(result.get("entry_price", "?")))
    print("TP: " + str(result.get("take_profit_price", "?")))
    print("SL: " + str(result.get("stop_price", "?")))
    print("Account: " + str(result.get("account", "?")))
    print("\nEntry order: " + str(result.get("entry", {})))
    print("Take profit: " + str(result.get("take_profit", {})))
    print("Stop loss:   " + str(result.get("stop_loss", {})))
    errors = result.get("errors", [])
    if errors:
        print("\nERRORI: " + str(errors))
    else:
        print("\nNessun errore — ordini inviati a TWS!")

asyncio.run(main())
