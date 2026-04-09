"""
Test round-trip BUY+SELL IWDA via TWS con prezzo live (delayed).
Esegui: python test_order_roundtrip.py
"""
import asyncio
import math
import ib_insync as ibi


async def main() -> None:
    ib = ibi.IB()
    await ib.connectAsync("host.docker.internal", 7497, clientId=11, timeout=10)
    account = ib.managedAccounts()[0]
    contract = ibi.Stock("IWDA", "SMART", "EUR")

    # Leggi prezzo corrente (delayed, tipo 3)
    ib.reqMarketDataType(3)
    tickers = await ib.reqTickersAsync(contract)
    t = tickers[0]
    ask  = t.ask  if t.ask  and t.ask  > 0 and not math.isnan(t.ask)  else None
    bid  = t.bid  if t.bid  and t.bid  > 0 and not math.isnan(t.bid)  else None
    last = t.last if t.last and t.last > 0 and not math.isnan(t.last) else None
    print(f"Prezzo IWDA  bid={bid}  ask={ask}  last={last}")

    ref = ask or last or 113.0
    buy_price  = round(ref + 0.10, 2)   # leggermente sopra ask → fill immediato
    sell_price = round(ref - 0.10, 2)   # leggermente sotto bid → fill immediato

    # ── BUY ──────────────────────────────────────────────────────────────────
    buy_order = ibi.LimitOrder("BUY", 1, buy_price)
    buy_order.account = account
    buy_order.tif = "DAY"
    print(f"\n[BUY]  LMT 1 IWDA @ {buy_price} EUR  (account={account})")
    t_buy = ib.placeOrder(contract, buy_order)
    for i in range(12):
        await asyncio.sleep(1)
        s = t_buy.orderStatus
        print(f"  [{i+1}s] {s.status}  filled={s.filled}  avg={s.avgFillPrice}")
        if s.status in ("Filled", "Cancelled", "Inactive"):
            break

    if t_buy.orderStatus.status != "Filled":
        print("BUY non eseguito — cancello e esco")
        ib.cancelOrder(buy_order)
        ib.disconnect()
        return

    # ── SELL ─────────────────────────────────────────────────────────────────
    sell_order = ibi.LimitOrder("SELL", 1, sell_price)
    sell_order.account = account
    sell_order.tif = "DAY"
    print(f"\n[SELL] LMT 1 IWDA @ {sell_price} EUR")
    t_sell = ib.placeOrder(contract, sell_order)
    for i in range(12):
        await asyncio.sleep(1)
        s = t_sell.orderStatus
        print(f"  [{i+1}s] {s.status}  filled={s.filled}  avg={s.avgFillPrice}")
        if s.status in ("Filled", "Cancelled", "Inactive"):
            break

    # ── Cleanup ordini pendenti ───────────────────────────────────────────────
    print("\n[CLEANUP] ordini ancora aperti...")
    pending = [
        tr for tr in ib.trades()
        if tr.orderStatus.status not in ("Filled", "Cancelled", "Inactive")
    ]
    if pending:
        for tr in pending:
            print(f"  Cancello: {tr.contract.symbol} {tr.order.action} {tr.order.totalQuantity}")
            ib.cancelOrder(tr.order)
            await asyncio.sleep(1)
    else:
        print("  Nessuno.")

    # ── Riepilogo ─────────────────────────────────────────────────────────────
    buy_fill  = t_buy.orderStatus.avgFillPrice
    sell_fill = t_sell.orderStatus.avgFillPrice
    pnl = sell_fill - buy_fill
    print(f"\nRIEPILOGO:")
    print(f"  BUY  filled @ {buy_fill:.4f} EUR")
    print(f"  SELL filled @ {sell_fill:.4f} EUR")
    print(f"  P&L round-trip: {pnl:+.4f} EUR/azione (escluse commissioni 3 EUR x2)")

    ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
