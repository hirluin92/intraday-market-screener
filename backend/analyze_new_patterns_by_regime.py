"""
Analisi dei nuovi pattern v2 per regime di mercato (bull/bear/neutral).
Approccio veloce: carica regimi SPY separatamente, usa bisect per match.
"""
from __future__ import annotations
import asyncio, os, sys, math, statistics, bisect
from collections import defaultdict

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
    if entry <= 0 or len(closes) < 2: return None
    risk = entry * STOP_PCT
    stop = entry - risk if direction == "long" else entry + risk
    tp1  = entry + risk * RR_TP1 if direction == "long" else entry - risk * RR_TP1
    tp2  = entry + risk * RR_TP2 if direction == "long" else entry - risk * RR_TP2
    pos, pnl = 1.0, 0.0
    for i in range(min(MAX_BARS, len(closes))):
        hi, lo = highs[i], lows[i]
        if direction == "long":
            if lo <= stop:   return pnl + pos * (-1.0)
            if hi >= tp1 and pos >= 1.0: pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
            if hi >= tp2 and pos > 0:    return pnl + pos * RR_TP2
        else:
            if hi >= stop:   return pnl + pos * (-1.0)
            if lo <= tp1 and pos >= 1.0: pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
            if lo <= tp2 and pos > 0:    return pnl + pos * RR_TP2
    cl = closes[min(MAX_BARS, len(closes)) - 1]
    return pnl + pos * ((cl - entry) / risk if direction == "long" else (entry - cl) / risk)


