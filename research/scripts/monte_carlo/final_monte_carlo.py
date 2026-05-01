"""
final_monte_carlo.py  —  Simulazione Monte Carlo FINALE
=========================================================
Applica tutti i fix di produzione e proietta i risultati:
  1. Chiusura EOD (1h: interpola pnl_r a bar 7 per trade overnight)
  2. TIF=DAY (entry scade a fine giornata)
  3. Max 5 posizioni simultanee (walk cronologico)
  4. Risk: LONG <= 3%, SHORT <= 2% | Strength [0.60, 0.80)

Due scenari Monte Carlo:
  A) Teorico (edge storico invariato) — mostra il massimo matematico
  B) Paper trading conservativo (edge ridotto al 40%, slippage 0.30R)
     basato sull'OOS degradation media osservata (IS→OOS ~40-85%)

Uso: python final_monte_carlo.py [--data1h PATH] [--data5m PATH] [--sims N]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _TZ_ET = _ZoneInfo("America/New_York")
except Exception:
    _TZ_ET = None  # type: ignore[assignment]

# ── Parametri produzione ─────────────────────────────────────────────────────
_PATTERNS_1H = frozenset({
    "double_bottom", "double_top",
    "macd_divergence_bull", "rsi_divergence_bull",
    "macd_divergence_bear", "rsi_divergence_bear",
    "engulfing_bullish",
})
_PATTERNS_5M = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bull", "macd_divergence_bear",
})
_BLOCKED_5M = frozenset({"SPY", "AAPL", "MSFT", "GOOGL", "WMT"})

MAX_RISK_LONG  = 3.0    # % (risk_pct nel CSV gia' in %)
MAX_RISK_SHORT = 2.0    # %
MAX_STRENGTH   = 0.80
MIN_STRENGTH   = 0.60
MAX_BTE_1H     = 4
MAX_BTE_5M     = 3
EOD_CUTOFF     = 7      # barre max intraday per 1h
MAX_POSITIONS  = 5
CAPITAL        = 100_000.0


# ── Utility ──────────────────────────────────────────────────────────────────

def _et_hm(ts_str: str) -> tuple[int, int]:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if _TZ_ET is not None:
            dt_et = dt.astimezone(_TZ_ET)
        else:
            dt_et = (dt - timedelta(hours=4)).replace(tzinfo=None)
        return dt_et.hour, dt_et.minute
    except Exception:
        return 12, 0


def _parse_ts(ts_str: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def _load_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["pnl_r"]            = float(r["pnl_r"])
                r["risk_pct"]         = float(r.get("risk_pct") or 0)
                r["pattern_strength"] = float(r.get("pattern_strength") or 0)
                r["final_score"]      = float(r.get("final_score") or 0)
                r["entry_filled"]     = r.get("entry_filled", "False") == "True"
                bte = r.get("bars_to_entry")
                r["bars_to_entry"]    = int(float(bte)) if bte not in ("", "None", None) else None
                bx  = r.get("bars_to_exit")
                r["bars_to_exit"]     = int(float(bx)) if bx not in ("", "None", None) else None
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows


def _wilson_ci(wins: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    z = 1.96
    p = wins / n
    c = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    m = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / (1 + z**2 / n)
    return round(max(0.0, c - m) * 100, 1), round(min(1.0, c + m) * 100, 1)


def _stats(trades: list[dict]) -> tuple[int, float, float]:
    if not trades:
        return 0, 0.0, 0.0
    pnls = [r["pnl_r"] for r in trades]
    n    = len(pnls)
    avg  = sum(pnls) / n
    wr   = sum(1 for p in pnls if p > 0) / n * 100
    return n, avg, wr


def _data_years(rows: list[dict]) -> float:
    ts = [_parse_ts(r.get("pattern_timestamp", "")) for r in rows]
    ts = [t for t in ts if t]
    if len(ts) < 2:
        return 2.0
    return max(0.5, (max(ts) - min(ts)).total_seconds() / 86400 / 365.25)


# ── Filtri produzione ────────────────────────────────────────────────────────

def _filt_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe") != "1h":
            continue
        if r.get("pattern_name") not in _PATTERNS_1H:
            continue
        if r.get("pattern_name") == "engulfing_bullish":
            reg = r.get("market_regime", "")
            if reg and reg not in ("bear", "neutral"):
                continue
        h, _ = _et_hm(r.get("pattern_timestamp", ""))
        if h == 3:
            continue
        s = r["pattern_strength"]
        if not (MIN_STRENGTH <= s < MAX_STRENGTH):
            continue
        rp = r["risk_pct"]
        d  = r.get("direction", "bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG:
            continue
        if d == "bearish" and rp > MAX_RISK_SHORT:
            continue
        bte = r["bars_to_entry"]
        if bte is None or bte > MAX_BTE_1H:
            continue
        out.append(r)
    return out


def _filt_5m(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe") != "5m":
            continue
        if r.get("provider") != "alpaca":
            continue
        if r.get("pattern_name") not in _PATTERNS_5M:
            continue
        if r.get("symbol", "").upper() in _BLOCKED_5M:
            continue
        h, _ = _et_hm(r.get("pattern_timestamp", ""))
        if h < 11:
            continue
        s = r["pattern_strength"]
        if not (MIN_STRENGTH <= s < MAX_STRENGTH):
            continue
        rp = r["risk_pct"]
        d  = r.get("direction", "bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG:
            continue
        if d == "bearish" and rp > MAX_RISK_SHORT:
            continue
        bte = r["bars_to_entry"]
        if bte is None or bte > MAX_BTE_5M:
            continue
        out.append(r)
    return out


# ── Fix A: EOD close 1h ──────────────────────────────────────────────────────

def _eod_1h(rows: list[dict], slippage_extra: float = 0.05) -> tuple[list[dict], int, float, float]:
    adj, overnight = [], []
    for r in rows:
        bx = r.get("bars_to_exit")
        if bx is not None and bx > EOD_CUTOFF:
            overnight.append(r["pnl_r"])
            row = dict(r)
            row["pnl_r"]     = r["pnl_r"] * (EOD_CUTOFF / bx) - slippage_extra
            row["bars_to_exit"] = EOD_CUTOFF
            row["outcome"]   = "eod_close"
            adj.append(row)
        else:
            adj.append(r)
    avg_b = sum(overnight) / max(1, len(overnight))
    avg_a = sum(r["pnl_r"] for r in adj if r.get("outcome") == "eod_close") / max(1, len(overnight))
    return adj, len(overnight), avg_b, avg_a


# ── Fix B: TIF=DAY ───────────────────────────────────────────────────────────

def _tif_day(rows: list[dict]) -> tuple[list[dict], int]:
    out, rej = [], 0
    for r in rows:
        h, m  = _et_hm(r.get("pattern_timestamp", ""))
        tf    = r.get("timeframe", "1h")
        bte   = r.get("bars_to_entry")
        if bte is None:
            out.append(r); continue
        if tf == "1h":
            rem = max(0, 16 - h)
        elif tf == "5m":
            rem = max(0, (960 - h * 60 - m) // 5)
        else:
            out.append(r); continue
        if bte > rem:
            rej += 1
        else:
            out.append(r)
    return out, rej


# ── Fix C: Max 5 posizioni simultanee ───────────────────────────────────────

def _max_pos(rows: list[dict], cap: int = MAX_POSITIONS) -> tuple[list[dict], int]:
    def _times(r: dict):
        ts  = _parse_ts(r.get("pattern_timestamp", ""))
        bte = r.get("bars_to_entry") or 1
        bx  = r.get("bars_to_exit")  or 7
        tf  = r.get("timeframe", "1h")
        if not ts:
            return None, None
        dur = timedelta(hours=1) if tf == "1h" else timedelta(minutes=5)
        e   = ts + bte * dur
        return e, e + bx * dur

    timed = [(e, x, r) for r in rows for e, x in [_times(r)] if e]
    timed.sort(key=lambda v: v[0])

    done, skip, active = [], 0, []
    for et, xt, r in timed:
        active = [a for a in active if a > et]
        if len(active) >= cap:
            skip += 1
            continue
        if xt:
            active.append(xt)
        done.append(r)
    return done, skip


# ── Monte Carlo ──────────────────────────────────────────────────────────────

def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, round(rng.gauss(lam, lam ** 0.5)))
    L, k, p = math.exp(-lam), 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def monte_carlo(
    trades: list[dict],
    *,
    n_sims:   int   = 5000,
    n_months: int   = 12,
    cap:      float = CAPITAL,
    risk:     float = 0.01,
    slip:     float = 0.15,
    oos_frac: float = 1.0,   # de-rating: 1.0=teorico, 0.4=conservativo
    seed:     int   = 42,
) -> dict:
    if not trades:
        return {}
    rng  = random.Random(seed)
    dyrs = _data_years(trades)
    tpy  = len(trades) / dyrs          # trade/anno
    tpm  = tpy / 12                    # trade/mese (Poisson mean)

    pool     = [r["pnl_r"] * oos_frac - slip for r in trades]
    avg_net  = sum(pool) / len(pool)

    # Calcola slippage di pareggio
    avg_gross = sum(r["pnl_r"] for r in trades) / len(trades)
    breakeven_slip = avg_gross * oos_frac  # slippage che azzera avg_r_net

    month_eq: list[list[float]] = [[] for _ in range(n_months)]
    fin_eq:   list[float] = []
    max_dds:  list[float] = []

    for _ in range(n_sims):
        eq, peak, max_dd = cap, cap, 0.0
        for mi in range(n_months):
            nt = _poisson(rng, tpm)
            for _ in range(nt):
                pnl = rng.choice(pool)
                eq  = max(0.0, eq + pnl * (eq * risk))
                if eq > peak:
                    peak = eq
                elif peak > 0:
                    dd = (peak - eq) / peak
                    if dd > max_dd:
                        max_dd = dd
            month_eq[mi].append(eq)
        fin_eq.append(eq)
        max_dds.append(max_dd)

    fin_eq.sort(); max_dds.sort()
    n = len(fin_eq)

    pm = {}
    for i, el in enumerate(month_eq):
        el.sort()
        m = len(el)
        pm[i + 1] = {
            "med": el[m // 2],
            "p5":  el[max(0, int(m * .05))],
            "p25": el[max(0, int(m * .25))],
            "p75": el[min(m - 1, int(m * .75))],
        }

    simple_annual = tpy * avg_net * risk * 100   # % semplice annuo

    return {
        "per_month": pm,
        "final": {
            "med":  fin_eq[n // 2],
            "p5":   fin_eq[max(0, int(n * .05))],
            "p25":  fin_eq[max(0, int(n * .25))],
            "p75":  fin_eq[min(n - 1, int(n * .75))],
            "p95":  fin_eq[min(n - 1, int(n * .95))],
            "pp":   sum(1 for e in fin_eq if e > cap) / n,
        },
        "dd_med":      max_dds[n // 2],
        "dd_p95":      max_dds[min(n - 1, int(n * .95))],
        "tpy":         tpy,
        "avg_net":     avg_net,
        "simple_ann":  simple_annual,
        "breakeven_slip": breakeven_slip,
    }


# ── Output ───────────────────────────────────────────────────────────────────

def _pret(eq: float) -> float:
    return (eq / CAPITAL - 1) * 100


def _mc_row(mc: dict, lbl: str) -> None:
    f   = mc.get("final", {})
    if not f:
        return
    tpy = mc["tpy"]
    ar  = mc["avg_net"]
    sa  = mc["simple_ann"]
    med = _pret(f["med"])
    p5  = _pret(f["p5"])
    dd  = mc["dd_med"] * 100
    pp  = f["pp"] * 100
    print(f"  {lbl:<15}  {tpy:>7.0f}/a  {ar:>+8.3f}R  {sa:>+9.1f}%/a  {med:>+10.1f}%  {p5:>+9.1f}%  {dd:>6.1f}%  {pp:>5.1f}%")


def _print_impact_table(stages: list[tuple[str, list[dict]]], title: str) -> None:
    print("\n" + "=" * 95)
    print(title)
    print("=" * 95)
    print(f"  {'Fix':<42}  {'n_trade':>8}  {'avg_r':>8}  {'WR%':>6}  {'Trade persi':>12}  {'Delta avg_r':>12}")
    print("  " + "-" * 90)
    base_n, base_avg, _ = _stats(stages[0][1]) if stages else (1, 0.0, 0.0)
    prev_n = base_n
    for label, trades in stages:
        n, avg_r, wr = _stats(trades)
        lost    = prev_n - n
        delta_r = avg_r - base_avg
        l_s = f"{lost:+d}" if label != stages[0][0] else "—"
        d_s = f"{delta_r:+.3f}R" if label != stages[0][0] else "—"
        print(f"  {label:<42}  {n:>8}  {avg_r:>+8.3f}R  {wr:>5.1f}%  {l_s:>12}  {d_s:>12}")
        prev_n = n


def _print_per_pattern(trades: list[dict], lbl: str) -> None:
    by = defaultdict(list)
    for r in trades:
        by[r.get("pattern_name", "?")].append(r)
    print(f"\n  Dettaglio per pattern — {lbl}:")
    print(f"  {'Pattern':<40}  {'n':>5}  {'WR%':>6}  {'avg_r':>8}  {'CI 95%':>15}")
    print("  " + "-" * 80)
    for pat in sorted(by):
        n, avg, wr = _stats(by[pat])
        lo, hi = _wilson_ci(sum(1 for r in by[pat] if r["pnl_r"] > 0), n)
        print(f"  {pat:<40}  {n:>5}  {wr:>5.1f}%  {avg:>+8.3f}R  [{lo:.0f}%-{hi:.0f}%]")


def _print_equity_curve(mc: dict, label: str) -> None:
    pm = mc.get("per_month", {})
    if not pm:
        return
    print(f"\n  Curva equity mensile — {label} (mediana 5000 sims, risk 0.5%):")
    print(f"  {'Mese':>4}  {'Equity med':>12}  {'P25-P75':>20}  {'Ritorno mensile':>15}  {'Ritorno cum':>11}")
    print("  " + "-" * 70)
    prev = CAPITAL
    for m in range(1, 13):
        d   = pm.get(m, {})
        eq  = d.get("med", CAPITAL)
        p25 = d.get("p25", CAPITAL)
        p75 = d.get("p75", CAPITAL)
        mr  = (eq / prev - 1) * 100
        cr  = _pret(eq)
        print(f"  {m:>4}  EUR{eq:>11,.0f}  [{p25:>8,.0f}-{p75:>8,.0f}]  {mr:>+14.2f}%  {cr:>+10.2f}%")
        prev = eq


def _print_slippage_sensitivity(trades: list[dict], n_sims: int) -> None:
    print("\n" + "=" * 80)
    print("SENSITIVITY ALLO SLIPPAGE — Combinato (risk 0.5%, €100,000)")
    print("=" * 80)
    print(f"  {'Slippage':>9}  {'avg_r net':>10}  {'Rend. semplice/a':>17}  {'Rend. compound med':>19}  {'DD med':>7}  {'ProbP':>5}")
    print("  " + "-" * 72)
    avg_gross = sum(r["pnl_r"] for r in trades) / max(1, len(trades))
    for slip in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]:
        mc = monte_carlo(trades, n_sims=n_sims, risk=0.005, slip=slip, seed=42)
        if mc and mc.get("final"):
            an = mc["avg_net"]
            sa = mc["simple_ann"]
            med = _pret(mc["final"]["med"])
            dd  = mc["dd_med"] * 100
            pp  = mc["final"]["pp"] * 100
            flag = " <- BREAK EVEN" if abs(an) < 0.05 else ""
            print(f"  {slip:>9.2f}R  {an:>+10.3f}R  {sa:>+16.1f}%  {med:>+18.1f}%  {dd:>6.1f}%  {pp:>5.1f}%{flag}")


def _print_risk_sensitivity(trades: list[dict], n_sims: int) -> None:
    print("\n" + "=" * 85)
    print("SENSITIVITY AL RISK% — Combinato (€100,000, 12 mesi, 5000 sims)")
    print("=" * 85)
    print(f"  {'Risk%':>6}  {'Rend. semplice/a':>17}  {'Mediana 12m':>12}  {'Worst 5%':>9}  {'Best 5%':>8}  {'DD med':>7}")
    print("  " + "-" * 70)
    for rp in [0.005, 0.010, 0.015, 0.020]:
        mc = monte_carlo(trades, n_sims=n_sims, risk=rp, slip=0.15, seed=42)
        if mc and mc.get("final"):
            sa  = mc["simple_ann"]
            med = _pret(mc["final"]["med"])
            p5  = _pret(mc["final"]["p5"])
            p95 = _pret(mc["final"]["p95"])
            dd  = mc["dd_med"] * 100
            print(f"  {rp*100:>5.1f}%  {sa:>+16.1f}%  {med:>+11.1f}%  {p5:>+8.1f}%  {p95:>+7.1f}%  {dd:>6.1f}%")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data1h", default="data/val_1h_production.csv")
    parser.add_argument("--data5m", default="data/val_5m_expanded.csv")
    parser.add_argument("--sims",   type=int, default=5000)
    args = parser.parse_args()

    print("\n" + "=" * 95)
    print("SIMULAZIONE MONTE CARLO FINALE — tutti i fix di produzione")
    print(f"  Capital: EUR{CAPITAL:,.0f} | Slippage default: 0.15R | Sims: {args.sims:,}")
    print("=" * 95)

    # Carica dati
    raw_1h, raw_5m = [], []
    for p_str, store in [
        (args.data1h, "1h"),
        ("data/val_1h_large_post_fix.csv", "1h"),
        ("data/val_1h_full.csv", "1h"),
    ]:
        if store == "1h" and not raw_1h:
            p = Path(p_str)
            if p.exists():
                raw_1h = _load_csv(p)
                print(f"  [1h] {p}: {len(raw_1h):,} righe")
                break

    for p_str in [args.data5m, "data/val_5m_full.csv", "data/val_5m_fix3_fix4.csv"]:
        p = Path(p_str)
        if p.exists():
            raw_5m = _load_csv(p)
            print(f"  [5m] {p}: {len(raw_5m):,} righe")
            break

    # Filtri produzione
    r1h = _filt_1h(raw_1h)
    r5m = _filt_5m(raw_5m)
    n1, a1, w1 = _stats(r1h)
    n5, a5, w5 = _stats(r5m)
    print(f"\n  Dopo filtri produzione:")
    print(f"    1h: {n1:,} trade  avg_r={a1:+.3f}R  WR={w1:.1f}%")
    print(f"    5m: {n5:,} trade  avg_r={a5:+.3f}R  WR={w5:.1f}%")

    # ── Fix A: EOD close 1h ──
    r1h_eod, n_on, ab_on, aa_on = _eod_1h(r1h)
    nn, aa, ww = _stats(r1h_eod)
    print(f"\n  EOD close 1h (max {EOD_CUTOFF} barre, interpol. lineare + 0.05R extra):")
    print(f"    Overnight:  {n_on:,} trade ({n_on/max(1,n1)*100:.1f}%)")
    print(f"    avg_r overnight: {ab_on:+.3f}R prima  ->  {aa_on:+.3f}R dopo EOD")
    print(f"    avg_r 1h totale: {a1:+.3f}R prima  ->  {aa:+.3f}R dopo EOD")

    # ── Fix B: TIF=DAY ──
    r1h_tif, rej1 = _tif_day(r1h_eod)
    r5m_tif, rej5 = _tif_day(r5m)
    n1t, a1t, w1t = _stats(r1h_tif)
    n5t, a5t, w5t = _stats(r5m_tif)
    print(f"\n  TIF=DAY filter:")
    print(f"    1h: rimossi {rej1} trade ({rej1/max(1,nn)*100:.1f}%)  ->  {n1t:,} rimasti")
    print(f"    5m: rimossi {rej5} trade ({rej5/max(1,n5)*100:.1f}%)  ->  {n5t:,} rimasti")

    # ── Fix C: Max 5 posizioni ──
    r1h_f, s1 = _max_pos(r1h_tif)
    r5m_f, s5 = _max_pos(r5m_tif)
    comb_all   = r1h_tif + r5m_tif
    r_cf, sc   = _max_pos(comb_all)

    n1f, a1f, w1f = _stats(r1h_f)
    n5f, a5f, w5f = _stats(r5m_f)
    ncf, acf, wcf = _stats(r_cf)
    print(f"\n  Max 5 posizioni simultanee:")
    print(f"    1h (solo):  saltati {s1:,} ({s1/max(1,n1t)*100:.1f}%)  ->  {n1f:,} rimasti")
    print(f"    5m (solo):  saltati {s5:,} ({s5/max(1,n5t)*100:.1f}%)  ->  {n5f:,} rimasti")
    print(f"    Combinato:  saltati {sc:,} ({sc/max(1,len(comb_all))*100:.1f}%)  ->  {ncf:,} rimasti")

    # ── Tabelle impatto ──
    _print_impact_table([
        ("Baseline (filtri prod 1h)",              r1h),
        ("+ EOD close (bar 7, interp. lineare)",   r1h_eod),
        ("+ TIF=DAY filter",                       r1h_tif),
        ("+ Max 5 posizioni (solo 1h)",            r1h_f),
    ], "TABELLA IMPATTO SINGOLI FIX — 1h")

    _print_impact_table([
        ("Baseline (filtri prod 5m)",              r5m),
        ("+ TIF=DAY filter",                       r5m_tif),
        ("+ Max 5 posizioni (solo 5m)",            r5m_f),
        ("Combinato (1h+5m, max 5 pos condiviso)", r_cf),
    ], "TABELLA IMPATTO SINGOLI FIX — 5m + Combinato")

    # ── Distribuzione per pattern (stato finale) ──
    _print_per_pattern(r1h_f,  "1h eseguiti")
    _print_per_pattern(r5m_f,  "5m eseguiti")

    # ── Monte Carlo ──
    print(f"\n  Avvio Monte Carlo ({args.sims:,} sims x 4 scenari x 3 TF)...")

    # Scenari per la curva mensile e la tabella principale: risk 0.5% (interpretabile)
    mc_1h_05   = monte_carlo(r1h_f,  n_sims=args.sims, risk=0.005, slip=0.15, oos_frac=1.0, seed=42)
    mc_5m_05   = monte_carlo(r5m_f,  n_sims=args.sims, risk=0.005, slip=0.15, oos_frac=1.0, seed=42)
    mc_cf_05   = monte_carlo(r_cf,   n_sims=args.sims, risk=0.005, slip=0.15, oos_frac=1.0, seed=42)

    # Scenario conservativo: OOS de-rate 40% + slippage 0.30R
    mc_cf_cons = monte_carlo(r_cf,   n_sims=args.sims, risk=0.005, slip=0.30, oos_frac=0.40, seed=42)

    dyrs_1h = _data_years(r1h_f)
    dyrs_5m = _data_years(r5m_f)

    print("\n" + "=" * 95)
    print("MONTE CARLO FINALE — EUR100,000 | risk 0.5% | slippage 0.15R | 5000 sims | 12 mesi")
    print("  (risk 0.5% = EUR500/trade = 2% del capitale per la colonna 'rendimento semplice/a')")
    print("=" * 95)
    print(f"  {'Scenario':<15}  {'Trade/anno':>10}  {'avg_r net':>9}  {'Rend.sem./a':>12}  {'Mediana 12m':>12}  {'Worst 5%':>9}  {'DD med':>7}  {'ProbP':>6}")
    print("  " + "-" * 90)
    for lbl, mc in [("Solo 1h", mc_1h_05), ("Solo 5m", mc_5m_05), ("Combinato", mc_cf_05)]:
        if mc:
            _mc_row(mc, lbl)

    # Scenario conservativo
    print("\n  -- Scenario conservativo (edge al 40%, slippage 0.30R) --")
    if mc_cf_cons:
        _mc_row(mc_cf_cons, "Conservativo")

    # ── Nota metodologica ──
    print("""
  NOTE METODOLOGICHE:
    * 'Rendimento semplice/a' = n_trade/anno x avg_r_netto x risk (non composto).
      E' la stima di primo ordine, indipendente dalla frequenza di compounding.
    * 'Mediana 12m' e' il risultato COMPOSTO (fixed-fractional) su 5000 sims.
      Con alte frequenze di trading il compounding e' molto sensibile all'edge:
      small positive edge x many trades = geometric growth.
    * Dati IN-SAMPLE (backtest). OOS degradation media storica: 40-85% dell'edge IS.
      Il breakeven slippage (vedi tabella sotto) e' la misura piu' robusta del margine.
    * Scenario conservativo: edge ridotto al 40% di IS + slippage 0.30R.
      Rappresenta un paper trading con esecuzione mediocre e 60% di degradazione.
