"""
analisi_v2_mfe_mae_volume.py
============================
Step 3 — Analisi completa con MFE, MAE, Volume sul dataset val_5m_v2.csv

Config TRIPLO: ALPHA=15:xx ET tutto, MIDDAY_F=11-14 ET filtrato
6 pattern validati: double_bottom/top, macd/rsi divergence bull/bear
(engulfing_bullish escluso dal TRIPLO in quanto pattern non selezionato)

Sezioni:
  3A. Volume come filtro (vol_rel fascia)
  3B. MFE distribuzione
  3C. Trailing stop REALE con MFE dati
  3D. TP ottimale REALE con MFE
  3E. MAE distribuzione
  3F. Stop ottimale REALE con MAE
  3G. MIN_RISK_PCT ottimale
  3H. Combinazione ottimale finale + Monte Carlo

Uso:
  python analisi_v2_mfe_mae_volume.py
  python analisi_v2_mfe_mae_volume.py --dataset data/val_5m_v2.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ─── Costanti ────────────────────────────────────────────────────────────────
COST_RATE = 0.0015          # 0.15% round-trip (già in pnl_r)
ALPHA_HOUR = 15             # 15:00-15:59 ET
MIDDAY_HOURS = {11, 12, 13, 14}

# 6 pattern TRIPLO validati (escludo engulfing_bullish che trascina il sistema)
TRIPLO_6_PATTERNS = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
TRIPLO_ALL_PATTERNS = TRIPLO_6_PATTERNS | {"engulfing_bullish"}

# Parametri sistema corrente
MIN_RISK_PCT_CURRENT = 0.30  # % attuale

# ─── Utility ─────────────────────────────────────────────────────────────────

def _ny_hour(ts: str) -> int | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        offset = 4 if 3 <= dt.month <= 10 else 5
        return (dt - timedelta(hours=offset)).hour
    except Exception:
        return None


def _fascia(r: dict) -> str:
    h = _ny_hour(r.get("pattern_timestamp", ""))
    if h == ALPHA_HOUR:
        return "ALPHA"
    if h in MIDDAY_HOURS:
        return "MIDDAY_F"
    return "OTHER"


def _cost_r(ep: float, sp: float) -> float:
    risk = abs(ep - sp)
    return COST_RATE * ep / risk if risk > 1e-9 and ep > 0 else 0.0


def _wilson(w: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    p, z = w/n, 1.96
    c = (p + z**2/(2*n)) / (1 + z**2/n)
    m = z * ((p*(1-p)/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)
    return round(max(0.0, c-m)*100, 1), round(min(1.0, c+m)*100, 1)


def _hdr(t: str) -> None:
    print("\n" + "=" * 82)
    print(t)
    print("=" * 82)


def _sep(n: int = 80) -> None:
    print("  " + "-" * n)


def _f(v, fmt="+.4f") -> str:
    return f"{v:{fmt}}R" if v is not None else "    —"


def _stats(rows: list[dict]) -> tuple[int, float, float, float, float]:
    """Ritorna (n, WR%, avg_gross_r, avg_net_r, ci_str)."""
    n = len(rows)
    if n == 0:
        return 0, 0.0, 0.0, 0.0, 0.0
    wins = sum(1 for r in rows if r["_pnl"] > 0)
    wr = wins/n*100
    avg_net = sum(r["_pnl"] for r in rows)/n
    avg_gross = sum(r["_gross"] for r in rows)/n
    return n, wr, avg_gross, avg_net, wins


# ─── Caricamento ─────────────────────────────────────────────────────────────

def load(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Ritorna (all_filled_triplo_all, filled_triplo_6, raw_all)."""
    with path.open(encoding="utf-8") as f:
        raw = list(csv.DictReader(f))

    missing_cols = []
    for col in ["mfe_r", "mae_r", "volume_relative", "pattern_candle_volume"]:
        if col not in (raw[0].keys() if raw else {}):
            missing_cols.append(col)
    if missing_cols:
        print(f"  ERRORE: colonne mancanti nel CSV: {missing_cols}")
        print("  Rigenerare il dataset con build_validation_dataset.py modificato.")
        sys.exit(1)

    def _f_or_none(v: str) -> float | None:
        return float(v) if v not in ("", "None", None) else None

    def _i_or_none(v: str) -> int | None:
        try:
            return int(v) if v not in ("", "None", None) else None
        except Exception:
            return None

    for r in raw:
        r["_filled"] = r["entry_filled"] == "True"
        r["_pnl"] = float(r["pnl_r"])
        r["_ep"] = float(r.get("entry_price") or 0)
        r["_sp"] = float(r.get("stop_price") or 0)
        r["_cost"] = _cost_r(r["_ep"], r["_sp"])
        r["_gross"] = r["_pnl"] + r["_cost"]
        r["_risk_pct"] = float(r.get("risk_pct") or 0)
        r["_dir"] = r.get("direction", "bullish")
        r["_fascia"] = _fascia(r)
        r["_mfe"] = _f_or_none(r.get("mfe_r", ""))
        r["_mae"] = _f_or_none(r.get("mae_r", ""))
        r["_vol_rel"] = _f_or_none(r.get("volume_relative", ""))
        r["_vol"] = _f_or_none(r.get("pattern_candle_volume", ""))
        r["_next_open"] = _f_or_none(r.get("next_candle_open", ""))
        r["_bars_to_mfe"] = _i_or_none(r.get("bars_to_mfe", ""))

    all_filled = [r for r in raw if r["_filled"]]
    triplo_all = [r for r in all_filled if r["_fascia"] in ("ALPHA", "MIDDAY_F")]
    triplo_6 = [r for r in triplo_all if r["pattern_name"] in TRIPLO_6_PATTERNS]

    print(f"\nDataset: {len(raw)} righe | Filled totale: {len(all_filled)}")
    print(f"TRIPLO (tutti): {len(triplo_all)} | TRIPLO (6 pattern): {len(triplo_6)}")
    alpha_6 = sum(1 for r in triplo_6 if r["_fascia"]=="ALPHA")
    mid_6   = sum(1 for r in triplo_6 if r["_fascia"]=="MIDDAY_F")
    print(f"  ALPHA 6-pat: {alpha_6}  |  MIDDAY_F 6-pat: {mid_6}")
    n_mfe = sum(1 for r in triplo_6 if r["_mfe"] is not None)
    n_vol = sum(1 for r in triplo_6 if r["_vol_rel"] is not None)
    print(f"  Con MFE: {n_mfe}/{len(triplo_6)} ({n_mfe/max(1,len(triplo_6))*100:.1f}%)")
    print(f"  Con vol_rel: {n_vol}/{len(triplo_6)} ({n_vol/max(1,len(triplo_6))*100:.1f}%)")

    return triplo_all, triplo_6, raw


