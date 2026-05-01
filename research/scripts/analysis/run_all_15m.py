"""
Pipeline completa Progetto 15m — esegui tutti gli step in sequenza.

  cd backend
  python research/run_all.py

Ogni step può essere eseguito singolarmente:
  python research/01_aggregate_15m.py
  python research/02_patterns_15m.py
  python research/03_val_15m.py
  python research/04_analysis_15m.py
  python research/05_compare_timeframes.py

Flag:
  --from N     Inizia dallo step N (default 1)
  --to   N     Finisci allo step N (default 5)
  --skip-db    Salta gli step che richiedono il DB (step 1)
               Utile se candles_15m_aggregated.csv esiste già
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = {
    1: ("01_aggregate_15m.py",     "Aggregazione 5m -> 15m (richiede DB)"),
    2: ("02_patterns_15m.py",      "Rilevamento pattern 15m"),
    3: ("03_val_15m.py",           "Simulazione trade -> val_15m.csv"),
    4: ("04_analysis_15m.py",      "Analisi 4a-4j"),
    5: ("05_compare_timeframes.py","Confronto TF + Monte Carlo"),
}

RESEARCH_DIR = Path(__file__).parent


def run_step(step: int) -> bool:
    script_name, label = SCRIPTS[step]
    script_path = RESEARCH_DIR / script_name

    print(f"\n{'='*65}")
    print(f"  STEP {step}: {label}")
    print(f"{'='*65}")

    start = time.time()
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(RESEARCH_DIR.parent),
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n  FAIL STEP {step} fallito (exit code {result.returncode})  [{elapsed:.1f}s]")
        return False

    print(f"\n  ✓ STEP {step} completato  [{elapsed:.1f}s]")
    return True


def main():
    parser = argparse.ArgumentParser(description="Pipeline completa Progetto 15m")
    parser.add_argument("--from", dest="from_step", type=int, default=1)
    parser.add_argument("--to",   dest="to_step",   type=int, default=5)
    parser.add_argument("--skip-db", action="store_true",
                        help="Salta step 1 (usa CSV già esistente)")
    args = parser.parse_args()

    steps_to_run = list(range(args.from_step, args.to_step + 1))
    if args.skip_db and 1 in steps_to_run:
        steps_to_run.remove(1)
        print("  Skip step 1 (--skip-db)")

    print(f"\n  Pipeline 15m: step {steps_to_run}")
    total_start = time.time()

    for step in steps_to_run:
        if step not in SCRIPTS:
            print(f"  Step {step} non esiste (range 1-5)")
            continue
        ok = run_step(step)
        if not ok:
            print(f"\n  Pipeline interrotta allo step {step}.")
            sys.exit(1)

    total = time.time() - total_start
    print(f"\n{'='*65}")
    print(f"  Pipeline completata in {total:.1f}s")
    print(f"  Output: research/datasets/val_15m.csv")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
