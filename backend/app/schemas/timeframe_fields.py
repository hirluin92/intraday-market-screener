"""Reusable Pydantic types for optional timeframe validation (multi-market MVP)."""

from typing import Annotated

from pydantic import AfterValidator

from app.core.timeframes import ALLOWED_TIMEFRAMES_SET, ALL_MARKETS_TIMEFRAMES_SET


def _validate_optional_binance_timeframe(v: str | None) -> str | None:
    if v is None:
        return None
    if v not in ALLOWED_TIMEFRAMES_SET:
        raise ValueError(
            f"timeframe must be one of {sorted(ALLOWED_TIMEFRAMES_SET)}, got {v!r}",
        )
    return v


def _validate_optional_all_markets_timeframe(v: str | None) -> str | None:
    if v is None:
        return None
    if v not in ALL_MARKETS_TIMEFRAMES_SET:
        raise ValueError(
            f"timeframe must be one of {sorted(ALL_MARKETS_TIMEFRAMES_SET)}, got {v!r}",
        )
    return v


# Solo pipeline / scheduler crypto (Binance).
OptionalBinanceTimeframe = Annotated[str | None, AfterValidator(_validate_optional_binance_timeframe)]

# GET e filtri che possono includere serie Yahoo (es. 1d).
OptionalAllMarketsTimeframe = Annotated[str | None, AfterValidator(_validate_optional_all_markets_timeframe)]