# ════════════════════════════════════════════════════════════════════════════
# 3A. VOLUME
# ════════════════════════════════════════════════════════════════════════════

def sect_3a_volume(filled: list[dict]) -> None:
    _hdr("3A. VOLUME COME FILTRO (6 pattern TRIPLO)")
    print("  vol_rel = pattern_candle_volume / SMA20(volume stesso simbolo/timeframe)")
    print("  pnl_r+slip = avg netto (già include 0.15% RT cost)")
    print()

    vol_bins = [
        ("< 0.5  (molto basso)", lambda v: v < 0.5),
        ("0.5-0.75",              lambda v: 0.5 <= v < 0.75),
        ("0.75-1.0 (nella media)",lambda v: 0.75 <= v < 1.0),
        ("1.0-1.5 (sopra media)", lambda v: 1.0 <= v < 1.5),
        ("1.5-2.0",               lambda v: 1.5 <= v < 2.0),
        ("2.0-3.0 (alto)",        lambda v: 2.0 <= v < 3.0),
        "> 3.0 (anomalo)",
    ]
    # Correzione: ultima entry non è lambda, la sistemò qua:
    vol_bins_corrected = [
        ("< 0.5  (molto basso)", lambda v: v < 0.5),
        ("0.5-0.75",              lambda v: 0.5 <= v < 0.75),
        ("0.75-1.0 (nella media)",lambda v: 0.75 <= v < 1.0),
        ("1.0-1.5 (sopra media)", lambda v: 1.0 <= v < 1.5),
        ("1.5-2.0",               lambda v: 1.5 <= v < 2.0),
        ("2.0-3.0 (alto)",        lambda v: 2.0 <= v < 3.0),
        ("> 3.0 (anomalo)",       lambda v: v >= 3.0),
    ]

    has_vol = [r for r in filled if r["_vol_rel"] is not None]
    print(f"  Trade con vol_rel disponibile: {len(has_vol)}/{len(filled)} ({len(has_vol)/max(1,len(filled))*100:.1f}%)")
    print()
    print(f"  {'Fascia vol_rel':25s} {'n':>5} {'WR%':>6} {'avg_r+slip':>11} {'CI 95%':>14} {'Δ vs totale':>12}")
    _sep(78)

    base_net = sum(r["_pnl"] for r in has_vol) / len(has_vol) if has_vol else 0

    for label, flt in vol_bins_corrected:
        sub = [r for r in has_vol if flt(r["_vol_rel"])]
        if not sub:
            print(f"  {label:25s} {'—':>5} {'—':>6} {'—':>11} {'—':>14}")
            continue
        n, wr, avg_g, avg_n, w = _stats(sub)
        clo, chi = _wilson(w, n)
        delta = avg_n - base_net
        mk = " ★" if avg_n > 0.1 else (" ▼" if avg_n < -0.5 else "")
        print(f"  {label:25s} {n:>5} {wr:>5.1f}% {avg_n:>+11.4f}R [{clo:.1f}%-{chi:.1f}%] {delta:>+12.4f}R{mk}")

    # Volume × fascia oraria
    print()
    print("  VOLUME × FASCIA ORARIA:")
    print(f"  {'Fascia vol_rel':25s} {'ALPHA n':>7} {'ALPHA avg+slip':>15} {'MID n':>6} {'MID avg+slip':>13}")
    _sep(78)
    for label, flt in vol_bins_corrected:
        sub_a = [r for r in has_vol if r["_fascia"]=="ALPHA" and flt(r["_vol_rel"])]
        sub_m = [r for r in has_vol if r["_fascia"]=="MIDDAY_F" and flt(r["_vol_rel"])]
        na = len(sub_a); nm = len(sub_m)
        avg_a = sum(r["_pnl"] for r in sub_a)/na if sub_a else 0
        avg_m = sum(r["_pnl"] for r in sub_m)/nm if sub_m else 0
        mk_a = " ★" if avg_a > 0.1 else ""
        mk_m = " ★" if avg_m > 0.1 else ""
        print(f"  {label:25s} {na:>7} {avg_a:>+15.4f}R{mk_a:3s} {nm:>6} {avg_m:>+13.4f}R{mk_m}")

    # Volume × pattern
    print()
    print("  VOLUME × PATTERN (vol basso = vol_rel<1.0 / vol alto = vol_rel>=1.5):")
    print(f"  {'Pattern':30s} {'n_low':>6} {'avg_low':>9} {'n_high':>7} {'avg_high':>10} {'diff':>7}")
    _sep(78)
    by_pat: dict[str, list] = defaultdict(list)
    for r in has_vol:
        by_pat[r["pattern_name"]].append(r)
    for pat in sorted(by_pat.keys()):
        sub = by_pat[pat]
        low = [r for r in sub if r["_vol_rel"] < 1.0]
        high = [r for r in sub if r["_vol_rel"] >= 1.5]
        if not low and not high:
            continue
        avg_l = sum(r["_pnl"] for r in low)/len(low) if low else 0
        avg_h = sum(r["_pnl"] for r in high)/len(high) if high else 0
        diff = avg_h - avg_l
        mk = " ★" if diff > 0.1 else (" ▼" if diff < -0.1 else "")
        print(f"  {pat:30s} {len(low):>6} {avg_l:>+9.4f}R {len(high):>7} {avg_h:>+10.4f}R {diff:>+7.4f}R{mk}")


# ════════════════════════════════════════════════════════════════════════════
# 3B. MFE DISTRIBUZIONE
# ════════════════════════════════════════════════════════════════════════════

