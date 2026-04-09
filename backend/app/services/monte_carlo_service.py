"""
Monte Carlo: bootstrap sui trade storici (ricampionamento con replacement)
per stimare distribuzione di drawdown massimo e rendimento finale.

Non preserva dipendenze temporali tra trade (bootstrap i.i.d.).
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class MonteCarloResult:
    n_simulations: int
    n_trades_per_sim: int
    dd_median_pct: float
    dd_p95_pct: float
    dd_p99_pct: float
    dd_max_ever_pct: float
    ret_median_pct: float
    ret_p5_pct: float
    ret_p95_pct: float
    pct_simulations_positive: float
    pct_simulations_ruin: float


def _percentile_sorted(sorted_lst: list[float], p: float) -> float:
    """Percentile p in [0, 100] su lista già ordinata (indice lineare)."""
    if not sorted_lst:
        return 0.0
    n = len(sorted_lst)
    if n == 1:
        return sorted_lst[0]
    idx = int(round((n - 1) * (p / 100.0)))
    idx = max(0, min(idx, n - 1))
    return sorted_lst[idx]


def run_monte_carlo(
    pnl_r_list: list[float],
    *,
    n_simulations: int = 1000,
    n_trades: int | None = None,
    initial_capital: float = 10000.0,
    risk_per_trade_pct: float = 1.0,
    seed: int = 42,
) -> MonteCarloResult:
    """
    Bootstrap Monte Carlo su R netti storici (``pnl_r_net`` per trade).

    Per ogni simulazione: ricampiona ``n_trades`` valori con replacement, poi
    ``equity *= (1 + pnl_r_net * risk_per_trade_pct/100)`` in sequenza e calcola
    max drawdown % e rendimento totale %.
    """
    rng = random.Random(seed)

    if not pnl_r_list:
        raise ValueError("pnl_r_list vuota — nessun trade da ricampionare")

    n = n_trades if n_trades is not None else len(pnl_r_list)
    if n < 1:
        raise ValueError("n_trades deve essere >= 1")

    risk_fraction = risk_per_trade_pct / 100.0

    drawdowns: list[float] = []
    returns: list[float] = []

    for _ in range(n_simulations):
        sample = rng.choices(pnl_r_list, k=n)

        equity = float(initial_capital)
        peak = float(initial_capital)
        max_dd = 0.0

        for pnl_r in sample:
            equity *= 1.0 + pnl_r * risk_fraction
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd

        drawdowns.append(max_dd)
        final_return = (equity - initial_capital) / initial_capital * 100.0
        returns.append(final_return)

    drawdowns.sort()
    returns.sort()

    pct_positive = sum(1 for r in returns if r > 0) / len(returns) * 100.0
    pct_ruin = sum(1 for d in drawdowns if d > 50.0) / len(drawdowns) * 100.0

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades_per_sim=n,
        dd_median_pct=round(_percentile_sorted(drawdowns, 50.0), 2),
        dd_p95_pct=round(_percentile_sorted(drawdowns, 95.0), 2),
        dd_p99_pct=round(_percentile_sorted(drawdowns, 99.0), 2),
        dd_max_ever_pct=round(max(drawdowns), 2),
        ret_median_pct=round(_percentile_sorted(returns, 50.0), 2),
        ret_p5_pct=round(_percentile_sorted(returns, 5.0), 2),
        ret_p95_pct=round(_percentile_sorted(returns, 95.0), 2),
        pct_simulations_positive=round(pct_positive, 1),
        pct_simulations_ruin=round(pct_ruin, 1),
    )
