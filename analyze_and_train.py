#!/usr/bin/env python3
"""
Analisi esplorativa (EDA) e modello baseline del dataset trade signals.

Uso:
    python analyze_and_train.py [--csv trade_dataset_v1.csv] [--target tp1_hit]
                                [--output-dir eda_output] [--save-model]
                                [--cv-splits 5] [--no-plots]

Dipendenze extra (non nel backend):
    pip install lightgbm scikit-learn matplotlib seaborn

Il modello viene valutato con TimeSeriesSplit sul campo signal_timestamp,
rispettando l'ordine cronologico per evitare look-ahead.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ── Costanti default ──────────────────────────────────────────────────────────
_DEFAULT_CSV = Path(__file__).parent / "trade_dataset_v1.csv"
_DEFAULT_TARGET = "tp1_hit"
_DEFAULT_OUTPUT_DIR = Path(__file__).parent / "eda_output"
_MIN_TRAIN_ROWS = 50  # minimo per fold valido

# Colonne da escludere dal training (identificatori, timestamp, outcome non-target)
_EXCLUDE_COLS = {
    "signal_id", "symbol", "provider", "pattern_name",
    "signal_timestamp", "entry_timestamp",
    "was_executed", "skip_reason", "skip_reason_bucket", "leakage_ok",
    # Outcome / label (tutti tranne il target)
    "pnl_final_r", "tp1_hit", "tp2_hit", "stop_hit",
    "bars_to_exit", "mfe_r", "mae_r",
    "pnl_4h_r", "pnl_12h_r", "pnl_24h_r", "pnl_48h_r",
    "early_exit_better",
}

# Colonne categoriche da one-hot encode
_CAT_COLS = {
    "direction", "timeframe", "symbol_group",
    "regime_spy", "ctx_market_regime", "ctx_volatility_regime",
    "ctx_candle_expansion", "ctx_direction_bias",
    "rs_signal", "cvd_trend", "session",
    "vix_regime",
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilità
# ─────────────────────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if "signal_timestamp" in df.columns:
        df["signal_timestamp"] = pd.to_datetime(df["signal_timestamp"], utc=True, errors="coerce")
    for col in ["tp1_hit", "tp2_hit", "stop_hit", "was_executed",
                "leakage_ok", "in_fvg_bullish", "in_fvg_bearish",
                "in_ob_bullish", "in_ob_bearish", "has_quality_score",
                "in_earnings_window", "is_opex_week",
                "is_quarter_start", "is_quarter_end"]:
        if col in df.columns:
            df[col] = df[col].astype("boolean")
    return df


def _nan_report(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    report = pd.DataFrame({
        "missing_n": df.isnull().sum(),
        "missing_pct": (df.isnull().sum() / total * 100).round(2),
        "dtype": df.dtypes,
    }).sort_values("missing_pct", ascending=False)
    return report[report["missing_n"] > 0]


def _prepare_features(df: pd.DataFrame, target: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Prepara X, y per training:
    - Filtra solo righe con target non nullo
    - Esclude colonne non-feature
    - One-hot encode categoriche
    - Fill NaN numerici con mediana
    """
    # Filtra righe senza target
    mask = df[target].notna()
    sub = df[mask].copy()
    y = sub[target].astype(float)

    # Seleziona colonne feature
    drop = _EXCLUDE_COLS - {target}
    feat_cols = [c for c in sub.columns if c not in drop and c != target]

    X = sub[feat_cols].copy()

    # One-hot encode colonne categoriche
    cat_present = [c for c in _CAT_COLS if c in X.columns]
    if cat_present:
        X = pd.get_dummies(X, columns=cat_present, drop_first=False, dummy_na=True)

    # Converti bool in int
    for c in X.columns:
        if X[c].dtype == object:
            X[c] = pd.to_numeric(X[c], errors="coerce")
        if X[c].dtype == "boolean":
            X[c] = X[c].astype("Int64").astype(float)

    # Fill NaN numerici con mediana della colonna
    for c in X.columns:
        if X[c].isnull().any():
            med = X[c].median()
            X[c] = X[c].fillna(med if pd.notna(med) else 0.0)

    return X, y, feat_cols


# ─────────────────────────────────────────────────────────────────────────────
# Analisi esplorativa
# ─────────────────────────────────────────────────────────────────────────────