def sect_3b_mfe(filled: list[dict]) -> None:
    _hdr("3B. MFE — DISTRIBUZIONE (6 pattern TRIPLO)")
    print("  MFE = Maximum Favorable Excursion in R durante il trade")
    print("  Se MFE >= TP1 → il mercato SI è mosso abbastanza per il TP")
    print()

    has_mfe = [r for r in filled if r["_mfe"] is not None]
    mfe_bins = [
        ("0-0.5R   (quasi nessun movimento)", 0.0, 0.5),
        ("0.5-1.0R",                           0.5, 1.0),
        ("1.0-1.5R",                           1.0, 1.5),
        ("1.5-2.0R (vicino TP1)",              1.5, 2.0),
        ("2.0-3.0R (raggiunge TP1)",           2.0, 3.0),
        ("3.0R+   (raggiunge TP2)",            3.0, 999),
    ]

    print(f"  {'Fascia MFE':35s} {'n':>5} {'%':>5} {'outcome stop%':>14} {'outcome tp%':>11} {'avg_r+slip':>11}")
    _sep(82)
    total = len(has_mfe)

    for label, lo, hi in mfe_bins:
        sub = [r for r in has_mfe if lo <= r["_mfe"] < hi]
        if not sub:
            print(f"  {label:35s} {'—':>5}")
            continue
        n = len(sub)
        pct = n/total*100
        n_stop = sum(1 for r in sub if r["outcome"]=="stop")
        n_tp = sum(1 for r in sub if r["outcome"] in ("tp1","tp2"))
        pct_stop = n_stop/n*100
        pct_tp = n_tp/n*100
        avg_net = sum(r["_pnl"] for r in sub)/n
        print(f"  {label:35s} {n:>5} {pct:>4.1f}%  stop:{pct_stop:>5.1f}% tp:{pct_tp:>5.1f}%  {avg_net:>+11.4f}R")

    # Stats MFE
    mfes = [r["_mfe"] for r in has_mfe]
    mfes_s = sorted(mfes)
    nn = len(mfes_s)
    print()
    print(f"  MFE stats: n={nn} min={min(mfes):.3f} p25={mfes_s[int(0.25*nn)]:.3f} "
          f"p50={mfes_s[int(0.50*nn)]:.3f} p75={mfes_s[int(0.75*nn)]:.3f} max={max(mfes):.3f}")
    pct_reach_1r = sum(1 for v in mfes if v >= 1.0)/nn*100
    pct_reach_2r = sum(1 for v in mfes if v >= 2.0)/nn*100
    pct_reach_3r = sum(1 for v in mfes if v >= 3.0)/nn*100
    print(f"  % trade con MFE >= 1.0R: {pct_reach_1r:.1f}%  >= 2.0R: {pct_reach_2r:.1f}%  >= 3.0R: {pct_reach_3r:.1f}%")

    # MFE per outcome
    print()
    print("  MFE medio per outcome:")
    for out in ["stop", "tp1", "tp2", "timeout"]:
        sub = [r for r in has_mfe if r["outcome"]==out]
        if sub:
            avg_mfe = sum(r["_mfe"] for r in sub)/len(sub)
            avg_pnl = sum(r["_pnl"] for r in sub)/len(sub)
            print(f"    {out:8s}: n={len(sub):>5}  avg_MFE={avg_mfe:+.3f}R  avg_pnl={avg_pnl:+.3f}R")


# ════════════════════════════════════════════════════════════════════════════
# 3C. TRAILING STOP REALE con MFE
# ════════════════════════════════════════════════════════════════════════════

