"""
Step 1 — Aggrega candele 5m Alpaca -> 15m
Legge dal DB (read-only), salva in research/datasets/candles_15m_aggregated.csv

NON scrive nulla al DB di produzione.

Uso:
  cd backend
  python research/01_aggregate_15m.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.models  # noqa: F401 — registra tutti i modelli ORM

from datetime import timezone

import pandas as pd
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.candle import Candle

OUTPUT = Path(__file__).parent / "datasets" / "candles_15m_aggregated.csv"

# Simboli che costituiscono l'universo Alpaca 5m (inclusi quelli bloccati,
# per analisi completa — i filtri vengono applicati nello Step 4).
SYMBOLS_ALPACA_5M = [
    "META", "NVDA", "TSLA", "AMD", "NFLX",
    "COIN", "MSTR", "HOOD", "SHOP", "SOFI",
    "ZS", "NET", "CELH", "RBLX", "PLTR",
    "MDB", "SMCI", "DELL", "NVO", "LLY",
    "MRNA", "NKE", "TGT", "SCHW", "AMZN",
    "MU", "LUNR", "CAT", "GS",
    # Includi SPY per regime — verrà escluso dall'analisi trade ma usato come anchor
    "SPY", "AAPL", "MSFT", "GOOGL", "WMT",
]


async def load_candles_by_symbol(session, symbol: str) -> list:
    stmt = (
        select(Candle)
        .where(Candle.provider == "alpaca")
        .where(Candle.timeframe == "5m")
        .where(Candle.symbol == symbol)
        .order_by(Candle.timestamp.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def candles_to_df(candles: list) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    records = []
    for c in candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        records.append({
            "symbol": c.symbol,
            "exchange": c.exchange,
            "provider": c.provider,
            "timestamp": ts,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume) if c.volume is not None else 0.0,
        })
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def aggregate_5m_to_15m(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggrega un DataFrame 5m in 15m:
    - timestamp = timestamp della prima candela del gruppo (floor 15 min)
    - open = open della prima candela
    - high = max(high)
    - low = min(low)
    - close = close dell'ultima candela
    - volume = sum(volume)
    Scarta gruppi incompleti (n_bars != 3).
    """
    df = df.sort_values("timestamp").reset_index(drop=True)
    # Floor al 15m bucket
    df["ts_15m"] = df["timestamp"].dt.floor("15min")

    agg = (
        df.groupby(["symbol", "exchange", "provider", "ts_15m"])
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            n_bars=("open", "count"),
        )
        .reset_index()
    )

    # Solo gruppi completi di 3 barre
    agg = agg[agg["n_bars"] == 3].copy()
    agg.rename(columns={"ts_15m": "timestamp"}, inplace=True)
    agg["timeframe"] = "15m"
    agg = agg.drop(columns=["n_bars"])
    agg = agg[["symbol", "exchange", "provider", "timeframe", "timestamp",
               "open", "high", "low", "close", "volume"]]
    return agg.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


async def main():
    print("=" * 60)
    print("STEP 1 — Aggregazione 5m Alpaca -> 15m")
    print("=" * 60)

    all_groups: list[pd.DataFrame] = []
    total_5m = 0

    async with AsyncSessionLocal() as session:
        for sym in SYMBOLS_ALPACA_5M:
            candles = await load_candles_by_symbol(session, sym)
            if not candles:
                print(f"  {sym:8s}: nessuna candela 5m trovata — skip")
                continue

            df_5m = candles_to_df(candles)
            df_15m = aggregate_5m_to_15m(df_5m)

            n5 = len(df_5m)
            n15 = len(df_15m)
            total_5m += n5
            ratio = n5 / n15 if n15 > 0 else 0

            ts_min = df_15m["timestamp"].min() if n15 > 0 else "—"
            ts_max = df_15m["timestamp"].max() if n15 > 0 else "—"
            print(f"  {sym:8s}: {n5:6,} 5m -> {n15:5,} 15m  (1:{ratio:.2f})  {ts_min} … {ts_max}")

            if n15 > 0:
                all_groups.append(df_15m)

    if not all_groups:
        print("\nNessun dato trovato. Verificare la connessione al DB.")
        return

    result = pd.concat(all_groups, ignore_index=True)
    result = result.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    total_15m = len(result)
    ratio_global = total_5m / total_15m if total_15m > 0 else 0

    print()
    print("-" * 60)
    print(f"  Totale 5m originali:    {total_5m:>10,}")
    print(f"  Totale 15m aggregati:   {total_15m:>10,}")
    print(f"  Rapporto globale:       1:{ratio_global:.3f}  (teorico 1:3.000)")
    print(f"  Simboli con dati:       {result['symbol'].nunique():>3}")
    print(f"  Periodo coperto:        {result['timestamp'].min()} -> {result['timestamp'].max()}")
    print()

    # Verifica per anno
    result["year"] = result["timestamp"].dt.year
    print("  Candele 15m per anno:")
    for yr, cnt in result.groupby("year").size().items():
        print(f"    {yr}: {cnt:,}")
    result.drop(columns=["year"], inplace=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False)
    print(f"\n  Salvato in: {OUTPUT}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
