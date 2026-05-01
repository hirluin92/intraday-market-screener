"""Mostra e cancella tutti gli ordini aperti su TWS."""
import asyncio
import ib_insync as ibi


async def main() -> None:
    ib = ibi.IB()
    await ib.connectAsync("host.docker.internal", 7497, clientId=11, timeout=10)

    trades = ib.trades()
    open_trades = [
        t for t in trades
        if t.orderStatus.status not in ("Filled", "Cancelled", "Inactive", "ApiCancelled")
    ]

    print(f"Ordini aperti trovati: {len(open_trades)}")
    for t in open_trades:
        lmt = getattr(t.order, "lmtPrice", None)
        print(
            f"  orderId={t.order.orderId}"
            f"  {t.contract.symbol} ({t.contract.currency})"
            f"  {t.order.action}"
            f"  qty={t.order.totalQuantity}"
            f"  tipo={t.order.orderType}"
            f"  lmt={lmt}"
            f"  status={t.orderStatus.status}"
        )

    if not open_trades:
        print("Nessun ordine da cancellare.")
        ib.disconnect()
        return

    risposta = input("\nVuoi cancellarli tutti? (s/n): ").strip().lower()
    if risposta == "s":
        for t in open_trades:
            print(f"  Cancello orderId={t.order.orderId} {t.contract.symbol} {t.order.action}...")
            ib.cancelOrder(t.order)
            await asyncio.sleep(1)
            print(f"  -> {t.orderStatus.status}")
        print("Fatto.")
    else:
        print("Nessuna cancellazione eseguita.")

    ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
