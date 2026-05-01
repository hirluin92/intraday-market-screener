"""
Pipeline extract+context+patterns sui 4 simboli candidati (NIO, RIVN, DKNG, SOUN).
Replica logica pipeline_extract.ps1 ma parametrizzato.
"""
import time
import requests

SYMBOLS = ["NIO", "RIVN", "DKNG", "SOUN"]
BASE = "http://localhost:8000/api/v1/market-data"
TIMEFRAME = "5m"
LIMIT = 42000  # cap server: 50000. 42000 = stesso valore pipeline_extract.ps1.

def call(endpoint, body, timeout=1800):
    r = requests.post(f"{BASE}/{endpoint}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def main():
    print("=" * 80)
    print(f"PIPELINE CANDIDATES — symbols={SYMBOLS} tf={TIMEFRAME}")
    print("=" * 80)

    # FASE 2: features
    print("\n[FASE 2] features extraction...")
    for sym in SYMBOLS:
        t0 = time.time()
        try:
            r = call("features/extract", {
                "provider": "alpaca", "exchange": "ALPACA_US",
                "symbol": sym, "timeframe": TIMEFRAME, "limit": LIMIT
            })
            dt = time.time() - t0
            print(f"  FE OK {sym:<6} series={r.get('series_processed')} candles={r.get('candles_read')} time={dt:.1f}s")
        except Exception as e:
            print(f"  FE FAIL {sym}: {e}")

    # FASE 3: contexts
    print("\n[FASE 3] context extraction...")
    for sym in SYMBOLS:
        t0 = time.time()
        try:
            r = call("context/extract", {
                "provider": "alpaca", "exchange": "ALPACA_US",
                "symbol": sym, "timeframe": TIMEFRAME, "limit": LIMIT, "lookback": 100
            })
            dt = time.time() - t0
            print(f"  CTX OK {sym:<6} features={r.get('features_read')} contexts={r.get('contexts_upserted')} time={dt:.1f}s")
        except Exception as e:
            print(f"  CTX FAIL {sym}: {e}")

    # FASE 3b: indicators (richiesti per swing_high/low + RSI usati da double_top/bottom + divergenze)
    print("\n[FASE 3b] indicators extraction (RICHIESTO per pattern complessi)...")
    for sym in SYMBOLS:
        t0 = time.time()
        try:
            r = call("indicators/extract", {
                "provider": "alpaca", "exchange": "ALPACA_US",
                "symbol": sym, "timeframe": TIMEFRAME, "limit": LIMIT
            })
            dt = time.time() - t0
            print(f"  IND OK {sym:<6} candles={r.get('candles_read')} indicators={r.get('indicators_upserted')} time={dt:.1f}s")
        except Exception as e:
            print(f"  IND FAIL {sym}: {e}")

    # FASE 4: patterns
    print("\n[FASE 4] pattern extraction...")
    for sym in SYMBOLS:
        t0 = time.time()
        try:
            r = call("patterns/extract", {
                "provider": "alpaca", "exchange": "ALPACA_US",
                "symbol": sym, "timeframe": TIMEFRAME, "limit": LIMIT
            }, timeout=2400)
            dt = time.time() - t0
            print(f"  PAT OK {sym:<6} rows={r.get('rows_read')} patterns={r.get('patterns_upserted')} time={dt:.1f}s")
        except Exception as e:
            print(f"  PAT FAIL {sym}: {e}")

    print("\n=== DONE ===")

if __name__ == "__main__":
    main()
