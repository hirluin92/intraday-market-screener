"""
measure_scoring_change.py
==========================
Misura l'impatto di una modifica ai pesi del scoring sul dataset di validazione.

Uso:
  cd backend
  python measure_scoring_change.py --dataset data/validation_set_v1.csv

Output:
  - Tabella win rate e avg PnL per soglia di score (v1 attuale vs v2 variante)
  - Numero di segnali selezionati per ogni soglia
  - Precision@K (top K per score — quanti sono win?)

Aggiungere qui la logica della "variante" da misurare (modifica i parametri
in _score_v2 o importa una funzione diversa).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Parametri scoring CORRENTE (v1) — copiati da opportunity_final_score.py
# Cambiarli qui NON cambia il codice di produzione.
# ---------------------------------------------------------------------------
_V1_QUALITY_FROM_SCORE_MAX = 14.0
_V1_QUALITY_BAND = {"high": 10.0, "medium": 5.0, "low": 2.0}
_V1_ALIGNMENT_CONFLICTING = -10.0
_V1_ALIGNMENT_ALIGNED = 4.0
_V1_ALIGNMENT_NEUTRAL = 0.0
_V1_STRENGTH_MAX_BONUS = 8.0

# ---------------------------------------------------------------------------
# Parametri VARIANTE (v2) — modifica questi per misurare l'effetto
# ---------------------------------------------------------------------------
_V2_QUALITY_FROM_SCORE_MAX = 14.0       # es: prova 10.0 o 18.0
_V2_QUALITY_BAND = {"high": 10.0, "medium": 5.0, "low": 2.0}
_V2_ALIGNMENT_CONFLICTING = -10.0
_V2_ALIGNMENT_ALIGNED = 4.0
_V2_ALIGNMENT_NEUTRAL = 0.0
_V2_STRENGTH_MAX_BONUS = 8.0


def _quality_bonus(pq: float | None, max_pts: float, band: dict) -> float:
    if pq is None:
        return -6.0  # PENALTY_UNKNOWN
    normalized = pq / 100.0 * max_pts
    if pq >= 70:
        band_bonus = band["high"]
    elif pq >= 40:
        band_bonus = band["medium"]
    else:
        band_bonus = band["low"]
    return normalized + band_bonus


def _alignment_bonus(alignment: str, aligned_pts: float, neutral_pts: float, conflict_pts: float) -> float:
    a = (alignment or "neutral").lower()
    if a == "aligned":
        return aligned_pts
    if a == "conflicting":
        return conflict_pts
    return neutral_pts


def _score_v1(row: dict) -> float:
    """Ricalcola il final score con i parametri V1 correnti."""
    scr = float(row.get("screener_score") or 0)
    pq = float(row["pattern_quality_score"]) if row.get("pattern_quality_score") not in (None, "", "None") else None
    strength = float(row.get("pattern_strength") or 0)
    alignment = row.get("signal_alignment") or "neutral"

    # I dati nel CSV non hanno signal_alignment direttamente (viene da ctx).
    # Usiamo final_score già calcolato come proxy per v1 — confrontiamo solo v2 vs v1.
    # In alternativa, puoi ricalcolare da screener_score + componenti se li hai salvati.
    return float(row.get("final_score") or 0)


def _score_v2(row: dict) -> float:
    """
    Ricalcola il final score con i parametri V2 variante.

    NOTA: questo è un recalcolo approssimato perché il CSV non include tutti
    i sub-componenti (es. signal_alignment). Per una misura esatta, aggiungi
    signal_alignment allo schema del CSV e ricalcola da zero.
    """
    scr = float(row.get("screener_score") or 0)
    pq = float(row["pattern_quality_score"]) if row.get("pattern_quality_score") not in (None, "", "None") else None
    strength = float(row.get("pattern_strength") or 0)

    qb = _quality_bonus(pq, _V2_QUALITY_FROM_SCORE_MAX, _V2_QUALITY_BAND)
    # strength bonus: normalizzato 0..1 → max bonus
    sb = min(strength, 1.0) * _V2_STRENGTH_MAX_BONUS

    # alignment: non disponibile nel CSV, usiamo 0 come proxy neutro
    ab = _V2_ALIGNMENT_NEUTRAL

    return scr + qb + sb + ab


def load_dataset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def win_rate_by_threshold(
    rows: list[dict],
    score_col: str,
    thresholds: list[float],
) -> None:
    print(f"\n{'Threshold':>10} {'n':>6} {'WR%':>7} {'AvgR':>8} {'Prec@K':>8}")
    print("-" * 45)
    for thr in thresholds:
        subset = [r for r in rows if r["entry_filled"] == "True" and float(r.get(score_col) or 0) >= thr]
        if not subset:
            print(f"{thr:>10.0f} {'0':>6} {'—':>7} {'—':>8} {'—':>8}")
            continue
        wins = sum(1 for r in subset if float(r["pnl_r"]) > 0)
        avg_r = sum(float(r["pnl_r"]) for r in subset) / len(subset)
        wr = wins / len(subset) * 100
        print(f"{thr:>10.0f} {len(subset):>6} {wr:>6.1f}% {avg_r:>8.3f}R")


def compare_v1_v2(rows: list[dict], thresholds: list[float]) -> None:
    # Aggiunge colonne calcolate
    for r in rows:
        r["_score_v1"] = _score_v1(r)
        r["_score_v2"] = _score_v2(r)

    print("\n" + "=" * 70)
    print("SCORING v1 (attuale basato su final_score salvato nel dataset)")
    print("=" * 70)
    win_rate_by_threshold(rows, "_score_v1", thresholds)

    print("\n" + "=" * 70)
    print("SCORING v2 (variante con parametri modificati)")
    print("=" * 70)
    win_rate_by_threshold(rows, "_score_v2", thresholds)

    # Delta: quanti segnali cambiano classificazione sopra/sotto la soglia principale
    main_thr = thresholds[len(thresholds) // 2]
    promoted = sum(
        1 for r in rows
        if r["entry_filled"] == "True"
        and float(r["_score_v1"]) < main_thr
        and float(r["_score_v2"]) >= main_thr
    )
    demoted = sum(
        1 for r in rows
        if r["entry_filled"] == "True"
        and float(r["_score_v1"]) >= main_thr
        and float(r["_score_v2"]) < main_thr
    )
    print(f"\n  Rispetto alla soglia {main_thr}:")
    print(f"    Promossi v1→v2:  {promoted}")
    print(f"    Rimossi v1→v2:   {demoted}")

    if promoted > 0:
        promo_rows = [
            r for r in rows
            if r["entry_filled"] == "True"
            and float(r["_score_v1"]) < main_thr
            and float(r["_score_v2"]) >= main_thr
        ]
        pr_wins = sum(1 for r in promo_rows if float(r["pnl_r"]) > 0)
        print(f"    WR dei promossi: {pr_wins/promoted*100:.1f}%  (se >50% → promozione utile)")

    if demoted > 0:
        dem_rows = [
            r for r in rows
            if r["entry_filled"] == "True"
            and float(r["_score_v1"]) >= main_thr
            and float(r["_score_v2"]) < main_thr
        ]
        dem_wins = sum(1 for r in dem_rows if float(r["pnl_r"]) > 0)
        print(f"    WR dei rimossi:  {dem_wins/demoted*100:.1f}%  (se <50% → rimozione corretta)")


def cliff_analysis(rows: list[dict]) -> None:
    """Analisi del cliff a pq=34: win rate per bucket di quality score."""
    print("\n" + "=" * 60)
    print("ANALISI CLIFF pq=34 — WR per bucket quality score")
    print("=" * 60)
    buckets = [(0, 20), (20, 34), (34, 45), (45, 60), (60, 80), (80, 101)]
    print(f"{'PQ bucket':>12} {'n':>6} {'WR%':>7} {'AvgR':>8}")
    print("-" * 38)
    for lo, hi in buckets:
        subset = [
            r for r in rows
            if r["entry_filled"] == "True"
            and r.get("pattern_quality_score") not in (None, "", "None")
            and lo <= float(r["pattern_quality_score"]) < hi
        ]
        if not subset:
            print(f"  [{lo:3d}-{hi:3d}): {'0':>6} {'—':>7} {'—':>8}")
            continue
        wins = sum(1 for r in subset if float(r["pnl_r"]) > 0)
        avg_r = sum(float(r["pnl_r"]) for r in subset) / len(subset)
        wr = wins / len(subset) * 100
        marker = " ← cliff" if lo == 34 else ""
        print(f"  [{lo:3d}-{hi:3d}): {len(subset):>6} {wr:>6.1f}% {avg_r:>8.3f}R{marker}")


def main(args: argparse.Namespace) -> None:
    path = Path(args.dataset)
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        print("Lancia prima: python build_validation_dataset.py", file=sys.stderr)
        sys.exit(1)

    rows = load_dataset(path)
    print(f"Dataset: {len(rows)} righe da {path}")

    filled = [r for r in rows if r["entry_filled"] == "True"]
    wins = sum(1 for r in filled if float(r["pnl_r"]) > 0)
    print(f"Entry filled: {len(filled)}/{len(rows)} ({len(filled)/len(rows)*100:.1f}%)")
    if filled:
        print(f"Win rate globale: {wins/len(filled)*100:.1f}%")
        print(f"Avg PnL globale: {sum(float(r['pnl_r']) for r in filled)/len(filled):.3f}R")

    thresholds = args.thresholds

    compare_v1_v2(rows, thresholds)
    cliff_analysis(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Misura impatto di modifiche al scoring")
    parser.add_argument("--dataset", type=str, default="data/validation_set_v1.csv",
                        help="Path dataset CSV (default: data/validation_set_v1.csv)")
    parser.add_argument("--thresholds", type=float, nargs="+",
                        default=[40.0, 50.0, 55.0, 60.0, 65.0, 70.0],
                        help="Soglie di score da analizzare")
    args = parser.parse_args()
    main(args)
