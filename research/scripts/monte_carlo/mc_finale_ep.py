#!/usr/bin/env python3
"""
mc_finale_ep.py — Monte Carlo Definitivo con Strategia E+
==========================================================
Tutti i fix di produzione + Strategy E+ (slot separation bidirezionale 3+2,
sfratto del trade 5m piu' vecchio con costo 0.10R).

Uso: python mc_finale_ep.py [--sims N] [--seed S]
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from zoneinfo import ZoneInfo as _ZI
    _TZ_ET = _ZI("America/New_York")
except Exception:
    _TZ_ET = None  # type: ignore[assignment]

# ── Costanti produzione ───────────────────────────────────────────────────────
_PAT_1H  = frozenset({"double_bottom","double_top","macd_divergence_bull",
                       "rsi_divergence_bull","macd_divergence_bear","rsi_divergence_bear",
                       "engulfing_bullish"})
_PAT_5M  = frozenset({"double_top","double_bottom","macd_divergence_bull","macd_divergence_bear"})
_BLOK_5M = frozenset({"SPY","AAPL","MSFT","GOOGL","WMT"})

MAX_RISK_LONG  = 3.0
MAX_RISK_SHORT = 2.0
MAX_STR  = 0.80
MIN_STR  = 0.60
BTE_1H   = 4
BTE_5M   = 3
EOD_BAR  = 7
EOD_SLIP = 0.05    # extra R al momento della chiusura EOD
SLIP_DEF = 0.15    # slippage default per trade
EV_COST  = 0.10    # costo sfratto (5m chiuso anticipatamente, pnl_r = -EV_COST)
SLOTS_1H = 3
SLOTS_5M = 2
MAX_POS  = 5

CAPITAL  = 100_000.0
N_MONTHS = 12
SEED_DEF = 42


# ── Utility ───────────────────────────────────────────────────────────────────

def _et_hm(ts: str) -> tuple[int,int]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        det = dt.astimezone(_TZ_ET) if _TZ_ET else (dt - timedelta(hours=4))
        return det.hour, det.minute
    except Exception:
        return 12,0

def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None

def _load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["pnl_r"]            = float(r["pnl_r"])
                r["risk_pct"]         = float(r.get("risk_pct") or 0)
                r["pattern_strength"] = float(r.get("pattern_strength") or 0)
                r["entry_filled"]     = r.get("entry_filled","False") == "True"
                bte = r.get("bars_to_entry"); r["bars_to_entry"] = int(float(bte)) if bte not in ("","None",None) else None
                bx  = r.get("bars_to_exit");  r["bars_to_exit"]  = int(float(bx))  if bx  not in ("","None",None) else None
                sc  = r.get("screener_score"); r["screener_score"] = int(float(sc)) if sc  not in ("","None",None) else 10
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows

def _years(rows: list[dict]) -> float:
    ts = [_parse_ts(r.get("pattern_timestamp","")) for r in rows]
    ts = [t for t in ts if t]
    return max(0.5, (max(ts)-min(ts)).total_seconds()/86400/365.25) if len(ts)>=2 else 2.5


# ── Filtri produzione ─────────────────────────────────────────────────────────

def _filt_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe")!="1h": continue
        if r.get("pattern_name") not in _PAT_1H: continue
        if r.get("pattern_name")=="engulfing_bullish":
            reg = r.get("market_regime","")
            if reg and reg not in ("bear","neutral"): continue
        h,_ = _et_hm(r.get("pattern_timestamp",""))
        if h==3: continue
        s = r["pattern_strength"]
        if not (MIN_STR <= s < MAX_STR): continue
        rp = r["risk_pct"]; d = r.get("direction","bullish").lower()
        if d=="bullish" and rp>MAX_RISK_LONG: continue
        if d=="bearish" and rp>MAX_RISK_SHORT: continue
        bte = r["bars_to_entry"]
        if bte is None or bte>BTE_1H: continue
        out.append(r)
    return out

def _filt_5m(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe")!="5m": continue
        if r.get("provider")!="alpaca": continue
        if r.get("pattern_name") not in _PAT_5M: continue
        if r.get("symbol","").upper() in _BLOK_5M: continue
        h,_ = _et_hm(r.get("pattern_timestamp",""))
        if h<11: continue
        s = r["pattern_strength"]
        if not (MIN_STR <= s < MAX_STR): continue
        rp = r["risk_pct"]; d = r.get("direction","bullish").lower()
        if d=="bullish" and rp>MAX_RISK_LONG: continue
        if d=="bearish" and rp>MAX_RISK_SHORT: continue
        bte = r["bars_to_entry"]
        if bte is None or bte>BTE_5M: continue
        out.append(r)
    return out

def _eod_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        bx = r.get("bars_to_exit")
        if bx is not None and bx>EOD_BAR:
            row = dict(r); row["pnl_r"] = r["pnl_r"]*(EOD_BAR/bx)-EOD_SLIP; row["bars_to_exit"]=EOD_BAR
            out.append(row)
        else:
            out.append(r)
    return out

def _tif_day(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        h,m = _et_hm(r.get("pattern_timestamp",""))
        tf  = r.get("timeframe","1h"); bte = r.get("bars_to_entry")
        if bte is None: out.append(r); continue
        rem = max(0,16-h) if tf=="1h" else max(0,(960-h*60-m)//5)
        if bte<=rem: out.append(r)
    return out


# ── Preparazione trade: entry/exit time ───────────────────────────────────────

def _compute_times(r: dict) -> tuple[datetime|None, datetime|None]:
    ts = _parse_ts(r.get("pattern_timestamp",""))
    if not ts: return None,None
    bte = r.get("bars_to_entry") or 1
    bx  = r.get("bars_to_exit")  or EOD_BAR
    tf  = r.get("timeframe","1h")
    dur = timedelta(hours=1) if tf=="1h" else timedelta(minutes=5)
    e = ts + bte*dur
    return e, e + bx*dur


# ── Strategy E+: slot separation bidirezionale con sfratto ───────────────────

def _count(active: list[dict]) -> tuple[int,int,int,int]:
    n1h1 = sum(1 for a in active if a.get("timeframe","5m")=="1h" and a["slot"]=="1h_prio")
    n5m1 = sum(1 for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="1h_prio")
    n1h5 = sum(1 for a in active if a.get("timeframe","5m")=="1h" and a["slot"]=="5m")
    n5m5 = sum(1 for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="5m")
    return n1h1,n5m1,n1h5,n5m5

def _expire(active: list[dict], t: datetime) -> list[dict]:
    return [a for a in active if a["exit_time"]>t]

def _simulate_fifo(trades: list[dict], max_pos: int=MAX_POS) -> list[dict]:
    """FIFO semplice — usato per solo 1h e solo 5m."""
    done, active = [], []
    for t in trades:
        entry,exit_ = _compute_times(t)
        if entry is None: continue
        active = [a for a in active if a["exit_time"]>entry]
        if len(active)<max_pos:
            active.append({**t,"exit_time":exit_})
            done.append(t)
    return done

def _simulate_ep(trades: list[dict],
                 ev_cost: float = EV_COST) -> list[dict]:
    """
    Strategy E+: slot separation bidirezionale 3+2.
    Ritorna il pool completo: trade naturali + trade sfrattati (pnl_r=-ev_cost).
    """
    pool, active = [], []
    for t in trades:
        entry,exit_ = _compute_times(t)
        if entry is None: continue
        active = _expire(active, entry)
        n1h1,n5m1,n1h5,n5m5 = _count(active)
        n1hprio_free = SLOTS_1H - n1h1 - n5m1
        n5m_free     = SLOTS_5M - n1h5 - n5m5
        tf = t.get("timeframe","5m").strip().lower()

        if tf=="1h":
            if n1hprio_free>0:
                slot="1h_prio"
            elif n5m_free>0:
                slot="5m"
            elif n5m1>0:
                # Sfratta il 5m piu' vecchio dallo slot 1h_prio
                cands = [a for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="1h_prio"]
                oldest = min(cands, key=lambda a: a["entry_time"])
                active.remove(oldest)
                evicted = dict(oldest); evicted["pnl_r"]=-ev_cost
                pool.append(evicted)
                slot="1h_prio"
            else:
                continue  # skip
        else:  # 5m
            if n5m_free>0:
                slot="5m"
            elif n1hprio_free>0:
                slot="1h_prio"
            else:
                continue  # skip

        entry_rec = {**t,"entry_time":entry,"exit_time":exit_,"slot":slot}
        active.append(entry_rec)
        pool.append(t)  # usa il pnl_r originale del dataset

    return pool


# ── Monte Carlo Engine (numpy) ────────────────────────────────────────────────

def _poisson_scalar(rng_py, lam: float) -> int:
    """Poisson tramite algoritmo di Knuth per lambda <= 60."""
    import random as _r
    if lam<=0: return 0
    if lam>60: return max(0, int(round(lam + math.sqrt(lam)*rng_py.gauss(0,1))))
    L = math.exp(-lam); k=0; p=1.0
    while p>L: k+=1; p*=rng_py.random()
    return k-1

def run_mc(
    pool_pnl:     "np.ndarray",
    monthly_rate: float,
    *,
    n_sims:  int,
    capital: float,
    risk:    float,
    slip:    float,
    edge:    float = 1.0,
    seed:    int   = SEED_DEF,
) -> tuple["np.ndarray","np.ndarray"]:
    """
    Monte Carlo fixed-fractional su N_MONTHS mesi.

    Ritorna:
      equity_curves: (n_sims, N_MONTHS) — equity alla fine di ogni mese
      max_drawdowns: (n_sims,)          — max drawdown % per ogni sim

    edge: riduzione dell'edge (0.5 = edge dimezzato, varianza invariata).
      pnl_r_eff = pnl_r - pool_mean * (1 - edge) - slip
    """
    rng_np  = np.random.default_rng(seed)
    import random as _py_rng
    rng_py  = _py_rng.Random(seed)

    pool_mean = float(pool_pnl.mean())

    equity_curves = np.zeros((n_sims, N_MONTHS))
    max_drawdowns = np.zeros(n_sims)

    for sim in range(n_sims):
        month_counts = np.array([_poisson_scalar(rng_py, monthly_rate) for _ in range(N_MONTHS)])
        n_total = int(month_counts.sum())

        if n_total>0:
            raw  = pool_pnl[rng_np.integers(0, len(pool_pnl), size=n_total)]
            # Applica edge degradation e slippage
            eff  = raw - pool_mean*(1.0-edge) - slip
            facs = 1.0 + eff * risk
            cum  = capital * np.cumprod(facs)

            # Drawdown su tutta la path
            with_start = np.concatenate([[capital], cum])
            run_max    = np.maximum.accumulate(with_start)
            dds        = 1.0 - with_start/run_max
            max_drawdowns[sim] = float(dds.max())

            # Equity a fine mese
            bounds = np.cumsum(month_counts)
            prev   = capital
            for m in range(N_MONTHS):
                b = int(bounds[m])
                equity_curves[sim,m] = float(cum[b-1]) if b>0 else prev
                prev = equity_curves[sim,m]
        else:
            equity_curves[sim] = capital

    return equity_curves, max_drawdowns


def _mc_stats(equity_curves: "np.ndarray", max_dds: "np.ndarray", capital: float) -> dict:
    final = equity_curves[:,-1]
    return {
        "med12m_pct": (np.percentile(final,50)/capital-1)*100,
        "p5_pct":     (np.percentile(final,5)/capital-1)*100,
        "p25_pct":    (np.percentile(final,25)/capital-1)*100,
        "p75_pct":    (np.percentile(final,75)/capital-1)*100,
        "p95_pct":    (np.percentile(final,95)/capital-1)*100,
        "dd_med":     float(np.percentile(max_dds,50))*100,
        "dd_p95":     float(np.percentile(max_dds,95))*100,
        "prob_profit":float(np.mean(final>capital))*100,
        "equity_med": np.percentile(equity_curves,50,axis=0),  # (N_MONTHS,)
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not HAS_NUMPY:
        print("ERRORE: numpy non installato. Installa con: pip install numpy")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=SEED_DEF)
    args = parser.parse_args()
    N_SIMS = args.sims
    SEED   = args.seed

    base = Path(__file__).parent
    p1h  = base/"data"/"val_1h_production.csv"
    p5m  = base/"data"/"val_5m_expanded.csv"

    print("Caricamento e filtri...")
    raw1h = _load(p1h); raw5m = _load(p5m)
    f1h   = _tif_day(_eod_1h(_filt_1h(raw1h)))
    f5m   = _tif_day(_filt_5m(raw5m))
    years = _years(f1h + f5m)
    print(f"  1h filtrati: {len(f1h):,}  |  5m filtrati: {len(f5m):,}  |  {years:.2f} anni")

    # ── Simulazioni slot ──────────────────────────────────────────────────────
    print("Simulazione E+ (slot 3+2, costo sfratto 0.10R)...")
    combined_sorted = sorted(f1h+f5m, key=lambda r:(
        _parse_ts(r.get("pattern_timestamp","")) or datetime.min.replace(tzinfo=timezone.utc),
        -int(r.get("screener_score",10))
    ))

    pool_1h   = _simulate_fifo([r for r in combined_sorted if r.get("timeframe")=="1h"], max_pos=MAX_POS)
    pool_5m   = _simulate_fifo([r for r in combined_sorted if r.get("timeframe")=="5m"], max_pos=MAX_POS)
    pool_comb = _simulate_ep(combined_sorted, ev_cost=EV_COST)

    def _pnl_arr(pool): return np.array([r["pnl_r"] for r in pool], dtype=float)

    pnl_1h   = _pnl_arr(pool_1h)
    pnl_5m   = _pnl_arr(pool_5m)
    pnl_comb = _pnl_arr(pool_comb)

    yr_1h   = len(pool_1h)   / years
    yr_5m   = len(pool_5m)   / years
    yr_comb = len(pool_comb) / years

    mr_1h   = yr_1h   / 12
    mr_5m   = yr_5m   / 12
    mr_comb = yr_comb / 12

    def _avg_net(arr, slip=SLIP_DEF): return float(arr.mean()) - slip
    def _wr(arr):     return float((arr>0).mean())*100

    print(f"  Pool 1h:   {len(pool_1h):,}  ({yr_1h:.0f}/a)  avg_r_gross={float(pnl_1h.mean()):+.3f}R")
    print(f"  Pool 5m:   {len(pool_5m):,}  ({yr_5m:.0f}/a)  avg_r_gross={float(pnl_5m.mean()):+.3f}R")
    print(f"  Pool comb: {len(pool_comb):,}  ({yr_comb:.0f}/a)  avg_r_gross={float(pnl_comb.mean()):+.3f}R")

    n_sost = sum(1 for r in pool_comb if r.get("pnl_r")==-EV_COST)
    print(f"  Di cui sfratti: {n_sost:,} ({n_sost/years:.0f}/anno)")

    # ── Tabella principale ────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"TABELLA PRINCIPALE — €{CAPITAL:,.0f} | risk 0.5% | slip {SLIP_DEF}R | {N_SIMS:,} sims | {N_MONTHS} mesi")
    print(f"{'='*100}")
    print(f"  *** DATI IN-SAMPLE: il compounding su 3,000-4,000 trade/anno amplifica l'edge in modo")
    print(f"      non lineare. Mediana/Worst5% sono matematicamente corretti ma non realizzabili. ***")
    print(f"  *** Usa 'Rend.semplice/a' come stima di I ordine; 'Scenario Conservativo' per il realismo. ***\n")

    RISK_BASE = 0.005  # 0.5%
    hdr = (f"  {'Scenario':<22}  {'Trade/a':>7}  {'avg_r(N)':>9}  {'Rend.sem.':>10}  "
           f"{'Med12m':>10}  {'Worst5%':>10}  {'Best5%':>10}  {'DDmed':>7}  {'DDp95':>7}  {'ProbP':>7}")
    print(hdr); print("  "+"-"*(len(hdr)-2))

    main_runs = [
        ("Solo 1h (E+)",   pnl_1h,   mr_1h),
        ("Solo 5m (E+)",   pnl_5m,   mr_5m),
        ("Combinato (E+)", pnl_comb, mr_comb),
    ]
    main_stats = {}
    for label, pnl, mr in main_runs:
        eq, dd = run_mc(pnl, mr, n_sims=N_SIMS, capital=CAPITAL, risk=RISK_BASE, slip=SLIP_DEF, seed=SEED)
        s = _mc_stats(eq, dd, CAPITAL)
        an = float(pnl.mean())-SLIP_DEF
        rend_s = (len(pnl)/years) * an * RISK_BASE * 100
        print(f"  {label:<22}  {len(pnl)/years:>7.0f}  {an:>+9.3f}R  {rend_s:>+9.1f}%  "
              f"{s['med12m_pct']:>+9.0f}%  {s['p5_pct']:>+9.0f}%  {s['p95_pct']:>+9.0f}%  "
              f"{s['dd_med']:>6.1f}%  {s['dd_p95']:>6.1f}%  {s['prob_profit']:>6.1f}%")
        main_stats[label] = s

    # ── Sensitivity Risk% ─────────────────────────────────────────────────────
    print(f"\n{'='*85}")
    print(f"SENSITIVITY RISK% — Combinato E+  |  slip={SLIP_DEF}R  |  {N_SIMS:,} sims")
    print(f"{'='*85}")
    print(f"  {'Risk%':>6}  {'Trade/a':>7}  {'avg_r(N)':>9}  {'Med12m':>10}  "
          f"{'Worst5%':>10}  {'DDmed':>7}  {'DDp95':>7}")
    print("  "+"-"*72)
    risk_runs = {}
    for r_pct in [0.005, 0.010, 0.015, 0.020]:
        eq, dd = run_mc(pnl_comb, mr_comb, n_sims=N_SIMS, capital=CAPITAL, risk=r_pct, slip=SLIP_DEF, seed=SEED)
        s = _mc_stats(eq, dd, CAPITAL)
        risk_runs[r_pct] = (eq, dd, s)
        print(f"  {r_pct*100:>5.1f}%  {yr_comb:>7.0f}  {_avg_net(pnl_comb):>+9.3f}R  "
              f"{s['med12m_pct']:>+9.0f}%  {s['p5_pct']:>+9.0f}%  "
              f"{s['dd_med']:>6.1f}%  {s['dd_p95']:>6.1f}%")

    # ── Equity curve mensile (combinato, 1% risk) ─────────────────────────────
    print(f"\n{'='*80}")
    print(f"CURVA EQUITY MENSILE — Combinato E+ | €{CAPITAL:,.0f} | 1% risk | mediana 5000 sims")
    print(f"{'='*80}")
    eq_1pct, dd_1pct = risk_runs[0.010][0], risk_runs[0.010][1]
    eq_med = np.percentile(eq_1pct, 50, axis=0)
    eq_p25 = np.percentile(eq_1pct, 25, axis=0)
    eq_p75 = np.percentile(eq_1pct, 75, axis=0)

    print(f"  {'Mese':>4}  {'Equity med':>14}  {'P25-P75':>26}  "
          f"{'Prof.mese':>12}  {'Prof.cum%':>10}")
    print("  "+"-"*74)
    prev = CAPITAL
    for m in range(N_MONTHS):
        em = eq_med[m]; e25 = eq_p25[m]; e75 = eq_p75[m]
        delta_m   = em - prev
        cum_pct   = (em/CAPITAL-1)*100
        print(f"  {m+1:>4}  EUR{em:>11,.0f}  [{e25:>9,.0f}-{e75:>9,.0f}]  "
              f"EUR{delta_m:>+9,.0f}  {cum_pct:>+9.1f}%")
        prev = em

    # Profitto mensile medio in EUR
    med_monthly_eur_1pct  = float(np.median(np.diff(np.concatenate([[CAPITAL],eq_med]))))
    eq_05pct = np.percentile(risk_runs[0.005][0], 50, axis=0)
    med_monthly_eur_05pct = float(np.median(np.diff(np.concatenate([[CAPITAL],eq_05pct]))))

    print(f"\n  PROFITTO MENSILE MEDIO (mediana 12 mesi, mediana 5000 sims):")
    print(f"    1.0% risk: EUR {med_monthly_eur_1pct:>+,.0f}/mese")
    print(f"    0.5% risk: EUR {med_monthly_eur_05pct:>+,.0f}/mese")

    # ── Sensitivity Slippage ──────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"SENSITIVITY SLIPPAGE — Combinato E+ | 1% risk | {N_SIMS:,} sims")
    print(f"{'='*80}")
    print(f"  {'Slip':>7}  {'avg_r(N)':>9}  {'Rend.sem.':>10}  {'Med12m':>10}  {'ProbP':>7}  {'Break-even'}")
    print("  "+"-"*66)
    be_found = False
    for slip in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]:
        an = float(pnl_comb.mean()) - slip
        rend_s = yr_comb * an * 0.01 * 100
        eq, dd = run_mc(pnl_comb, mr_comb, n_sims=N_SIMS, capital=CAPITAL, risk=0.01, slip=slip, seed=SEED)
        s = _mc_stats(eq, dd, CAPITAL)
        be_str = "  <- BREAK EVEN" if abs(an)<0.02 and not be_found else \
                 ("  <- oltre BE" if an<0 and not be_found else "")
        if an<0 and not be_found: be_found=True
        print(f"  {slip:>6.2f}R  {an:>+9.3f}R  {rend_s:>+9.1f}%  "
              f"{s['med12m_pct']:>+9.0f}%  {s['prob_profit']:>6.1f}%{be_str}")

    # ── Scenario conservativo: edge degradation ───────────────────────────────
    print(f"\n{'='*90}")
    print(f"SCENARIO CONSERVATIVO (edge degradation) — Combinato E+ | 1% risk | slip={SLIP_DEF}R | {N_SIMS:,} sims")
    print(f"{'='*90}")
    print(f"  Formula: pnl_r_eff = pnl_r - mean_gross*(1-edge_frac) - slip  (varianza invariata)")
    print(f"  {'Edge':>7}  {'avg_r(N)':>9}  {'Rend.sem.':>10}  {'Med12m':>10}  {'Worst5%':>10}  {'ProbP':>7}")
    print("  "+"-"*66)
    pool_mean_g = float(pnl_comb.mean())
    for edge_frac in [1.00, 0.75, 0.50, 0.25]:
        an = pool_mean_g*edge_frac - SLIP_DEF
        rend_s = yr_comb * an * 0.01 * 100
        eq, dd = run_mc(pnl_comb, mr_comb, n_sims=N_SIMS, capital=CAPITAL,
                        risk=0.01, slip=SLIP_DEF, edge=edge_frac, seed=SEED)
        s = _mc_stats(eq, dd, CAPITAL)
        print(f"  {edge_frac:>6.0%}  {an:>+9.3f}R  {rend_s:>+9.1f}%  "
              f"{s['med12m_pct']:>+9.0f}%  {s['p5_pct']:>+9.0f}%  {s['prob_profit']:>6.1f}%")

    # ── Numeri concreti in EUR ────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"NUMERI CONCRETI — €{CAPITAL:,.0f} | 1% risk | Combinato E+")
    print(f"{'='*80}")

    eq_1pct_stats = _mc_stats(eq_1pct, dd_1pct, CAPITAL)
    med_final  = float(np.percentile(eq_1pct[:,-1], 50))
    p5_final   = float(np.percentile(eq_1pct[:,-1], 5))
    dd_med_eur = CAPITAL * eq_1pct_stats["dd_med"] / 100
    dd_p95_eur = CAPITAL * eq_1pct_stats["dd_p95"] / 100

    # Monthly profit distribution
    monthly_profits_med = np.diff(np.concatenate([[CAPITAL], eq_med]))
    med_monthly = float(np.median(monthly_profits_med))
    med_weekly  = med_monthly * 5/20
    med_daily   = med_monthly / 20

    print(f"\n  SCENARIO TEORICO (IS) — usare come upper bound:")
    print(f"    Al giorno (mediano):        EUR {med_daily:>+,.0f}")
    print(f"    Alla settimana (mediana):   EUR {med_weekly:>+,.0f}")
    print(f"    Al mese (mediana):          EUR {med_monthly:>+,.0f}")
    print(f"    In 12 mesi (mediana):       EUR {med_final-CAPITAL:>+,.0f}  ({eq_1pct_stats['med12m_pct']:+.0f}%)")
    print(f"    In 12 mesi (worst 5%):      EUR {p5_final-CAPITAL:>+,.0f}  ({eq_1pct_stats['p5_pct']:+.0f}%)")
    print(f"    Drawdown atteso:            EUR {dd_med_eur:>,.0f}  ({eq_1pct_stats['dd_med']:.1f}%)  [med]")
    print(f"    Drawdown p95:               EUR {dd_p95_eur:>,.0f}  ({eq_1pct_stats['dd_p95']:.1f}%)  [stress]")

    # Scenario conservativo 50% edge
    eq_c50, dd_c50 = run_mc(pnl_comb, mr_comb, n_sims=N_SIMS, capital=CAPITAL,
                             risk=0.01, slip=SLIP_DEF, edge=0.50, seed=SEED)
    s50 = _mc_stats(eq_c50, dd_c50, CAPITAL)
    med_c50 = float(np.percentile(eq_c50[:,-1],50))
    p5_c50  = float(np.percentile(eq_c50[:,-1],5))
    dd_c50_eur = CAPITAL * s50["dd_med"] / 100
    eq_c50_med_monthly = np.diff(np.concatenate([[CAPITAL], np.percentile(eq_c50,50,axis=0)]))
    med_monthly_c50 = float(np.median(eq_c50_med_monthly))

    print(f"\n  SCENARIO CONSERVATIVO (50% edge, slip={SLIP_DEF}R) — usare come stima realistica:")
    print(f"    avg_r netto:                {pool_mean_g*0.50-SLIP_DEF:>+.3f}R")
    print(f"    Al mese (mediana):          EUR {med_monthly_c50:>+,.0f}")
    print(f"    In 12 mesi (mediana):       EUR {med_c50-CAPITAL:>+,.0f}  ({s50['med12m_pct']:+.0f}%)")
    print(f"    In 12 mesi (worst 5%):      EUR {p5_c50-CAPITAL:>+,.0f}  ({s50['p5_pct']:+.0f}%)")
    print(f"    Drawdown atteso:            EUR {dd_c50_eur:>,.0f}  ({s50['dd_med']:.1f}%)")
    print(f"    Prob. profitto 12m:         {s50['prob_profit']:.1f}%")

    # ── Riepilogo finale ──────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"RIEPILOGO NUMERI DEFINITIVI — SISTEMA COMPLETO (tutti i 28 fix + E+)")
    print(f"{'='*80}")
    print(f"\n  Dataset: {len(f1h):,} trade 1h  |  {len(f5m):,} trade 5m  |  {years:.2f} anni")
    print(f"\n  Pool finale dopo slot E+ ({SLOTS_1H}+{SLOTS_5M}, costo sfratto -{EV_COST}R):")
    print(f"    Combinato: {len(pool_comb):,} trade  ({yr_comb:.0f}/anno)")
    print(f"    avg_r lordo:   {float(pnl_comb.mean()):+.3f}R")
    print(f"    avg_r netto:   {_avg_net(pnl_comb):+.3f}R  (slip={SLIP_DEF}R)")
    print(f"    WR%:           {_wr(pnl_comb):.1f}%")
    print(f"    BE slippage:   {float(pnl_comb.mean()):+.3f}R")
    print(f"    Sfratti/anno:  {n_sost/years:.0f}")
    print(f"\n  Rendimento semplice annuo (non composto):")
    print(f"    0.5% risk: {yr_comb * _avg_net(pnl_comb) * 0.005 * 100:+.1f}%/anno")
    print(f"    1.0% risk: {yr_comb * _avg_net(pnl_comb) * 0.010 * 100:+.1f}%/anno")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
