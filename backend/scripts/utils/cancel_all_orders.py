"""Cancella tutti gli ordini aperti su TWS."""
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
            f"  prezzo={lmt}"
            f"  status={t.orderStatus.status}"
        )

    if not open_trades:
        print("Nessun ordine aperto.")
        ib.disconnect()
        return

    print("\nCancellazione in corso...")
    for t in open_trades:
        print(f"  Cancello {t.contract.symbol} {t.order.action} {t.order.totalQuantity}...")
        ib.cancelOrder(t.order)
        await asyncio.sleep(1.5)
        print(f"  -> status: {t.orderStatus.status}")

    print("\nFatto. Verifica finale:")
    still_open = [
        t for t in ib.trades()
        if t.orderStatus.status not in ("Filled", "Cancelled", "Inactive", "ApiCancelled")
    ]
    print(f"  Ordini ancora aperti: {len(still_open)}")

    ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
