"""
test_approfondito_vol_tp_entry.py
==================================
Test approfondito: Volumi, TP/SL, Entry sul dataset 5m val_5m_expanded.csv
Config TRIPLO: ALPHA=15:00-16:00 ET, MIDDAY_F=11:00-14:00 ET

PARTE A — Volume (verifica disponibilità colonne)
PARTE B — TP/SL ottimizzazione granulare
PARTE C — Entry ottimizzazione

pnl_r nel CSV è NET (include BACKTEST_TOTAL_COST_RATE_DEFAULT=0.15% RT fee+slip).
"avg_r" = gross (add back per-trade cost estimate)
"avg_r+slip" = net = pnl_r dal CSV

Uso:
  python test_approfondito_vol_tp_entry.py
  python test_approfondito_vol_tp_entry.py --dataset data/val_5m_expanded.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Costanti ────────────────────────────────────────────────────────────────
BACKTEST_TOTAL_COST_RATE = 0.0015   # 0.10% fee + 0.05% slippage round-trip
SLIP_FIXED_R = 0.15                  # stima fissa legacy per riferimento
ALPHA_HOUR_ET = 15                   # 15:00-15:59 ET
MIDDAY_HOURS_ET = {11, 12, 13, 14}  # 11:00-14:59 ET
TRIPLO_PATTERNS = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}

# ─── Utilità ─────────────────────────────────────────────────────────────────

def _ny_hour(ts_str: str) -> int | None:
    """Converte timestamp UTC → ora ET (approssimazione DST: mar-ott EDT UTC-4, altro EST UTC-5)."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        offset_h = 4 if 3 <= dt.month <= 10 else 5
        et_dt = dt - timedelta(hours=offset_h)
        return et_dt.hour
    except Exception:
        return None


def _fascia(row: dict) -> str:
    h = _ny_hour(row.get("pattern_timestamp", ""))
    if h is None:
        return "UNKNOWN"
    if h == ALPHA_HOUR_ET:
        return "ALPHA"
    if h in MIDDAY_HOURS_ET:
        return "MIDDAY_F"
    return "OTHER"


def _cost_r(ep: float, sp: float) -> float:
    """Costo round-trip in R-multipli (0.15% notional / rischio)."""
    risk = abs(ep - sp)
    if risk < 1e-9 or ep <= 0:
        return 0.0
    return BACKTEST_TOTAL_COST_RATE * ep / risk


def _gross_r(pnl_net: float, cost_r: float) -> float:
    return pnl_net + cost_r


