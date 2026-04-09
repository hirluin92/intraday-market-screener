#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raccolta storica bid/ask da IBKR Trader Workstation.

Scarica gli ultimi 30 giorni di barre orarie BID_ASK per ogni simbolo
dell'universo e le salva in:
  - bid_ask_history.csv  (per analisi manuali e futura integrazione nel ML)
  - bid_ask_history_meta.json (statistiche per simbolo)

I dati raccolti saranno usati come feature aggiuntive nel modello ML
quando avremo abbastanza storico (3-6 mesi).

Uso:
    python collect_bid_ask_history.py [--symbols AAPL,NVDA,...] [--days 30] [--bar-size "1 hour"]

Prerequisiti:
    1. TWS aperto con API socket abilitata (porta 7497 paper / 7496 live)
    2. pip install ib-insync
    3. $env:PYTHONPATH = "backend"

Note:
    - Limite IBKR: max 60 richieste storiche al minuto → lo script attende automaticamente
    - Per dati oltre 30 giorni usare bar_size piu' grande ("1 day")
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fix encoding Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_DEFAULT_SYMBOLS = (
    "GOOGL,TSLA,AMD,META,NVDA,NFLX,COIN,MSTR,HOOD,SHOP,SOFI,ZS,NET,CELH,RBLX,PLTR,"
    "HPE,MDB,SMCI,DELL,ACHR,ASTS,JOBY,RKLB,NNE,OKLO,WULF,APLD,SMR,RXRX,NVO,LLY,"
    "MRNA,NKE,TGT,NEM,SCHW,WMT,SPY"
)

_OUTPUT_CSV = Path("bid_ask_history.csv")
_OUTPUT_META = Path("bid_ask_history_meta.json")


def _connect_tws(host: str, port: int, client_id: int):
    """Connette al TWS in modo sincrono. Restituisce IB instance o None."""
    try:
        import ib_insync as ibi
        ib = ibi.IB()
        ib.connect(host, port, clientId=client_id, timeout=15)
        if not ib.isConnected():
            print(f"  [ERRORE] Connessione fallita a {host}:{port}")
            return None
        print(f"  [OK] TWS connesso: {host}:{port} clientId={client_id}")
        return ib
    except ImportError:
        print("  [ERRORE] ib_insync non installato. Esegui: pip install ib-insync")
        return None
    except Exception as exc:
        print(f"  [ERRORE] TWS non disponibile: {exc}")
        print(f"  Assicurati che TWS sia aperto e API socket abilitata (porta {port})")
        return None