def sect_3c_trailing(filled: list[dict]) -> None:
    _hdr("3C. TRAILING STOP REALE con MFE (6 pattern TRIPLO)")
    print("  Ora sappiamo QUALI trade STOP avevano MFE >= trigger (dal dataset)")
    print("  Trail to BE: se MFE >= trigger, lo stop sale a 0 (break-even)")
    print("  Ipotesi: dopo trigger, se outcome=stop → si è chiuso a BE (0R net) invece di -1.5R")
    print()

    has_mfe = [r for r in filled if r["_mfe"] is not None]
    n_all = len(has_mfe)
    base_avg = sum(r["_pnl"] for r in has_mfe)/n_all
    base_wr = sum(1 for r in has_mfe if r["_pnl"]>0)/n_all*100
    n_stop = sum(1 for r in has_mfe if r["outcome"]=="stop")

    print(f"  Trade con MFE (base analisi): {n_all}  stop={n_stop}")
    print(f"  Baseline avg+slip={base_avg:+.4f}R  WR={base_wr:.1f}%")
    print()

    configs = [
        ("Stop fisso (baseline)",   None,   None),
        ("Trail BE dopo +0.5R",     0.5,    0.0),
        ("Trail BE dopo +0.75R",    0.75,   0.0),
        ("Trail BE dopo +1.0R",     1.0,    0.0),
        ("Trail +0.5R dopo +1.0R",  1.0,    0.5),
        ("Trail +0.5R dopo +1.5R",  1.5,    0.5),
    ]

    print(f"  {'Config':35s} {'n':>5} {'avg+slip':>10} {'Δ':>8} {'n_salvati':>10} {'n_persi_prem':>13}")
    _sep(82)

    for label, trigger, new_stop_gross in configs:
        if trigger is None:
            print(f"  {label:35s} {n_all:>5} {base_avg:>+10.4f}R {'—':>8} {'0':>10} {'0':>13}")
            continue

        sim_pnls = []
        saved = 0       # stop trades salvati dal trailing
        lost_early = 0  # tp trades chiusi presto dal trailing

        for r in has_mfe:
            pnl = r["_pnl"]
            mfe = r["_mfe"]
            cost = r["_cost"]
            out = r["outcome"]

            # Il trailing si attiva se MFE >= trigger (REALE, dato dal CSV)
            triggered = mfe >= trigger

            if not triggered:
                sim_pnls.append(pnl)
                continue

            # Trailing attivato: nuovo stop a new_stop_gross R (lordo)
            net_new_stop = new_stop_gross - cost * 0.5  # exit cost solo

            if out == "stop":
                # In realtà era stoppato: con trailing avrebbe chiuso a new_stop
                # Se new_stop > stop_price (-1R) → SALVATO
                sim_pnls.append(net_new_stop)
                saved += 1
            elif out in ("tp1", "tp2"):
                # TP hit: il prezzo è andato oltre il trigger E oltre il new_stop
                # Il trailing non si attiva perché il TP è hit prima del pullback
                # MA: se il prezzo era sceso sotto new_stop prima del TP → loss early
                # Conservativo: se MFE >> TP → probabilmente MAE piccolo → non lost
                # Approssimazione: se MAE >= new_stop_gross → potenzialmente lost early
                mae = r["_mae"] if r["_mae"] is not None else 0.0
                if mae >= new_stop_gross and new_stop_gross > 0:
                    # Il prezzo ha toccato new_stop durante il trade → uscita prematura
                    sim_pnls.append(net_new_stop)
                    lost_early += 1
                else:
                    sim_pnls.append(pnl)
            elif out == "timeout":
                # Timeout: il prezzo ha raggiunto trigger ma poi è tornato indietro
                # Se pnl < net_new_stop → il trailing avrebbe migliorato l'exit
                if pnl < net_new_stop:
                    sim_pnls.append(net_new_stop)
                    saved += 1
                else:
                    sim_pnls.append(pnl)
            else:
                sim_pnls.append(pnl)

        avg_sim = sum(sim_pnls)/len(sim_pnls)
        delta = avg_sim - base_avg
        wr_sim = sum(1 for p in sim_pnls if p>0)/len(sim_pnls)*100
        mk = " ★" if delta > 0.02 else (" ▼" if delta < -0.02 else "")
        print(f"  {label:35s} {len(sim_pnls):>5} {avg_sim:>+10.4f}R {delta:>+8.4f}R {saved:>10} {lost_early:>13}{mk}")

    print()
    print("  NOTA: 'n_salvati' = stop trades con MFE >= trigger (ora contati con certezza)")
    print("  'n_persi_prem' = tp trades dove MAE >= new_stop (potrebbero uscire presto)")
    print("  La differenza è il NETTO. Se Δ > 0 → il trailing migliora il sistema.")

    # Breakdown per fascia oraria
    print()
    print("  TRAILING BE dopo +0.75R — ALPHA vs MIDDAY_F:")
    for fascia_label in ["ALPHA", "MIDDAY_F"]:
        sub_f = [r for r in has_mfe if r["_fascia"]==fascia_label]
        if not sub_f: continue
        base_f = sum(r["_pnl"] for r in sub_f)/len(sub_f)
        sim_f = []
        for r in sub_f:
            if r["_mfe"] >= 0.75:
                if r["outcome"] == "stop":
                    sim_f.append(-r["_cost"]*0.5)
                elif r["outcome"]=="timeout" and r["_pnl"] < -r["_cost"]*0.5:
                    sim_f.append(-r["_cost"]*0.5)
                else:
                    sim_f.append(r["_pnl"])
            else:
                sim_f.append(r["_pnl"])
        avg_f = sum(sim_f)/len(sim_f)
        print(f"    {fascia_label:10s}: base={base_f:+.4f}R → trail_BE_0.75={avg_f:+.4f}R  Δ={avg_f-base_f:+.4f}R")


# ════════════════════════════════════════════════════════════════════════════
# 3D. TP OTTIMALE REALE con MFE
# ════════════════════════════════════════════════════════════════════════════

def sect_3d_tp_reale(filled: list[dict]) -> None:
    _hdr("3D. TP OTTIMALE REALE con MFE — quale % dei trade raggiunge ogni livello")
    print("  MFE reale → sappiamo con certezza se il prezzo ha raggiunto ogni TP level")
    print("  'exit qui' = chiudi TUTTI a quel TP (se MFE >= TP → win al TP, altrimenti usa pnl_r)")
    print()

    has_mfe = [r for r in filled if r["_mfe"] is not None]
    n_all = len(has_mfe)

    tp_levels = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

    print(f"  {'TP level':10s} {'% raggiunge':>12} {'avg_r+slip':>12} {'WR%':>6} {'n_win':>6} {'n_loss':>6}")
    _sep(68)

    for tp in tp_levels:
        # Quanti trade hanno MFE >= tp?
        n_reach = sum(1 for r in has_mfe if r["_mfe"] >= tp)
        pct_reach = n_reach/n_all*100

        # Simula: se TP fosse a tp_gross=tp
        sim_pnls = []
        for r in has_mfe:
            if r["outcome"] == "stop":
                sim_pnls.append(r["_pnl"])  # stop invariato
            elif r["_mfe"] >= tp:
                # Prezzo ha raggiunto TP → chiude qui
                sim_pnls.append(tp - r["_cost"])
            else:
                # Non ha raggiunto TP → usa pnl attuale (timeout o TP più basso)
                sim_pnls.append(r["_pnl"])

        avg_net = sum(sim_pnls)/len(sim_pnls)
        n_win = sum(1 for p in sim_pnls if p > 0)
        n_loss = sum(1 for p in sim_pnls if p <= 0)
        wr = n_win/len(sim_pnls)*100
        mk = " ★" if avg_net > 0.05 else ""
        print(f"  {tp:>8.2f}R  {pct_reach:>11.1f}%  {avg_net:>+12.4f}R {wr:>5.1f}%  {n_win:>6}  {n_loss:>6}{mk}")

    # Baseline attuale (sistema con TP1+TP2 combo)
    base_net = sum(r["_pnl"] for r in has_mfe)/n_all
    base_wr = sum(1 for r in has_mfe if r["_pnl"]>0)/n_all*100
    print(f"\n  Baseline attuale (TP1+TP2 combo): avg+slip={base_net:+.4f}R  WR={base_wr:.1f}%")

    # Per ALPHA separatamente
    print()
    print("  ALPHA (15:xx) — TP ottimale:")
    alpha = [r for r in has_mfe if r["_fascia"]=="ALPHA"]
    if alpha:
        na = len(alpha)
        best_tp, best_avg = None, -99.0
        for tp in tp_levels:
            sim = []
            for r in alpha:
                if r["outcome"]=="stop": sim.append(r["_pnl"])
                elif r["_mfe"] >= tp: sim.append(tp - r["_cost"])
                else: sim.append(r["_pnl"])
            avg = sum(sim)/len(sim)
            n_r = sum(1 for r in alpha if r["_mfe"]>=tp)
            print(f"    TP={tp:.2f}R: {avg:>+.4f}R  WR={sum(1 for p in sim if p>0)/na*100:.1f}%  raggiunge={n_r/na*100:.1f}%")
            if avg > best_avg:
                best_avg = avg; best_tp = tp
        print(f"  → TP ottimale ALPHA: {best_tp:.2f}R → {best_avg:+.4f}R")

    print()
    print("  MIDDAY_F (11-14) — TP ottimale:")
    midday = [r for r in has_mfe if r["_fascia"]=="MIDDAY_F"]
    if midday:
        nm = len(midday)
        best_tp, best_avg = None, -99.0
        for tp in tp_levels:
            sim = []
            for r in midday:
                if r["outcome"]=="stop": sim.append(r["_pnl"])
                elif r["_mfe"] >= tp: sim.append(tp - r["_cost"])
                else: sim.append(r["_pnl"])
            avg = sum(sim)/len(sim)
            if avg > best_avg:
                best_avg = avg; best_tp = tp
        print(f"  → TP ottimale MIDDAY_F: {best_tp:.2f}R → {best_avg:+.4f}R")


