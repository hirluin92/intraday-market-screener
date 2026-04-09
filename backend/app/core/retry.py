"""
Utility retry con backoff esponenziale per chiamate esterne transienti.

Uso tipico:
    from app.core.retry import with_retry

    data = await with_retry(
        lambda: exchange.fetch_ohlcv(symbol, tf),
        label="binance.fetch_ohlcv",
        max_attempts=3,
    )
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_BASE_DELAY = 5.0   # secondi tra primo e secondo tentativo
_DEFAULT_BACKOFF    = 2.0   # moltiplicatore
_DEFAULT_MAX_DELAY  = 30.0  # cap massimo tra tentativi
_DEFAULT_MAX_ATTEMPTS = 3


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    label: str = "operation",
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY,
    backoff: float = _DEFAULT_BACKOFF,
    max_delay: float = _DEFAULT_MAX_DELAY,
    reraise: bool = True,
) -> T:
    """
    Chiama ``fn()`` fino a ``max_attempts`` volte con backoff esponenziale.

    - Riloga ogni tentativo fallito come WARNING.
    - Se tutti i tentativi esauriscono l'eccezione dell'ultimo viene ri-lanciata
      (se ``reraise=True``) oppure viene restituita ``None`` (se ``reraise=False``).
    """
    delay = base_delay
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "%s: tentativo %d/%d fallito (%s: %s) — retry tra %.1fs",
                    label,
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff, max_delay)
            else:
                logger.error(
                    "%s: tutti i %d tentativi falliti — ultimo errore: %s: %s",
                    label,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )

    if reraise and last_exc is not None:
        raise last_exc
    return None  # type: ignore[return-value]