""")

    # ── Curva mensile (risk 0.5%, scenario conservativo per interpretabilita') ──
    _print_equity_curve(mc_cf_cons, "Combinato conservativo (edge 40%, slip 0.30R)")

    # ── Sensitivity slippage ──
    _print_slippage_sensitivity(r_cf, args.sims)

    # ── Sensitivity risk% ──
    _print_risk_sensitivity(r_cf, args.sims)

    # ── Riepilogo ──
    be_1h = sum(r["pnl_r"] for r in r1h_f) / max(1, len(r1h_f))
    be_5m = sum(r["pnl_r"] for r in r5m_f) / max(1, len(r5m_f))
    be_cf = sum(r["pnl_r"] for r in r_cf)  / max(1, len(r_cf))
    print("\n" + "=" * 95)
    print("RIEPILOGO — NUMERI DEFINITIVI DEL SISTEMA (dopo tutti i fix)")
    print("=" * 95)
    print(f"  Dataset 1h: {n1:,} trade prod | {dyrs_1h:.1f} anni | {n1/dyrs_1h:.0f} trade/anno")
    print(f"  Dataset 5m: {n5:,} trade prod | {dyrs_5m:.1f} anni | {n5/dyrs_5m:.0f} trade/anno")
    print()
    print(f"  Trade ESEGUITI (EOD+TIF+MaxPos):")
    print(f"    1h: {n1f:,}  ({n1f/dyrs_1h:.0f}/anno)  avg_r={a1f:+.3f}R  WR={w1f:.1f}%  BE slippage={be_1h:.3f}R")
    print(f"    5m: {n5f:,}  ({n5f/dyrs_5m:.0f}/anno)  avg_r={a5f:+.3f}R  WR={w5f:.1f}%  BE slippage={be_5m:.3f}R")
    print(f"    Combined: {ncf:,}  ({ncf/max(dyrs_1h,dyrs_5m):.0f}/anno)  avg_r={acf:+.3f}R  WR={wcf:.1f}%  BE slippage={be_cf:.3f}R")
    print()
    print(f"  Proiezione 12 mesi — Scenario teorico (risk 0.5%, slip 0.15R):")
    if mc_cf_05 and mc_cf_05.get("final"):
        f = mc_cf_05["final"]
        print(f"    Mediana:   EUR{f['med']:>10,.0f}  ({_pret(f['med']):>+.1f}%)")
        print(f"    P25/P75:   EUR{f['p25']:>10,.0f}  /  EUR{f['p75']:>10,.0f}")
        print(f"    Worst 5%:  EUR{f['p5']:>10,.0f}  ({_pret(f['p5']):>+.1f}%)")
        print(f"    DD med:    {mc_cf_05['dd_med']*100:.1f}%  |  DD P95: {mc_cf_05['dd_p95']*100:.1f}%")
        print(f"    Prob. profit: {f['pp']*100:.1f}%")
    print()
    print(f"  Proiezione 12 mesi — Scenario conservativo (risk 0.5%, slip 0.30R, edge 40%):")
    if mc_cf_cons and mc_cf_cons.get("final"):
        f = mc_cf_cons["final"]
        print(f"    Mediana:   EUR{f['med']:>10,.0f}  ({_pret(f['med']):>+.1f}%)")
        print(f"    P25/P75:   EUR{f['p25']:>10,.0f}  /  EUR{f['p75']:>10,.0f}")
        print(f"    Worst 5%:  EUR{f['p5']:>10,.0f}  ({_pret(f['p5']):>+.1f}%)")
        print(f"    DD med:    {mc_cf_cons['dd_med']*100:.1f}%  |  DD P95: {mc_cf_cons['dd_p95']*100:.1f}%")
        print(f"    Prob. profit: {f['pp']*100:.1f}%")
    print("\n" + "=" * 95)


if __name__ == "__main__":
    main()