def run_eda(df: pd.DataFrame, target: str, output_dir: Path, no_plots: bool) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    # Overview
    n = len(df)
    n_ex = int(df["was_executed"].sum()) if "was_executed" in df.columns else None
    n_target_valid = int(df[target].notna().sum()) if target in df.columns else 0
    target_pos = int((df[target] == 1).sum()) if target in df.columns else 0
    target_neg = int((df[target] == 0).sum()) if target in df.columns else 0

    report["overview"] = {
        "total_rows": n,
        "was_executed": n_ex,
        "target_valid_rows": n_target_valid,
        "target_pos": target_pos,
        "target_neg": target_neg,
        "target_base_rate_pct": round(target_pos / (target_pos + target_neg) * 100, 2) if (target_pos + target_neg) > 0 else None,
    }

    # NaN report
    nan_rep = _nan_report(df)
    report["nan_report"] = nan_rep.to_dict(orient="index")

    # Date range
    if "signal_timestamp" in df.columns and df["signal_timestamp"].notna().any():
        ts = df["signal_timestamp"].dropna()
        report["date_range"] = {
            "min": str(ts.min()),
            "max": str(ts.max()),
            "n_unique_dates": int(ts.dt.date.nunique()),
        }

    # Distribuzione per simbolo e pattern
    if "symbol" in df.columns:
        report["top_symbols"] = df["symbol"].value_counts().head(20).to_dict()
    if "pattern_name" in df.columns:
        report["top_patterns"] = df["pattern_name"].value_counts().head(20).to_dict()

    # Win rate per simbolo (solo eseguiti)
    if all(c in df.columns for c in ["was_executed", "symbol", "pnl_final_r"]):
        ex = df[df["was_executed"] == True].copy()
        if len(ex) > 0:
            ex["win"] = ex["pnl_final_r"] > 0
            wr_sym = ex.groupby("symbol")["win"].agg(["mean", "count"])
            wr_sym = wr_sym[wr_sym["count"] >= 5].sort_values("mean", ascending=False)
            report["wr_by_symbol"] = {
                k: {"wr": round(float(v["mean"]) * 100, 1), "n": int(v["count"])}
                for k, v in wr_sym.iterrows()
            }

    # Win rate per pattern
    if all(c in df.columns for c in ["was_executed", "pattern_name", "pnl_final_r"]):
        ex = df[df["was_executed"] == True].copy()
        if len(ex) > 0:
            ex["win"] = ex["pnl_final_r"] > 0
            wr_pat = ex.groupby("pattern_name")["win"].agg(["mean", "count"])
            wr_pat = wr_pat[wr_pat["count"] >= 3].sort_values("mean", ascending=False)
            report["wr_by_pattern"] = {
                k: {"wr": round(float(v["mean"]) * 100, 1), "n": int(v["count"])}
                for k, v in wr_pat.iterrows()
            }

    # Win rate per VIX regime (Tranche A)
    if all(c in df.columns for c in ["was_executed", "vix_regime", "pnl_final_r"]):
        ex = df[df["was_executed"] == True].dropna(subset=["vix_regime"]).copy()
        if len(ex) > 0:
            ex["win"] = ex["pnl_final_r"] > 0
            wr_vix = ex.groupby("vix_regime")["win"].agg(["mean", "count"])
            report["wr_by_vix_regime"] = {
                k: {"wr": round(float(v["mean"]) * 100, 1), "n": int(v["count"])}
                for k, v in wr_vix.iterrows()
            }

    # Win rate in/out earnings window
    if all(c in df.columns for c in ["was_executed", "in_earnings_window", "pnl_final_r"]):
        ex = df[df["was_executed"] == True].dropna(subset=["in_earnings_window"]).copy()
        if len(ex) > 0:
            ex["win"] = ex["pnl_final_r"] > 0
            wr_earn = ex.groupby(ex["in_earnings_window"].astype(str))["win"].agg(["mean", "count"])
            report["wr_earnings_window"] = {
                k: {"wr": round(float(v["mean"]) * 100, 1), "n": int(v["count"])}
                for k, v in wr_earn.iterrows()
            }

    # Statistiche descrittive numeriche
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if num_cols:
        desc = df[num_cols].describe().T
        report["numeric_stats_summary"] = desc.to_dict(orient="index")

    # Plots opzionali
    if not no_plots:
        _try_plots(df, target, output_dir)

    return report


