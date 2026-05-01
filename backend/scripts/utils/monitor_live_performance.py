"""
Monitor performance live — eseguito manualmente o via docker exec.

Uso:
  docker exec intraday-market-screener-backend-1 python /app/data/monitor_live_performance.py
  docker exec intraday-market-screener-backend-1 python /app/data/monitor_live_performance.py --days 7
"""

import os
import sys
import asyncio
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

# ── Valori attesi backtest ──────────────────────────────────────────────────
EXPECTED = {
    "1h": {"avg_r": 0.975, "wr_pct": 69.0},
    "5m": {"avg_r": 0.705, "wr_pct": 55.0},
    "all": {"avg_r": 0.840, "wr_pct": 62.0},
}

SKIP_OUTCOMES = {"stale_lost", "stale"}

# Soglie alert
ALERT_N_WEAK   = 30
ALERT_N_FULL   = 50
ALERT_AVG_R    = 0.10
ALERT_WR_PCT   = 35.0
ALERT_STREAK   = 8

NY_TZ = datetime.timezone(datetime.timedelta(hours=-4))  # EDT


# ── Helpers ─────────────────────────────────────────────────────────────────

def _stats(rows: list[dict]) -> dict:
    valid = [r for r in rows if r.get("realized_r") is not None
             and r.get("close_outcome") not in SKIP_OUTCOMES]
    if not valid:
        return {"n": 0, "avg_r": None, "total_r": None, "wr": None,
                "max_dd": None, "best": None, "worst": None}
    rs = [float(r["realized_r"]) for r in valid]
    wins = [x for x in rs if x > 0]
    total = sum(rs)
    avg = total / len(rs)
    cum = peak = max_dd = 0.0
    for x in rs:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "n": len(valid),
        "avg_r": round(avg, 4),
        "total_r": round(total, 4),
        "wr": round(len(wins) / len(valid) * 100, 1),
        "max_dd": round(max_dd, 4),
        "best": round(max(rs), 4),
        "worst": round(min(rs), 4),
    }


def _streak_current(rs: list[float]) -> int:
    n = 0
    for x in reversed(rs):
        if x <= 0:
            n += 1
        else:
            break
    return n


def _streak_max(rs: list[float]) -> int:
    cur = mx = 0
    for x in rs:
        cur = cur + 1 if x <= 0 else 0
        mx = max(mx, cur)
    return mx


def _bar(val: float, width: int = 30) -> str:
    """Equity curve ascii bar."""
    col = "+" if val >= 0 else "-"
    filled = min(int(abs(val) * width / 3.0), width)
    return col * filled


def _rstr(v) -> str:
    if v is None:
        return "     —    "
    return f"{float(v):+.3f}R"


def _vs(actual, expected) -> str:
    if actual is None or expected is None:
        return ""
    delta = actual - expected
    sign = "+" if delta >= 0 else ""
    return f"(vs exp {expected:+.3f}, Δ={sign}{delta:.3f})"


def _wr_vs(actual, expected) -> str:
    if actual is None or expected is None:
        return ""
    delta = actual - expected
    sign = "+" if delta >= 0 else ""
    return f"(vs exp {expected:.0f}%, Δ={sign}{delta:.1f}%)"


# ── Main ────────────────────────────────────────────────────────────────────

