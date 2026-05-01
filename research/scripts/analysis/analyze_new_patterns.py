"""
Analisi statistica dei 10 nuovi pattern v2.
Approccio efficiente: fetch pattern + candele per simbolo, simula in Python.
"""
from __future__ import annotations
import asyncio, os, sys, math, statistics
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/intraday_market_screener",
)

NEW_PATTERNS = [
    "nr7_breakout",
    "liquidity_sweep_bull", "liquidity_sweep_bear",
    "rsi_divergence_bull",  "rsi_divergence_bear",
    "volatility_squeeze_breakout",
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
]

SYMBOLS_V42 = {
    "GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SHOP",
    "SOFI","ZS","NET","CELH","RBLX","PLTR","HPE","MDB","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","NEM","SCHW","WMT","SPY",
}

MIN_STRENGTH = 0.70
RR_TP1, RR_TP2 = 1.5, 3.0
STOP_PCT = 0.015
TP1_SIZE = 0.5
MAX_BARS = 8


def simulate(direction: str, entry: float, closes: list, highs: list, lows: list) -> float | None:
    if entry <= 0 or len(closes) < 2:
        return None
    risk = entry * STOP_PCT
    stop = entry - risk if direction == "long" else entry + risk
    tp1  = entry + risk * RR_TP1 if direction == "long" else entry - risk * RR_TP1
    tp2  = entry + risk * RR_TP2 if direction == "long" else entry - risk * RR_TP2
    pos = 1.0
    pnl = 0.0
    for i in range(min(MAX_BARS, len(closes))):
        hi, lo = highs[i], lows[i]
        if direction == "long":
            if lo <= stop:
                return pnl + pos * (-1.0)
            if hi >= tp1 and pos >= 1.0:
                pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
            if hi >= tp2 and pos > 0:
                return pnl + pos * RR_TP2
        else:
            if hi >= stop:
                return pnl + pos * (-1.0)
            if lo <= tp1 and pos >= 1.0:
                pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
            if lo <= tp2 and pos > 0:
                return pnl + pos * RR_TP2
    # timeout
    cl = closes[min(MAX_BARS, len(closes)) - 1]
    return pnl + pos * ((cl - entry) / risk if direction == "long" else (entry - cl) / risk)


async def main():
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    pat_ph  = ", ".join(f"'{p}'" for p in NEW_PATTERNS)
    sym_ph  = ", ".join(f"'{s}'" for s in SYMBOLS_V42)

    async with AsyncSessionLocal() as session:
        # 1) Fetch pattern con timestamp e candela di segnale
        print("Carico pattern...")
        q_pat = f"""
            SELECT cp.pattern_name, cp.direction, cp.symbol, cp.exchange, cp.timeframe,
                   cp.pattern_strength, cp.timestamp AS ts,
                   cf.candle_id
            FROM candle_patterns cp
            JOIN candle_features cf ON cp.candle_feature_id = cf.id
            WHERE cp.pattern_name IN ({pat_ph})
              AND cp.symbol IN ({sym_ph})
              AND cp.pattern_strength >= {MIN_STRENGTH}
            ORDER BY cp.symbol, cp.timeframe, cp.timestamp
        """
        r = await session.execute(text(q_pat))
        patterns = r.fetchall()
        print(f"  {len(patterns)} pattern caricati")

        # 2) Fetch tutte le candele per i simboli necessari (solo OHLC + timestamp)
        print("Carico candele...")
        q_candles = f"""
            SELECT symbol, exchange, timeframe, timestamp,
                   open, high, low, close
            FROM candles
            WHERE symbol IN ({sym_ph})
              AND timeframe = '1h'
            ORDER BY symbol, exchange, timestamp
        """
        r2 = await session.execute(text(q_candles))
        candle_rows = r2.fetchall()
        print(f"  {len(candle_rows)} candele caricate")

    # Indice candele per (symbol, exchange, timeframe) → lista timestamp-ordinata
    from collections import defaultdict
    import bisect
    candle_idx: dict[tuple, list] = defaultdict(list)
    for sym, exc, tf, ts, o, hi, lo, cl in candle_rows:
        candle_idx[(sym, exc, tf)].append((ts, float(o), float(hi), float(lo), float(cl)))

    print("Costruisco indice temporale...")
    ts_idx: dict[tuple, list] = {}
    for key, lst in candle_idx.items():
        lst.sort(key=lambda x: x[0])
        ts_idx[key] = [row[0] for row in lst]

    # Simula ogni pattern
    print("Simulo trade...")
    stats: dict[str, list[float]] = defaultdict(list)
    skipped = 0

    for row in patterns:
        pname, direction, sym, exc, tf, strength, ts, candle_id = row
        direction = direction.lower()
        dir_str = "long" if direction in ("bullish", "long") else "short"
        key = (sym, exc, tf)
        if key not in ts_idx:
            skipped += 1; continue
        tss = ts_idx[key]
        idx = bisect.bisect_right(tss, ts)   # prima barra DOPO il segnale
        if idx >= len(tss):
            skipped += 1; continue
        candles = candle_idx[key]
        entry = candles[idx][4]  # close della prima barra dopo segnale = proxy entry
        future = candles[idx+1 : idx+1+MAX_BARS]
        if len(future) < 3:
            skipped += 1; continue
        fut_cl = [c[4] for c in future]
        fut_hi = [c[2] for c in future]
        fut_lo = [c[3] for c in future]
        pnl = simulate(dir_str, entry, fut_cl, fut_hi, fut_lo)
        if pnl is not None and not math.isnan(pnl) and abs(pnl) < 15:
            stats[pname].append(pnl)

    print(f"Simulazioni completate. Skipped: {skipped}")

    # Risultati
    print()
    print("=" * 80)
    print(f"{'PATTERN':<35} {'WR':>7} {'AvgR':>8} {'EV':>8} {'n':>6}  GRAFICO")
    print("=" * 80)

    results = []
    for pname, pnls in stats.items():
        if len(pnls) < 5:
            continue
        wins   = [r for r in pnls if r > 0]
        losses = [r for r in pnls if r <= 0]
        wr = len(wins) / len(pnls) * 100
        avg_r = statistics.mean(pnls)
        aw = statistics.mean(wins)   if wins   else 0.0
        al = statistics.mean(losses) if losses else 0.0
        ev = (wr/100)*aw + (1-wr/100)*al
        results.append((pname, wr, avg_r, ev, len(pnls), aw, al))

    results.sort(key=lambda x: x[3], reverse=True)

    for pname, wr, avg_r, ev, n, aw, al in results:
        bar = "█" * int(wr / 5)
        ev_tag = "BUONO" if ev > 0.20 else ("OK" if ev > 0.05 else "BASSO")
        print(f"{pname:<35} {wr:>6.1f}% {avg_r:>+7.3f}R {ev:>+7.3f}R {n:>6}  {bar}  [{ev_tag}]")
        print(f"  {'':35} avg_win={aw:+.3f}R  avg_loss={al:+.3f}R")

    print()
    print("-" * 80)
    print("RIFERIMENTO pattern top esistenti (dal dataset):")
    print("  compression_to_expansion_transition  WR~61%  EV~+0.45R  [TOP]")
    print("  rsi_momentum_continuation            WR~56%  EV~+0.30R  [TOP]")
    print("  engulfing_bullish (regime bear)      WR~67%  EV~+0.15R  [BUONO]")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