def _try_plots(df: pd.DataFrame, target: str, output_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        # 1. Distribuzione target
        if target in df.columns and df[target].notna().any():
            fig, ax = plt.subplots(figsize=(6, 4))
            df[target].dropna().astype(float).value_counts().plot(kind="bar", ax=ax)
            ax.set_title(f"Distribuzione {target}")
            ax.set_xlabel("Valore")
            ax.set_ylabel("Count")
            plt.tight_layout()
            plt.savefig(output_dir / f"dist_{target}.png", dpi=100)
            plt.close()

        # 2. Distribuzione VIX
        if "vix_close" in df.columns and df["vix_close"].notna().any():
            fig, ax = plt.subplots(figsize=(8, 4))
            df["vix_close"].dropna().hist(bins=50, ax=ax)
            ax.set_title("Distribuzione VIX Close")
            ax.set_xlabel("VIX")
            plt.tight_layout()
            plt.savefig(output_dir / "dist_vix.png", dpi=100)
            plt.close()

        # 3. Win rate per ora UTC (solo eseguiti)
        if all(c in df.columns for c in ["was_executed", "hour_utc", "pnl_final_r"]):
            ex = df[df["was_executed"] == True].dropna(subset=["pnl_final_r"]).copy()
            ex["win"] = ex["pnl_final_r"] > 0
            wr_hour = ex.groupby("hour_utc")["win"].mean()
            if len(wr_hour) > 1:
                fig, ax = plt.subplots(figsize=(10, 4))
                wr_hour.plot(kind="bar", ax=ax)
                ax.set_title("Win Rate per ora UTC (eseguiti)")
                ax.set_ylabel("WR")
                ax.set_xlabel("Hour UTC")
                plt.tight_layout()
                plt.savefig(output_dir / "wr_by_hour.png", dpi=100)
                plt.close()

        # 4. Temporal: segnali per settimana
        if "signal_timestamp" in df.columns and df["signal_timestamp"].notna().any():
            ts = df["signal_timestamp"].dropna()
            weekly = ts.dt.to_period("W").value_counts().sort_index()
            if len(weekly) > 1:
                fig, ax = plt.subplots(figsize=(14, 4))
                weekly.plot(kind="bar", ax=ax, width=0.8)
                ax.set_title("Segnali per settimana")
                ax.set_ylabel("N segnali")
                ax.set_xticklabels([str(p) for p in weekly.index], rotation=90, fontsize=6)
                plt.tight_layout()
                plt.savefig(output_dir / "signals_per_week.png", dpi=100)
                plt.close()

        print(f"  Plot salvati in {output_dir}/")
    except ImportError:
        print("  [skip plots] matplotlib/seaborn non installati.")
    except Exception as exc:
        print(f"  [skip plots] Errore: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Modello baseline (LightGBM + TimeSeriesSplit)
# ─────────────────────────────────────────────────────────────────────────────

def run_baseline_model(
    df: pd.DataFrame,
    target: str,
    output_dir: Path,
    cv_splits: int,
    save_model: bool,
) -> dict:
    try:
        import lightgbm as lgb
        from sklearn.metrics import (
            average_precision_score,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import TimeSeriesSplit
    except ImportError as e:
        return {"error": f"Dipendenza mancante: {e}. Installa: pip install lightgbm scikit-learn"}

    output_dir.mkdir(parents=True, exist_ok=True)

    # Ordina per timestamp per TimeSeriesSplit corretto
    if "signal_timestamp" in df.columns:
        df = df.sort_values("signal_timestamp").reset_index(drop=True)

    X, y, feat_cols = _prepare_features(df, target)

    if len(y) < _MIN_TRAIN_ROWS * 2:
        return {"error": f"Troppo poche righe con target ({len(y)}); serve >= {_MIN_TRAIN_ROWS * 2}"}

    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    scale_pos_weight = n_neg / n_pos if n_pos > 0 else 1.0

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
        "scale_pos_weight": scale_pos_weight,
        "verbose": -1,
        "n_jobs": -1,
        "random_state": 42,
    }

    tscv = TimeSeriesSplit(n_splits=cv_splits)
    fold_metrics: list[dict] = []

    print(f"\n  TimeSeriesSplit CV ({cv_splits} fold) su {len(y)} righe…")

    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]

        if len(X_tr) < _MIN_TRAIN_ROWS or len(X_val) < _MIN_TRAIN_ROWS:
            print(f"    Fold {fold_idx + 1}: saltato (train={len(X_tr)}, val={len(X_val)})")
            continue

        n_pos_val = int((y_val == 1).sum())
        if n_pos_val == 0 or n_pos_val == len(y_val):
            print(f"    Fold {fold_idx + 1}: saltato (target monoclasse in val)")
            continue

        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
        )

        proba = model.predict_proba(X_val)[:, 1]
        pred = (proba >= 0.5).astype(int)

        auc = roc_auc_score(y_val, proba)
        ap = average_precision_score(y_val, proba)
        prec = precision_score(y_val, pred, zero_division=0)
        rec = recall_score(y_val, pred, zero_division=0)
        f1 = f1_score(y_val, pred, zero_division=0)

        fold_metrics.append({
            "fold": fold_idx + 1,
            "train_rows": len(X_tr),
            "val_rows": len(X_val),
            "val_pos_rate": round(n_pos_val / len(y_val), 4),
            "roc_auc": round(auc, 4),
            "avg_precision": round(ap, 4),
            "precision_50": round(prec, 4),
            "recall_50": round(rec, 4),
            "f1_50": round(f1, 4),
            "n_estimators_best": model.best_iteration_ or lgb_params["n_estimators"],
        })
        print(f"    Fold {fold_idx + 1}: AUC={auc:.4f} | AP={ap:.4f} | P={prec:.3f} R={rec:.3f} F1={f1:.3f} | val={len(X_val)}")

    if not fold_metrics:
        return {"error": "Nessun fold valido completato."}

    # Metriche aggregate
    aucs = [m["roc_auc"] for m in fold_metrics]
    aps = [m["avg_precision"] for m in fold_metrics]
    summary = {
        "target": target,
        "n_features": len(X.columns),
        "n_rows_training": int(len(y)),
        "class_balance_pos_pct": round(n_pos / len(y) * 100, 2),
        "cv_folds_completed": len(fold_metrics),
        "roc_auc_mean": round(float(np.mean(aucs)), 4),
        "roc_auc_std": round(float(np.std(aucs)), 4),
        "avg_precision_mean": round(float(np.mean(aps)), 4),
        "avg_precision_std": round(float(np.std(aps)), 4),
        "fold_details": fold_metrics,
    }

    # Train modello finale su tutti i dati
    print("\n  Training modello finale su tutti i dati…")
    final_model = lgb.LGBMClassifier(**{**lgb_params, "n_estimators": int(np.mean([m["n_estimators_best"] for m in fold_metrics]))})
    final_model.fit(X, y)

    # Feature importance
    fi = pd.DataFrame({
        "feature": X.columns,
        "importance_gain": final_model.booster_.feature_importance(importance_type="gain"),
        "importance_split": final_model.booster_.feature_importance(importance_type="split"),
    }).sort_values("importance_gain", ascending=False)

    summary["top_20_features_gain"] = fi.head(20)[["feature", "importance_gain"]].to_dict(orient="records")

    # Salva feature importance CSV
    fi.to_csv(output_dir / "feature_importance.csv", index=False)
    print(f"  Feature importance salvata: {output_dir / 'feature_importance.csv'}")

    # Plot feature importance
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 8))
        top30 = fi.head(30)
        ax.barh(top30["feature"][::-1], top30["importance_gain"][::-1])
        ax.set_title(f"Top 30 Feature Importance (Gain) — target: {target}")
        ax.set_xlabel("Gain")
        plt.tight_layout()
        plt.savefig(output_dir / "feature_importance.png", dpi=100)
        plt.close()
        print(f"  Feature importance plot: {output_dir / 'feature_importance.png'}")
    except Exception:
        pass

    # Salva modello
    if save_model:
        try:
            import joblib
            model_path = output_dir / f"lgbm_baseline_{target}.pkl"
            joblib.dump(final_model, model_path)
            print(f"  Modello salvato: {model_path}")
            summary["model_path"] = str(model_path)
        except ImportError:
            print("  [skip save] joblib non installato.")

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="EDA + baseline LightGBM per trade_dataset")
    ap.add_argument("--csv", type=Path, default=_DEFAULT_CSV, help="Path al CSV dataset")
    ap.add_argument("--target", default=_DEFAULT_TARGET, help="Colonna target (default: tp1_hit)")
    ap.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    ap.add_argument("--save-model", action="store_true", help="Salva modello LightGBM con joblib")
    ap.add_argument("--cv-splits", type=int, default=5)
    ap.add_argument("--no-plots", action="store_true", help="Salta generazione plot")
    ap.add_argument("--eda-only", action="store_true", help="Solo EDA, salta training")
    ap.add_argument("--model-only", action="store_true", help="Solo training, salta EDA dettagliata")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"ERRORE: CSV non trovato: {args.csv}")
        print("Genera prima il dataset con: python build_trade_dataset.py")
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Caricamento dataset: {args.csv}")
    df = _load_csv(args.csv)
    print(f"  Righe: {len(df):,} | Colonne: {len(df.columns)}")

    full_report: dict = {
        "csv_path": str(args.csv),
        "csv_size_rows": len(df),
        "target": args.target,
        "columns": list(df.columns),
    }

    # ── EDA ──────────────────────────────────────────────────────────────────
    if not args.model_only:
        print("\n=== EDA ===")
        eda_report = run_eda(df, args.target, args.output_dir, args.no_plots)
        full_report["eda"] = eda_report

        print(f"\n  Righe totali      : {eda_report['overview']['total_rows']:,}")
        print(f"  was_executed      : {eda_report['overview']['was_executed']}")
        print(f"  Target valido     : {eda_report['overview']['target_valid_rows']:,}")
        print(f"  Base rate (target): {eda_report['overview']['target_base_rate_pct']}%")

        if eda_report.get("nan_report"):
            print(f"\n  Colonne con NaN ({len(eda_report['nan_report'])}):")
            for col, info in list(eda_report["nan_report"].items())[:15]:
                print(f"    {col:<35} {info['missing_pct']:6.1f}%")
            if len(eda_report["nan_report"]) > 15:
                print(f"    ... e altre {len(eda_report['nan_report']) - 15}")

        if eda_report.get("wr_by_vix_regime"):
            print("\n  Win Rate per regime VIX:")
            for regime, stats in sorted(eda_report["wr_by_vix_regime"].items()):
                print(f"    {regime:<12}: WR={stats['wr']}%  n={stats['n']}")

        if eda_report.get("wr_earnings_window"):
            print("\n  Win Rate in/out earnings window:")
            for k, stats in eda_report["wr_earnings_window"].items():
                label = "in window" if k in ("True", "1", "1.0") else "out of window"
                print(f"    {label:<20}: WR={stats['wr']}%  n={stats['n']}")

    # ── Modello baseline ─────────────────────────────────────────────────────
    if not args.eda_only:
        if args.target not in df.columns:
            print(f"\nERRORE: colonna target '{args.target}' non trovata nel dataset.")
            print(f"Colonne disponibili: {[c for c in df.columns if 'hit' in c or 'pnl' in c or 'stop' in c]}")
        else:
            print(f"\n=== Baseline LightGBM (target: {args.target}) ===")
            model_report = run_baseline_model(
                df, args.target, args.output_dir, args.cv_splits, args.save_model
            )
            full_report["model"] = model_report

            if "error" not in model_report:
                print(f"\n  ── Risultati CV ({model_report['cv_folds_completed']} fold) ──")
                print(f"  ROC-AUC : {model_report['roc_auc_mean']:.4f} ± {model_report['roc_auc_std']:.4f}")
                print(f"  Avg-Prec: {model_report['avg_precision_mean']:.4f} ± {model_report['avg_precision_std']:.4f}")
                print(f"  Features: {model_report['n_features']} | Class balance: {model_report['class_balance_pos_pct']}% positivi")
                print("\n  Top 10 feature (gain):")
                for row in model_report.get("top_20_features_gain", [])[:10]:
                    print(f"    {row['feature']:<40} {row['importance_gain']:,.0f}")
            else:
                print(f"\n  ERRORE training: {model_report['error']}")

    # ── Salva report JSON ─────────────────────────────────────────────────────
    report_path = args.output_dir / "eda_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReport salvato: {report_path}")
    print(f"Output dir    : {args.output_dir}/")


if __name__ == "__main__":
    main()
