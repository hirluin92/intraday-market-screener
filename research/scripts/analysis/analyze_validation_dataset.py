"""
analyze_validation_dataset.py
==============================
Misurazioni empiriche sul dataset di validazione:

  1.  Expectancy per timeframe (WR + avg_r + Wilson CI)
  1b. Expectancy per (timeframe × pattern_name) — top-5 pattern per TF
  2.  AUC pq vs win (senza sklearn — formula Mann-Whitney O(n²))
  3.  WR per timeframe filtrata su "simulated execute" (final_score >= soglia)
  4.  Correlazione WR(pattern_name) vs pq(pattern_name) a livello aggregato
  4b. Spearman stratificato per timeframe (globale vs TF-specifico)
  5.  AUC di tutti i componenti del final_score:
        pattern_strength, screener_score, pattern_quality_score, final_score
      → risponde a: "dove sta davvero l'edge nel final_score?"
  6.  AUC per pattern_name (n>=30): inversione uniforme o condizionale?
      Per ogni pattern calcola AUC(strength), AUC(screener_score), AUC(pq).
      → risponde a: "strength invertita su tutti i pattern o solo su alcuni?"
  7.  AUC screener_score stratificato per trade_direction (long vs short).
      → risponde a: "screener sbaglia la direzione o sbaglia il valore?"
  9.  Sub-sistema "pattern che funzionano": volume e performance dei pattern
      con max(AUC) >= soglia empirica. Risponde a: il problema è riparare
      il sistema, o estrarre e tenere solo il sub-sistema che già funziona?
  10. Validazione Strada A: gate binario per contro-trend + ranker per trend-following.
      Misura avg_r e WR della strategia ibrida vs sistema attuale, SENZA scrivere
      una riga di validator — usa i dati storici come proxy per il deploy.
  + Bonus: distribuzione temporale per trimestre (per verificare bias di periodo)

Uso:
  cd backend
  python analyze_validation_dataset.py --dataset data/validation_set_v1.csv
  python analyze_validation_dataset.py --dataset data/validation_set_v1.csv --execute-threshold 60
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    center = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margin = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / (1 + z**2 / n)
    return round(max(0.0, center - margin) * 100, 1), round(min(1.0, center + margin) * 100, 1)


def _auc_mann_whitney(scores: list[float], labels: list[int]) -> float:
    """
    AUC (ROC) calcolata con la statistica di Mann-Whitney.

    Non richiede sklearn: AUC = P(score_win > score_loss) per una coppia
    (win, loss) estratta casualmente. Trattamento legami: 0.5 per coppia.

    Complessità: O(n_win * n_loss). Per n~220 è istantaneo.
    """
    wins = [s for s, l in zip(scores, labels) if l == 1]
    losses = [s for s, l in zip(scores, labels) if l == 0]
    if not wins or not losses:
        return 0.5
    concordant = sum(1 for w in wins for l in losses if w > l)
    tied = sum(0.5 for w in wins for l in losses if w == l)
    return (concordant + tied) / (len(wins) * len(losses))


def _spearman_r(x: list[float], y: list[float]) -> float:
    """Spearman correlation tramite rank. Robusto a outlier e relazioni monotone non lineari."""
    n = len(x)
    if n < 2:
        return 0.0

    def _rank(vals: list[float]) -> list[float]:
        sorted_idx = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[sorted_idx[j + 1]] == vals[sorted_idx[j]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[sorted_idx[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    den_x = (sum((a - mean_rx) ** 2 for a in rx)) ** 0.5
    den_y = (sum((b - mean_ry) ** 2 for b in ry)) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _pearson_r(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = (sum((a - mx) ** 2 for a in x)) ** 0.5
    dy = (sum((b - my) ** 2 for b in y)) ** 0.5
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


def _quarter(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    except Exception:
        return "unknown"


def load_dataset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # cast numerici
    for r in rows:
        r["pnl_r"] = float(r["pnl_r"])
        r["final_score"] = float(r["final_score"]) if r.get("final_score") else 0.0
        r["entry_filled"] = r["entry_filled"] == "True"
        r["pattern_quality_score"] = (
            float(r["pattern_quality_score"])
            if r.get("pattern_quality_score") not in (None, "", "None")
            else None
        )
        r["screener_score"] = float(r.get("screener_score") or 0)
        r["pattern_strength"] = float(r.get("pattern_strength") or 0)
        r["win"] = 1 if r["pnl_r"] > 0 and r["entry_filled"] else 0
    return rows


# ---------------------------------------------------------------------------
# 1. Expectancy per timeframe (WR + avg_r + Wilson CI)
# ---------------------------------------------------------------------------

def section_expectancy_by_tf(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("1. EXPECTANCY PER TIMEFRAME (risposta: 1d ha EV positivo nonostante WR bassa?)")
    print("=" * 78)

    filled = [r for r in rows if r["entry_filled"]]
    by_tf: dict[str, list] = defaultdict(list)
    for r in filled:
        by_tf[r["timeframe"]].append(r)

    print(f"  {'TF':6s}  {'n':>5}  {'WR%':>7}  {'CI 95%':>14}  {'AvgR':>7}  {'EV sign':>10}  {'WinAvgR':>8}  {'LossAvgR':>9}")
    print("  " + "-" * 70)
    for tf, tfrows in sorted(by_tf.items()):
        n = len(tfrows)
        wins = [r for r in tfrows if r["pnl_r"] > 0]
        losses = [r for r in tfrows if r["pnl_r"] <= 0]
        wr = len(wins) / n * 100
        avg_r = sum(r["pnl_r"] for r in tfrows) / n
        ci_lo, ci_hi = _wilson_ci(len(wins), n)
        win_avg = sum(r["pnl_r"] for r in wins) / len(wins) if wins else 0
        loss_avg = sum(r["pnl_r"] for r in losses) / len(losses) if losses else 0
        ev_sign = "✓ +EV" if avg_r > 0 else "✗ -EV"
        print(f"  {tf:6s}  {n:>5}  {wr:>6.1f}%  [{ci_lo:.1f}%-{ci_hi:.1f}%]  {avg_r:>7.3f}R  {ev_sign:>10}  {win_avg:>8.3f}R  {loss_avg:>9.3f}R")

    print()
    print("  NOTA: avg_r già include entrambi i lati (win e loss) — è l'expectancy diretta.")
    print("  Un avg_r >0 con WR <50% indica che le size dei win sono maggiori delle size dei loss.")


# ---------------------------------------------------------------------------
# 1b. Expectancy per (timeframe × pattern_name) — top-N per TF
# ---------------------------------------------------------------------------

def section_expectancy_by_tf_pattern(rows: list[dict], top_n: int = 8) -> None:
    print("\n" + "=" * 78)
    print("1b. EXPECTANCY PER (TIMEFRAME × PATTERN_NAME) — top pattern per TF")
    print("=" * 78)
    print(f"    (mostra i {top_n} pattern più numerosi per ciascun TF con n>=5)")

    filled = [r for r in rows if r["entry_filled"]]
    by_tf_pat: dict[tuple[str, str], list] = defaultdict(list)
    for r in filled:
        by_tf_pat[(r["timeframe"], r["pattern_name"])].append(r)

    by_tf: dict[str, dict[str, list]] = defaultdict(dict)
    for (tf, pat), prows in by_tf_pat.items():
        by_tf[tf][pat] = prows

    for tf in sorted(by_tf.keys()):
        pat_map = by_tf[tf]
        ordered = sorted(pat_map.items(), key=lambda x: -len(x[1]))
        candidates = [(pat, prows) for pat, prows in ordered if len(prows) >= 5]
        print(f"\n  TF={tf} — top {min(top_n, len(candidates))} pattern (su {len(candidates)} con n>=5):")
        print(f"  {'Pattern':40s}  {'n':>4}  {'WR%':>7}  {'CI 95%':>14}  {'AvgR':>7}  {'WinR':>7}  {'LossR':>7}")
        print("  " + "-" * 88)
        for pat, prows in candidates[:top_n]:
            n = len(prows)
            wins = [r for r in prows if r["pnl_r"] > 0]
            losses = [r for r in prows if r["pnl_r"] <= 0]
            wr = len(wins) / n * 100
            avg = sum(r["pnl_r"] for r in prows) / n
            win_avg = sum(r["pnl_r"] for r in wins) / len(wins) if wins else 0
            loss_avg = sum(r["pnl_r"] for r in losses) / len(losses) if losses else 0
            clo, chi = _wilson_ci(len(wins), n)
            print(f"  {pat:40s}  {n:>4}  {wr:>6.1f}%  [{clo:.1f}%-{chi:.1f}%]  {avg:>7.3f}R  {win_avg:>7.3f}R  {loss_avg:>7.3f}R")


# ---------------------------------------------------------------------------
# 2. AUC pq vs win
# ---------------------------------------------------------------------------

def section_auc_pq(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("2. AUC pattern_quality_score vs WIN (Mann-Whitney, nessuna dipendenza esterna)")
    print("=" * 78)

    pq_rows = [r for r in rows if r["entry_filled"] and r["pattern_quality_score"] is not None]
    if not pq_rows:
        print("  Nessun record con pq disponibile.")
        return

    scores = [r["pattern_quality_score"] for r in pq_rows]
    labels = [r["win"] for r in pq_rows]
    auc = _auc_mann_whitney(scores, labels)
    pearson = _pearson_r(scores, [float(l) for l in labels])
    spearman = _spearman_r(scores, [float(l) for l in labels])

    print(f"  n con pq non-null:  {len(pq_rows)}")
    print(f"  AUC (Mann-Whitney): {auc:.4f}")
    print(f"  Pearson  r(pq,win): {pearson:.4f}")
    print(f"  Spearman r(pq,win): {spearman:.4f}")
    print()

    if auc >= 0.60:
        interp = "SEGNALE FORTE: pq ha potere predittivo reale. Problema è nel peso, non nella metrica."
    elif auc >= 0.55:
        interp = "SEGNALE DEBOLE ma reale: edge piccolo, peso 14 amplifica rumore > segnale."
    elif auc >= 0.52:
        interp = "SEGNALE MOLTO DEBOLE: quasi caso. C1 è urgente — la metrica va rifatta."
    else:
        interp = "RUMORE PURO: pq non predice il win. C1 è il problema principale del sistema."

    print(f"  Interpretazione: {interp}")

    # AUC stratificata per timeframe
    print()
    print(f"  AUC per timeframe:")
    by_tf: dict[str, list] = defaultdict(list)
    for r in pq_rows:
        by_tf[r["timeframe"]].append(r)
    for tf, tfrows in sorted(by_tf.items()):
        if len(tfrows) < 10:
            print(f"    {tf:6s}: n={len(tfrows):3d}  AUC=n/a (n<10)")
            continue
        s = [r["pattern_quality_score"] for r in tfrows]
        l = [r["win"] for r in tfrows]
        auc_tf = _auc_mann_whitney(s, l)
        print(f"    {tf:6s}: n={len(tfrows):3d}  AUC={auc_tf:.4f}")


# ---------------------------------------------------------------------------
# 3. WR per timeframe sui soli "simulated execute"
# ---------------------------------------------------------------------------

def section_execute_only(rows: list[dict], threshold: float) -> None:
    print("\n" + "=" * 78)
    print(f"3. WR per timeframe → solo segnali con final_score >= {threshold} (proxy 'execute')")
    print("=" * 78)
    print(f"  (Il validator reale ha criteri più complessi, ma final_score è il predittore principale)")

    all_filled = [r for r in rows if r["entry_filled"]]
    execute = [r for r in all_filled if r["final_score"] >= threshold]
    non_exec = len(all_filled) - len(execute)

    print(f"\n  Su {len(all_filled)} filled: {len(execute)} segnali >= {threshold} ({len(execute)/len(all_filled)*100:.1f}%),")
    print(f"  {non_exec} scartati ({non_exec/len(all_filled)*100:.1f}%)")

    if not execute:
        print("  Nessun record sopra la soglia.")
        return

    # Globale execute
    wins_exec = sum(r["win"] for r in execute)
    wr_exec = wins_exec / len(execute) * 100
    avg_r_exec = sum(r["pnl_r"] for r in execute) / len(execute)
    ci_lo, ci_hi = _wilson_ci(wins_exec, len(execute))
    print(f"\n  TUTTI i segnali execute: n={len(execute)}  WR={wr_exec:.1f}%  CI [{ci_lo}%-{ci_hi}%]  AvgR={avg_r_exec:.3f}R")

    # Per timeframe
    print(f"\n  {'TF':6s}  {'n exec':>7}  {'WR%':>7}  {'CI 95%':>14}  {'AvgR':>7}  vs ALL filled")
    print("  " + "-" * 65)
    by_tf_exec: dict[str, list] = defaultdict(list)
    by_tf_all: dict[str, list] = defaultdict(list)
    for r in execute:
        by_tf_exec[r["timeframe"]].append(r)
    for r in all_filled:
        by_tf_all[r["timeframe"]].append(r)

    for tf in sorted(by_tf_all.keys()):
        texec = by_tf_exec.get(tf, [])
        tall = by_tf_all.get(tf, [])
        wr_all = sum(r["win"] for r in tall) / len(tall) * 100 if tall else 0
        if not texec:
            print(f"  {tf:6s}  {'0':>7}  {'—':>7}  {'—':>14}  {'—':>7}  (all:{wr_all:.1f}%)")
            continue
        n_exec = len(texec)
        w_exec = sum(r["win"] for r in texec)
        wr = w_exec / n_exec * 100
        avg = sum(r["pnl_r"] for r in texec) / n_exec
        clo, chi = _wilson_ci(w_exec, n_exec)
        delta = wr - wr_all
        sign = "↑" if delta > 1 else ("↓" if delta < -1 else "≈")
        print(f"  {tf:6s}  {n_exec:>7}  {wr:>6.1f}%  [{clo:.1f}%-{chi:.1f}%]  {avg:>7.3f}R  {sign} {delta:+.1f}% vs all")


# ---------------------------------------------------------------------------
# 4. Correlazione WR(pattern) vs pq(pattern)
# ---------------------------------------------------------------------------

def section_pattern_agg_correlation(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("4. CORRELAZIONE WR(pattern_name) vs pq(pattern_name) — livello aggregato")
    print("=" * 78)
    print("  (Domanda: il pq fa bene pattern selection anche se non disaggrega tra occorrenze?)")

    filled = [r for r in rows if r["entry_filled"] and r["pattern_quality_score"] is not None]
    by_pat: dict[str, list] = defaultdict(list)
    for r in filled:
        key = f"{r['pattern_name']}|{r['timeframe']}"
        by_pat[key].append(r)

    agg_wr: list[float] = []
    agg_pq: list[float] = []
    agg_n: list[int] = []

    print(f"\n  {'Pattern|TF':40s}  {'n':>4}  {'pq':>6}  {'WR%':>7}  {'CI 95%':>14}  {'AvgR':>7}")
    print("  " + "-" * 80)

    for key, prows in sorted(by_pat.items(), key=lambda x: -len(x[1])):
        n = len(prows)
        if n < 10:
            continue
        pq = prows[0]["pattern_quality_score"]  # stesso per tutte le occorrenze del pattern
        wins = sum(r["win"] for r in prows)
        wr = wins / n * 100
        avg = sum(r["pnl_r"] for r in prows) / n
        clo, chi = _wilson_ci(wins, n)
        agg_wr.append(wr)
        agg_pq.append(pq)
        agg_n.append(n)
        print(f"  {key:40s}  {n:>4}  {pq:>6.1f}  {wr:>6.1f}%  [{clo:.1f}%-{chi:.1f}%]  {avg:>7.3f}R")

    if len(agg_wr) < 3:
        print("\n  Troppo pochi pattern con n>=10 per correlazione significativa.")
        return

    pearson = _pearson_r(agg_pq, agg_wr)
    spearman = _spearman_r(agg_pq, agg_wr)

    print(f"\n  Pattern aggregati analizzati: {len(agg_wr)}")
    print(f"  Pearson  r(pq_agg, WR_agg):  {pearson:.4f}")
    print(f"  Spearman r(pq_agg, WR_agg):  {spearman:.4f}")
    print()

    if spearman >= 0.5:
        interp = "BUONO: pq fa pattern selection efficace. Problema è la mancanza di disaggregazione intra-pattern."
    elif spearman >= 0.3:
        interp = "DEBOLE: segnale parziale. pq cattura qualcosa a livello pattern ma è rumoroso."
    else:
        interp = "BASSO: pq non seleziona bene i pattern migliori. La metrica è problematica già a livello aggregato."

    print(f"  Interpretazione Spearman: {interp}")


# ---------------------------------------------------------------------------
# 4b. Correlazione pq vs WR stratificata per timeframe
# ---------------------------------------------------------------------------

def section_pattern_agg_correlation_by_tf(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("4b. SPEARMAN r(pq, WR) STRATIFICATO PER TIMEFRAME")
    print("=" * 78)
    print("    (Il pq aggregato su 5m — dove esiste — è più informativo di quello cross-TF?)")

    filled = [r for r in rows if r["entry_filled"] and r["pattern_quality_score"] is not None]

    by_tf: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in filled:
        by_tf[r["timeframe"]][r["pattern_name"]].append(r)

    for tf in sorted(by_tf.keys()):
        pat_map = by_tf[tf]
        agg_pq: list[float] = []
        agg_wr: list[float] = []
        rows_tf = []
        for pat, prows in pat_map.items():
            if len(prows) < 5:
                continue
            pq = prows[0]["pattern_quality_score"]
            wins = sum(r["win"] for r in prows)
            wr = wins / len(prows) * 100
            agg_pq.append(pq)
            agg_wr.append(wr)
            rows_tf.extend(prows)

        n_pats = len(agg_pq)
        n_rec = len(rows_tf)
        if n_pats < 3:
            print(f"\n  TF={tf}: troppo pochi pattern con pq e n>=5 (n_pat={n_pats}, n_rec={n_rec}) — skip")
            continue

        sp = _spearman_r(agg_pq, agg_wr)
        pe = _pearson_r(agg_pq, agg_wr)
        print(f"\n  TF={tf}: n_pat={n_pats} (n_rec={n_rec})")
        print(f"    Pearson  r(pq_agg, WR_agg): {pe:.4f}")
        print(f"    Spearman r(pq_agg, WR_agg): {sp:.4f}")
        if n_pats < 6:
            print(f"    ⚠ n_pat={n_pats} → CI Spearman molto ampio, interpretare con cautela")


# ---------------------------------------------------------------------------
# 5. AUC di tutti i componenti del final_score
# ---------------------------------------------------------------------------

def section_component_auc(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("5. AUC DEI COMPONENTI DEL FINAL_SCORE — dove sta davvero l'edge?")
    print("=" * 78)
    print("  (Tutti i Mann-Whitney, stessa metodologia della sezione 2)")
    print("  AUC > 0.55 = segnale reale | 0.50-0.55 = debole | < 0.50 = invertito o rumore")

    filled = [r for r in rows if r["entry_filled"]]
    n_total = len(filled)
    labels = [r["win"] for r in filled]

    components: list[tuple[str, list[float | None], str]] = [
        ("pattern_strength",      [r["pattern_strength"] for r in filled],      "peso ×8 nel final_score"),
        ("screener_score",        [r["screener_score"] for r in filled],         "peso ×5 nel final_score (max 60pt)"),
        ("pattern_quality_score", [r["pattern_quality_score"] for r in filled],  "peso ×14 nel final_score (se non-null)"),
        ("final_opportunity_score (composito)", [r["final_score"] for r in filled], "somma di tutti i componenti"),
    ]

    print(f"\n  {'Componente':40s}  {'n':>5}  {'AUC':>6}  {'Pearson r':>9}  {'Nota'}")
    print("  " + "-" * 78)

    for name, raw_scores, note in components:
        non_null = [(s, l) for s, l in zip(raw_scores, labels) if s is not None]
        if len(non_null) < 20:
            print(f"  {name:40s}  {'—':>5}  {'—':>6}  {'—':>9}  troppo pochi dati")
            continue
        scores_nn = [s for s, _ in non_null]
        labels_nn = [l for _, l in non_null]
        n = len(non_null)
        auc = _auc_mann_whitney(scores_nn, labels_nn)
        pe = _pearson_r(scores_nn, [float(l) for l in labels_nn])
        auc_str = f"{auc:.4f}"
        if auc >= 0.57:
            flag = "★ segnale reale"
        elif auc >= 0.53:
            flag = "~ debole"
        elif auc >= 0.47:
            flag = "≈ rumore"
        else:
            flag = "▼ invertito?"
        print(f"  {name:40s}  {n:>5}  {auc_str:>6}  {pe:>+9.4f}  {flag}  ({note})")

    # Aggiunge il confronto: final_score batte i suoi componenti singoli?
    auc_final = None
    for name, raw_scores, _ in components:
        if "composito" in name:
            scores_nn = [s for s in raw_scores if s is not None]
            if len(scores_nn) == n_total:
                auc_final = _auc_mann_whitney(scores_nn, labels)
    auc_best_component = None
    for name, raw_scores, _ in components:
        if "composito" not in name:
            nn = [(s, l) for s, l in zip(raw_scores, labels) if s is not None]
            if len(nn) >= 20:
                a = _auc_mann_whitney([s for s, _ in nn], [l for _, l in nn])
                if auc_best_component is None or a > auc_best_component:
                    auc_best_component = a

    print()
    if auc_final is not None and auc_best_component is not None:
        if auc_final > auc_best_component + 0.01:
            print(f"  ✓ La combinazione AGGIUNGE valore: final_score AUC ({auc_final:.4f}) > miglior componente ({auc_best_component:.4f})")
        elif auc_final < auc_best_component - 0.01:
            print(f"  ✗ La combinazione DISTRUGGE valore: final_score AUC ({auc_final:.4f}) < miglior componente ({auc_best_component:.4f})")
        else:
            print(f"  ≈ La combinazione è NEUTRA: final_score AUC ({auc_final:.4f}) ≈ miglior componente ({auc_best_component:.4f})")

    # AUC stratificata per TF per screener_score e strength (che esistono per tutti i record)
    print(f"\n  AUC stratificata per TF — screener_score e pattern_strength:")
    by_tf: dict[str, list] = defaultdict(list)
    for r in filled:
        by_tf[r["timeframe"]].append(r)
    print(f"  {'TF':6s}  {'n':>5}  {'AUC(strength)':>13}  {'AUC(screener)':>13}  {'AUC(final)':>10}")
    print("  " + "-" * 55)
    for tf in sorted(by_tf.keys()):
        tfrows = by_tf[tf]
        if len(tfrows) < 20:
            continue
        lbl = [r["win"] for r in tfrows]
        str_scores = [r["pattern_strength"] for r in tfrows]
        scr_scores = [r["screener_score"] for r in tfrows]
        fin_scores = [r["final_score"] for r in tfrows]
        auc_str_tf = _auc_mann_whitney(str_scores, lbl)
        auc_scr_tf = _auc_mann_whitney(scr_scores, lbl)
        auc_fin_tf = _auc_mann_whitney(fin_scores, lbl)
        print(f"  {tf:6s}  {len(tfrows):>5}  {auc_str_tf:>13.4f}  {auc_scr_tf:>13.4f}  {auc_fin_tf:>10.4f}")


# ---------------------------------------------------------------------------
# 6. AUC per pattern_name — inversione uniforme o condizionale?
# ---------------------------------------------------------------------------

def section_auc_by_pattern(rows: list[dict], min_n: int = 30) -> None:
    print("\n" + "=" * 78)
    print(f"6. AUC PER PATTERN_NAME (n>={min_n}) — inversione uniforme o condizionale?")
    print("=" * 78)
    print("  AUC(strength), AUC(screener_score), AUC(pq) per ogni pattern su filled")
    print("  Se strength AUC ≈ 0.45 su quasi tutti → inversione strutturale")
    print("  Se varia molto (0.35–0.65) → inversione condizionale (pesi per pattern)")

    filled = [r for r in rows if r["entry_filled"]]
    by_pat: dict[str, list] = defaultdict(list)
    for r in filled:
        by_pat[r["pattern_name"]].append(r)

    rows_out: list[tuple] = []
    for pat, prec in sorted(by_pat.items()):
        if len(prec) < min_n:
            continue
        lbl = [r["win"] for r in prec]
        auc_str = _auc_mann_whitney([r["pattern_strength"] for r in prec], lbl)
        auc_scr = _auc_mann_whitney([r["screener_score"] for r in prec], lbl)
        pq_nn = [(r["pattern_quality_score"], r["win"]) for r in prec if r["pattern_quality_score"] is not None]
        auc_pq = _auc_mann_whitney([s for s, _ in pq_nn], [l for _, l in pq_nn]) if len(pq_nn) >= 10 else None
        wr = sum(lbl) / len(lbl) * 100
        rows_out.append((pat, len(prec), wr, auc_str, auc_scr, auc_pq))

    if not rows_out:
        print(f"  Nessun pattern con n>={min_n}.")
        return

    # Ordina per AUC(strength) per evidenziare i pattern più anomali
    rows_out.sort(key=lambda x: x[3])

    print(f"\n  {'Pattern':40s}  {'n':>5}  {'WR%':>6}  {'AUC(str)':>8}  {'AUC(scr)':>8}  {'AUC(pq)':>8}")
    print("  " + "-" * 84)
    for pat, n, wr, auc_str, auc_scr, auc_pq in rows_out:
        pq_str = f"{auc_pq:.4f}" if auc_pq is not None else "   —"
        # Flag colori testuali per leggibilità
        str_flag = "▼" if auc_str < 0.47 else ("★" if auc_str > 0.55 else " ")
        scr_flag = "▼" if auc_scr < 0.47 else ("★" if auc_scr > 0.55 else " ")
        print(f"  {pat:40s}  {n:>5}  {wr:>5.1f}%  {str_flag}{auc_str:.4f}  {scr_flag}{auc_scr:.4f}  {pq_str}")

    # Riepilogo: quanti pattern hanno strength invertita?
    n_inv_str = sum(1 for _, _, _, auc_str, _, _ in rows_out if auc_str < 0.47)
    n_pos_str = sum(1 for _, _, _, auc_str, _, _ in rows_out if auc_str > 0.55)
    n_inv_scr = sum(1 for _, _, _, _, auc_scr, _ in rows_out if auc_scr < 0.47)
    n_pos_scr = sum(1 for _, _, _, _, auc_scr, _ in rows_out if auc_scr > 0.55)
    tot = len(rows_out)
    print(f"\n  RIEPILOGO (su {tot} pattern con n>={min_n}):")
    print(f"  pattern_strength  : {n_inv_str}/{tot} invertiti (<0.47), {n_pos_str}/{tot} positivi (>0.55)")
    print(f"  screener_score    : {n_inv_scr}/{tot} invertiti (<0.47), {n_pos_scr}/{tot} positivi (>0.55)")
    if n_inv_str > tot * 0.6:
        print("  → Inversione UNIFORME su strength: il problema è strutturale (calcolo strength mal progettato).")
    elif n_inv_str > tot * 0.3:
        print("  → Inversione CONDIZIONALE su strength: alcuni pattern ne beneficiano, altri no. Pesi per pattern.")
    else:
        print("  → Strength NON è globalmente invertita: il problema aggregato è un artefatto di composizione.")


# ---------------------------------------------------------------------------
# 7. AUC screener_score stratificato per trade_direction (long vs short)
# ---------------------------------------------------------------------------

def section_auc_by_direction(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("7. AUC SCREENER_SCORE STRATIFICATO PER TRADE_DIRECTION")
    print("=" * 78)
    print("  Se AUC(long) ≈ 0.55 e AUC(short) ≈ 0.39 → screener sbaglia la DIREZIONE")
    print("  Se entrambi ≈ 0.47 → screener ha valore assoluto debole indipendentemente")

    filled = [r for r in rows if r["entry_filled"]]
    by_dir: dict[str, list] = defaultdict(list)
    for r in filled:
        by_dir[r.get("direction", "unknown")].append(r)

    print(f"\n  {'Direzione':10s}  {'n':>5}  {'WR%':>6}  {'AUC(screener)':>13}  {'AUC(strength)':>13}  {'AUC(final)':>10}")
    print("  " + "-" * 65)
    for direction in ["bullish", "bearish", "unknown"]:
        drec = by_dir.get(direction, [])
        if len(drec) < 20:
            continue
        lbl = [r["win"] for r in drec]
        wr = sum(lbl) / len(lbl) * 100
        auc_scr = _auc_mann_whitney([r["screener_score"] for r in drec], lbl)
        auc_str = _auc_mann_whitney([r["pattern_strength"] for r in drec], lbl)
        auc_fin = _auc_mann_whitney([r["final_score"] for r in drec], lbl)
        print(f"  {direction:10s}  {len(drec):>5}  {wr:>5.1f}%  {auc_scr:>13.4f}  {auc_str:>13.4f}  {auc_fin:>10.4f}")

    # Analisi ulteriore: TF × direzione
    print(f"\n  AUC(screener_score) per TF × direzione:")
    by_tf_dir: dict[tuple[str, str], list] = defaultdict(list)
    for r in filled:
        key = (r["timeframe"], r.get("direction", "unknown"))
        by_tf_dir[key].append(r)

    print(f"  {'TF':6s}  {'Dir':8s}  {'n':>5}  {'WR%':>6}  {'AUC(screener)':>13}  {'AUC(strength)':>13}")
    print("  " + "-" * 55)
    for tf in sorted({r["timeframe"] for r in filled}):
        for direction in ["bullish", "bearish"]:
            key = (tf, direction)
            recs = by_tf_dir.get(key, [])
            if len(recs) < 15:
                continue
            lbl = [r["win"] for r in recs]
            wr = sum(lbl) / len(lbl) * 100
            auc_scr = _auc_mann_whitney([r["screener_score"] for r in recs], lbl)
            auc_str = _auc_mann_whitney([r["pattern_strength"] for r in recs], lbl)
            scr_flag = "▼" if auc_scr < 0.47 else ("★" if auc_scr > 0.55 else " ")
            str_flag = "▼" if auc_str < 0.47 else ("★" if auc_str > 0.55 else " ")
            print(f"  {tf:6s}  {direction:6s}  {len(recs):>5}  {wr:>5.1f}%  {scr_flag}{auc_scr:>12.4f}  {str_flag}{auc_str:>12.4f}")


# ---------------------------------------------------------------------------
# 9. Sub-sistema "pattern che funzionano"
# ---------------------------------------------------------------------------

def section_working_subsystem(rows: list[dict], auc_threshold: float = 0.55) -> None:
    """
    Risponde alla domanda strategica: il problema è riparare il sistema intero,
    o estrarre e tenere solo il sub-sistema che già funziona?

    Per ogni pattern, calcola AUC(strength), AUC(screener), AUC(final_score).
    Classifica come "working" se max(AUC) >= auc_threshold.
    Poi confronta: performance del sub-sistema "working" vs il resto.

    Include anche AUC_weighted (media AUC per-pattern pesata per n):
    metrica consigliata per valutare LightGBM futuro, più robusta dell'AUC globale
    perché cattura il funzionamento operativo a livello di pattern.
    """
    print("\n" + "=" * 78)
    print(f"9. SUB-SISTEMA PATTERN CHE FUNZIONANO (max AUC >= {auc_threshold})")
    print("=" * 78)
    print("  Risponde a: riparare il sistema intero o estrarre il sub-sistema che funziona?")
    print(f"  Soglia: max(AUC_strength, AUC_screener, AUC_final) >= {auc_threshold} su filled.")

    filled = [r for r in rows if r["entry_filled"]]
    by_pat: dict[str, list] = defaultdict(list)
    for r in filled:
        by_pat[r["pattern_name"]].append(r)

    working_patterns: list[str] = []
    struggling_patterns: list[str] = []
    auc_per_pattern_n: list[tuple[float, int]] = []  # per AUC_weighted

    print(f"\n  {'Pattern':40s}  {'n':>5}  {'WR%':>6}  {'AvgR':>7}  {'max AUC':>8}  Stato")
    print("  " + "-" * 78)

    for pat in sorted(by_pat.keys()):
        prec = by_pat[pat]
        if len(prec) < 10:
            continue
        lbl = [r["win"] for r in prec]
        auc_str = _auc_mann_whitney([r["pattern_strength"] for r in prec], lbl)
        auc_scr = _auc_mann_whitney([r["screener_score"] for r in prec], lbl)
        auc_fin = _auc_mann_whitney([r["final_score"] for r in prec], lbl)
        max_auc = max(auc_str, auc_scr, auc_fin)
        # AUC_weighted usa final_score AUC come rappresentativa del sistema completo
        auc_per_pattern_n.append((auc_fin, len(prec)))

        n = len(prec)
        wr = sum(lbl) / n * 100
        avg_r = sum(r["pnl_r"] for r in prec) / n
        status = "✓ working" if max_auc >= auc_threshold else "  noise  "
        if max_auc >= auc_threshold:
            working_patterns.append(pat)
        else:
            struggling_patterns.append(pat)
        print(f"  {pat:40s}  {n:>5}  {wr:>5.1f}%  {avg_r:>+7.3f}R  {max_auc:>8.4f}  {status}")

    # AUC_weighted del sistema attuale (metrica per confronto LightGBM futuro)
    if auc_per_pattern_n:
        total_n = sum(n for _, n in auc_per_pattern_n)
        auc_w = sum(a * n for a, n in auc_per_pattern_n) / total_n
        print(f"\n  AUC_weighted (media per-pattern pesata per n): {auc_w:.4f}")
        print("  (Usare questa metrica — non AUC globale — per confrontare con LightGBM)")

    # Volume e performance del sub-sistema "working"
    working_rows = [r for r in filled if r["pattern_name"] in working_patterns]
    struggling_rows = [r for r in filled if r["pattern_name"] in struggling_patterns]
    other_rows = [r for r in filled
                  if r["pattern_name"] not in working_patterns
                  and r["pattern_name"] not in struggling_patterns]

    print(f"\n  DISTRIBUZIONE VOLUME:")
    n_tot = len(filled)
    for label, subset in [("Working patterns", working_rows),
                           ("Struggling patterns", struggling_rows),
                           ("Pattern piccoli (n<10)", other_rows)]:
        if not subset:
            continue
        n = len(subset)
        pct = n / n_tot * 100
        wins = sum(r["win"] for r in subset)
        wr = wins / n * 100
        avg_r = sum(r["pnl_r"] for r in subset) / n
        clo, chi = _wilson_ci(wins, n)
        print(f"  {label:25s}  n={n:>5} ({pct:4.1f}%)  WR={wr:.1f}%  [{clo:.1f}%-{chi:.1f}%]  AvgR={avg_r:+.3f}R")

    # Risposta diretta alla domanda strategica
    if working_patterns:
        n_working = len(working_rows)
        pct_working = n_working / n_tot * 100
        print(f"\n  RISPOSTA STRATEGICA:")
        print(f"  Pattern working: {working_patterns}")
        print(f"  Coprono {pct_working:.1f}% del volume totale ({n_working}/{n_tot} trade).")
        if pct_working >= 30:
            print(f"  → SEPARABILE: >30% del volume. Potrebbe valere una 'whitelist' nel validator.")
            print(f"    Fix di una riga: esegui solo i pattern working, gli altri restano in monitor.")
            print(f"    MA: verifica che il WR del sub-sistema working sia significativamente meglio del resto.")
        elif pct_working >= 15:
            print(f"  → NICCHIA: 15-30% del volume. Separarli è un'ottimizzazione, non un fix sistemico.")
            print(f"    Considera solo se il LightGBM non riesce a catturarli in modo migliore.")
        else:
            print(f"  → TROPPO PICCOLO: <15% del volume. Non vale la pena isolare come sub-sistema.")
            print(f"    Il problema è il sistema intero: la strada giusta è LightGBM su tutto.")
    else:
        print(f"\n  Nessun pattern con max AUC >= {auc_threshold}. Il problema è sistemico.")

    # Confronto: se il validator usasse solo "working", come cambierebbe la WR?
    if working_rows and struggling_rows:
        wr_w = sum(r["win"] for r in working_rows) / len(working_rows) * 100
        wr_s = sum(r["win"] for r in struggling_rows) / len(struggling_rows) * 100
        ar_w = sum(r["pnl_r"] for r in working_rows) / len(working_rows)
        ar_s = sum(r["pnl_r"] for r in struggling_rows) / len(struggling_rows)
        print(f"\n  Confronto WR e AvgR working vs struggling:")
        print(f"  Working:    WR={wr_w:.1f}%  AvgR={ar_w:+.3f}R")
        print(f"  Struggling: WR={wr_s:.1f}%  AvgR={ar_s:+.3f}R")
        if ar_w > ar_s + 0.05:
            print(f"  → Working operativamente migliore. Whitelist nel validator ha senso.")
        elif ar_s > ar_w + 0.05:
            print(f"  → Struggling operativamente MIGLIORE del working. La whitelist peggiorerebbe l'EV.")
            print(f"    Il sistema filtra attivamente i pattern con edge maggiore (Simpson's paradox).")
        else:
            print(f"  → Differenza marginale: la separazione sarebbe cosmetic, non funzionale.")

    # ---- avg_r@K e Spearman(score, pnl_r) — la metrica vera per LightGBM ---------
    print(f"\n  avg_r@K — metrica primaria per valutare sostituti del scoring:")
    print(f"  (top K% ordinati per final_score desc; da confrontare con random=all)")
    by_score = sorted(filled, key=lambda r: -r["final_score"])
    n_tot = len(filled)
    all_avg_r = sum(r["pnl_r"] for r in filled) / n_tot
    all_wr = sum(1 for r in filled if r["pnl_r"] > 0) / n_tot * 100

    print(f"  {'K%':>5}  {'n':>5}  {'avg_r':>8}  {'WR%':>6}  vs random")
    print("  " + "-" * 40)
    for k in (10, 20, 30, 50):
        cutoff = max(1, int(n_tot * k / 100))
        top = by_score[:cutoff]
        avg_r = sum(r["pnl_r"] for r in top) / len(top)
        wr = sum(1 for r in top if r["pnl_r"] > 0) / len(top) * 100
        delta = avg_r - all_avg_r
        flag = "★" if delta > 0.05 else ("▼" if delta < -0.02 else " ")
        print(f"  {k:>4}%  {cutoff:>5}  {avg_r:>+8.4f}R  {wr:>5.1f}%  {flag}{delta:>+.4f}R vs random")
    print(f"  ALL    {n_tot:>5}  {all_avg_r:>+8.4f}R  {all_wr:>5.1f}%  (baseline random)")

    # Bottom 20% per conferma inversione
    bot_n = max(1, int(n_tot * 0.20))
    bot = by_score[-bot_n:]
    bot_avg = sum(r["pnl_r"] for r in bot) / len(bot)
    bot_wr = sum(1 for r in bot if r["pnl_r"] > 0) / len(bot) * 100
    print(f"  bot20% {bot_n:>5}  {bot_avg:>+8.4f}R  {bot_wr:>5.1f}%  (le 'peggiori' secondo il sistema)")

    if bot_avg > all_avg_r:
        print(f"\n  ⚠ SCORING INVERTITO: bot20% ({bot_avg:+.3f}R) > random ({all_avg_r:+.3f}R).")
        print(f"    Il sistema seleziona attivamente i pattern con edge MINORE.")
        print(f"    Target per sostituto: avg_r@top20% > {all_avg_r:.3f}R (battere il random).")
    top20_avg = sum(r["pnl_r"] for r in by_score[:int(n_tot*0.2)]) / int(n_tot*0.2)
    print(f"    Ceiling teorico: avg_r@top20% → {bot_avg:+.3f}R (= l'attuale bot20%)")
    print(f"    Target minimo:   avg_r@top20% > {all_avg_r:+.3f}R (random baseline)")
    print(f"    Sistema attuale: avg_r@top20% = {top20_avg:+.3f}R")

    # Spearman(final_score, pnl_r) — correlazione monotona score vs guadagno reale
    scores_all = [r["final_score"] for r in filled]
    pnls_all = [r["pnl_r"] for r in filled]
    sp = _spearman_r(scores_all, pnls_all)
    print(f"\n  Spearman(final_score, pnl_r) = {sp:+.4f}")
    if sp < -0.02:
        print(f"  → INVERTITO: score alto correla con pnl_r basso. Scoring controproducente.")
    elif sp < 0.02:
        print(f"  → NEUTRO: nessuna correlazione monotona. Lo scoring non aggiunge né toglie EV.")
    else:
        print(f"  → POSITIVO: score alto correla con pnl_r maggiore. Scoring funzionale.")
    print(f"  Target per sostituto: Spearman > 0 sul test out-of-time (battere l'inversione).")


# ---------------------------------------------------------------------------
# 10. Validazione Strada A (gate binario contro-trend + ranker trend-following)
# ---------------------------------------------------------------------------

# Classificazione empirica derivata da sezione 6 (AUC per pattern, dataset 1h).
# CONTRO_TREND = pattern dove AUC(screener) < 0.47 in aggregato: il ranker
#   interno non funziona, ma la WR media è alta (60-69%). Gate binario.
# RANKING_NEEDED = pattern dove max(AUC) > 0.55: il ranker funziona.
# AMBIGUOUS = tutti gli altri: comportamento conservativo (v1 invariato).
_CONTRO_TREND_PATTERNS: frozenset[str] = frozenset({
    "rsi_divergence_bull",
    "rsi_divergence_bear",
    "macd_divergence_bull",
    "macd_divergence_bear",
    "double_top",
    "double_bottom",
})
_RANKING_NEEDED_PATTERNS: frozenset[str] = frozenset({
    "engulfing_bullish",  # AUC(final)=0.629, unico con max AUC>0.55 sul dataset 1h
})


def section_strada_a_validation(rows: list[dict]) -> None:
    """
    Misura quanto vale la strategia 'Strada A' *sui dati già raccolti*,
    senza scrivere codice nel validator.

    Strada A:
      - Pattern contro-trend: esegui TUTTI i segnali che passano i gate di base
        (il ranker interno è rumore, WR media alta).
      - Pattern ranking-dependent: esegui solo il top K% per final_score.
      - Pattern non classificati: mantieni comportamento attuale (v1).

    La stima è ottimistica (usa il training set per definire le soglie),
    ma è sufficiente per decidere se vale la pena implementarla.
    """
    print("\n" + "=" * 78)
    print("10. VALIDAZIONE STRADA A — gate binario contro-trend + ranker trend-following")
    print("=" * 78)
    print("  Contra-trend patterns: esegui tutti (gate binario).")
    print("  Ranking-dependent:     esegui solo top K% per final_score.")
    print("  Confronto vs sistema attuale (execute tutto ciò che passa il validator).")

    filled = [r for r in rows if r["entry_filled"]]
    all_avg = sum(r["pnl_r"] for r in filled) / len(filled)
    all_wr = sum(1 for r in filled if r["pnl_r"] > 0) / len(filled) * 100
    n_tot = len(filled)

    contro = [r for r in filled if r["pattern_name"] in _CONTRO_TREND_PATTERNS]
    ranking_pool = [r for r in filled if r["pattern_name"] in _RANKING_NEEDED_PATTERNS]
    other = [r for r in filled
             if r["pattern_name"] not in _CONTRO_TREND_PATTERNS
             and r["pattern_name"] not in _RANKING_NEEDED_PATTERNS]

    if not contro and not ranking_pool:
        print("  Nessun pattern classificato nel dataset. Aggiornare _CONTRO_TREND_PATTERNS.")
        return

    avg_c = sum(r["pnl_r"] for r in contro) / max(1, len(contro))
    wr_c = sum(1 for r in contro if r["pnl_r"] > 0) / max(1, len(contro)) * 100

    ranking_sorted = sorted(ranking_pool, key=lambda r: -r["final_score"])

    print(f"\n  Componenti della Strada A:")
    print(f"  {'Gruppo':35s}  {'n':>5}  {'avg_r':>8}  {'WR%':>6}")
    print("  " + "-" * 60)
    print(f"  {'Contro-trend (tutti)':35s}  {len(contro):>5}  {avg_c:>+8.4f}R  {wr_c:>5.1f}%")
    for k in (10, 20, 30):
        cut = max(1, int(len(ranking_sorted) * k / 100))
        top = ranking_sorted[:cut]
        avg_e = sum(r["pnl_r"] for r in top) / len(top)
        wr_e = sum(1 for r in top if r["pnl_r"] > 0) / len(top) * 100
        print(f"  {'Engulfing top '+str(k)+'%':35s}  {len(top):>5}  {avg_e:>+8.4f}R  {wr_e:>5.1f}%")

    print(f"\n  {'K% engulf':>10}  {'n Strada A':>10}  {'Δtrade':>7}  {'avg_r':>8}  {'WR%':>6}  "
          f"{'vs random':>10}  Verdetto")
    print("  " + "-" * 78)
    for k in (10, 20, 30):
        cut = max(1, int(len(ranking_sorted) * k / 100))
        top_eng = ranking_sorted[:cut]
        combined = contro + top_eng
        n_comb = len(combined)
        avg_A = sum(r["pnl_r"] for r in combined) / n_comb
        wr_A = sum(1 for r in combined if r["pnl_r"] > 0) / n_comb * 100
        delta_r = avg_A - all_avg
        delta_n = n_comb - n_tot
        verdict = "✓ UPGRADE" if delta_r > 0.05 else ("≈ pari" if delta_r > -0.02 else "✗ DOWNGRADE")
        print(f"  {k:>9}%  {n_comb:>10}  {delta_n:>+7}  {avg_A:>+8.4f}R  {wr_A:>5.1f}%  "
              f"{delta_r:>+10.4f}R  {verdict}")

    # Best k recommendation
    print(f"\n  Sistema attuale: n={n_tot}  avg_r={all_avg:+.4f}R  WR={all_wr:.1f}%  (baseline)")

    # Stima temporale robustezza: la stessa analisi sui soli test records
    all_sorted_ts = sorted(filled, key=lambda r: r.get("pattern_timestamp", ""))
    n_test = int(n_tot * 0.30)
    test_rows = all_sorted_ts[-n_test:]
    test_contro = [r for r in test_rows if r["pattern_name"] in _CONTRO_TREND_PATTERNS]
    test_ranking = sorted(
        [r for r in test_rows if r["pattern_name"] in _RANKING_NEEDED_PATTERNS],
        key=lambda r: -r["final_score"],
    )
    test_all_avg = sum(r["pnl_r"] for r in test_rows) / max(1, len(test_rows))

    print(f"\n  Verifica sul TEST SET (ultimi 30%, n={len(test_rows)}):")
    print(f"  {'K% engulf':>10}  {'n Strada A':>10}  {'avg_r test':>12}  vs random test ({test_all_avg:+.3f}R)")
    print("  " + "-" * 60)
    for k in (10, 20, 30):
        cut = max(1, int(len(test_ranking) * k / 100))
        top_e = test_ranking[:cut]
        comb = test_contro + top_e
        if not comb:
            continue
        avg_A_te = sum(r["pnl_r"] for r in comb) / len(comb)
        delta_te = avg_A_te - test_all_avg
        verdict = "✓ UPGRADE" if delta_te > 0.03 else ("≈ pari" if delta_te > -0.02 else "✗ DOWNGRADE")
        print(f"  {k:>9}%  {len(comb):>10}  {avg_A_te:>+12.4f}R  {delta_te:>+10.4f}R  {verdict}")

    print(f"\n  RACCOMANDAZIONE:")
    best_cut = max(
        (10, 20, 30),
        key=lambda k: sum(r["pnl_r"] for r in (contro + ranking_sorted[:max(1, int(len(ranking_sorted)*k/100))])) /
                       max(1, len(contro) + max(1, int(len(ranking_sorted)*k/100))),
    )
    print(f"  K% ottimale stimato per engulfing: top {best_cut}%")
    print(f"  Stima conservativa: verificare che l'upgrade persista nel test set prima del deploy.")
    print(f"  Se confermato, implementare in opportunity_validator.py:")
    print(f"    - Pattern contro-trend ({len(_CONTRO_TREND_PATTERNS)} noti): gate binario, nessun threshold di score.")
    print(f"    - Pattern ranking-dependent ({len(_RANKING_NEEDED_PATTERNS)} noti): soglia final_score = percentile 90 del pool corrente.")
    print(f"    - Pattern non classificati: comportamento v1 invariato (conservativo).")


# ---------------------------------------------------------------------------
# Bonus: distribuzione temporale per trimestre
# ---------------------------------------------------------------------------

def section_temporal_distribution(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("BONUS: Distribuzione temporale — verifica bias di periodo")
    print("=" * 78)

    filled = [r for r in rows if r["entry_filled"]]
    by_q: dict[str, list] = defaultdict(list)
    for r in filled:
        q = _quarter(r.get("pattern_timestamp", ""))
        by_q[q].append(r)

    print(f"\n  {'Trimestre':10s}  {'n':>5}  {'WR%':>7}  {'CI 95%':>14}  {'AvgR':>7}")
    print("  " + "-" * 52)
    for q in sorted(by_q.keys()):
        qrows = by_q[q]
        n = len(qrows)
        wins = sum(r["win"] for r in qrows)
        wr = wins / n * 100
        avg = sum(r["pnl_r"] for r in qrows) / n
        clo, chi = _wilson_ci(wins, n)
        print(f"  {q:10s}  {n:>5}  {wr:>6.1f}%  [{clo:.1f}%-{chi:.1f}%]  {avg:>7.3f}R")

    all_quarters = sorted(by_q.keys())
    wrs = [sum(r["win"] for r in by_q[q]) / len(by_q[q]) * 100 for q in all_quarters if len(by_q[q]) >= 10]
    if len(wrs) >= 2:
        wr_range = max(wrs) - min(wrs)
        print(f"\n  Range WR tra trimestri (n>=10): {wr_range:.1f}pp")
        if wr_range > 20:
            print("  ⚠ Varianza temporale alta (>20pp): i numeri medi nascondono forte variazione di regime.")
        elif wr_range > 10:
            print("  ⚠ Varianza temporale moderata (>10pp): interpretare le medie con cautela.")
        else:
            print("  ✓ Varianza temporale bassa (<10pp): i numeri sono relativamente stabili nel tempo.")


# ---------------------------------------------------------------------------
# 8. Confronto v1 vs v2: AUC train/test split temporale 70/30
# ---------------------------------------------------------------------------

def section_v1_vs_v2(rows: list[dict], train_ratio: float = 0.70) -> None:
    """
    Confronta final_score v1 (sistema attuale) con scoring_v2 (pesi per-pattern).

    Split: i record vengono ordinati per pattern_timestamp. I primi 70% sono "train"
    (il set su cui i pesi v2 sono stati derivati indirettamente, via sezione 6),
    gli ultimi 30% sono "test" (unseen). L'AUC sul test set è la metrica che conta:
      - AUC_test(v2) > AUC_test(v1) → v2 generalizza meglio, upgrade vale la pena
      - AUC_train(v2) >> AUC_test(v2) → overfitting sui pesi, generalizzazione debole
      - AUC_test(v2) ≈ AUC_test(v1) → v2 non porta valore, torna al v1 e aspetta più dati
    """
    try:
        from scoring_v2 import compute_score_v2  # noqa: PLC0415
    except ImportError:
        print("\n  [Sezione 8 saltata: scoring_v2.py non trovato nella directory corrente]")
        return

    print("\n" + "=" * 78)
    print("8. CONFRONTO v1 vs v2 — train/test split temporale 70/30")
    print("=" * 78)
    print(f"  Train: {train_ratio*100:.0f}% (record più vecchi) | Test: {(1-train_ratio)*100:.0f}% (record più recenti)")
    print("  AUC calcolata su entry_filled=True, stessa metodologia sezioni precedenti.")

    filled = [r for r in rows if r["entry_filled"]]
    if not filled:
        print("  Nessun record con entry fill.")
        return

    # Ordina per timestamp (split temporale, non random, per simulare deployment reale)
    def _ts(r: dict) -> str:
        return r.get("pattern_timestamp", "") or ""

    filled_sorted = sorted(filled, key=_ts)
    n_train = int(len(filled_sorted) * train_ratio)
    train_rows = filled_sorted[:n_train]
    test_rows = filled_sorted[n_train:]

    print(f"\n  Totale filled: {len(filled_sorted)}  |  Train: {len(train_rows)}  |  Test: {len(test_rows)}")

    # Calcola score_v2 per ogni record
    for r in filled_sorted:
        r["score_v2"] = compute_score_v2(
            pattern_name=r["pattern_name"],
            screener_score=r["screener_score"],
            pattern_strength=r["pattern_strength"],
            pattern_quality_score=r["pattern_quality_score"],
            signal_alignment=r.get("signal_alignment", "mixed"),
        )

    # AUC globale
    all_lbl = [r["win"] for r in filled_sorted]
    all_v1 = [r["final_score"] for r in filled_sorted]
    all_v2 = [r["score_v2"] for r in filled_sorted]
    auc_v1_all = _auc_mann_whitney(all_v1, all_lbl)
    auc_v2_all = _auc_mann_whitney(all_v2, all_lbl)

    # AUC train
    tr_lbl = [r["win"] for r in train_rows]
    auc_v1_tr = _auc_mann_whitney([r["final_score"] for r in train_rows], tr_lbl)
    auc_v2_tr = _auc_mann_whitney([r["score_v2"] for r in train_rows], tr_lbl)

    # AUC test
    te_lbl = [r["win"] for r in test_rows]
    auc_v1_te = _auc_mann_whitney([r["final_score"] for r in test_rows], te_lbl)
    auc_v2_te = _auc_mann_whitney([r["score_v2"] for r in test_rows], te_lbl)

    print(f"\n  {'':12s}  {'AUC v1 (attuale)':>18}  {'AUC v2 (per-pattern)':>20}  {'Delta':>7}")
    print("  " + "-" * 64)
    print(f"  {'Globale':12s}  {auc_v1_all:>18.4f}  {auc_v2_all:>20.4f}  {auc_v2_all-auc_v1_all:>+7.4f}")
    print(f"  {'Train (70%)':12s}  {auc_v1_tr:>18.4f}  {auc_v2_tr:>20.4f}  {auc_v2_tr-auc_v1_tr:>+7.4f}")
    print(f"  {'Test (30%)':12s}  {auc_v1_te:>18.4f}  {auc_v2_te:>20.4f}  {auc_v2_te-auc_v1_te:>+7.4f}")

    # Diagnosi overfitting: gap train-test
    gap_v2 = auc_v2_tr - auc_v2_te
    print(f"\n  Gap train/test v2: {gap_v2:+.4f}", end="")
    if gap_v2 > 0.05:
        print("  ⚠ Gap >0.05: possibile overfitting. I pesi v2 potrebbero non generalizzare.")
    elif gap_v2 > 0.02:
        print("  ≈ Gap moderato (0.02–0.05): accettabile per ora, monitorare con più dati.")
    else:
        print("  ✓ Gap basso (<0.02): i pesi generalizzano bene nel test set.")

    # Verdetto finale
    print(f"\n  VERDETTO:")
    if auc_v2_te > auc_v1_te + 0.02:
        print(f"  ✓ v2 MIGLIORE nel test set ({auc_v2_te:.4f} vs {auc_v1_te:.4f}).")
        print("    Delta significativo (>0.02). I pesi per-pattern portano valore misurabile.")
    elif auc_v2_te > auc_v1_te:
        print(f"  ~ v2 leggermente migliore nel test set ({auc_v2_te:.4f} vs {auc_v1_te:.4f}).")
        print("    Delta <0.02: dentro il rumore di campionamento. Attendere più dati per conferma.")
    else:
        print(f"  ✗ v2 NON migliora nel test set ({auc_v2_te:.4f} vs {auc_v1_te:.4f}).")
        print("    I pesi per-pattern attuali non generalizzano. Rivedere prima di deployare.")

    # AUC per pattern nel test set (per vedere se la direzione è giusta per ogni pattern)
    by_pat: dict[str, list] = defaultdict(list)
    for r in test_rows:
        by_pat[r["pattern_name"]].append(r)

    candidates = [(p, recs) for p, recs in by_pat.items() if len(recs) >= 10]
    if candidates:
        print(f"\n  AUC per pattern nel TEST set (n>=10):")
        print(f"  {'Pattern':40s}  {'n':>4}  {'AUC_v1':>7}  {'AUC_v2':>7}  {'Delta':>7}")
        print("  " + "-" * 68)
        for pat, recs in sorted(candidates, key=lambda x: x[0]):
            lbl = [r["win"] for r in recs]
            a1 = _auc_mann_whitney([r["final_score"] for r in recs], lbl)
            a2 = _auc_mann_whitney([r["score_v2"] for r in recs], lbl)
            delta = a2 - a1
            flag = "★" if delta > 0.03 else ("▼" if delta < -0.03 else " ")
            print(f"  {pat:40s}  {len(recs):>4}  {a1:>7.4f}  {a2:>7.4f}  {flag}{delta:>+6.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(args: argparse.Namespace) -> None:
    path = Path(args.dataset)
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    rows = load_dataset(path)
    filled = [r for r in rows if r["entry_filled"]]
    print(f"\nDataset: {len(rows)} righe, {len(filled)} con entry fill  ({path})")

    section_expectancy_by_tf(rows)
    section_expectancy_by_tf_pattern(rows)
    section_auc_pq(rows)
    section_execute_only(rows, threshold=args.execute_threshold)
    section_pattern_agg_correlation(rows)
    section_pattern_agg_correlation_by_tf(rows)
    section_component_auc(rows)
    section_auc_by_pattern(rows)
    section_auc_by_direction(rows)
    section_v1_vs_v2(rows)
    section_working_subsystem(rows)
    section_strada_a_validation(rows)
    section_temporal_distribution(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quattro misurazioni di validazione post-dataset")
    parser.add_argument("--dataset", type=str, default="data/validation_set_v1.csv")
    parser.add_argument(
        "--execute-threshold", type=float, default=60.0,
        help="Soglia final_score per 'simulated execute' (default 60)",
    )
    args = parser.parse_args()
    main(args)