# ════════════════════════════════════════════════════════════════════════════
# 3E. MAE DISTRIBUZIONE
# ════════════════════════════════════════════════════════════════════════════

def sect_3e_mae(filled: list[dict]) -> None:
    _hdr("3E. MAE — DISTRIBUZIONE (6 pattern TRIPLO)")
    print("  MAE = Maximum Adverse Excursion in R durante il trade")
    print("  Se MAE < 0.3R → il prezzo quasi non scende (stop larghissimo inutilizzato)")
    print()

    has_mae = [r for r in filled if r["_mae"] is not None]
    total = len(has_mae)

    mae_bins = [
        ("0-0.3R   (quasi nessun drawdown)", 0.0, 0.3),
        ("0.3-0.5R",                          0.3, 0.5),
        ("0.5-0.8R",                          0.5, 0.8),
        ("0.8-1.0R (quasi stoppato)",         0.8, 1.0),
        ("1.0-1.5R (stoppato / oltre stop)",  1.0, 1.5),
        ("1.5R+",                             1.5, 999),
    ]

    print(f"  {'Fascia MAE':35s} {'n':>5} {'%':>5} {'stop%':>7} {'tp%':>6} {'avg_r+slip':>11}")
    _sep(80)

    for label, lo, hi in mae_bins:
        sub = [r for r in has_mae if lo <= r["_mae"] < hi]
        if not sub:
            print(f"  {label:35s} {'—':>5}")
            continue
        n = len(sub)
        pct = n/total*100
        n_stop = sum(1 for r in sub if r["outcome"]=="stop")
        n_tp = sum(1 for r in sub if r["outcome"] in ("tp1","tp2"))
        avg_n = sum(r["_pnl"] for r in sub)/n
        print(f"  {label:35s} {n:>5} {pct:>4.1f}%  {n_stop/n*100:>6.1f}%  {n_tp/n*100:>5.1f}%  {avg_n:>+11.4f}R")

    # Casi anomali
    print()
    low_mae_stop = [r for r in has_mae if r["_mae"] < 0.3 and r["outcome"]=="stop"]
    high_mae_tp = [r for r in has_mae if r["_mae"] > 0.8 and r["outcome"] in ("tp1","tp2")]
    print(f"  ANOMALIA 1 — MAE<0.3R E outcome=stop: {len(low_mae_stop)} trade")
    print(f"    → Stop troppo largo (prezzo quasi non scende ma poi crolla sotto stop)")
    print(f"    → Questi trade potrebbero essere catturati da trailing stop più stretto")
    print()
    print(f"  ANOMALIA 2 — MAE>0.8R E outcome=tp: {len(high_mae_tp)} trade")
    print(f"    → Trade 'miracolosi': quasi toccano lo stop poi recuperano al TP")
    if high_mae_tp:
        avg_pnl = sum(r["_pnl"] for r in high_mae_tp)/len(high_mae_tp)
        avg_mfe = sum(r["_mfe"] for r in high_mae_tp if r["_mfe"] is not None)/len(high_mae_tp)
        print(f"    → avg_pnl={avg_pnl:+.3f}R  avg_MFE={avg_mfe:.3f}R")
        print(f"    → Con stop più stretto (0.75×): questi trade sarebbero persi!")

    # MAE per pattern
    print()
    print("  MAE medio per pattern:")
    by_pat: dict[str, list] = defaultdict(list)
    for r in has_mae:
        by_pat[r["pattern_name"]].append(r)
    for pat in sorted(by_pat.keys()):
        sub = by_pat[pat]
        avg_mae = sum(r["_mae"] for r in sub)/len(sub)
        avg_pnl = sum(r["_pnl"] for r in sub)/len(sub)
        print(f"    {pat:30s}: avg_MAE={avg_mae:.3f}R  avg_pnl={avg_pnl:+.3f}R  n={len(sub)}")


# ════════════════════════════════════════════════════════════════════════════
# 3F. STOP OTTIMALE con MAE
# ════════════════════════════════════════════════════════════════════════════

