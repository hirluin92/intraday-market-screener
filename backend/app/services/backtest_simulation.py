"""Re-export: simulazione equity in ``simulation_service`` (forward return da candele, deterministico)."""

from app.services.simulation_service import run_backtest_simulation, run_simulation

__all__ = ["run_backtest_simulation", "run_simulation"]
