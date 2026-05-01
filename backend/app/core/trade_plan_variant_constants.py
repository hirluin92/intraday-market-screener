"""
Re-export shim — all constants now live in app/core/constants/ submodules.
Kept for backward compatibility: all ~30 existing importers work unchanged.
"""

# flake8: noqa: F401,F403
from app.core.constants.backtest import *   # noqa: F401,F403
from app.core.constants.patterns import *   # noqa: F401,F403
from app.core.constants.risk import *       # noqa: F401,F403
from app.core.constants.scheduling import * # noqa: F401,F403
from app.core.constants.symbols import *    # noqa: F401,F403

# Private names excluded from wildcard import — re-exported explicitly
from app.core.constants.risk import _SLIPPAGE_R_THRESHOLD      # noqa: F401
from app.core.constants.symbols import _UK_SYMBOLS_BLOCKED_A8  # noqa: F401