def _stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "wr": 0.0, "avg_r": 0.0, "avg_slip": 0.0}
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": n,
        "wr": wins / n * 100,
        "avg_r": sum(pnls) / n,           # net (già dopo cost)
    }


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    c = (p + z**2 / (2*n)) / (1 + z**2/n)
    m = z * ((p*(1-p)/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)
    return round(max(0.0, c-m)*100, 1), round(min(1.0, c+m)*100, 1)


def _hdr(title: str) -> None:
    print("\n" + "═"*80)
    print(title)
    print("═"*80)


def _sep() -> None:
    print("  " + "─"*76)


# ─── Caricamento dati ─────────────────────────────────────────────────────────

def load_data(path: Path) -> tuple[list[dict], list[dict]]:
    """Ritorna (all_rows, filled_triplo)."""
    with path.open(encoding="utf-8") as f:
        raw = list(csv.DictReader(f))

    for r in raw:
        r["_pnl"] = float(r["pnl_r"])
        r["_filled"] = r["entry_filled"] == "True"
        r["_ep"] = float(r.get("entry_price") or 0)
        r["_sp"] = float(r.get("stop_price") or 0)
        r["_tp1"] = float(r.get("tp1_price") or 0)
        r["_tp2"] = float(r.get("tp2_price") or 0)
        r["_risk_pct"] = float(r.get("risk_pct") or 0)
        r["_direction"] = r.get("direction", "bullish")
        r["_fascia"] = _fascia(r)
        r["_cost_r"] = _cost_r(r["_ep"], r["_sp"])
        r["_gross_r"] = _gross_r(r["_pnl"], r["_cost_r"])
        # TP1_R e TP2_R (gross)
        risk_abs = abs(r["_ep"] - r["_sp"])
        if risk_abs > 1e-9:
            if r["_direction"] == "bullish":
                r["_tp1_r"] = (r["_tp1"] - r["_ep"]) / risk_abs
                r["_tp2_r"] = (r["_tp2"] - r["_ep"]) / risk_abs
            else:
                r["_tp1_r"] = (r["_ep"] - r["_tp1"]) / risk_abs
                r["_tp2_r"] = (r["_ep"] - r["_tp2"]) / risk_abs
        else:
            r["_tp1_r"] = 2.0
            r["_tp2_r"] = 3.0

    total = len(raw)
    filled_all = [r for r in raw if r["_filled"]]
    filled_triplo = [r for r in filled_all if r["_fascia"] in ("ALPHA", "MIDDAY_F")]

    print(f"\nDataset: {total} righe | Filled: {len(filled_all)} | TRIPLO filled: {len(filled_triplo)}")
    alpha_n = sum(1 for r in filled_triplo if r["_fascia"] == "ALPHA")
    mid_n = sum(1 for r in filled_triplo if r["_fascia"] == "MIDDAY_F")
    print(f"  ALPHA (15:xx ET): {alpha_n}  |  MIDDAY_F (11-14 ET): {mid_n}")
    print(f"  NOTA: pnl_r nel CSV è NET dopo 0.15% RT cost.")
    print(f"  avg_r = gross (prima del costo), avg_r+slip = net (dopo costo = pnl_r dal CSV)")

    return raw, filled_triplo


# ════════════════════════════════════════════════════════════════════════════
# PARTE A — VOLUME
# ════════════════════════════════════════════════════════════════════════════

def parte_a_volume(raw: list[dict]) -> None:
    _hdr("PARTE A — VOLUME COME FILTRO")

    # Verifica colonne disponibili
    cols = set(raw[0].keys()) if raw else set()
    vol_cols = [c for c in cols if "vol" in c.lower() or "volume" in c.lower()]

    print(f"\n  Colonne CSV disponibili ({len(cols)} totali):")
    print(f"  {sorted(cols)}")
    print()
    if vol_cols:
        print(f"  ✓ Colonne volume trovate: {vol_cols}")
    else:
        print("  ✗ VOLUME NON PRESENTE nel CSV val_5m_expanded.csv")
        print()
        print("  Le sezioni A1-A5 richiedono il volume della candela del pattern.")
        print("  Il CSV contiene: entry_price, stop_price, tp1_price, tp2_price, risk_pct")
        print("  ma NON volume, open, high, low della candela pattern.")
        print()
        print("  Per aggiungere volume all'analisi, modificare build_validation_dataset.py")
        print("  per includere nel CSV: candle.volume, candle.open, candle.high, candle.low")
        print("  e calcolare SMA(volume,20) per simbolo dalla tabella Candle.")
        print()
        print("  ══════════════════════════════════════════════════════════")
        print("  A1. Volume relativo per fascia → SKIP (dati non disponibili)")
        print("  A2. Volume × ora             → SKIP")
        print("  A3. Volume × pattern          → SKIP")
        print("  A4. Volume candela successiva → SKIP")
        print("  A5. OBV trend                 → SKIP")
        print("  ══════════════════════════════════════════════════════════")
        print()
        print("  ALTERNATIVA DISPONIBILE: proxy 'volatilità' via risk_pct")
        print("  High risk_pct → candela ampia (volatilità alta, proxy volume indiretto)")

        # Proxy: risk_pct come proxy di volatilità / volume
        # Quartili risk_pct vs performance
        filled = [r for r in raw if r["_filled"] and r["_fascia"] in ("ALPHA","MIDDAY_F")]
        if not filled:
            return

        rps = sorted(r["_risk_pct"] for r in filled)
        n = len(rps)
        p25 = rps[int(0.25*n)]
        p50 = rps[int(0.50*n)]
        p75 = rps[int(0.75*n)]

        print()
        print("  PROXY: risk_pct (volatilità candela) vs performance TRIPLO")
        print(f"  Quartili risk_pct: Q1={p25:.3f}% Q2={p50:.3f}% Q3={p75:.3f}%")
        print()
        print(f"  {'Fascia risk_pct':22s} {'n':>5} {'WR%':>6} {'avg_r(gross)':>13} {'avg_r+slip(net)':>16} {'CI 95%':>14}")
        _sep()

        fascia_defs = [
            (f"< {p25:.3f}%",    lambda r: r["_risk_pct"] < p25),
            (f"{p25:.3f}-{p50:.3f}%", lambda r: p25 <= r["_risk_pct"] < p50),
            (f"{p50:.3f}-{p75:.3f}%", lambda r: p50 <= r["_risk_pct"] < p75),
            (f"> {p75:.3f}%",    lambda r: r["_risk_pct"] >= p75),
        ]
        for label, flt in fascia_defs:
            sub = [r for r in filled if flt(r)]
            if not sub:
                continue
            ns = len(sub)
            wins = sum(1 for r in sub if r["_pnl"] > 0)
            wr = wins/ns*100
            avg_gross = sum(r["_gross_r"] for r in sub)/ns
            avg_net = sum(r["_pnl"] for r in sub)/ns
            clo, chi = _wilson(wins, ns)
            print(f"  {label:22s} {ns:>5} {wr:>5.1f}% {avg_gross:>+13.4f}R {avg_net:>+16.4f}R [{clo}-{chi}%]")


# ════════════════════════════════════════════════════════════════════════════
# PARTE B — TP/SL OTTIMIZZAZIONE
# ════════════════════════════════════════════════════════════════════════════

def _sim_tp(rows: list[dict], tp_gross: float) -> list[float]:
    """
    Simula pnl_r NET se TP1 fosse a tp_gross R (lordo).
    - outcome='stop': pnl netto invariato (stop sempre eseguito)
    - se gross_r_attuale >= tp_gross: chiude a tp_gross → net = tp_gross - cost_r
    - altrimenti: usa pnl netto attuale (non ha raggiunto tp_gross)
    """
    result = []
    for r in rows:
        if r["outcome"] == "stop":
            result.append(r["_pnl"])
        elif r["_gross_r"] >= tp_gross:
            result.append(tp_gross - r["_cost_r"])
        else:
            result.append(r["_pnl"])
    return result


def parte_b1_tp_per_fascia(filled: list[dict]) -> None:
    _hdr("B1. TP1 OTTIMALE PER FASCIA ORARIA")
    print("  Simulazione: cosa succede variando TP1 (in R lordi) per ALPHA vs MIDDAY_F")
    print("  pnl_r_stop invariato | pnl_net_tp = tp_gross - cost_r_per_trade")
    print()

    tp_targets = [1.0, 1.25, 1.50, 1.75, 2.0, 2.5, 3.0]

    alpha = [r for r in filled if r["_fascia"] == "ALPHA"]
    midday = [r for r in filled if r["_fascia"] == "MIDDAY_F"]

    # Header
    print(f"  {'TP1 (gross)':>11} {'ALPHA n':>8} {'ALPHA WR%':>10} {'ALPHA avg_gross':>15} {'ALPHA avg+slip':>15} {'MID n':>6} {'MID WR%':>8} {'MID avg_gross':>14} {'MID avg+slip':>14}")
    _sep()

    for tp in tp_targets:
        # ALPHA
        if alpha:
            sim_a = _sim_tp(alpha, tp)
            na = len(sim_a)
            wa = sum(1 for p in sim_a if p > 0)
            wr_a = wa/na*100
            avg_net_a = sum(sim_a)/na
            # gross stima: aggiungi cost medio
            avg_cost_a = sum(r["_cost_r"] for r in alpha)/na
            avg_gross_a = avg_net_a + avg_cost_a
        else:
            na = wr_a = avg_gross_a = avg_net_a = 0

        # MIDDAY_F
        if midday:
            sim_m = _sim_tp(midday, tp)
            nm = len(sim_m)
            wm = sum(1 for p in sim_m if p > 0)
            wr_m = wm/nm*100
            avg_net_m = sum(sim_m)/nm
            avg_cost_m = sum(r["_cost_r"] for r in midday)/nm
            avg_gross_m = avg_net_m + avg_cost_m
        else:
            nm = wr_m = avg_gross_m = avg_net_m = 0

        print(f"  {tp:>10.2f}R {na:>8} {wr_a:>9.1f}% {avg_gross_a:>+15.4f}R {avg_net_a:>+15.4f}R {nm:>6} {wr_m:>7.1f}% {avg_gross_m:>+14.4f}R {avg_net_m:>+14.4f}R")

    # Baseline corrente (TP1 ≈ 2R, TP2 ≈ 3R, metà al TP1 e metà al TP2)
    print()
    print("  BASELINE attuale (nessuna sim):")
    for label, sub in [("ALPHA", alpha), ("MIDDAY_F", midday)]:
        if sub:
            n = len(sub)
            w = sum(1 for r in sub if r["_pnl"] > 0)
            avg_g = sum(r["_gross_r"] for r in sub)/n
            avg_n = sum(r["_pnl"] for r in sub)/n
            wr = w/n*100
            print(f"  {label:>10}: n={n} WR={wr:.1f}% avg_r(gross)={avg_g:+.4f}R avg_r+slip={avg_n:+.4f}R")


def parte_b2_tp_per_pattern(filled: list[dict]) -> None:
    _hdr("B2. TP1 OTTIMALE PER PATTERN")
    print("  Per ogni pattern: TP lordo che massimizza avg_r+slip nel TRIPLO")
    print()

    tp_targets = [1.0, 1.25, 1.50, 1.75, 2.0, 2.5, 3.0]
    by_pat: dict[str, list] = defaultdict(list)
    for r in filled:
        by_pat[r["pattern_name"]].append(r)

    print(f"  {'Pattern':30s} {'n':>5} {'TP ottimale':>12} {'avg+slip al TP ottimale':>23} {'WR%':>6} {'baseline avg+slip':>17}")
    _sep()

    for pat in sorted(by_pat.keys()):
        sub = by_pat[pat]
        n = len(sub)
        baseline_net = sum(r["_pnl"] for r in sub)/n
        baseline_wr = sum(1 for r in sub if r["_pnl"]>0)/n*100

        best_tp = None
        best_avg = -9999
        best_wr = 0.0
        for tp in tp_targets:
            sim = _sim_tp(sub, tp)
            avg_n = sum(sim)/len(sim)
            if avg_n > best_avg:
                best_avg = avg_n
                best_tp = tp
                best_wr = sum(1 for p in sim if p>0)/len(sim)*100

        print(f"  {pat:30s} {n:>5} {best_tp:>10.2f}R  {best_avg:>+23.4f}R {best_wr:>6.1f}% {baseline_net:>+17.4f}R")

    # Detail table per pattern × TP
    print()
    print("  DETAIL: avg_r+slip per ogni (pattern × TP)")
    header = f"  {'Pattern':30s}" + "".join(f" {tp:>8.2f}R" for tp in tp_targets)
    print(header)
    _sep()
    for pat in sorted(by_pat.keys()):
        sub = by_pat[pat]
        line = f"  {pat:30s}"
        for tp in tp_targets:
            sim = _sim_tp(sub, tp)
            avg_n = sum(sim)/len(sim)
            line += f" {avg_n:>+9.4f}"
        print(line)


def parte_b3_tp_per_regime(filled: list[dict]) -> None:
    _hdr("B3. TP1 OTTIMALE PER REGIME")
    print()
    print("  ✗ Colonna 'regime' (BULL/BEAR/NEUTRAL) NON presente nel CSV.")
    print("  Il regime viene filtrato PRIMA della costruzione del dataset")
    print("  tramite regime_filter_service.py e spy_1d.csv.")
    print()
    print("  ALTERNATIVA: classificare regime empiricamente da spy_1d.csv (presente")
    print("  in data/spy_1d.csv) e joinare su data per il giorno del pattern.")
    print()

    # Proviamo con spy_1d.csv se disponibile
    spy_path = Path("data/spy_1d.csv")
    if not spy_path.exists():
        print("  data/spy_1d.csv non trovato — skip.")
        return

    # Leggi SPY daily per stimare regime
    spy_by_date: dict[str, str] = {}
    try:
        with spy_path.open() as f:
            spy_rows = list(csv.DictReader(f))
        # Stima regime: 200-day SMA
        close_col = next((c for c in spy_rows[0].keys() if "close" in c.lower()), None)
        date_col = next((c for c in spy_rows[0].keys() if "date" in c.lower() or "time" in c.lower()), None)
        if close_col and date_col and len(spy_rows) >= 20:
            closes = [(r[date_col], float(r[close_col])) for r in spy_rows if r.get(close_col)]
            closes.sort(key=lambda x: x[0])
            SMA_PERIOD = 50
            for i, (dt_str, cl) in enumerate(closes):
                if i < SMA_PERIOD - 1:
                    spy_by_date[dt_str[:10]] = "NEUTRAL"
                    continue
                sma = sum(c for _, c in closes[i-SMA_PERIOD+1:i+1]) / SMA_PERIOD
                regime = "BULL" if cl > sma * 1.01 else ("BEAR" if cl < sma * 0.99 else "NEUTRAL")
                spy_by_date[dt_str[:10]] = regime
    except Exception as e:
        print(f"  Errore lettura spy_1d.csv: {e}")
        return

    # Assegna regime ai trade
    for r in filled:
        ts = r.get("pattern_timestamp", "")
        date_key = ts[:10] if ts else ""
        r["_regime"] = spy_by_date.get(date_key, "UNKNOWN")

    tp_targets = [1.0, 1.25, 1.50, 1.75, 2.0, 2.5, 3.0]
    by_regime: dict[str, list] = defaultdict(list)
    for r in filled:
        if r.get("_regime", "UNKNOWN") != "UNKNOWN":
            by_regime[r["_regime"]].append(r)

    if not by_regime:
        print("  Nessun trade con regime noto — skip.")
        return

    print(f"  Regime stimato via SPY SMA50 (dati in spy_1d.csv):")
    for reg, sub in sorted(by_regime.items()):
        print(f"  {reg}: {len(sub)} trade ({len(sub)/len(filled)*100:.1f}%)")

    print()
    print(f"  {'Regime':8s} {'n':>5} {'TP ottimale':>12} {'avg+slip':>9} {'WR%':>6}")
    _sep()
    for reg, sub in sorted(by_regime.items()):
        n = len(sub)
        best_tp, best_avg, best_wr = None, -9999, 0.0
        for tp in tp_targets:
            sim = _sim_tp(sub, tp)
            avg_n = sum(sim)/len(sim)
            if avg_n > best_avg:
                best_avg = avg_n; best_tp = tp
                best_wr = sum(1 for p in sim if p>0)/len(sim)*100
        print(f"  {reg:8s} {n:>5} {best_tp:>10.2f}R  {best_avg:>+9.4f}R {best_wr:>6.1f}%")

    print()
    print("  DETAIL: avg+slip per regime × TP")
    header = f"  {'Regime':8s}" + "".join(f" {tp:>8.2f}R" for tp in tp_targets)
    print(header)
    _sep()
    for reg, sub in sorted(by_regime.items()):
        line = f"  {reg:8s}"
        for tp in tp_targets:
            sim = _sim_tp(sub, tp)
            avg_n = sum(sim)/len(sim)
            line += f" {avg_n:>+9.4f}"
        print(line)


def parte_b4_stop_loss(filled: list[dict]) -> None:
    _hdr("B4. STOP LOSS OTTIMALE — ANALISI RISK_PCT")
    print("  Senza dati MFE/MAE per singola barra, simulazione esatta SL impossibile.")
    print("  Approssimazione A: solo perdita per stop (non WR change — richiede MFE).")
    print("  Approssimazione B: risk_pct come proxy empirico — quartili vs performance.")
    print()

    # Approssimazione A: cambia solo la dimensione della perdita per i trade stop
    # (WR invariato — ipotesi conservativa per analisi costi)
    stop_mult = [0.75, 1.0, 1.25, 1.50]

    alpha = [r for r in filled if r["_fascia"] == "ALPHA"]
    midday = [r for r in filled if r["_fascia"] == "MIDDAY_F"]

    print("  APPROSSIMAZIONE A — Solo costo stop (WR conservato uguale)")
    print("  Logica: stop M× → perdita M×, ma le vittorie NON cambiano (WR ignora MFE)")
    print()
    print(f"  {'Stop mult':>10} {'n':>6} {'WR%':>6} {'avg_r(gross)':>14} {'avg_r+slip':>12}")
    _sep()
    for mult in stop_mult:
        sim_pnls = []
        for r in filled:
            if r["outcome"] == "stop":
                # Nuova perdita = mult * 1R - cost
                # stop_gross = -mult, net = -mult - cost_r_new
                # cost_r_new = cost_rate * ep / (mult * risk_abs) = cost_r / mult
                new_cost = r["_cost_r"] / mult if mult > 0 else r["_cost_r"]
                sim_pnls.append(-mult - new_cost)
            else:
                # TP o timeout: pnl non cambia (ipotesi conservativa)
                sim_pnls.append(r["_pnl"])
        n = len(sim_pnls)
        w = sum(1 for p in sim_pnls if p > 0)
        avg_n = sum(sim_pnls)/n
        avg_g = avg_n + sum(r["_cost_r"] for r in filled)/n
        wr = w/n*100
        marker = " ★" if avg_n > -0.1 else ""
        print(f"  {mult:>9.2f}× {n:>6} {wr:>5.1f}% {avg_g:>+14.4f}R {avg_n:>+12.4f}R{marker}")

    print()
    print("  APPROSSIMAZIONE B — risk_pct quartili (proxy volatilità/stop naturale)")
    print()

    rps = sorted(r["_risk_pct"] for r in filled)
    nq = len(rps)
    q1 = rps[int(0.25*nq)]; q2 = rps[int(0.50*nq)]; q3 = rps[int(0.75*nq)]
    print(f"  Quartili: Q1={q1:.3f}% Q2={q2:.3f}% Q3={q3:.3f}%")
    print()

    print(f"  {'Fascia risk_pct':25s} {'n':>5} {'WR%':>6} {'avg_r(gross)':>14} {'avg_r+slip':>12} {'cost medio':>11}")
    _sep()
    fascie = [
        (f"< {q1:.3f}% (stretto)",    [r for r in filled if r["_risk_pct"] < q1]),
        (f"{q1:.3f}-{q2:.3f}%",       [r for r in filled if q1 <= r["_risk_pct"] < q2]),
        (f"{q2:.3f}-{q3:.3f}%",       [r for r in filled if q2 <= r["_risk_pct"] < q3]),
        (f"> {q3:.3f}% (largo)",       [r for r in filled if r["_risk_pct"] >= q3]),
    ]
    for label, sub in fascie:
        if not sub: continue
        n = len(sub)
        w = sum(1 for r in sub if r["_pnl"] > 0)
        wr = w/n*100
        avg_n = sum(r["_pnl"] for r in sub)/n
        avg_g = sum(r["_gross_r"] for r in sub)/n
        avg_cost = sum(r["_cost_r"] for r in sub)/n
        print(f"  {label:25s} {n:>5} {wr:>5.1f}% {avg_g:>+14.4f}R {avg_n:>+12.4f}R {avg_cost:>+11.4f}R")

    print()
    print("  INTERPRETAZIONE: se risk_pct alto → avg_r MIGLIORE → stop più largo è meglio")
    print("  NB: alta correlazione risk_pct↔volatilità stock, non solo larghezza stop.")


def parte_b5_stop_per_fascia(filled: list[dict]) -> None:
    _hdr("B5. STOP × FASCIA ORARIA (risk_pct proxy)")
    print()

    alpha = [r for r in filled if r["_fascia"] == "ALPHA"]
    midday = [r for r in filled if r["_fascia"] == "MIDDAY_F"]

    rps = sorted(r["_risk_pct"] for r in filled)
    n = len(rps)
    q2 = rps[int(0.50*n)]
    q3 = rps[int(0.75*n)]

    print(f"  Fascia bassa: < {q2:.3f}%  |  Media: {q2:.3f}-{q3:.3f}%  |  Alta: > {q3:.3f}%")
    print()
    print(f"  {'Fascia risk':16s} {'ALPHA n':>7} {'ALPHA avg+slip':>15} {'MID n':>6} {'MID avg+slip':>13}")
    _sep()

    def _bucket(rows: list[dict], lo: float, hi: float) -> list[dict]:
        return [r for r in rows if lo <= r["_risk_pct"] < hi]

    buckets = [
        (f"< {q2:.3f}% (stretto)", 0.0, q2),
        (f"{q2:.3f}-{q3:.3f}%",    q2, q3),
        (f"> {q3:.3f}% (largo)",    q3, 9999),
    ]
    for label, lo, hi in buckets:
        sa = _bucket(alpha, lo, hi)
        sm = _bucket(midday, lo, hi)
        na = len(sa); nm = len(sm)
        avg_a = sum(r["_pnl"] for r in sa)/na if sa else 0
        avg_m = sum(r["_pnl"] for r in sm)/nm if sm else 0
        wr_a = sum(1 for r in sa if r["_pnl"]>0)/na*100 if sa else 0
        wr_m = sum(1 for r in sm if r["_pnl"]>0)/nm*100 if sm else 0
        print(f"  {label:16s} {na:>7} {avg_a:>+15.4f}R {nm:>6} {avg_m:>+13.4f}R")


def parte_b6_trailing_stop(filled: list[dict]) -> None:
    _hdr("B6. TRAILING STOP — DATASET TRIPLO")
    print("  Metodo: calcolo determinisitico sui trade con MFE nota (TP/timeout positivi)")
    print("  Per i trade STOP: MFE sconosciuta → range [conservativo=0%, ottimistico=stima]")
    print("  Per i trade timeout/tp: MFE nota ≥ pnl_r → trailing si applica se pnl_r ≥ trigger")
    print()

    configs = [
        ("Stop fisso (baseline)",           None,   None),
        ("Trail BE dopo +0.5R",             0.50,   0.0),
        ("Trail BE dopo +0.75R",            0.75,   0.0),
        ("Trail BE dopo +1.0R",             1.00,   0.0),
        ("Trail +0.5R dopo +1.0R",          1.00,   0.50),
        ("Trail +0.5R dopo +1.5R",          1.50,   0.50),
    ]

    # Baseline
    n_all = len(filled)
    n_stop = sum(1 for r in filled if r["outcome"] == "stop")
    n_tp1 = sum(1 for r in filled if r["outcome"] == "tp1")
    n_tp2 = sum(1 for r in filled if r["outcome"] == "tp2")
    n_timeout = sum(1 for r in filled if r["outcome"] == "timeout")
    baseline_avg = sum(r["_pnl"] for r in filled) / n_all

    print(f"  Composizione TRIPLO: n={n_all}  stop={n_stop} tp1={n_tp1} tp2={n_tp2} timeout={n_timeout}")
    print(f"  Baseline avg_r+slip={baseline_avg:+.4f}R")
    print()

    print(f"  {'Config':35s} {'n':>5} {'avg+slip':>10} {'Δ vs base':>10} {'trade salvati':>14} {'trade persi prem.':>18}")
    _sep()

    for cfg_label, trigger_r, new_stop_r in configs:
        if trigger_r is None:
            # Baseline
            avg_n = baseline_avg
            saved = 0
            lost_early = 0
            n_eff = n_all
        else:
            sim_pnls = []
            saved = 0       # trade che migliorano da trailing
            lost_early = 0  # trade che peggiorano da trailing

            for r in filled:
                pnl = r["_pnl"]
                outcome = r["outcome"]
                gross = r["_gross_r"]
                cost = r["_cost_r"]

                # Determinazione: il prezzo ha raggiunto trigger_r (gross) prima dell'exit?
                # - Per TP1/TP2: pnl_r_gross = gross_r >= tp1_r (sicuramente raggiunto)
                # - Per timeout positivo: gross ≈ pnl_r + cost (il prezzo era almeno qui all'exit)
                # - Per stop/timeout negativo: MFE sconosciuta
                triggered = False
                if outcome in ("tp1", "tp2") and gross >= trigger_r:
                    triggered = True
                elif outcome == "timeout" and gross >= trigger_r:
                    triggered = True
                # Per outcome='stop': triggered=False (conservative)
                # Per timeout negativo: triggered=False (conservative)

                if not triggered:
                    sim_pnls.append(pnl)
                    continue

                # Trailing attivato: il nuovo stop è a new_stop_r (gross)
                # net_new_stop = new_stop_r - cost (il costo è già pagato all'entrata,
                # ma paghi la metà exit comunque → approssimiamo: 0 se new_stop=BE)
                net_new_stop = new_stop_r - cost * 0.5 if new_stop_r > 0 else -cost * 0.5

                # Cosa succede dopo il trigger?
                # - Se il trade finalizza al TP (outcome tp1/tp2): stesso exit (TP > new_stop)
                # - Se il trade finisce a timeout con pnl < net_new_stop: trailing ferma a net_new_stop
                # - Altrimenti: usa pnl_r attuale

                if outcome in ("tp1", "tp2"):
                    # TP hit: il prezzo ha superato trigger E ha continuato fino al TP
                    # Il trailing stop non si attiva (TP > new_stop)
                    sim_pnls.append(pnl)

                elif outcome == "timeout":
                    # Timeout: il prezzo ha raggiunto trigger, poi timeout a pnl
                    if pnl < net_new_stop:
                        # Il trailing avrebbe fermato prima del timeout
                        sim_pnls.append(net_new_stop)
                        saved += 1
                    else:
                        # Timeout a pnl >= new_stop → nessun cambio
                        sim_pnls.append(pnl)

                else:
                    sim_pnls.append(pnl)

            n_eff = len(sim_pnls)
            avg_n = sum(sim_pnls) / n_eff

        delta = avg_n - baseline_avg
        marker = " ★" if delta > 0.01 else (" ▼" if delta < -0.01 else "")
        print(f"  {cfg_label:35s} {n_eff:>5} {avg_n:>+10.4f}R {delta:>+10.4f}R {saved:>14} {lost_early:>18}{marker}")

    print()
    print("  NOTA CRITICA: 'trade salvati' include SOLO timeout positivi dove il trailing")
    print("  avrebbe chiuso prima del pullback al new_stop. I trade STOP non sono contati")
    print("  (MFE sconosciuta). La stima è conservativa: il vero beneficio potrebbe essere")
    print("  significativamente maggiore se molti stop trades hanno MFE > trigger.")
    print()
    print("  STIMA OTTIMISTICA stop trades (se il 20% degli stop ha MFE ≥ trigger):")

    for cfg_label, trigger_r, new_stop_r in configs[1:]:
        stop_pnls = [r["_pnl"] for r in filled if r["outcome"] == "stop"]
        if not stop_pnls: continue
        n_stop_saved = int(0.20 * len(stop_pnls))
        # Ogni stop salvato: da -1.55R (avg stop) a ≈ -cost_r*0.5 ≈ -0.25R
        avg_stop = sum(stop_pnls) / len(stop_pnls)
        avg_saved_pnl = -sum(r["_cost_r"] for r in filled if r["outcome"]=="stop") / len(stop_pnls) * 0.5
        saving_per_trade = avg_saved_pnl - avg_stop  # sempre positivo
        total_uplift = saving_per_trade * n_stop_saved / n_all
        print(f"  {cfg_label:35s} uplift ≈ {total_uplift:+.4f}R/trade (20% stop ha MFE ≥ {trigger_r:.2f}R)")


# ════════════════════════════════════════════════════════════════════════════
# PARTE C — ENTRY OTTIMIZZAZIONE
# ════════════════════════════════════════════════════════════════════════════

def parte_c1_entry_timing(filled: list[dict], raw: list[dict]) -> None:
    _hdr("C1. TIMING DELL'ENTRY")
    print("  Il sistema entra con LMT al close candela pattern, eseguito su bar+1 o bar+2.")
    print("  bars_to_entry: 1=barra successiva, 2=due barre dopo, 3=tre barre dopo")
    print("  NOTA: bars_to_entry=0 non esiste nel dataset → nessun fill sulla stessa barra")
    print()

    # bars_to_entry analysis
    by_bte: dict[int, list] = defaultdict(list)
    for r in filled:
        bte_str = r.get("bars_to_entry", "")
        try:
            bte = int(bte_str)
            by_bte[bte].append(r)
        except (ValueError, TypeError):
            pass

    print(f"  {'Entry':35s} {'n':>6} {'WR%':>6} {'avg_r(gross)':>14} {'avg_r+slip':>12} {'CI 95%':>14}")
    _sep()

    labels = {
        1: "Close bar pattern (1 bar dopo) — corrente",
        2: "Open+1 barra (2 bars delay)",
        3: "Close bar+1 (3 bars delay)",
    }

    for bte in sorted(by_bte.keys()):
        sub = by_bte[bte]
        n = len(sub)
        w = sum(1 for r in sub if r["_pnl"] > 0)
        wr = w/n*100
        avg_n = sum(r["_pnl"] for r in sub)/n
        avg_g = sum(r["_gross_r"] for r in sub)/n
        clo, chi = _wilson(w, n)
        lbl = labels.get(bte, f"{bte} bars delay")
        marker = " ★" if avg_n > -0.1 else ""
        print(f"  {lbl:35s} {n:>6} {wr:>5.1f}% {avg_g:>+14.4f}R {avg_n:>+12.4f}R [{clo}-{chi}%]{marker}")

    # No-fill (sarebbe "Close candela +1 piena conferma" nel senso che il LMT non è stato riempito)
    no_fill = [r for r in raw if r["entry_filled"] == "False"]
    # Per i no-fill non abbiamo pnl_r significativo
    print()
    print(f"  No fill (LMT non eseguito): {len(no_fill)} trade ({len(no_fill)/(len(raw))*100:.1f}%)")
    print(f"  → questi trade sarebbero 'perduti' con un sistema market order")

    # Per fascia oraria
    print()
    print("  BREAKDOWN PER FASCIA ORARIA:")
    for fascia_label in ["ALPHA", "MIDDAY_F"]:
        sub_f = [r for r in filled if r["_fascia"] == fascia_label]
        print(f"\n  {fascia_label}:")
        bte_f: dict[int, list] = defaultdict(list)
        for r in sub_f:
            try:
                bte = int(r.get("bars_to_entry",""))
                bte_f[bte].append(r)
            except: pass
        for bte in sorted(bte_f.keys()):
            sub = bte_f[bte]
            n = len(sub)
            w = sum(1 for r in sub if r["_pnl"] > 0)
            avg_n = sum(r["_pnl"] for r in sub)/n
            wr = w/n*100
            lbl = labels.get(bte, f"{bte} bars")
            print(f"    {lbl:35s} n={n:>5} WR={wr:.1f}% avg+slip={avg_n:+.4f}R")


def parte_c2_entry_position(filled: list[dict]) -> None:
    _hdr("C2. PREZZO ENTRY VS POSIZIONE NELLA CANDELA")
    print("  Proxy: risk_pct relativo alla candela (stop distance = proxy per 'close vicino al low')")
    print("  Per LONG: close vicino al low = entry_price ≈ stop_price (risk_pct piccolo)")
    print("  → Per candela bullish: stop sotto il low. Close vicino al low → risk_pct piccolo.")
    print()
    print("  Alternativa: rapporto (entry - stop) / (tp1 - stop) come proxy posizione.")
    print("  Piccolo → entry vicino al low (bullish forte). Grande → entry vicino al TP (debole).")
    print()

    # Ratio: rischio rispetto al movimento totale (entry→stop vs entry→tp1)
    # proxy = risk / (tp1 - stop) per bullish = 1 / (tp1_r + 1)
    # piccolo = entry vicina alla bottom (bassa posizione relativa)

    def _pos_ratio(r: dict) -> float | None:
        """0 = close vicino al low, 1 = close vicino al high (per signal LONG)."""
        try:
            ep = r["_ep"]; sp = r["_sp"]; tp1 = r["_tp1"]
            if r["_direction"] == "bullish":
                range_ = tp1 - sp
                if range_ <= 0: return None
                return (ep - sp) / range_  # 0=vicino low, 1=vicino TP1
            else:
                range_ = sp - tp1
                if range_ <= 0: return None
                return (sp - ep) / range_
        except: return None

    filled_with_pos = [(r, _pos_ratio(r)) for r in filled]
    filled_with_pos = [(r, p) for r, p in filled_with_pos if p is not None and 0 <= p <= 1]

    print(f"  Trade con posizione calcolabile: {len(filled_with_pos)}/{len(filled)}")
    print()

    thresholds = [
        ("Vicino al low (pos < 0.30)",       lambda p: p < 0.30),
        ("A metà (0.30 ≤ pos < 0.55)",       lambda p: 0.30 <= p < 0.55),
        ("Vicino al high (pos ≥ 0.55)",      lambda p: p >= 0.55),
    ]

    print(f"  {'Close nella candela':30s} {'n':>6} {'WR%':>6} {'avg_r(gross)':>14} {'avg_r+slip':>12} {'CI 95%':>14}")
    _sep()
    for label, flt in thresholds:
        sub = [(r, p) for r, p in filled_with_pos if flt(p)]
        if not sub: continue
        rows = [r for r, _ in sub]
        n = len(rows)
        w = sum(1 for r in rows if r["_pnl"] > 0)
        wr = w/n*100
        avg_n = sum(r["_pnl"] for r in rows)/n
        avg_g = sum(r["_gross_r"] for r in rows)/n
        clo, chi = _wilson(w, n)
        marker = " ★" if avg_n > -0.05 else ""
        print(f"  {label:30s} {n:>6} {wr:>5.1f}% {avg_g:>+14.4f}R {avg_n:>+12.4f}R [{clo}-{chi}%]{marker}")

    # Breakdown per direzione
    print()
    print("  BREAKDOWN PER DIREZIONE:")
    for direction in ["bullish", "bearish"]:
        sub_d = [(r, p) for r, p in filled_with_pos if r["_direction"] == direction]
        print(f"\n  {direction.upper()}:")
        for label, flt in thresholds:
            sub = [r for r, p in sub_d if flt(p)]
            if not sub: continue
            n = len(sub)
            w = sum(1 for r in sub if r["_pnl"] > 0)
            wr = w/n*100
            avg_n = sum(r["_pnl"] for r in sub)/n
            print(f"    {label:30s} n={n:>5} WR={wr:.1f}% avg+slip={avg_n:+.4f}R")

    # Per pattern × posizione
    print()
    print("  TP1/TP2/STOP per posizione (TRIPLO):")
    for label, flt in thresholds:
        sub = [(r, p) for r, p in filled_with_pos if flt(p)]
        rows = [r for r, _ in sub]
        n_stop = sum(1 for r in rows if r["outcome"]=="stop")
        n_tp1 = sum(1 for r in rows if r["outcome"]=="tp1")
        n_tp2 = sum(1 for r in rows if r["outcome"]=="tp2")
        n_to = sum(1 for r in rows if r["outcome"]=="timeout")
        n = len(rows)
        if n:
            print(f"  {label:30s} stop={n_stop/n*100:.1f}% tp1={n_tp1/n*100:.1f}% tp2={n_tp2/n*100:.1f}% timeout={n_to/n*100:.1f}%")


def parte_c3_gap_entry(filled: list[dict]) -> None:
    _hdr("C3. GAP TRA CLOSE PATTERN E OPEN BAR+1")
    print()
    print("  ✗ Il CSV non contiene open, high, low della candela pattern né della barra successiva.")
    print("  Solo entry_price (= limite LMT inviato) e bars_to_entry (quando fill).")
    print()
    print("  PROXY DISPONIBILE: bars_to_entry come indicatore di gap avverso.")
    print("  bars_to_entry=1: fill immediato sul bar+1 → open favorevole (LMT non saltato)")
    print("  bars_to_entry=2: open+1 sfavorevole → LMT non riempito sul bar+1, fill sul bar+2")
    print("  bars_to_entry=3: aperta gap ancora più avversa → fill sul bar+3")
    print()
    print("  INTERPRETAZIONE: bars_to_entry alto → mercato si è mosso contro la direzione")
    print("  prima del fill → entry peggiore → dovrebbe corrispondere a pnl_r peggiore.")
    print()
    print("  (Vedi C1 per la tabella completa bars_to_entry → avg_r+slip)")
    print()

    # Extra: correlazione bars_to_entry vs pnl_r
    bte_pnl = []
    for r in filled:
        try:
            bte = int(r.get("bars_to_entry", ""))
            bte_pnl.append((bte, r["_pnl"]))
        except: pass

    if bte_pnl:
        from collections import Counter
        bte_counts = Counter(b for b, _ in bte_pnl)
        print(f"  Distribuzione bars_to_entry: {dict(sorted(bte_counts.items()))}")

        # Simula: se i trade con bars_to_entry>1 vengono scartati
        sub_bte1 = [r for r in filled if r.get("bars_to_entry","") == "1"]
        sub_bte_gt1 = [r for r in filled if r.get("bars_to_entry","") in ("2","3")]
        print()
        print(f"  {'Subset':30s} {'n':>6} {'WR%':>6} {'avg+slip':>10}")
        _sep()
        for label, sub in [("bars_to_entry=1 (fill immediato)", sub_bte1),
                            ("bars_to_entry>1 (fill ritardato)", sub_bte_gt1),
                            ("Tutti filled", filled)]:
            if sub:
                n = len(sub); w = sum(1 for r in sub if r["_pnl"]>0)
                avg_n = sum(r["_pnl"] for r in sub)/n
                wr = w/n*100
                print(f"  {label:30s} {n:>6} {wr:>5.1f}% {avg_n:>+10.4f}R")


def parte_c4_limit_vs_market(raw: list[dict]) -> None:
    _hdr("C4. LIMIT VS MARKET ENTRY — ANALISI NO-FILL")
    print("  Sistema attuale: LMT al close candela pattern.")
    print("  Se open bar+1 > close pattern (per LONG) → no fill → trade perso.")
    print()

    filled = [r for r in raw if r["_filled"] and r["_fascia"] in ("ALPHA","MIDDAY_F")]
    no_fill_all = [r for r in raw if not r["_filled"]]
    no_fill_triplo = [r for r in no_fill_all if r["_fascia"] in ("ALPHA","MIDDAY_F")]

    n_total_opps = len(filled) + len(no_fill_triplo)
    print(f"  Opportunità TRIPLO totali: {n_total_opps}")
    print(f"  Fill eseguiti:  {len(filled)} ({len(filled)/n_total_opps*100:.1f}%)")
    print(f"  No fill TRIPLO: {len(no_fill_triplo)} ({len(no_fill_triplo)/n_total_opps*100:.1f}%)")
    print()

    # Per i no-fill, non abbiamo pnl_r (è 0.0). Ma abbiamo pattern_name, direction, final_score
    # Possiamo vedere la qualità dei trade persi vs quelli eseguiti (final_score comparison)
    print(f"  Qualità dei trade NO-FILL vs FILL (final_score):")
    fs_fill = [float(r.get("final_score","0")) for r in filled]
    fs_nf = [float(r.get("final_score","0")) for r in no_fill_triplo]

    if fs_fill:
        avg_fs_fill = sum(fs_fill)/len(fs_fill)
        avg_fs_nf = sum(fs_nf)/len(fs_nf) if fs_nf else 0
        print(f"  avg final_score FILL:    {avg_fs_fill:.2f}")
        print(f"  avg final_score NO-FILL: {avg_fs_nf:.2f}")
        diff = avg_fs_nf - avg_fs_fill
        print(f"  Δ = {diff:+.2f} (positivo → trade persi hanno score più alto = gap sfavorevole su trade migliori)")

    print()
    print(f"  {'Situazione':35s} {'n':>6} {'%':>6} {'avg pnl_r':>10} {'avg final_score':>16}")
    _sep()

    # Per i fill: suddividi per bars_to_entry
    by_bte: dict[str, list] = defaultdict(list)
    for r in filled:
        bte = str(r.get("bars_to_entry","?"))
        by_bte[bte].append(r)

    rows_table = [
        ("Fill barra+1 (LMT immediato)", by_bte.get("1", [])),
        ("Fill barra+2 (LMT delay)",     by_bte.get("2", [])),
        ("Fill barra+3 (LMT long delay)",by_bte.get("3", [])),
    ]
    for label, sub in rows_table:
        if not sub: continue
        n = len(sub)
        pct = n/n_total_opps*100
        avg_pnl = sum(r["_pnl"] for r in sub)/n
        avg_fs = sum(float(r.get("final_score","0")) for r in sub)/n
        print(f"  {label:35s} {n:>6} {pct:>5.1f}% {avg_pnl:>+10.4f}R {avg_fs:>16.2f}")

    # No-fill
    if no_fill_triplo:
        n_nf = len(no_fill_triplo)
        pct_nf = n_nf/n_total_opps*100
        avg_fs_nf_v = sum(float(r.get("final_score","0")) for r in no_fill_triplo)/n_nf
        print(f"  {'No fill (trade perso)':35s} {n_nf:>6} {pct_nf:>5.1f}% {'—':>10}  {avg_fs_nf_v:>16.2f}")

    print()
    print("  ANALISI: se avg_pnl di barra+1 > barra+2 > barra+3 → il ritardo peggiora l'EV")
    print("  Se i no-fill hanno final_score > fill → stiamo perdendo i trade migliori con LMT")
    print()
    print("  SOLUZIONE SE GRADE SFAVOREVOLE:")
    print("  LMT + buffer: entry = close_pattern + 0.05% (per LONG)")
    print("  → cattura gap di apertura fino a 0.05% → più fill, costo marginalmente peggiore")

    # Impatto buffer su fill rate (stima)
    print()
    print("  Stima impatto buffer LMT+0.05% (ipotetica):")
    # Se il gap medio sfavorevole è X%, e buffer è 0.05%, guadagniamo (buffer/avg_gap)% di no-fill
    # Non possiamo calcolare esattamente senza open price, ma forniamo range teorico
    print("  Con buffer 0.05%: potenzialmente cattura trade con gap ≤ 0.05% sfavorevole")
    print("  Stima fill rate aggiuntivo: 5-15% dei no-fill (gap piccoli)")
    avg_fill_pnl = sum(r["_pnl"] for r in filled)/len(filled) if filled else 0
    print(f"  Se avg pnl_r dei nuovi fill ≈ avg fill attuale ({avg_fill_pnl:+.4f}R): impatto positivo")
    print(f"  Se avg pnl_r nuovi fill ≈ 0 (gap crea entry neutra): impatto ≈ nullo")

    # Pattern breakdown no-fill
    print()
    print("  No-fill per pattern:")
    by_pat_nf: dict[str, int] = defaultdict(int)
    by_pat_fill: dict[str, int] = defaultdict(int)
    for r in no_fill_triplo:
        by_pat_nf[r.get("pattern_name","")] += 1
    for r in filled:
        by_pat_fill[r.get("pattern_name","")] += 1

    print(f"  {'Pattern':30s} {'fill':>6} {'no-fill':>8} {'no-fill%':>9}")
    _sep()
    all_pats = sorted(set(list(by_pat_fill.keys()) + list(by_pat_nf.keys())))
    for pat in all_pats:
        nf_c = by_pat_fill.get(pat, 0)
        nf_n = by_pat_nf.get(pat, 0)
        total_p = nf_c + nf_n
        pct_nf_p = nf_n/total_p*100 if total_p else 0
        print(f"  {pat:30s} {nf_c:>6} {nf_n:>8} {pct_nf_p:>8.1f}%")


# ════════════════════════════════════════════════════════════════════════════
# RIEPILOGO FINALE
# ════════════════════════════════════════════════════════════════════════════

def riepilogo(filled: list[dict]) -> None:
    _hdr("RIEPILOGO AZIONI PRIORITARIE")
    print()

    alpha = [r for r in filled if r["_fascia"] == "ALPHA"]
    midday = [r for r in filled if r["_fascia"] == "MIDDAY_F"]

    def _quick_stats(sub: list) -> str:
        if not sub: return "n/a"
        n = len(sub)
        w = sum(1 for r in sub if r["_pnl"] > 0)
        avg = sum(r["_pnl"] for r in sub)/n
        wr = w/n*100
        return f"n={n} WR={wr:.1f}% avg+slip={avg:+.4f}R"

    print(f"  ALPHA (15:xx):   {_quick_stats(alpha)}")
    print(f"  MIDDAY_F (11-14): {_quick_stats(midday)}")
    print()
    print("  ┌─ PRIORITÀ 1: Aggiungere VOLUME al CSV ────────────────────────────────┐")
    print("  │  Modificare build_validation_dataset.py per includere:               │")
    print("  │  - candle.volume (volume candela pattern)                             │")
    print("  │  - SMA20 del volume per simbolo (da calcolare sulla serie storica)    │")
    print("  │  - candle.open, candle.high, candle.low (per C2, C3, trailing)       │")
    print("  │  - candle_next.open (per analisi gap entry)                           │")
    print("  └────────────────────────────────────────────────────────────────────────┘")
    print()
    print("  ┌─ PRIORITÀ 2: TP1 OTTIMALE ────────────────────────────────────────────┐")
    print("  │  Vedere B1/B2: quale TP1 massimizza avg_r+slip per ALPHA vs MIDDAY.  │")
    print("  │  Se ALPHA si comporta meglio con TP più alto → movimenti più veloci. │")
    print("  └────────────────────────────────────────────────────────────────────────┘")
    print()
    print("  ┌─ PRIORITÀ 3: ENTRY TIMING ─────────────────────────────────────────────┐")
    print("  │  Se bars_to_entry=1 >> bars_to_entry>1 → il sistema è già ottimale.  │")
    print("  │  Se bars_to_entry=2-3 è peggio → valutare LMT+buffer (C4).          │")
    print("  └────────────────────────────────────────────────────────────────────────┘")
    print()
    print("  ┌─ PRIORITÀ 4: TRAILING STOP ─────────────────────────────────────────────┐")
    print("  │  Aggiungere MFE (max favorable excursion) al CSV per quantificare     │")
    print("  │  il beneficio reale del trailing stop sui trade STOP.                  │")
    print("  └─────────────────────────────────────────────────────────────────────────┘")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/val_5m_expanded.csv")
    args = parser.parse_args()

    path = Path(args.dataset)
    if not path.exists():
        print(f"ERRORE: {path} non trovato", file=sys.stderr)
        sys.exit(1)

    raw, filled = load_data(path)

    # ── PARTE A ──────────────────────────────────────────────────────────────
    parte_a_volume(raw)

    # ── PARTE B ──────────────────────────────────────────────────────────────
    parte_b1_tp_per_fascia(filled)
    parte_b2_tp_per_pattern(filled)
    parte_b3_tp_per_regime(filled)
    parte_b4_stop_loss(filled)
    parte_b5_stop_per_fascia(filled)
    parte_b6_trailing_stop(filled)

    # ── PARTE C ──────────────────────────────────────────────────────────────
    parte_c1_entry_timing(filled, raw)
    parte_c2_entry_position(filled)
    parte_c3_gap_entry(filled)
    parte_c4_limit_vs_market(raw)

    # ── RIEPILOGO ────────────────────────────────────────────────────────────
    riepilogo(filled)


if __name__ == "__main__":
    main()
