"""
Analisi sistematica di TUTTI i pattern 1h Yahoo non ancora in VALIDATED_PATTERNS_OPERATIONAL.

Per ogni pattern:
  - Statistiche globali (WR, EV, campione)
  - Statistiche per regime SPY (bull / bear / neutral)
  - Flag candidato a promozione

Output: tabella ordinata per EV totale + dettaglio per regime.
"""
from __future__ import annotations
import asyncio, os, sys, math, statistics, bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
# Connessione diretta psycopg2 (sincrona) per script standalone su Windows
# evita il problema WinError 64 di asyncpg/SSL su Windows host con Docker
DB_DSN = "host=localhost port=5432 dbname=intraday_market_screener user=postgres password=postgres"

# ── Pattern già validati (da escludere dall'analisi) ─────────────────────────
ALREADY_VALIDATED = {
    "compression_to_expansion_transition",
    "rsi_momentum_continuation",
    "double_bottom", "double_top",
    "engulfing_bullish",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
}

# ── Tutti i pattern presenti nel DB 1h Yahoo ─────────────────────────────────
ALL_PATTERNS = [
    # Reversal / Candlestick
    "hammer_reversal", "shooting_star_reversal",
    "morning_star", "evening_star",
    "engulfing_bearish",
    # Continuation
    "bull_flag", "bear_flag",
    "trend_continuation_pullback",
    "inside_bar_breakout_bull",
    # Breakout
    "breakout_with_retest",
    "opening_range_breakout_bull", "opening_range_breakout_bear",
    "nr7_breakout",
    "volatility_squeeze_breakout",
    "range_expansion_breakout_candidate",
    "impulsive_bullish_candle", "impulsive_bearish_candle",
    # Support/Resistance
    "support_bounce", "resistance_rejection",
    "vwap_bounce_bull", "vwap_bounce_bear",
    "ema_pullback_to_support", "ema_pullback_to_resistance",
    # Smart Money / Institutional
    "fvg_retest_bull", "fvg_retest_bear",
    "ob_retest_bull", "ob_retest_bear",
    "liquidity_sweep_bull", "liquidity_sweep_bear",
    # Fibonacci
    "fibonacci_bounce",
]

SYMBOLS = {
    "GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SHOP",
    "SOFI","ZS","NET","CELH","RBLX","PLTR","HPE","MDB","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","NEM","SCHW","WMT","MP",
}

MIN_STRENGTH = 0.70
RR_TP1, RR_TP2 = 1.5, 3.0
STOP_PCT = 0.015
TP1_SIZE = 0.5
MAX_BARS = 8
MIN_SAMPLE = 20   # soglia minima per considerare un risultato affidabile


def simulate(direction: str, entry: float, closes: list, highs: list, lows: list) -> float | None:
    if entry <= 0 or len(closes) < 2:
        return None
    risk = entry * STOP_PCT
    stop = entry - risk if direction == "long" else entry + risk
    tp1  = entry + risk * RR_TP1 if direction == "long" else entry - risk * RR_TP1
    tp2  = entry + risk * RR_TP2 if direction == "long" else entry - risk * RR_TP2
    pos, pnl = 1.0, 0.0
    for i in range(min(MAX_BARS, len(closes))):
        hi, lo = highs[i], lows[i]
        if direction == "long":
            if lo <= stop:                   return pnl + pos * (-1.0)
            if hi >= tp2 and pos > 0:        return pnl + pos * RR_TP2
            if hi >= tp1 and pos >= 1.0:     pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
        else:
            if hi >= stop:                   return pnl + pos * (-1.0)
            if lo <= tp2 and pos > 0:        return pnl + pos * RR_TP2
            if lo <= tp1 and pos >= 1.0:     pnl += TP1_SIZE * RR_TP1; pos -= TP1_SIZE
    cl = closes[min(MAX_BARS, len(closes)) - 1]
    return pnl + pos * ((cl - entry) / risk if direction == "long" else (entry - cl) / risk)


def fmt_stats(pnls: list[float], min_n: int = MIN_SAMPLE) -> str:
    if len(pnls) < min_n:
        return f"n={len(pnls):>4}  (campione insufficiente)"
    wins   = [r for r in pnls if r > 0]
    losses = [r for r in pnls if r <= 0]
    wr = len(wins) / len(pnls) * 100
    aw = statistics.mean(wins)   if wins   else 0.0
    al = statistics.mean(losses) if losses else 0.0
    ev = (wr / 100) * aw + (1 - wr / 100) * al
    bar = "█" * int(wr / 5)
    if   ev > 0.40: tag = "[****] PROMUOVI"
    elif ev > 0.20: tag = "[*** ] CANDIDATO"
    elif ev > 0.08: tag = "[**  ] INTERESSANTE"
    elif ev > 0.0:  tag = "[*   ] DEBOLE"
    else:           tag = "[----] NEGATIVO"
    bar_ascii = "#" * int(wr / 5)
    return f"WR={wr:5.1f}%  EV={ev:+6.3f}R  W={aw:+5.2f}R  L={al:+5.2f}R  n={len(pnls):>4}  {bar_ascii:12s}  {tag}"