def sect_3f_stop_mae(filled: list[dict]) -> None:
    _hdr("3F. STOP OTTIMALE REALE con MAE (6 pattern TRIPLO)")
    print("  Ora possiamo simulare stop più stretto/largo con precisione:")
    print("  Stop M×: se MAE >= M → stop triggerato (loss = -1R - cost)")
    print("           se MAE <  M → trade continua (usa pnl_r attuale)")
    print()

    has_mae = [r for r in filled if r["_mae"] is not None and r["_mfe"] is not None]
    n_all = len(has_mae)
    base_avg = sum(r["_pnl"] for r in has_mae)/n_all
    base_wr = sum(1 for r in has_mae if r["_pnl"]>0)/n_all*100
    n_stop_base = sum(1 for r in has_mae if r["outcome"]=="stop")

    print(f"  Trade con MAE+MFE: {n_all}  stop={n_stop_base}  base avg+slip={base_avg:+.4f}R")
    print()

    stop_mults = [0.50, 0.75, 1.00, 1.25, 1.50]

    print(f"  {'Stop mult':>10} {'n_stoppati':>11} {'n_TP_persi':>11} {'WR%':>6} {'avg_r+slip':>11} {'Δ':>8}")
    _sep(68)

    for mult in stop_mults:
        sim_pnls = []
        n_stopped = 0  # trade stoppati dal nuovo stop (mult < 1 → più stop)
        n_tp_lost = 0  # trade TP che sarebbero stati stoppati (mult < 1)

        for r in has_mae:
            mae = r["_mae"]
            cost = r["_cost"]
            out = r["outcome"]
            pnl = r["_pnl"]

            # Con stop a mult × distanza originale: il stop si triggerà se MAE >= mult
            if mae >= mult:
                # Trade stoppato al nuovo stop
                # Perdita = mult R (il prezzo ha percorso mult × rischio contro di noi)
                # Ma in R units del sistema originale: -mult R lordo, net: -mult - cost_scaled
                # Cost_scaled: il rischio è mult × originale → cost_r diventa cost/mult
                new_cost = cost / mult
                sim_pnl = -mult - new_cost
                sim_pnls.append(sim_pnl)
                if out in ("tp1", "tp2"):
                    n_tp_lost += 1  # avrebbe vinto ma il nuovo stop era troppo stretto
                else:
                    n_stopped += 1  # era già stop, ora fermato prima
            else:
                # MAE < mult: stop non triggerato con il nuovo stop
                if out == "stop" and mult > 1.0:
                    # Era stoppato ma con stop più largo avrebbe continuato
                    # Usiamo MFE per stimare: se MFE >= 2.0 (TP1) → avrebbe vinto
                    mfe = r["_mfe"]
                    if mfe is not None and mfe >= 2.0:
                        # Trade recupera → usa TP1 (2R lordo - cost)
                        new_cost = cost / mult
                        sim_pnls.append(2.0 - new_cost)
                        n_tp_lost += 1  # non perso, anzi vinto (contato negativamente qui)
                    else:
                        # Non recupera abbastanza → usa pnl_r attuale
                        new_cost = cost / mult
                        sim_pnls.append(-1.0 - new_cost)  # ancora stop ma più lontano
                else:
                    sim_pnls.append(pnl)

        avg_sim = sum(sim_pnls)/len(sim_pnls)
        n_w = sum(1 for p in sim_pnls if p > 0)
        wr = n_w/len(sim_pnls)*100
        delta = avg_sim - base_avg
        mk = " ★" if delta > 0.05 else (" ▼" if delta < -0.05 else "")
        lbl = f"{mult:.2f}× {'(attuale)' if mult==1.0 else ''}"
        print(f"  {lbl:>10} {n_stopped:>11} {n_tp_lost:>11} {wr:>5.1f}%  {avg_sim:>+11.4f}R {delta:>+8.4f}R{mk}")

    print()
    print("  INTERPRETAZIONE:")
    print("  Stop 0.75×: ferma prima i trade in perdita MA perde alcuni TP (quelli che scendono")
    print("  quasi fino allo stop poi recuperano). L'ottimo dipende da:")
    print("  - Se MAE>0.8R e TP è comune → stop stretto distrugge EV")
    print("  - Se MAE>0.8R e TP è raro → stop stretto migliora EV (taglia le perdite)")


# ════════════════════════════════════════════════════════════════════════════
# 3G. MIN_RISK_PCT OTTIMALE
# ════════════════════════════════════════════════════════════════════════════

def sect_3g_min_risk_pct(filled_all: list[dict]) -> None:
    _hdr("3G. MIN_RISK_PCT OTTIMALE (6 pattern TRIPLO)")
    print("  cost_r = 0.15% / risk_pct → risk_pct basso → cost enorme in R")
    print("  Testare diversi floor: quanti trade rimangono e come cambia avg_r+slip")
    print()

    BARS_5M_PER_DAY = 65    # ~6.5h trading × 13 barre/ora (5m)
    TRADING_DAYS_YEAR = 252

    # Stima trade/anno: conta i giorni unici nel dataset e normalizza
    dates = set()
    for r in filled_all:
        ts = r.get("pattern_timestamp","")
        if ts:
            dates.add(ts[:10])
    n_days_dataset = len(dates) if dates else 252
    # Trade per anno = (n_trade / n_days_dataset) × TRADING_DAYS_YEAR
    # Per trade in un anno TRIPLO live:
    live_ratio = TRADING_DAYS_YEAR / max(1, n_days_dataset)

    floors = [0.0, 0.30, 0.40, 0.50, 0.60, 0.70, 0.75, 1.00, 1.25]

    print(f"  Dataset: {n_days_dataset} giorni di trading, live_ratio={live_ratio:.3f}x")
    print(f"  Trade/anno stimati come: n × {live_ratio:.3f}")
    print()

    # Capital assumption per € calc
    CAPITAL = 10000
    RISK_PER_TRADE_PCT = 0.5  # 0.5% del capitale per trade

    print(f"  Assunzione: capitale={CAPITAL}€, rischio/trade={RISK_PER_TRADE_PCT}% → {CAPITAL*RISK_PER_TRADE_PCT/100:.0f}€/trade")
    print()
    print(f"  {'Floor':>8} {'n TRIPLO':>9} {'avg_r+slip':>12} {'WR%':>6} {'cost medio':>11} "
          f"{'trade/anno':>11} {'€/anno':>9} {'OOS stabile?':>13}")
    _sep(90)

    base_sub = filled_all  # tutti i 6 pattern TRIPLO
    base_n = len(base_sub)
    base_avg = sum(r["_pnl"] for r in base_sub)/base_n if base_sub else 0
    base_cost = sum(r["_cost"] for r in base_sub)/base_n if base_sub else 0

    for floor in floors:
        sub = [r for r in filled_all if r["_risk_pct"] >= floor]
        n = len(sub)
        if n == 0:
            print(f"  {floor:>6.2f}%  {'—':>9}")
            continue
        avg_n = sum(r["_pnl"] for r in sub)/n
        avg_cost = sum(r["_cost"] for r in sub)/n
        w = sum(1 for r in sub if r["_pnl"]>0)
        wr = w/n*100
        trade_anno = int(n * live_ratio)
        # €/anno: trade/anno × avg_r × rischio_€_per_trade
        # rischio_€_per_trade = capital × risk_per_trade_pct / 100
        risk_euro = CAPITAL * RISK_PER_TRADE_PCT / 100
        euro_anno = trade_anno * avg_n * risk_euro
        pct_n = n/base_n*100

        # OOS stability: almeno 200 trade/anno con avg_r+slip > 0.1R
        oos = "SI" if trade_anno >= 200 and avg_n > 0.10 else ("LIMITE" if trade_anno >= 100 else "NO")

        current_mk = " <attuale>" if abs(floor - MIN_RISK_PCT_CURRENT) < 0.01 else ""
        print(f"  {floor:>6.2f}%  {n:>6} ({pct_n:.0f}%)  {avg_n:>+12.4f}R {wr:>5.1f}%  "
              f"{avg_cost:>11.4f}R {trade_anno:>11} {euro_anno:>+9.0f}€  {oos:>13}{current_mk}")

    print()
    print("  NOTA: avg_r+slip migliora monotonicamente con floor più alto perché")
    print("  il costo per trade (0.15%/risk_pct) scende. Trovare il floor che bilancia")
    print("  EV/trade (alto) vs volume (alto) → massimizza €/anno totale.")