async def main():
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    pat_ph = ", ".join(f"'{p}'" for p in NEW_PATTERNS)
    sym_ph = ", ".join(f"'{s}'" for s in SYMBOLS_V42)

    async with AsyncSessionLocal() as session:
        # 1) Pattern senza subquery correlata
        print("Carico pattern...")
        q_pat = f"""
            SELECT cp.pattern_name, cp.direction, cp.symbol, cp.exchange, cp.timeframe,
                   cp.timestamp AS ts
            FROM candle_patterns cp
            WHERE cp.pattern_name IN ({pat_ph})
              AND cp.symbol IN ({sym_ph})
              AND cp.pattern_strength >= {MIN_STRENGTH}
            ORDER BY cp.timestamp
        """
        r = await session.execute(text(q_pat))
        patterns = r.fetchall()
        print(f"  {len(patterns)} pattern")

        # 2) Regimi SPY (direction_bias da candle_contexts per SPY 1h)
        print("Carico regimi SPY...")
        q_spy = """
            SELECT ctx.timestamp, ctx.direction_bias
            FROM candle_contexts ctx
            JOIN candle_features cf ON ctx.candle_feature_id = cf.id
            WHERE cf.symbol = 'SPY' AND cf.timeframe = '1h'
            ORDER BY ctx.timestamp
        """
        r3 = await session.execute(text(q_spy))
        spy_rows = r3.fetchall()
        spy_ts   = [row[0] for row in spy_rows]
        spy_bias = [str(row[1]).lower() for row in spy_rows]
        print(f"  {len(spy_rows)} barre SPY")

        # 3) Candele per simulazione
        print("Carico candele...")
        q_candles = f"""
            SELECT symbol, exchange, timeframe, timestamp, high, low, close
            FROM candles
            WHERE symbol IN ({sym_ph}) AND timeframe = '1h'
            ORDER BY symbol, exchange, timestamp
        """
        r2 = await session.execute(text(q_candles))
        candle_rows = r2.fetchall()
        print(f"  {len(candle_rows)} candele")

    # Indice candele
    candle_idx: dict[tuple, list] = defaultdict(list)
    for sym, exc, tf, ts, hi, lo, cl in candle_rows:
        candle_idx[(sym, exc, tf)].append((ts, float(hi), float(lo), float(cl)))
    ts_idx: dict[tuple, list] = {}
    for key, lst in candle_idx.items():
        lst.sort(key=lambda x: x[0])
        ts_idx[key] = [row[0] for row in lst]

    def get_regime(ts) -> str:
        if not spy_ts: return "unknown"
        idx = bisect.bisect_right(spy_ts, ts) - 1
        if idx < 0: return "unknown"
        b = spy_bias[idx]
        if b == "bullish": return "bull"
        if b == "bearish": return "bear"
        return "neutral"

    # Simula
    print("Simulo trade...")
    stats: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for row in patterns:
        pname, direction, sym, exc, tf, ts = row
        dir_str = "long" if direction.lower() in ("bullish","long") else "short"
        key = (sym, exc, tf)
        if key not in ts_idx: continue
        tss = ts_idx[key]
        idx = bisect.bisect_right(tss, ts)
        if idx >= len(tss): continue
        candles = candle_idx[key]
        entry = candles[idx][3]
        future = candles[idx+1 : idx+1+MAX_BARS]
        if len(future) < 3: continue
        fut_cl = [c[3] for c in future]
        fut_hi = [c[1] for c in future]
        fut_lo = [c[2] for c in future]
        pnl = simulate(dir_str, entry, fut_cl, fut_hi, fut_lo)
        if pnl is None or math.isnan(pnl) or abs(pnl) >= 15: continue
        regime = get_regime(ts)
        stats[pname][regime].append(pnl)
        stats[pname]["ALL"].append(pnl)

    def fmt(pnls):
        if len(pnls) < 5: return f"  n={len(pnls)} (insufficiente)"
        wins   = [r for r in pnls if r > 0]
        losses = [r for r in pnls if r <= 0]
        wr = len(wins)/len(pnls)*100
        aw = statistics.mean(wins)   if wins   else 0.0
        al = statistics.mean(losses) if losses else 0.0
        ev = (wr/100)*aw+(1-wr/100)*al
        bar = "█"*int(wr/5)
        tag = "★★★" if ev>0.35 else ("★★" if ev>0.15 else ("★" if ev>0.05 else "✗"))
        return f"WR={wr:5.1f}%  EV={ev:+6.3f}R  W={aw:+5.2f}R  L={al:+5.2f}R  n={len(pnls):>4}  {bar} {tag}"

    # Ordina per EV totale
    order = []
    for pname in NEW_PATTERNS:
        pnls = stats.get(pname,{}).get("ALL",[])
        if not pnls: continue
        wins = [r for r in pnls if r>0]
        losses = [r for r in pnls if r<=0]
        wr = len(wins)/len(pnls)*100
        aw = statistics.mean(wins) if wins else 0
        al = statistics.mean(losses) if losses else 0
        ev = (wr/100)*aw+(1-wr/100)*al
        order.append((ev, pname))
    order.sort(reverse=True)

    print()
    print("=" * 90)
    print("  NUOVI PATTERN v2 — ANALISI PER REGIME MERCATO SPY")
    print("=" * 90)

    for _, pname in order:
        pdata = stats.get(pname, {})
        print(f"\n{'─'*90}")
        print(f"  {pname.upper()}")
        for regime in ["ALL", "bull", "neutral", "bear"]:
            label = {"ALL":"TUTTI", "bull":"BULL ", "neutral":"LATE ", "bear":"BEAR "}[regime]
            pnls = pdata.get(regime, [])
            print(f"    {label}  {fmt(pnls)}")

    # Riepilogo finale
    print()
    print("=" * 90)
    print("  RIEPILOGO: dove ogni pattern funziona meglio")
    print("=" * 90)
    for _, pname in order:
        pdata = stats.get(pname, {})
        results = []
        for regime in ["bull","neutral","bear"]:
            pnls = pdata.get(regime, [])
            if len(pnls) < 5: continue
            wins=[r for r in pnls if r>0]; losses=[r for r in pnls if r<=0]
            wr=len(wins)/len(pnls)*100
            aw=statistics.mean(wins) if wins else 0
            al=statistics.mean(losses) if losses else 0
            ev=(wr/100)*aw+(1-wr/100)*al
            results.append((regime, wr, ev, len(pnls)))
        if not results: continue
        best = max(results, key=lambda x: x[2])
        worst = min(results, key=lambda x: x[2])
        best_str = f"{best[0].upper()}(WR={best[1]:.0f}%,EV={best[2]:+.2f}R,n={best[3]})"
        worst_str = f"{worst[0].upper()}(WR={worst[1]:.0f}%,EV={worst[2]:+.2f}R,n={worst[3]})"
        print(f"  {pname:<35}  MEGLIO: {best_str:<35}  PEGGIO: {worst_str}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
