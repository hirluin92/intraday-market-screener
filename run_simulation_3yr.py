#!/usr/bin/env python3
"""
Simulazione 3 anni con strategia v2 (nuovi pattern + filtri regime + SL/TP ottimizzati).

Esegui da root repo (il backend deve essere avviato su localhost:8000):
  python run_simulation_3yr.py

Confronta automaticamente:
  A) Strategia VECCHIA: solo compression + rsi_momentum, regime filter base
  B) Strategia NUOVA v2: tutti i pattern validati con filtri regime specifici

Output: tabella comparativa con equity finale, WR, EV, drawdown, mesi profittevoli.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import httpx
except ImportError:
    print("Installa httpx: pip install httpx")
    sys.exit(1)

BASE_URL = "http://localhost:8000/api/v1/backtest/simulation"

# ── Universo simboli v4.2 ────────────────────────────────────────────────────
SYMBOLS_V42 = [
    "GOOGL", "TSLA", "AMD", "META", "NVDA", "NFLX", "COIN", "MSTR", "HOOD",
    "SHOP", "SOFI", "ZS", "NET", "CELH", "RBLX", "PLTR", "HPE", "MDB",
    "SMCI", "DELL", "ACHR", "ASTS", "JOBY", "RKLB", "NNE", "OKLO", "WULF",
    "APLD", "SMR", "RXRX", "NVO", "LLY", "MRNA", "NKE", "TGT", "NEM",
    "SCHW", "WMT", "SPY",
]

# ── Configurazioni da confrontare ────────────────────────────────────────────
CONFIGS: list[dict[str, Any]] = [
    {
        "label": "VECCHIA (v4.2 originale)",
        "pattern_names": [
            "compression_to_expansion_transition",
            "rsi_momentum_continuation",
        ],
        "use_regime_filter": True,
        "min_strength": 0.70,
        "color": "🔵",
    },
    {
        "label": "NUOVA v2 (tutti i pattern validati)",
        "pattern_names": [
            # Universali
            "compression_to_expansion_transition",
            "rsi_momentum_continuation",
            "double_bottom",
            "double_top",
            # Regime-dipendenti (bear-only e bull-only)
            # Il regime filter gestisce la direzione; pattern specifici
            # filtrati per direction alignment nel simulation engine
            "engulfing_bullish",
            "macd_divergence_bull",
            "rsi_divergence_bull",
            "rsi_divergence_bear",
            "macd_divergence_bear",
        ],
        "use_regime_filter": True,
        "min_strength": 0.70,
        "color": "🟢",
    },
    {
        "label": "NUOVA v2 — solo universali (no regime-specific)",
        "pattern_names": [
            "compression_to_expansion_transition",
            "rsi_momentum_continuation",
            "double_bottom",
            "double_top",
        ],
        "use_regime_filter": True,
        "min_strength": 0.70,
        "color": "🟡",
    },
]

# ── Parametri comuni ─────────────────────────────────────────────────────────
COMMON_PARAMS = {
    "provider": "yahoo_finance",
    "timeframe": "1h",
    "initial_capital": 10000.0,
    "risk_per_trade_pct": 1.0,
    "cost_rate": 0.0015,
    "max_simultaneous": 3,
    "track_capital": True,
    "use_temporal_quality": True,
    "regime_variant": "ema50",
    "date_from": "2022-04-01",
    "date_to": "2025-04-01",   # 3 anni esatti
    "pattern_row_limit": 100000,  # massimo consentito dall'API
    "include_trades": False,   # non serve il dettaglio per ogni trade
}


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "  n/a "
    return f"{v:+.1f}%"


def _fmt_r(v: float | None) -> str:
    if v is None:
        return "  n/a "
    return f"{v:+.3f}R"


def _fmt_equity(v: float | None, initial: float = 10000.0) -> str:
    if v is None:
        return "  n/a "
    gain_pct = (v - initial) / initial * 100
    sign = "+" if gain_pct >= 0 else ""
    return f"€{v:,.0f}  ({sign}{gain_pct:.1f}%)"


def _run_simulation(config: dict[str, Any]) -> dict[str, Any] | None:
    params = dict(COMMON_PARAMS)
    params["use_regime_filter"] = config["use_regime_filter"]
    params["min_strength"] = config["min_strength"]

    # Aggiungi simboli come include_symbols
    for sym in SYMBOLS_V42:
        pass  # gestito sotto con lista

    # Build query params (httpx accetta liste per parametri ripetuti)
    query: dict[str, Any] = {k: v for k, v in params.items()}
    query["pattern_names"] = config["pattern_names"]
    query["include_symbols"] = SYMBOLS_V42

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.get(BASE_URL, params=query)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        print(f"  ❌ HTTP error {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        print(f"  ❌ Errore: {e}")
        return None


def _extract_stats(data: dict[str, Any]) -> dict[str, Any]:
    """Estrae le metriche principali dalla risposta (struttura flat, non nested summary)."""
    # La risposta BacktestSimulationResponse è flat (non ha un sotto-oggetto "summary")
    eq = data.get("equity_curve", [])
    initial = data.get("initial_capital", 10000.0)
    final_equity = data.get("final_capital")

    # Equity finale dall'ultimo punto curva se non disponibile
    if final_equity is None and eq:
        final_equity = eq[-1].get("equity")

    # Calcolo mensile: raggruppa equity per mese YYYY-MM
    from collections import defaultdict
    monthly_returns: list[float] = []
    if eq and len(eq) >= 2:
        by_month: dict[str, list[float]] = defaultdict(list)
        for pt in eq:
            ts_raw = pt.get("timestamp") or pt.get("date")
            if ts_raw:
                try:
                    month = str(ts_raw)[:7]  # YYYY-MM
                    by_month[month].append(pt.get("equity", initial))
                except Exception:
                    pass
        if by_month:
            months = sorted(by_month.keys())
            prev_eq = initial
            for m in months:
                last_eq = by_month[m][-1]
                ret = (last_eq - prev_eq) / prev_eq * 100
                monthly_returns.append(ret)
                prev_eq = last_eq

    profitable_months = sum(1 for r in monthly_returns if r > 0)
    total_months = len(monthly_returns)

    return {
        "n_signals":         data.get("total_trades"),
        "n_executed":        data.get("total_trades"),
        "n_skipped_regime":  data.get("trades_skipped_by_regime"),
        "win_rate":          data.get("win_rate"),
        "ev_r":              data.get("expectancy_r"),
        "max_drawdown_pct":  data.get("max_drawdown_pct"),
        "final_equity":      final_equity,
        "initial_capital":   initial,
        "profit_factor":     data.get("profit_factor"),
        "total_return_pct":  data.get("total_return_pct"),
        "sharpe":            data.get("sharpe_ratio"),
        "profitable_months": profitable_months,
        "total_months":      total_months,
        "monthly_returns":   monthly_returns,
    }


def _print_equity_bar(monthly_returns: list[float], width: int = 36) -> None:
    """Barra ASCII con + e - per i mesi profittevoli/perdenti."""
    if not monthly_returns:
        return
    line = ""
    for r in monthly_returns:
        if r > 2:
            line += "█"
        elif r > 0:
            line += "▓"
        elif r > -2:
            line += "░"
        else:
            line += "▁"
    print(f"    Mesi: {line}  (█=ottimo ▓=positivo ░=lieve neg ▁=neg)")


def main() -> None:
    print("\n" + "=" * 72)
    print("  SIMULAZIONE 3 ANNI — CONFRONTO STRATEGIA VECCHIA vs NUOVA v2")
    print("=" * 72)
    print(f"  Periodo:   2022-04-01 → 2025-04-01  (36 mesi)")
    print(f"  Capitale:  €10.000  |  Rischio: 1% per trade  |  Max simultanei: 3")
    print(f"  Universo:  {len(SYMBOLS_V42)} simboli v4.2  |  Costi: 0.15% round-trip")
    print(f"  Regime filter: attivo (EMA50)\n")

    results: list[tuple[dict, dict]] = []

    for cfg in CONFIGS:
        print(f"  {cfg['color']} {cfg['label']}...")
        print(f"      Pattern: {', '.join(cfg['pattern_names'])}")
        data = _run_simulation(cfg)
        if data is None:
            print("      SKIP (errore)\n")
            continue
        stats = _extract_stats(data)
        results.append((cfg, stats))
        print(f"      ✓ completato ({stats.get('n_executed', 0)} trade eseguiti)\n")

    if not results:
        print("\n  Nessun risultato — verificare che il backend sia avviato su localhost:8000")
        return

    # ── Report comparativo ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  RISULTATI COMPARATIVI")
    print("=" * 72)

    col_w = 24
    metrics = [
        ("Trade eseguiti",       "n_executed",          lambda v: f"{v:,}" if v else "n/a"),
        ("Saltati x regime",     "n_skipped_regime",    lambda v: f"{v:,}" if v else "n/a"),
        ("Win Rate",             "win_rate",            lambda v: f"{v:.1f}%" if v else "n/a"),
        ("EV (expectancy)",      "ev_r",                _fmt_r),
        ("Profit Factor",        "profit_factor",       lambda v: f"{v:.2f}" if v else "n/a"),
        ("Sharpe Ratio",         "sharpe",              lambda v: f"{v:.2f}" if v else "n/a"),
        ("Max Drawdown",         "max_drawdown_pct",    lambda v: f"{v:.1f}%" if v else "n/a"),
        ("Ritorno totale",       "total_return_pct",    lambda v: f"{v:+.1f}%" if v else "n/a"),
        ("Equity finale",        "final_equity",        lambda v: _fmt_equity(v)),
        ("Mesi profittevoli",    "profitable_months",   lambda v: f"{v}/{results[0][1]['total_months']}" if v else "n/a"),
    ]

    # Header
    header = f"  {'Metrica':<28}"
    for cfg, _ in results:
        header += f"  {cfg['color']} {cfg['label'][:col_w]:<{col_w}}"
    print(header)
    print("  " + "─" * (28 + (col_w + 4) * len(results)))

    for label, key, fmt in metrics:
        row = f"  {label:<28}"
        for cfg, stats in results:
            val = stats.get(key)
            try:
                formatted = fmt(val)
            except Exception:
                formatted = str(val)
            row += f"  {formatted:<{col_w+2}}"
        print(row)

    # ── Equity mensile ─────────────────────────────────────────────────────────
    print(f"\n  {'─'*72}")
    print("  ANDAMENTO MENSILE")
    print(f"  {'─'*72}")
    for cfg, stats in results:
        print(f"\n  {cfg['color']} {cfg['label']}")
        _print_equity_bar(stats.get("monthly_returns", []))

    # ── Delta vs vecchia strategia ─────────────────────────────────────────────
    if len(results) >= 2:
        print(f"\n  {'─'*72}")
        print("  GUADAGNO AGGIUNTIVO vs STRATEGIA VECCHIA")
        print(f"  {'─'*72}")
        base_equity = results[0][1].get("final_equity") or 10000
        base_wr = results[0][1].get("win_rate") or 0
        base_ev = results[0][1].get("ev_r") or 0
        for cfg, stats in results[1:]:
            new_equity = stats.get("final_equity") or 10000
            delta_eur = new_equity - base_equity
            delta_pct = (new_equity - base_equity) / base_equity * 100 if base_equity else 0
            new_wr = stats.get("win_rate") or 0
            new_ev = stats.get("ev_r") or 0
            sign = "+" if delta_eur >= 0 else ""
            wr_delta = new_wr - base_wr
            ev_delta = new_ev - base_ev
            wr_sign = "+" if wr_delta >= 0 else ""
            ev_sign = "+" if ev_delta >= 0 else ""
            print(f"\n  {cfg['color']} {cfg['label']}")
            print(f"      Equity:      {sign}€{delta_eur:,.0f}  ({sign}{delta_pct:.1f}% vs vecchia)")
            print(f"      Win Rate:    {wr_sign}{wr_delta:.1f}pp  ({new_wr:.1f}% vs {base_wr:.1f}%)")
            print(f"      EV/trade:    {ev_sign}{ev_delta:+.3f}R  ({new_ev:+.3f}R vs {base_ev:+.3f}R)")

    print()


if __name__ == "__main__":
    main()
