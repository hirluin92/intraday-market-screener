import httpx, json

BASE = "http://localhost:8000/api/v1/ibkr"

SYMBOL   = "RBLX"
ACTION   = "SELL"
EXCHANGE = "SMART"
CURRENCY = "USD"
ENTRY    = 57.16
STOP     = 58.1444
TP1      = 55.3881
TP2      = 53.7146
QTY_HALF = 9   # 18 totali / 2


def place(label, tp, qty):
    params = {
        "symbol":            SYMBOL,
        "action":            ACTION,
        "quantity":          qty,
        "entry_price":       ENTRY,
        "stop_price":        STOP,
        "take_profit_price": tp,
        "exchange":          EXCHANGE,
        "currency":          CURRENCY,
    }
    with httpx.Client(timeout=30.0) as c:
        r = c.post(f"{BASE}/tws/test-bracket", params=params)
        data = r.json()
    print(f"\n--- {label} ---")
    print(f"  Status HTTP: {r.status_code}")
    if r.status_code == 200:
        print(f"  Entry  orderId={data['entry']['order_id']}  status={data['entry']['status']}")
        print(f"  TP     orderId={data['take_profit']['order_id']}  lmt={data['take_profit']['lmt_price']}  status={data['take_profit']['status']}")
        print(f"  SL     orderId={data['stop_loss']['order_id']}  aux={data['stop_loss']['aux_price']}  status={data['stop_loss']['status']}")
        if data.get("errors"):
            print(f"  ERRORI: {data['errors']}")
        else:
            print("  OK - nessun errore")
    else:
        print(f"  ERRORE: {data}")
    return data


place("Bracket 1 - TP1 (9 unita)", TP1, QTY_HALF)
place("Bracket 2 - TP2 (9 unita)", TP2, QTY_HALF)