# ════════════════════════════════════════════════════════════════════════════
# 3H. COMBINAZIONE OTTIMALE + MONTE CARLO
# ════════════════════════════════════════════════════════════════════════════

def sect_3h_combinazione(filled_all: list[dict], filled_6: list[dict]) -> None:
    _hdr("3H. COMBINAZIONE OTTIMALE FINALE + MONTE CARLO")
    print()

    # Trova parametri ottimali dalle sezioni precedenti
    has_mfe = [r for r in filled_6 if r["_mfe"] is not None and r["_mae"] is not None]

    # Testa combinazioni: (min_risk_floor, tp_target, trailing_trigger)
    combos = [
        ("Attuale (baseline)",   0.30, None, None),
        ("Risk ≥ 0.50%",         0.50, None, None),
        ("Risk ≥ 0.60%",         0.60, None, None),
        ("Risk ≥ 0.70%",         0.70, None, None),
        ("Risk ≥ 0.50% + TP2R",  0.50, 2.0,  None),
        ("Risk ≥ 0.60% + TP2R",  0.60, 2.0,  None),
        ("Risk ≥ 0.50% + Trail0.75", 0.50, None, 0.75),
        ("Risk ≥ 0.60% + Trail0.75", 0.60, None, 0.75),
        ("Ottimale (0.60+TP2R+Trail)", 0.60, 2.0, 0.75),
    ]

    CAPITAL = 10000
    RISK_PCT = 0.5  # rischio per trade in % del capitale
    risk_euro = CAPITAL * RISK_PCT / 100

    dates = set(r.get("pattern_timestamp","")[:10] for r in filled_6 if r.get("pattern_timestamp"))
    n_days = len(dates) if dates else 252
    live_ratio = 252 / max(1, n_days)

    print(f"  {'Config':38s} {'n':>5} {'avg+slip':>10} {'WR%':>6} {'trade/anno':>11} {'€/anno':>9}")
    _sep(85)

    best_euro = -999999
    best_label = ""

    for label, floor, tp_tgt, trail_trig in combos:
        # Filter by risk floor
        sub = [r for r in has_mfe if r["_risk_pct"] >= floor]
        if not sub:
            continue

        # Apply TP simulation
        if tp_tgt is not None:
            sim_pnls = []
            for r in sub:
                if r["outcome"]=="stop":
                    sim_pnls.append(r["_pnl"])
                elif r["_mfe"] >= tp_tgt:
                    sim_pnls.append(tp_tgt - r["_cost"])
                else:
                    sim_pnls.append(r["_pnl"])
        else:
            sim_pnls = [r["_pnl"] for r in sub]

        # Apply trailing stop
        if trail_trig is not None:
            final_pnls = []
            for r, p in zip(sub, sim_pnls):
                if r["_mfe"] >= trail_trig and r["outcome"]=="stop":
                    # Saved by trailing
                    final_pnls.append(-r["_cost"] * 0.5)
                elif r["_mfe"] >= trail_trig and r["outcome"]=="timeout" and p < -r["_cost"]*0.5:
                    final_pnls.append(-r["_cost"] * 0.5)
                else:
                    final_pnls.append(p)
        else:
            final_pnls = sim_pnls

        n = len(final_pnls)
        avg_n = sum(final_pnls)/n
        wr = sum(1 for p in final_pnls if p>0)/n*100
        trade_anno = int(n * live_ratio)
        euro_anno = trade_anno * avg_n * risk_euro
        mk = " ★" if euro_anno > best_euro and label != "Attuale (baseline)" else ""
        if euro_anno > best_euro and label != "Attuale (baseline)":
            best_euro = euro_anno
            best_label = label
        print(f"  {label:38s} {n:>5} {avg_n:>+10.4f}R {wr:>5.1f}%  {trade_anno:>11} {euro_anno:>+9.0f}€{mk}")

    print(f"\n  MIGLIORE: '{best_label}' → {best_euro:+.0f}€/anno stimato")

    # ── MONTE CARLO ──────────────────────────────────────────────────────────
    _hdr("3H-MC. MONTE CARLO — Attuale vs Ottimale (1000 simulazioni × 12 mesi)")
    print()

    import random
    random.seed(42)

    N_SIM = 1000
    MONTHS = 12
    TRADES_PER_MONTH_BASE = max(1, int(len(filled_6) * live_ratio / 12))
    TRADES_PER_MONTH_OPT = max(1, int(len([r for r in has_mfe if r["_risk_pct"] >= 0.60]) * live_ratio / 12))

    print(f"  Simulazioni: {N_SIM} | Periodo: {MONTHS} mesi")
    print(f"  Trade/mese stimati: baseline={TRADES_PER_MONTH_BASE} | ottimale={TRADES_PER_MONTH_OPT}")
    print()

    # Pnl pools
    pool_base = [r["_pnl"] for r in filled_6]
    # Pool ottimale: risk>=0.60, TP=2R, trail=0.75
    sub_opt = [r for r in has_mfe if r["_risk_pct"] >= 0.60]
    pool_opt = []
    for r in sub_opt:
        if r["outcome"]=="stop":
            p = r["_pnl"]
        elif r["_mfe"] >= 2.0:
            p = 2.0 - r["_cost"]
        else:
            p = r["_pnl"]
        if r["_mfe"] >= 0.75 and r["outcome"]=="stop":
            p = -r["_cost"] * 0.5
        pool_opt.append(p)

    def run_mc(pool: list[float], n_per_month: int, n_months: int, n_sim: int, risk_e: float) -> dict:
        results_12m = []
        for _ in range(n_sim):
            total = 0.0
            for _ in range(n_months):
                monthly = sum(random.choice(pool) for _ in range(n_per_month))
                total += monthly
            results_12m.append(total * risk_e)
        results_12m.sort()
        n = len(results_12m)
        return {
            "mean": sum(results_12m)/n,
            "median": results_12m[n//2],
            "p5": results_12m[int(0.05*n)],
            "p95": results_12m[int(0.95*n)],
            "prob_pos": sum(1 for v in results_12m if v > 0)/n*100,
        }

    mc_base = run_mc(pool_base, TRADES_PER_MONTH_BASE, MONTHS, N_SIM, risk_euro)
    mc_opt = run_mc(pool_opt, TRADES_PER_MONTH_OPT, MONTHS, N_SIM, risk_euro)

    avg_base = sum(pool_base)/len(pool_base)
    avg_opt = sum(pool_opt)/len(pool_opt) if pool_opt else 0

    print(f"  {'Scenario':25s} {'Trade/mese':>11} {'avg_r+slip':>12} {'Mediana 12m':>12} {'Worst 5%':>10} {'ProbP':>7}")
    _sep(78)
    print(f"  {'Attuale (6 pattern)':25s} {TRADES_PER_MONTH_BASE:>11} {avg_base:>+12.4f}R "
          f"{mc_base['median']:>+12.0f}€ {mc_base['p5']:>+10.0f}€ {mc_base['prob_pos']:>6.1f}%")
    print(f"  {'Ottimale (0.60+TP2R+T)':25s} {TRADES_PER_MONTH_OPT:>11} {avg_opt:>+12.4f}R "
          f"{mc_opt['median']:>+12.0f}€ {mc_opt['p5']:>+10.0f}€ {mc_opt['prob_pos']:>6.1f}%")

    print()
    print(f"  UPLIFT mediano: {mc_opt['median']-mc_base['median']:+.0f}€/anno")
    print(f"  UPLIFT media:   {mc_opt['mean']-mc_base['mean']:+.0f}€/anno")

    # ALPHA-only scenario
    pool_alpha = [r["_pnl"] for r in filled_6 if r["_fascia"]=="ALPHA"]
    n_alpha_month = max(1, int(len(pool_alpha) * live_ratio / 12))
    if pool_alpha:
        sub_alpha_opt = [r for r in has_mfe if r["_risk_pct"]>=0.60 and r["_fascia"]=="ALPHA"]
        pool_alpha_opt = []
        for r in sub_alpha_opt:
            if r["outcome"]=="stop": p = r["_pnl"]
            elif r["_mfe"] >= 2.0: p = 2.0 - r["_cost"]
            else: p = r["_pnl"]
            if r["_mfe"] >= 0.75 and r["outcome"]=="stop": p = -r["_cost"]*0.5
            pool_alpha_opt.append(p)

        n_alpha_opt_month = max(1, int(len(pool_alpha_opt)*live_ratio/12))
        mc_alpha = run_mc(pool_alpha, n_alpha_month, MONTHS, N_SIM, risk_euro)
        mc_alpha_opt = run_mc(pool_alpha_opt, n_alpha_opt_month, MONTHS, N_SIM, risk_euro) if pool_alpha_opt else mc_alpha
        avg_alpha = sum(pool_alpha)/len(pool_alpha)
        avg_alpha_opt = sum(pool_alpha_opt)/len(pool_alpha_opt) if pool_alpha_opt else 0

        print()
        print(f"  ALPHA-ONLY (15:xx):")
        print(f"  {'Attuale ALPHA':25s} {n_alpha_month:>11} {avg_alpha:>+12.4f}R "
              f"{mc_alpha['median']:>+12.0f}€ {mc_alpha['p5']:>+10.0f}€ {mc_alpha['prob_pos']:>6.1f}%")
        print(f"  {'Ottimale ALPHA':25s} {n_alpha_opt_month:>11} {avg_alpha_opt:>+12.4f}R "
              f"{mc_alpha_opt['median']:>+12.0f}€ {mc_alpha_opt['p5']:>+10.0f}€ {mc_alpha_opt['prob_pos']:>6.1f}%")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/val_5m_v2.csv")
    args = parser.parse_args()

    path = Path(args.dataset)
    if not path.exists():
        print(f"ERRORE: {path} non trovato", file=sys.stderr)
        print("Eseguire prima: python build_validation_dataset.py --timeframe 5m --limit 999999 --output data/val_5m_v2.csv")
        sys.exit(1)

    triplo_all, triplo_6, raw = load(path)

    sect_3a_volume(triplo_6)
    sect_3b_mfe(triplo_6)
    sect_3c_trailing(triplo_6)
    sect_3d_tp_reale(triplo_6)
    sect_3e_mae(triplo_6)
    sect_3f_stop_mae(triplo_6)
    sect_3g_min_risk_pct(triplo_6)
    sect_3h_combinazione(triplo_all, triplo_6)


if __name__ == "__main__":
    main()
