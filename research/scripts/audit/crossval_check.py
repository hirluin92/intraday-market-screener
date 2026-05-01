import pandas as pd
import psycopg2

conn = psycopg2.connect(host="postgres", port=5432,
    dbname="intraday_market_screener", user="postgres", password="postgres")
cur = conn.cursor()

df = pd.read_csv("/app/data/val_1h_production.csv")
yf = df[df["provider"] == "yahoo_finance"].copy()
sample = yf.sample(10, random_state=7)

print("Cross-validation: 10 random 1h Yahoo trades")
print(f"{'Symbol':<8} {'PatternTs (ET)':<20} {'entry':>8} {'stop':>8} {'tp1':>8} {'outcome':<9} {'pnl_r':>7}  candle_close  check")
print("-" * 110)

for _, row in sample.iterrows():
    sym = row["symbol"]
    pts = pd.Timestamp(row["pattern_timestamp"], tz="UTC")
    entry = float(row["entry_price"])
    stop  = float(row["stop_price"])
    tp1   = float(row["tp1_price"])
    outcome = row["outcome"]
    pnl_r = float(row["pnl_r"])
    direction = row["direction"]

    cur.execute("""
        SELECT ROUND(open::numeric,4), ROUND(high::numeric,4),
               ROUND(low::numeric,4), ROUND(close::numeric,4), volume::bigint
        FROM candles
        WHERE provider='yahoo_finance' AND timeframe='1h' AND symbol=%s
          AND timestamp=%s
    """, (sym, pts))
    row_db = cur.fetchone()

    if row_db is None:
        print(f"  {sym:<8} {str(pts)[:16]:<20}  *** CANDLE NOT FOUND IN DB ***")
        continue

    o, h, l, c, vol = row_db
    entry_ok = abs(float(c) - entry) < 0.02
    risk_pct = abs(entry - stop) / entry * 100
    stop_ok = 0.1 <= risk_pct <= 5.0
    if direction == "bullish":
        tp1_ok = tp1 > entry
    else:
        tp1_ok = tp1 < entry
    all_ok = entry_ok and stop_ok and tp1_ok
    status = "OK" if all_ok else f"WARN(entry={'ok' if entry_ok else 'FAIL'} stop={'ok' if stop_ok else 'FAIL'} tp1={'ok' if tp1_ok else 'FAIL'})"
    pts_et = str(pts.tz_convert("America/New_York"))[:16]
    print(f"  {sym:<8} {pts_et:<20} {entry:>8.2f} {stop:>8.2f} {tp1:>8.2f} {outcome:<9} {pnl_r:>7.3f}  c={float(c):.3f}  {status}")

conn.close()
print("\nDone.")
