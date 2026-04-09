"""
analyze_validation_dataset.py
==============================
Le quattro misurazioni richieste dopo il primo run del dataset:

  1. avg_r per timeframe (expectancy, non solo WR)
  2. AUC pq vs win (senza sklearn — formula Mann-Whitney O(n²))
  3. WR per timeframe filtrata su "simulated execute" (final_score >= soglia)
  4. Correlazione WR(pattern_name) vs pq(pattern_name) a livello aggregato
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
    section_auc_pq(rows)
    section_execute_only(rows, threshold=args.execute_threshold)
    section_pattern_agg_correlation(rows)
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
