#!/usr/bin/env python3
"""
slot_ep_analysis.py — Confronto Strategia E vs E+ (prestito bidirezionale)
===========================================================================
E  : 3 slot 1h (1h puo' prendere slot 5m; 5m NON puo' usare slot 1h)
E+ : slot 1h PRIORITARI ma 5m li usa quando VUOTI
     - 5m arriva, slot 5m pieni, slot 1h liberi → usa slot 1h temporaneamente
     - 1h arriva, slot 1h pieni di 5m (in prestito) → sfratta il 5m PIU' VECCHIO
     - 1h NON chiude MAI un 1h per fare spazio a un 5m
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Importa preparazione dati da slot_analysis.py
sys.path.insert(0, str(Path(__file__).parent))
from slot_analysis import (
    _prepare,
    _load_csv,
    _data_years,
    _stats,
    SLIP,
    RISK,
    CAPITAL,
)

# ── Costanti slot ─────────────────────────────────────────────────────────────
SLOTS_1H  = 3
SLOTS_5M  = 2
MAX_TOTAL = 5


# ── Helper ────────────────────────────────────────────────────────────────────

def _expire(active: list[dict], entry_time: datetime) -> list[dict]:
    return [a for a in active if a["exit_time"] > entry_time]


def _count(active: list[dict]) -> tuple[int, int, int, int]:
    """n_1h_in_1h, n_5m_in_1h, n_1h_in_5m, n_5m_in_5m"""
    n1h1 = sum(1 for a in active if a.get("timeframe","5m")=="1h" and a["slot"]=="1h")
    n5m1 = sum(1 for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="1h")
    n1h5 = sum(1 for a in active if a.get("timeframe","5m")=="1h" and a["slot"]=="5m")
    n5m5 = sum(1 for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="5m")
    return n1h1, n5m1, n1h5, n5m5


# ── Strategy E (attuale: 1h puo' prendere slot 5m, 5m NON viceversa) ─────────

def strategy_e(trades: list[dict]) -> tuple[list, list, list]:
    executed, skipped, replaced = [], [], []
    active: list[dict] = []

    for t in trades:
        active = _expire(active, t["entry_time"])
        n1h1, n5m1, n1h5, n5m5 = _count(active)
        tf = t.get("timeframe","5m").strip().lower()

        if tf == "1h":
            if n1h1 + n5m1 < SLOTS_1H:     # slot 1h proprio libero
                active.append({**t, "slot":"1h"})
                executed.append(t)
            elif n1h5 + n5m5 < SLOTS_5M:   # prende in prestito slot 5m
                active.append({**t, "slot":"5m"})
                executed.append(t)
            else:
                skipped.append(t)
        else:  # 5m: solo slot 5m propri
            n_5m_overflow = max(0, n1h1 + n5m1 - SLOTS_1H)  # wait, this is wrong
            # In E, 5m has only 2 slots, reduced when 1h borrows
            n1h_borrow_5m = n1h5  # 1h trades in 5m slot
            n5m_used = n5m5 + n1h_borrow_5m
            if n5m_used < SLOTS_5M:
                active.append({**t, "slot":"5m"})
                executed.append(t)
            else:
                skipped.append(t)

    return executed, skipped, replaced


# ── Strategy E+ (prestito bidirezionale, sfratto 5m per 1h) ──────────────────

def strategy_ep(
    trades: list[dict],
    repl_cost: float = 0.0,
) -> tuple[list, list, list, list]:
    """
    Ritorna: (executed, skipped, replaced, evictions_info)
    evictions_info: lista di dict con info sul trade 5m sfrattato
    """
    executed: list[dict] = []
    skipped:  list[dict] = []
    replaced: list[dict] = []  # sfrattati (pnl_r = repl_cost)
    evictions: list[dict] = []

    active: list[dict] = []

    for t in trades:
        active = _expire(active, t["entry_time"])
        n1h1, n5m1, n1h5, n5m5 = _count(active)

        # Slot liberi totali
        n1h_free = SLOTS_1H - n1h1 - n5m1   # slot 1h senza nessun trade
        n5m_free = SLOTS_5M - n1h5 - n5m5   # slot 5m senza nessun trade

        tf = t.get("timeframe","5m").strip().lower()

        if tf == "1h":
            if n1h_free > 0:
                # Slot 1h proprio libero
                active.append({**t, "slot":"1h"})
                executed.append(t)

            elif n5m_free > 0:
                # Prende in prestito slot 5m
                active.append({**t, "slot":"5m"})
                executed.append(t)

            elif n5m1 > 0:
                # Slot 1h occupati da 5m in prestito → sfratta il piu' vecchio
                # Trova il 5m piu' vecchio tra quelli in slot "1h"
                candidates = [a for a in active if a.get("timeframe","5m")=="5m" and a["slot"]=="1h"]
                oldest = min(candidates, key=lambda a: a["entry_time"])

                # Calcola quanto del trade era trascorso (per stima costo)
                elapsed = (t["entry_time"] - oldest["entry_time"]).total_seconds()
                total   = (oldest["exit_time"] - oldest["entry_time"]).total_seconds()
                elapsed_frac = min(1.0, max(0.0, elapsed / total)) if total > 0 else 0.5

                evictions.append({
                    "symbol":       oldest.get("symbol","?"),
                    "entry_time":   oldest["entry_time"],
                    "exit_time":    oldest["exit_time"],
                    "pnl_r_final":  oldest["pnl_r"],   # pnl_r backtest originale
                    "elapsed_frac": elapsed_frac,
                    "repl_cost":    repl_cost,
                })

                # Sfratta il 5m con pnl_r = repl_cost
                active.remove(oldest)
                rep = dict(oldest)
                rep["pnl_r"] = repl_cost
                replaced.append(rep)

                # Apri il 1h
                active.append({**t, "slot":"1h"})
                executed.append(t)

            else:
                # Tutti i 3 slot 1h occupati da trade 1h (+ slot 5m occupati)
                skipped.append(t)

        else:  # 5m
            if n5m_free > 0:
                # Slot 5m proprio libero
                active.append({**t, "slot":"5m"})
                executed.append(t)

            elif n1h_free > 0:
                # Slot 1h libero (non occupato da nessun trade) → 5m lo prende temporaneamente
                active.append({**t, "slot":"1h"})
                executed.append(t)

            else:
                # Slot 1h occupati (da 1h o altri 5m); 5m non chiude mai nessuno
                skipped.append(t)

    return executed, skipped, replaced, evictions


# ── Statistiche annualizzate ──────────────────────────────────────────────────

def _annual(all_positions: list[dict], years: float) -> dict:
    if not all_positions:
        return {"n":0, "tpy":0, "avg_gross":0, "avg_net":0, "wr":0, "rend":0}
    pnls = [p["pnl_r"] for p in all_positions]
    n    = len(pnls)
    avg  = sum(pnls) / n
    wr   = sum(1 for p in pnls if p > 0) / n * 100
    tpy  = n / years
    avg_net = avg - SLIP
    rend    = tpy * avg_net * RISK * 100
    return {"n": n, "tpy": tpy, "avg_gross": avg, "avg_net": avg_net, "wr": wr, "rend": rend}


def _total_r_per_year(all_positions: list[dict], years: float) -> float:
    """Somma R netti all'anno (misura piu' diretta del profitto totale)."""
    total_r_net = sum(p["pnl_r"] for p in all_positions) - len(all_positions) * SLIP
    return total_r_net / years


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    base = Path(__file__).parent
    p1h  = base / "data" / "val_1h_production.csv"
    p5m  = base / "data" / "val_5m_expanded.csv"

    print("Caricamento e filtri...")
    raw_1h = _load_csv(p1h)
    raw_5m = _load_csv(p5m)
    trades = _prepare(raw_1h, raw_5m)
    years  = _data_years(trades)
    n_1h   = sum(1 for t in trades if t.get("timeframe") == "1h")
    n_5m   = sum(1 for t in trades if t.get("timeframe") == "5m")
    print(f"  Trade combinati: {len(trades):,}  ({n_1h} 1h + {n_5m} 5m)  |  {years:.2f} anni\n")

    # ── Run strategie ─────────────────────────────────────────────────────────
    ex_e, sk_e, rep_e           = strategy_e(trades)
    ex_ep0, sk_ep0, rep_ep0, ev0  = strategy_ep(trades, repl_cost=0.00)
    ex_ep1, sk_ep1, rep_ep1, ev1  = strategy_ep(trades, repl_cost=-0.10)
    ex_ep2, sk_ep2, rep_ep2, ev2  = strategy_ep(trades, repl_cost=-0.20)

    # ── Tabella confronto ─────────────────────────────────────────────────────
    print("=" * 90)
    print("CONFRONTO E vs E+")
    print("=" * 90)

    rows = [
        ("E  (attuale, no borrow 5m→1h)", ex_e,  rep_e,  []),
        ("E+ cost=0.00R",                 ex_ep0, rep_ep0, ev0),
        ("E+ cost=-0.10R",                ex_ep1, rep_ep1, ev1),
        ("E+ cost=-0.20R",                ex_ep2, rep_ep2, ev2),
    ]

    header = (
        f"  {'Strategia':<32}  {'n_pos':>6}  {'n_sost':>6}  "
        f"{'avg_r(G)':>9}  {'avg_r(N)':>9}  {'WR%':>6}  "
        f"{'R_net/a':>8}  {'Rend%/a':>8}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    best_r = None
    for label, ex, rep, ev in rows:
        all_pos = ex + rep
        s   = _annual(all_pos, years)
        rya = _total_r_per_year(all_pos, years)
        if best_r is None:
            best_r = rya  # baseline = E
        flag = "  <-- BEST" if rya > best_r else ""
        best_r = max(best_r, rya)
        print(
            f"  {label:<32}  {len(all_pos):>6,}  {len(rep):>6,}  "
            f"{s['avg_gross']:>+9.3f}R  {s['avg_net']:>+9.3f}R  {s['wr']:>5.1f}%  "
            f"{rya:>+8.1f}R  {s['rend']:>+7.1f}%{flag}"
        )

    # ── Analisi dettagliata degli sfratti ─────────────────────────────────────
    print()
    print("=" * 90)
    print(f"ANALISI SFRATTI (E+ cost=0R — {len(ev0)} eventi)")
    print("=" * 90)

    if ev0:
        pnl_finals = [e["pnl_r_final"] for e in ev0]
        elapsed_fracs = [e["elapsed_frac"] for e in ev0]

        n_ev = len(ev0)
        avg_pnl_final = sum(pnl_finals) / n_ev
        pct_winning   = sum(1 for p in pnl_finals if p > 0) / n_ev * 100
        pct_losing    = sum(1 for p in pnl_finals if p < 0) / n_ev * 100
        avg_elapsed   = sum(elapsed_fracs) / n_ev * 100

        print(f"\n  Trade 5m sfrattati: {n_ev}")
        print(f"  avg_r finale atteso (se non sfrattato):  {avg_pnl_final:+.3f}R")
        print(f"  % sfrattati che avrebbero VINTO:         {pct_winning:.1f}%")
        print(f"  % sfrattati che avrebbero PERSO:         {pct_losing:.1f}%")
        print(f"  Durata media trascorsa al momento sfratto: {avg_elapsed:.1f}% del trade")

        # Distribuzione pnl_r dei sfrattati
        def _bkt(p):
            if p < -1: return "< -1R"
            if p < 0:  return "-1R-0R"
            if p < 1:  return "0R-1R"
            if p < 2:  return "1R-2R"
            return "> 2R"
        from collections import Counter
        dist = Counter(_bkt(p) for p in pnl_finals)
        buckets = ["< -1R","-1R-0R","0R-1R","1R-2R","> 2R"]
        print()
        print(f"  Distribuzione pnl_r dei trade 5m sfrattati:")
        for b in buckets:
            cnt = dist.get(b, 0)
            bar = "#" * int(cnt / max(1, n_ev) * 40)
            print(f"    {b:<8} {cnt:>5} ({cnt/n_ev*100:>5.1f}%)  {bar}")

        # Costo reale medio dello sfratto
        # In production: chiudi a mercato → P&L = qualcosa tra 0 e pnl_r_final
        # Stima conservativa: perdi ~50% del trade atteso
        print()
        print("  Stima costo sfratto in produzione:")
        print(f"    Se uscita a breakeven (0R):        costo = +{-0:+.3f}R/sfratto")
        est_cost_realistic = -abs(avg_pnl_final) * 0.3 - 0.10  # conservative estimate
        print(f"    Stima realistica (-bid-ask -0.1R): costo ≈ {est_cost_realistic:+.3f}R/sfratto")
        print(f"    Con {n_ev} sfratti/anno → costo totale ≈ {est_cost_realistic * n_ev / years:+.1f}R/anno")

        # Confronto 1h che ha sostituito
        print()
        ex_1h_after_eviction = []
        # Trova i 1h che sono stati eseguiti proprio sfrattando un 5m
        # (li identifichiamo dai trade 1h che avevano n_5m_in_1hprio > 0 al momento)
        # Approssimazione: guarda l'avg_r degli eseguiti 1h in E+ vs E
        ex_1h_e  = [t for t in ex_e  if t.get("timeframe") == "1h"]
        ex_1h_ep = [t for t in ex_ep0 if t.get("timeframe") == "1h"]
        _, avg1h_e,  wr1h_e  = _stats(ex_1h_e)
        _, avg1h_ep, wr1h_ep = _stats(ex_1h_ep)
        print(f"  Trade 1h eseguiti:  E={len(ex_1h_e):,} avg_r={avg1h_e:+.3f}R WR={wr1h_e:.1f}%")
        print(f"  Trade 1h eseguiti: E+={len(ex_1h_ep):,} avg_r={avg1h_ep:+.3f}R WR={wr1h_ep:.1f}%")

        ex_5m_e  = [t for t in ex_e  if t.get("timeframe") == "5m"]
        ex_5m_ep = [t for t in ex_ep0 if t.get("timeframe") == "5m"]
        _, avg5m_e,  wr5m_e  = _stats(ex_5m_e)
        _, avg5m_ep, wr5m_ep = _stats(ex_5m_ep)
        print(f"  Trade 5m eseguiti:  E={len(ex_5m_e):,} avg_r={avg5m_e:+.3f}R WR={wr5m_e:.1f}%")
        print(f"  Trade 5m eseguiti: E+={len(ex_5m_ep):,} avg_r={avg5m_ep:+.3f}R WR={wr5m_ep:.1f}%")

    else:
        print("\n  NESSUNO SFRATTO: il 5m non riesce mai a occupare slot 1h")
        print("  (i trade 5m scadono prima che arrivi un 1h in competizione)")
        print("  -> E e E+ sono equivalenti nei numeri.")

    # ── Distribuzione temporale degli sfratti ─────────────────────────────────
    if ev0:
        print()
        print("  Distribuzione oraria degli sfratti (ora ET del segnale 1h che ha sfrattato):")
        from collections import Counter
        hour_dist = Counter()
        for ev in ev0:
            # Approssimazione: usa l'entry_time del 5m sfrattato
            h = ev["entry_time"].hour  # UTC — approssimazione
            hour_dist[h] += 1
        for h in sorted(hour_dist):
            bar = "#" * int(hour_dist[h] / max(1, len(ev0)) * 30)
            print(f"    {h:02d}h UTC  {hour_dist[h]:>4}  {bar}")

    # ── Tabella dettaglio 1h vs 5m per tutte le strategie ─────────────────────
    print()
    print("=" * 90)
    print("DETTAGLIO 1h vs 5m per ogni scenario")
    print("=" * 90)
    print(f"  {'Strategia':<28}  {'1h_n':>6}  {'1h_avgR':>8}  {'1h_WR':>6}  "
          f"{'5m_n':>6}  {'5m_avgR':>8}  {'5m_WR':>6}")
    print("  " + "-" * 75)

    scenarios = [
        ("E",          ex_e,   rep_e),
        ("E+ cost=0R", ex_ep0, rep_ep0),
        ("E+ cost=-0.10R", ex_ep1, rep_ep1),
        ("E+ cost=-0.20R", ex_ep2, rep_ep2),
    ]
    for label, ex, rep in scenarios:
        all_pos = ex + rep
        e_1h = [t for t in all_pos if t.get("timeframe") == "1h"]
        e_5m = [t for t in all_pos if t.get("timeframe") == "5m"]
        n1, a1, w1 = _stats(e_1h)
        n5, a5, w5 = _stats(e_5m)
        print(f"  {label:<28}  {n1:>6,}  {a1:>+8.3f}R  {w1:>5.1f}%  "
              f"{n5:>6,}  {a5:>+8.3f}R  {w5:>5.1f}%")

    # ── Raccomandazione finale ─────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("RACCOMANDAZIONE")
    print("=" * 90)

    # Calcola R_net/anno per ogni scenario
    results_rpy = {}
    for label, ex, rep, ev in rows:
        all_pos = ex + rep
        results_rpy[label] = _total_r_per_year(all_pos, years)

    rpy_e   = results_rpy["E  (attuale, no borrow 5m→1h)"]
    rpy_ep0 = results_rpy["E+ cost=0.00R"]
    rpy_ep1 = results_rpy["E+ cost=-0.10R"]
    rpy_ep2 = results_rpy["E+ cost=-0.20R"]

    n_sost = len(ev0)
    sost_per_anno = n_sost / years

    print()
    print(f"  R_net/anno — E: {rpy_e:+.1f}R  E+(0R): {rpy_ep0:+.1f}R  "
          f"E+(-0.10R): {rpy_ep1:+.1f}R  E+(-0.20R): {rpy_ep2:+.1f}R")
    print(f"  Sfratti/anno: {sost_per_anno:.1f}")
    print()

    if rpy_ep2 > rpy_e:
        print("  -> E+ CONVIENE anche con -0.20R per sfratto.")
        print("     Implementa E+ (prestito bidirezionale con sfratto 5m piu' vecchio).")
        print("     Il guadagno in trade 1h catturati supera il costo degli sfratti.")
    elif rpy_ep1 > rpy_e:
        print("  -> E+ CONVIENE con -0.10R ma NON con -0.20R.")
        print("     Conviene se il costo reale di chiusura anticipata e' < 0.10-0.15R.")
        print("     Per IBKR con trade 5m intraday (poche ore), costo realistico ~0.05-0.12R.")
        print("     RACCOMANDAZIONE: implementa E+ ma monitora il costo reale degli sfratti.")
    elif rpy_ep0 > rpy_e:
        print("  -> E+ conviene SOLO se gli sfratti costano 0R (breakeven esatto).")
        print("     Con qualsiasi costo reale > 0, E rimane migliore.")
        print("     MANTIENI Strategy E attuale.")
    else:
        print("  -> E e E+ producono risultati equivalenti.")
        print(f"     ({sost_per_anno:.0f} sfratti/anno, impatto marginale)")
        if sost_per_anno < 10:
            print("     Pochissimi sfratti: E+ non porta benefici materiali.")
            print("     MANTIENI Strategy E attuale — meno complessita' operativa.")
        else:
            print("     MANTIENI Strategy E attuale.")

    print()
    print("  NOTE:")
    print(f"  - 'R_net/anno' = sum(pnl_r - slip) / anni  (misura diretta del profitto totale)")
    print(f"  - 'Rend%/a' = trades/a x avg_r_net x 0.5% risk (non composta)")
    print(f"  - Costo sfratto = pnl_r assegnato al trade 5m chiuso anticipatamente")
    print(f"    In produzione: ~0.05-0.15R (bid-ask spread + slippage chiusura MKT)")


if __name__ == "__main__":
    main()