async def main(days: int) -> None:
    now_ny = datetime.datetime.now(NY_TZ)
    since_utc = (now_ny - datetime.timedelta(days=days)).astimezone(datetime.timezone.utc)
    today_start_utc = now_ny.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(datetime.timezone.utc)
    week_start_utc  = (now_ny.replace(hour=0, minute=0, second=0, microsecond=0)
                       - datetime.timedelta(days=7)).astimezone(datetime.timezone.utc)

    async with AsyncSessionLocal() as s:
        # ── Fetch all trades ─────────────────────────────────────────────────
        r = await s.execute(text("""
            SELECT id, symbol, timeframe, direction, pattern_name,
                   tws_status, close_outcome, close_cause,
                   realized_r, entry_price, stop_price, take_profit_1,
                   quantity_tp1, close_fill_price, sl_order_id, tp_order_id,
                   executed_at AT TIME ZONE 'America/New_York' AS et_ny,
                   closed_at AT TIME ZONE 'America/New_York' AS closed_ny
            FROM executed_signals
            WHERE executed_at >= :since
              AND close_outcome NOT IN ('stale_lost', 'stale')
               OR close_outcome IS NULL
            ORDER BY COALESCE(closed_at, executed_at)
        """), {"since": since_utc})
        rows = [dict(x) for x in r.mappings().all()]

        closed = [r for r in rows if r["closed_ny"] is not None and r["realized_r"] is not None]
        closed_1h = [r for r in closed if r["timeframe"] == "1h"]
        closed_5m = [r for r in closed if r["timeframe"] == "5m"]
        open_pos  = [r for r in rows
                     if r["closed_ny"] is None
                     and r["tws_status"] in ("submitted", "partial_fill_resized", "filled")]
        today_cl  = [r for r in closed if r["closed_ny"] and r["closed_ny"] >= today_start_utc.replace(tzinfo=None)]
        week_cl   = [r for r in closed if r["closed_ny"] and r["closed_ny"] >= week_start_utc.replace(tzinfo=None)]

        st_all = _stats(closed)
        st_1h  = _stats(closed_1h)
        st_5m  = _stats(closed_5m)

        rs_all = [float(r["realized_r"]) for r in closed]
        cur_streak = _streak_current(rs_all)
        max_streak = _streak_max(rs_all)

    # ── Stampa ──────────────────────────────────────────────────────────────
    W = 82
    print()
    print("═" * W)
    print(f"  PERFORMANCE MONITOR  —  {now_ny.strftime('%Y-%m-%d %H:%M ET')}  —  ultimi {days}gg")
    print("═" * W)

    # ── 1. Riepilogo per timeframe ──────────────────────────────────────────
    print()
    print("  ▶ RIEPILOGO STATISTICHE")
    print(f"  {'Metrica':<22} {'1h':>12} {'5m':>12} {'TOTALE':>12}  {'Atteso (backtest)'}")
    print("  " + "─" * (W - 2))

    def _row(label, f1h, f5m, fall, exp_label=""):
        print(f"  {label:<22} {f1h:>12} {f5m:>12} {fall:>12}  {exp_label}")

    _row("N trade",
         str(st_1h["n"]), str(st_5m["n"]), str(st_all["n"]))
    _row("avg R",
         _rstr(st_1h["avg_r"]), _rstr(st_5m["avg_r"]), _rstr(st_all["avg_r"]),
         f"1h:+{EXPECTED['1h']['avg_r']:.3f}R  5m:+{EXPECTED['5m']['avg_r']:.3f}R")
    _row("Win Rate",
         f"{st_1h['wr']:.1f}%" if st_1h["wr"] is not None else "    —    ",
         f"{st_5m['wr']:.1f}%" if st_5m["wr"] is not None else "    —    ",
         f"{st_all['wr']:.1f}%" if st_all["wr"] is not None else "    —    ",
         f"1h:{EXPECTED['1h']['wr_pct']:.0f}%  5m:{EXPECTED['5m']['wr_pct']:.0f}%")
    _row("Total R",
         _rstr(st_1h["total_r"]), _rstr(st_5m["total_r"]), _rstr(st_all["total_r"]))
    _row("Max DD (R)",
         _rstr(st_1h["max_dd"]) if st_1h["max_dd"] else "    —    ",
         _rstr(st_5m["max_dd"]) if st_5m["max_dd"] else "    —    ",
         _rstr(st_all["max_dd"]) if st_all["max_dd"] else "    —    ")
    _row("Best trade",
         _rstr(st_1h["best"]), _rstr(st_5m["best"]), _rstr(st_all["best"]))
    _row("Worst trade",
         _rstr(st_1h["worst"]), _rstr(st_5m["worst"]), _rstr(st_all["worst"]))

    # Vs backtest delta
    if st_all["n"] > 0:
        print()
        for tf, st, label in [("1h", st_1h, "1h"), ("5m", st_5m, "5m"), ("all", st_all, "TOTALE")]:
            if st["n"] == 0:
                continue
            exp = EXPECTED.get(tf, {})
            da = round(st["avg_r"] - exp["avg_r"], 4) if st["avg_r"] else None
            dw = round(st["wr"] - exp["wr_pct"], 1) if st["wr"] is not None else None
            note = f"({st['n']} trade — campione {'ok' if st['n'] >= 30 else 'ridotto <30'})"
            print(f"  [{label}] avg_R: {_rstr(st['avg_r'])} "
                  f"Δ vs backtest: {('+' if da and da >= 0 else '') + f'{da:.4f}R' if da else '—':>9}  "
                  f"WR: {st['wr']:.1f}% Δ: {('+' if dw and dw >= 0 else '') + f'{dw:.1f}%' if dw else '—':>7}  "
                  f"{note}")

    # ── 2. Oggi e 7 giorni ────────────────────────────────────────────────
    st_today = _stats(today_cl)
    st_week  = _stats(week_cl)
    print()
    print("  ▶ OGGI / ULTIMI 7 GIORNI")
    print(f"  {'Metrica':<22} {'Oggi':>12} {'7 giorni':>12}")
    print("  " + "─" * 40)
    wr_today = f"{st_today['wr']:.1f}%" if st_today["wr"] is not None else "—"
    wr_week  = f"{st_week['wr']:.1f}%" if st_week["wr"] is not None else "—"
    print(f"  {'N trade':<22} {str(st_today['n']):>12} {str(st_week['n']):>12}")
    print(f"  {'avg R':<22} {_rstr(st_today['avg_r']):>12} {_rstr(st_week['avg_r']):>12}")
    print(f"  {'Win Rate':<22} {wr_today:>12} {wr_week:>12}")
    print(f"  {'Total R':<22} {_rstr(st_today['total_r']):>12} {_rstr(st_week['total_r']):>12}")

    # ── 3. Posizioni aperte ───────────────────────────────────────────────
    n_1h = sum(1 for r in open_pos if r["timeframe"] == "1h")
    n_5m = sum(1 for r in open_pos if r["timeframe"] == "5m")
    print()
    print(f"  ▶ POSIZIONI APERTE ({len(open_pos)}/5 slot — {n_1h}/3 1h, {n_5m}/2 5m)")
    if open_pos:
        print(f"  {'ID':>5} {'SYM':<6} {'TF':<4} {'DIR':<8} {'ENTRY':>8} {'STOP':>8} "
              f"{'STEP1@':>9} {'STEP2@':>9} {'SL_ID':>7} {'APERTA ET'}")
        print("  " + "─" * 80)
        for p in open_pos:
            entry = float(p["entry_price"])
            stop  = float(p["stop_price"])
            risk  = abs(entry - stop)
            is_long = (p["direction"] or "").lower() == "bullish"
            s1 = entry + 0.50 * risk if is_long else entry - 0.50 * risk
            s2 = entry + 1.00 * risk if is_long else entry - 1.00 * risk
            et = p["et_ny"].strftime("%m-%d %H:%M") if p["et_ny"] else "?"
            print(f"  {p['id']:>5} {p['symbol']:<6} {p['timeframe']:<4} {(p['direction'] or ''):<8} "
                  f"{entry:>8.2f} {stop:>8.2f} "
                  f"{s1:>9.2f} {s2:>9.2f} {str(p['sl_order_id'] or '—'):>7}  {et}")
    else:
        print("  (nessuna)")

    # ── 4. Ultimi 10 trade ────────────────────────────────────────────────
    last10 = closed[-10:][::-1]
    print()
    print(f"  ▶ ULTIMI {len(last10)} TRADE")
    if last10:
        print(f"  {'#':>3} {'DATA ET':<12} {'SYM':<6} {'TF':<4} {'DIR':<8} "
              f"{'PATTERN':<28} {'ENTRY':>8} {'EXIT':>8} {'R':>8} {'ESITO':<8}")
        print("  " + "─" * W)
        for i, t in enumerate(last10, 1):
            rr = float(t["realized_r"])
            exit_p = float(t["close_fill_price"]) if t["close_fill_price"] else 0.0
            dt = t["closed_ny"].strftime("%m-%d %H:%M") if t["closed_ny"] else "?"
            outcome = t["close_outcome"] or "?"
            pn = (t["pattern_name"] or "")[:27]
            mark = "✓" if rr > 0 else "✗"
            print(f"  {i:>3} {dt:<12} {t['symbol']:<6} {t['timeframe']:<4} {(t['direction'] or ''):<8} "
                  f"{pn:<28} {float(t['entry_price']):>8.2f} {exit_p:>8.2f} "
                  f"{rr:>+8.3f}R {mark} {outcome:<8}")
    else:
        print("  (nessun trade nel periodo)")

    # ── 5. Equity curve ───────────────────────────────────────────────────
    print()
    print(f"  ▶ EQUITY CURVE (in R)  — {len(closed)} trade totali")
    print("  " + "─" * W)
    cum = 0.0
    for t in closed:
        rr = float(t["realized_r"])
        cum += rr
        dt = t["closed_ny"].strftime("%m-%d") if t["closed_ny"] else "??"
        sym = f"{t['symbol'][:4]:<4}"
        bar = _bar(rr)
        print(f"  {dt} {sym} {rr:>+7.3f}R  cum:{cum:>+7.3f}R  {bar}")

    # ── 6. Alert ─────────────────────────────────────────────────────────
    print()
    print("  ▶ ALERT")
    has_alert = False
    n = st_all["n"]
    avg_r_val = st_all["avg_r"]
    wr_val = st_all["wr"]

    if n == 0:
        print("  (nessun trade chiuso — nessuna metrica disponibile)")
        has_alert = True
    else:
        if n >= ALERT_N_FULL and avg_r_val is not None and avg_r_val <= 0:
            print(f"  🚨 CRITICO: avg_R={avg_r_val:+.3f}R dopo {n} trade — EDGE ASSENTE, valutare stop")
            has_alert = True
        elif n >= ALERT_N_WEAK and avg_r_val is not None and avg_r_val < ALERT_AVG_R:
            print(f"  ⚠️  ATTENZIONE: avg_R={avg_r_val:+.3f}R dopo {n} trade — edge debole (<{ALERT_AVG_R}R)")
            has_alert = True

        if n >= ALERT_N_FULL and wr_val is not None and wr_val < ALERT_WR_PCT:
            print(f"  ⚠️  ATTENZIONE: WR={wr_val:.1f}% sotto soglia {ALERT_WR_PCT:.0f}% dopo {n} trade")
            has_alert = True

        if cur_streak >= ALERT_STREAK:
            print(f"  ⚠️  ATTENZIONE: {cur_streak} loss consecutive in corso (max storico: {max_streak})")
            has_alert = True

        if not has_alert:
            print(f"  ✓ Nessun alert  (n={n}, avg_R={_rstr(avg_r_val).strip()}, "
                  f"WR={wr_val:.1f}%, loss_streak={cur_streak})")

    print()
    print("═" * W)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor performance live")
    parser.add_argument("--days", type=int, default=90, help="Finestra storica in giorni (default: 90)")
    args = parser.parse_args()
    asyncio.run(main(args.days))