def main():
    import psycopg2

    targets = [p for p in ALL_PATTERNS if p not in ALREADY_VALIDATED]
    pat_ph  = ", ".join(f"'{p}'" for p in targets)
    sym_ph  = ", ".join(f"'{s}'" for s in SYMBOLS)

    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()

    print("Carico pattern dal DB...")
    cur.execute(f"""
        SELECT cp.pattern_name, cp.direction, cp.symbol, cp.exchange,
               cp.timeframe, cp.timestamp AS ts, cp.pattern_strength
        FROM candle_patterns cp
        WHERE cp.pattern_name IN ({pat_ph})
          AND cp.symbol IN ({sym_ph})
          AND cp.timeframe = '1h'
          AND cp.pattern_strength >= {MIN_STRENGTH}
        ORDER BY cp.timestamp
    """)
    patterns = cur.fetchall()
    print(f"  {len(patterns)} segnali caricati")

    print("Carico regime SPY (direction_bias 1h)...")
    cur.execute("""
        SELECT ctx.timestamp, ctx.direction_bias
        FROM candle_contexts ctx
        JOIN candle_features cf ON ctx.candle_feature_id = cf.id
        WHERE cf.symbol = 'SPY' AND cf.timeframe = '1h'
        ORDER BY ctx.timestamp
    """)
    spy_rows = cur.fetchall()
    spy_ts   = [row[0] for row in spy_rows]
    spy_bias = [str(row[1]).lower() for row in spy_rows]
    print(f"  {len(spy_rows)} barre SPY")

    print("Carico candele OHLCV...")
    cur.execute(f"""
        SELECT symbol, exchange, timeframe, timestamp, high, low, close
        FROM candles
        WHERE symbol IN ({sym_ph}) AND timeframe = '1h'
        ORDER BY symbol, exchange, timestamp
    """)
    candle_rows = cur.fetchall()
    conn.close()
    print(f"  {len(candle_rows)} candele")

    # Indice candele per serie
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
        if "bull" in b: return "bull"
        if "bear" in b: return "bear"
        return "neutral"

    # Simulazione
    print("Simulo trade...")
    stats: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    skipped = 0

    for row in patterns:
        pname, direction, sym, exc, tf, ts, strength = row
        dir_str = "long" if str(direction).lower() in ("bullish", "long") else "short"
        key = (sym, exc, tf)
        if key not in ts_idx:
            skipped += 1
            continue
        tss = ts_idx[key]
        idx = bisect.bisect_right(tss, ts)
        if idx >= len(tss):
            skipped += 1
            continue
        candles = candle_idx[key]
        entry = candles[idx][3]
        future = candles[idx + 1: idx + 1 + MAX_BARS]
        if len(future) < 3:
            skipped += 1
            continue
        pnl = simulate(dir_str, entry, [c[3] for c in future],
                       [c[1] for c in future], [c[2] for c in future])
        if pnl is None or math.isnan(pnl) or abs(pnl) >= 15:
            skipped += 1
            continue
        regime = get_regime(ts)
        stats[pname][regime].append(pnl)
        stats[pname]["ALL"].append(pnl)

    print(f"  Skipped: {skipped}")

    # Ordina per EV totale
    order = []
    for pname in targets:
        pnls = stats.get(pname, {}).get("ALL", [])
        if len(pnls) < MIN_SAMPLE:
            ev = -99.0
        else:
            wins = [r for r in pnls if r > 0]
            losses = [r for r in pnls if r <= 0]
            wr = len(wins) / len(pnls)
            ev = wr * (statistics.mean(wins) if wins else 0) + \
                 (1 - wr) * (statistics.mean(losses) if losses else 0)
        order.append((ev, pname))
    order.sort(reverse=True)

    SEP = "─" * 110
    print()
    print("=" * 110)
    print("  ANALISI PATTERN 1h YAHOO — NON VALIDATI (ordinati per EV globale)")
    print("=" * 110)

    for _, pname in order:
        all_pnls = stats.get(pname, {}).get("ALL", [])
        bull_pnls = stats.get(pname, {}).get("bull", [])
        bear_pnls = stats.get(pname, {}).get("bear", [])
        neut_pnls = stats.get(pname, {}).get("neutral", [])

        print()
        print(f"  >> {pname}")
        print(f"    GLOBALE  : {fmt_stats(all_pnls)}")
        print(f"    BULL     : {fmt_stats(bull_pnls, min_n=10)}")
        print(f"    BEAR     : {fmt_stats(bear_pnls, min_n=10)}")
        print(f"    NEUTRAL  : {fmt_stats(neut_pnls, min_n=10)}")

    print()
    print(SEP)
    print("LEGENDA: [****]=PROMUOVI (EV>0.40R) | [***]=CANDIDATO (EV>0.20R) | [**]=INTERESSANTE (EV>0.08R)")
    print("         [*]=DEBOLE (EV>0) | [--]=NEGATIVO | soglia campione globale >= 20 segnali")
    print(SEP)


if __name__ == "__main__":
    main()
