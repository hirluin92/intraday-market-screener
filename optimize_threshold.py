#!/usr/bin/env python3
"""
Analisi soglie ML — trova il ML_MIN_SCORE ottimale.

Carica il dataset CSV, ri-scorifica ogni segnale col modello salvato,
poi mostra per ogni soglia: quanti segnali passano, win rate atteso,
lift rispetto al baseline.

Uso:
    python optimize_threshold.py

Output: tabella console + eda_output/threshold_analysis.csv
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

_CSV = Path("trade_dataset_v1.csv")
_MODEL = Path("eda_output/lgbm_baseline_tp1_hit.pkl")
_OUTPUT_CSV = Path("eda_output/threshold_analysis.csv")
_OUTPUT_PLOT = Path("eda_output/threshold_analysis.png")

_CAT_COLS = [
    "direction", "timeframe", "symbol_group",
    "regime_spy", "ctx_market_regime", "ctx_volatility_regime",
    "ctx_candle_expansion", "ctx_direction_bias",
    "rs_signal", "cvd_trend", "session", "vix_regime",
]

_EXCLUDE = {
    "signal_id", "symbol", "provider", "pattern_name",
    "signal_timestamp", "entry_timestamp",
    "was_executed", "skip_reason", "skip_reason_bucket", "leakage_ok",
    "pnl_final_r", "tp1_hit", "tp2_hit", "stop_hit",
    "bars_to_exit", "mfe_r", "mae_r",
    "pnl_4h_r", "pnl_12h_r", "pnl_24h_r", "pnl_48h_r", "early_exit_better",
}


def main() -> None:
    if not _CSV.exists():
        print(f"ERRORE: {_CSV} non trovato.")
        return
    if not _MODEL.exists():
        print(f"ERRORE: modello non trovato in {_MODEL}.")
        print("Esegui prima: python analyze_and_train.py --save-model")
        return

    import joblib

    print(f"Carico modello da {_MODEL}…")
    model = joblib.load(_MODEL)

    print(f"Carico dataset da {_CSV}…")
    df = pd.read_csv(_CSV, low_memory=False)
    df["signal_timestamp"] = pd.to_datetime(df["signal_timestamp"], utc=True, errors="coerce")
    df = df.sort_values("signal_timestamp").reset_index(drop=True)

    # Solo righe con target valido
    df = df[df["tp1_hit"].notna()].copy()
    y = (df["tp1_hit"] == True).astype(int)
    n_total = len(df)
    baseline_wr = y.mean() * 100

    print(f"Righe con target: {n_total:,} | Baseline WR: {baseline_wr:.2f}%\n")

    # Prepara feature
    feat_cols = [c for c in df.columns if c not in _EXCLUDE and c != "tp1_hit"]
    X = df[feat_cols].copy()

    cat_present = [c for c in _CAT_COLS if c in X.columns]
    if cat_present:
        X = pd.get_dummies(X, columns=cat_present, drop_first=False, dummy_na=True)

    for c in X.columns:
        if X[c].dtype == object:
            X[c] = pd.to_numeric(X[c], errors="coerce")

    if hasattr(model, "feature_name_"):
        raw = model.feature_name_
        features = list(raw() if callable(raw) else raw)
    elif hasattr(model, "feature_names_in_"):
        features = list(model.feature_names_in_)
    else:
        print("ERRORE: modello senza feature names.")
        return

    for f in features:
        if f not in X.columns:
            X[f] = 0.0
    X = X[features].fillna(0.0)

    # ── Out-Of-Fold predictions (OOF) ────────────────────────────────────────
    # CRITICO: non usare il modello finale sui dati di training (in-sample bias).
    # Usiamo lo stesso TimeSeriesSplit del training per ottenere score onesti:
    # ogni segnale viene scorificato SOLO da un modello che NON lo ha mai visto.
    print("Calcolo score OOF (out-of-fold) con TimeSeriesSplit — questo è il numero onesto…")
    import lightgbm as lgb
    from sklearn.model_selection import TimeSeriesSplit

    lgb_params = {
        "objective": "binary",
        "metric": "auc",
        "n_estimators": 500,
        "learning_rate": 0.05,
        "max_depth": 6,
        "num_leaves": 31,
        "min_child_samples": 20,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "scale_pos_weight": (y == 0).sum() / max((y == 1).sum(), 1),
        "verbose": -1,
        "n_jobs": -1,
        "random_state": 42,
    }

    tscv = TimeSeriesSplit(n_splits=5)
    oof_scores = np.full(len(y), np.nan)

    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr = y.iloc[train_idx]
        y_val = y.iloc[val_idx]
        if len(X_tr) < 50 or (y_tr == 1).sum() == 0:
            continue
        fold_model = lgb.LGBMClassifier(**lgb_params)
        fold_model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
        )
        oof_scores[val_idx] = fold_model.predict_proba(X_val)[:, 1]
        print(f"  Fold {fold_idx + 1}/5 completato — val={len(val_idx):,}")

    # Mantieni solo le righe con OOF score (escluso il primo fold di train che non ha val)
    valid_mask = ~np.isnan(oof_scores)
    df["ml_score"] = oof_scores
    print(f"  Score OOF calcolati su {valid_mask.sum():,} segnali ({valid_mask.sum()/len(y)*100:.1f}%)\n")

    # Filtra solo righe con score OOF disponibile
    df = df[valid_mask].copy()
    y = y[valid_mask]

    # ── Analisi soglie ────────────────────────────────────────────────────────
    thresholds = np.arange(0.35, 0.76, 0.01)
    rows = []

    for thr in thresholds:
        mask = df["ml_score"] >= thr
        n_sel = mask.sum()
        if n_sel == 0:
            continue
        y_sel = y[mask]
        wr = y_sel.mean() * 100
        coverage = n_sel / n_total * 100
        lift = wr / baseline_wr
        # Solo eseguiti (was_executed=True)
        mask_ex = mask & (df["was_executed"] == True)
        n_ex = mask_ex.sum()
        wr_ex = (y[mask_ex].mean() * 100) if n_ex > 0 else None
        rows.append({
            "threshold": round(thr, 2),
            "n_selected": int(n_sel),
            "coverage_pct": round(coverage, 1),
            "win_rate_pct": round(wr, 2),
            "lift_vs_baseline": round(lift, 3),
            "n_executed_selected": int(n_ex),
            "wr_executed_pct": round(wr_ex, 2) if wr_ex is not None else None,
        })

    result = pd.DataFrame(rows)

    # ── Stampa tabella ────────────────────────────────────────────────────────
    print(f"\n{'Soglia':>7} | {'N segnali':>10} | {'Copertura':>9} | {'WR tutti':>8} | {'Lift':>6} | {'N eseguiti':>10} | {'WR eseguiti':>11}")
    print("-" * 80)
    for _, r in result.iterrows():
        flag = " ◄" if r["win_rate_pct"] >= 50.0 and r["coverage_pct"] >= 5.0 else ""
        wr_ex_str = f"{r['wr_executed_pct']:.1f}%" if r["wr_executed_pct"] is not None else "  n/a"
        print(
            f"  {r['threshold']:.2f}  | {r['n_selected']:>10,} | {r['coverage_pct']:>8.1f}% | "
            f"{r['win_rate_pct']:>7.2f}% | {r['lift_vs_baseline']:>6.3f} | "
            f"{r['n_executed_selected']:>10,} | {wr_ex_str:>10}{flag}"
        )

    # ── Raccomandazione automatica ────────────────────────────────────────────
    # Soglia bilanciata: WR >= 50% con copertura >= 10%
    cand = result[(result["win_rate_pct"] >= 50.0) & (result["coverage_pct"] >= 10.0)]
    print("\n" + "=" * 80)
    if len(cand) > 0:
        best = cand.sort_values("win_rate_pct", ascending=False).iloc[0]
        print(f"RACCOMANDAZIONE: ML_MIN_SCORE = {best['threshold']:.2f}")
        print(f"  → WR atteso:    {best['win_rate_pct']:.1f}%  (baseline: {baseline_wr:.1f}%)")
        print(f"  → Lift:         {best['lift_vs_baseline']:.3f}x")
        print(f"  → Copertura:    {best['coverage_pct']:.1f}% dei segnali passano il filtro")
        print(f"  → N segnali:    {int(best['n_selected']):,}")
        print()
        print(f"  Per attivarlo: nel .env → ML_MIN_SCORE={best['threshold']:.2f}")
    else:
        # Soglia più morbida: massimo WR con coverage >= 5%
        cand2 = result[result["coverage_pct"] >= 5.0]
        if len(cand2) > 0:
            best2 = cand2.sort_values("win_rate_pct", ascending=False).iloc[0]
            print(f"RACCOMANDAZIONE (bilanciata): ML_MIN_SCORE = {best2['threshold']:.2f}")
            print(f"  → WR atteso: {best2['win_rate_pct']:.1f}% | Lift: {best2['lift_vs_baseline']:.3f}x")
            print(f"  → Copertura: {best2['coverage_pct']:.1f}%")
            print()
            print(f"  Per attivarlo: nel .env → ML_MIN_SCORE={best2['threshold']:.2f}")
        else:
            print("Nessuna soglia soddisfa i criteri minimi. Il modello necessita di più dati o feature.")
    print("=" * 80)

    # ── Plot ─────────────────────────────────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        ax1.plot(result["threshold"], result["win_rate_pct"], "b-o", markersize=4, label="WR tutti i segnali")
        ax1.axhline(baseline_wr, color="gray", linestyle="--", label=f"Baseline {baseline_wr:.1f}%")
        ax1.axhline(50.0, color="green", linestyle=":", alpha=0.7, label="50% WR")
        ax1.set_ylabel("Win Rate (%)")
        ax1.set_title("Analisi soglia ML — Win Rate e Copertura")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(30, 70)

        ax2.fill_between(result["threshold"], result["coverage_pct"], alpha=0.4, color="orange")
        ax2.plot(result["threshold"], result["coverage_pct"], "r-", label="Copertura %")
        ax2.axhline(10.0, color="gray", linestyle="--", alpha=0.7, label="10% copertura minima")
        ax2.set_ylabel("Copertura (% segnali selezionati)")
        ax2.set_xlabel("Soglia ML_MIN_SCORE")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(_OUTPUT_PLOT, dpi=120)
        plt.close()
        print(f"\nPlot salvato: {_OUTPUT_PLOT}")
    except Exception as exc:
        print(f"Plot saltato: {exc}")

    result.to_csv(_OUTPUT_CSV, index=False)
    print(f"Tabella salvata: {_OUTPUT_CSV}")


if __name__ == "__main__":
    main()