def _fetch_bid_ask(ib, symbol: str, duration: str, bar_size: str) -> list[dict]:
    """Scarica barre BID_ASK storiche per un simbolo."""
    try:
        import ib_insync as ibi
        contract = ibi.Stock(symbol, "SMART", "USD")
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="BID_ASK",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
        )
        result = []
        for b in bars:
            ts = b.date
            if hasattr(ts, "astimezone"):
                ts = ts.astimezone(timezone.utc).isoformat()
            else:
                ts = str(ts)
            # Nei bar BID_ASK: open=bid, high=ask, low=bid_low, close=ask_close
            bid_c = float(b.open) if b.open else None
            ask_c = float(b.high) if b.high else None
            spread_pct = None
            if bid_c and ask_c and bid_c > 0:
                mid = (bid_c + ask_c) / 2.0
                spread_pct = round((ask_c - bid_c) / mid * 100.0, 6) if mid > 0 else None
            result.append({
                "symbol": symbol,
                "timestamp": ts,
                "bid_close": bid_c,
                "ask_close": ask_c,
                "avg_spread_pct": spread_pct,
                "volume": float(b.volume) if b.volume else None,
            })
        return result
    except Exception as exc:
        print(f"    [ERRORE] {symbol}: {exc}")
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description="Raccolta storica bid/ask da TWS")
    ap.add_argument("--symbols", default=_DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--bar-size", default="1 hour")
    ap.add_argument("--host", default="localhost",
                    help="localhost se esegui fuori Docker, host.docker.internal da dentro")
    ap.add_argument("--port", type=int, default=7497,
                    help="7497 paper, 7496 live")
    ap.add_argument("--client-id", type=int, default=11)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    duration = f"{args.days} D"

    print(f"\nRaccolta bid/ask storico da TWS")
    print(f"  Simboli:   {len(symbols)}")
    print(f"  Periodo:   {args.days} giorni")
    print(f"  Bar size:  {args.bar_size}")
    print(f"  TWS:       {args.host}:{args.port}\n")

    if _OUTPUT_CSV.exists() and not args.overwrite:
        print(f"File {_OUTPUT_CSV} gia' esistente. Usa --overwrite per sovrascrivere.")
        sys.exit(0)

    # Connessione TWS
    ib = _connect_tws(args.host, args.port, args.client_id)
    if ib is None:
        sys.exit(1)

    fieldnames = ["symbol", "timestamp", "bid_close", "ask_close", "avg_spread_pct", "volume"]
    all_rows: list[dict] = []
    meta: dict = {"symbols": {}, "generated_at": datetime.now(timezone.utc).isoformat()}

    try:
        for i, sym in enumerate(symbols):
            print(f"  [{i+1:2d}/{len(symbols)}] {sym:<8}", end=" ", flush=True)
            t0 = time.time()
            rows = _fetch_bid_ask(ib, sym, duration, args.bar_size)

            if rows:
                spreads = [r["avg_spread_pct"] for r in rows if r["avg_spread_pct"] is not None]
                avg_spread = round(sum(spreads) / len(spreads), 4) if spreads else None
                max_spread = round(max(spreads), 4) if spreads else None
                all_rows.extend(rows)
                print(f"{len(rows):4d} barre | spread medio {avg_spread}% | max {max_spread}%"
                      f" ({time.time()-t0:.1f}s)")
                meta["symbols"][sym] = {
                    "bars": len(rows),
                    "avg_spread_pct": avg_spread,
                    "max_spread_pct": max_spread,
                    "date_from": rows[0]["timestamp"][:10] if rows else None,
                    "date_to": rows[-1]["timestamp"][:10] if rows else None,
                }
            else:
                print("  nessun dato (simbolo non disponibile o mercato chiuso)")
                meta["symbols"][sym] = {"bars": 0}

            # Rispetta il rate limit IBKR (max ~50 req/min per dati storici)
            if i < len(symbols) - 1:
                time.sleep(1.5)

    finally:
        ib.disconnect()
        print("\nTWS disconnesso.")

    if not all_rows:
        print("Nessun dato raccolto.")
        sys.exit(1)

    # Salva CSV
    with open(_OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nCSV salvato: {_OUTPUT_CSV}  ({len(all_rows):,} righe)")

    # Statistiche globali
    all_spreads = [r["avg_spread_pct"] for r in all_rows if r["avg_spread_pct"] is not None]
    meta["total_rows"] = len(all_rows)
    meta["global_avg_spread_pct"] = round(sum(all_spreads) / len(all_spreads), 4) if all_spreads else None
    meta["symbols_collected"] = sum(1 for v in meta["symbols"].values() if v.get("bars", 0) > 0)

    with open(_OUTPUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Meta salvato:  {_OUTPUT_META}")

    # Report spread per simbolo
    print(f"\n{'Simbolo':<8} {'Barre':>6} {'Spread medio':>13} {'Spread max':>11}")
    print("-" * 45)
    for sym, info in sorted(meta["symbols"].items(), key=lambda x: x[1].get("avg_spread_pct") or 99):
        if info.get("bars", 0) > 0:
            print(f"  {sym:<6} {info['bars']:>6}   {str(info['avg_spread_pct'])+'%':>12}   {str(info['max_spread_pct'])+'%':>10}")

    print(f"\nSpread medio globale: {meta['global_avg_spread_pct']}%")
    print("\nProssimi passi:")
    print("  1. Controlla i simboli con spread > 0.5% — quelli sono i piu' rischiosi")
    print("  2. Usa questi dati per calibrare IBKR_MAX_SPREAD_PCT nel .env")
    print("  3. Tra 3-6 mesi, integra avg_spread_pct come feature nel modello ML")


if __name__ == "__main__":
    main()
