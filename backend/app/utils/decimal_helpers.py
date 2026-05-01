from decimal import Decimal
from typing import Union


def _f(v: Union[float, Decimal, None]) -> float:
    """Convert Decimal or None to float safely."""
    if v is None:
        return 0.0
    return float(v)
