"""
Cache in-memory semplice con TTL per lookup costosi (opportunities / backtest on-demand).
Thread-safe per uso con asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


def opportunity_lookup_key(
    kind: str,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None,
    asset_type: str | None,
    timeframe: str | None,
    cost_rate: float | None = None,
    limit: int | None = None,
) -> str:
    """Chiave stabile per lookup che dipendono da filtri serie + costi simulazione."""

    def n(x: str | None) -> str:
        return (x or "").strip() or "*"

    parts = [kind, n(provider), n(exchange), n(timeframe), n(symbol), n(asset_type)]
    if cost_rate is not None:
        parts.append(f"{float(cost_rate):.6f}")
    if limit is not None:
        parts.append(str(int(limit)))
    return "|".join(parts)


class TTLCache:
    """
    Cache in-memory con TTL (Time To Live).

    Se ``compute()`` solleva, l'eccezione viene propagata e **non** si cachea nulla.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.opportunity_lookup_cache_ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get_or_compute(
        self,
        key: str,
        compute: Callable[[], Coroutine[Any, Any, T]] | Callable[[], Awaitable[T]],
    ) -> T:
        now = time.monotonic()
        if key in self._store:
            value, expires_at = self._store[key]
            if now < expires_at:
                return value

        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            key_lock = self._locks[key]

        async with key_lock:
            now = time.monotonic()
            if key in self._store:
                value, expires_at = self._store[key]
                if now < expires_at:
                    return value

            logger.debug("Cache miss per chiave '%s' — ricalcolo", key)
            t0 = time.monotonic()
            try:
                value = await compute()  # type: ignore[misc]
            except Exception:
                logger.exception("Cache compute fallito per chiave '%s'", key)
                raise
            elapsed = time.monotonic() - t0
            logger.info(
                "Cache: calcolato '%s' in %.2fs, TTL=%ds",
                key,
                elapsed,
                self._ttl,
            )
            self._store[key] = (value, time.monotonic() + self._ttl)
            return value

    async def invalidate_keys_containing(self, needle: str) -> None:
        """Rimuove tutte le chiavi che contengono ``needle``."""
        async with self._global_lock:
            to_del = [k for k in list(self._store.keys()) if needle in k]
            for k in to_del:
                self._store.pop(k, None)
        if to_del:
            logger.info("Cache: invalidate_keys_containing %r — rimosse %d chiavi", needle, len(to_del))

    async def invalidate_all(self) -> None:
        async with self._global_lock:
            n = len(self._store)
            self._store.clear()
        logger.info("Cache svuotata completamente (%d chiavi)", n)

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        valid = 0
        for _, exp in self._store.values():
            if now < exp:
                valid += 1
        expired = len(self._store) - valid
        return {
            "total_keys": len(self._store),
            "valid_keys": valid,
            "expired_keys": expired,
            "ttl_seconds": self._ttl,
        }


pattern_quality_cache = TTLCache()
trade_plan_backtest_cache = TTLCache()
variant_best_cache = TTLCache()


async def invalidate_opportunity_lookups_after_pipeline(
    *,
    provider: str,
    exchange: str,
    timeframe: str | None,
) -> None:
    """
    Dopo un pipeline refresh, invalida i lookup coerenti con provider/exchange/timeframe.

    Se ``timeframe`` è assente, svuota tutte e tre le cache (refresh troppo ampio per
    chiavi puntuali).

    Nota: le chiavi cache usano ``"*"`` per valori None/vuoti (funzione ``n()`` in
    ``opportunity_lookup_key``). La needle deve usare la stessa normalizzazione per
    garantire il match — es. exchange=None dallo scheduler explicit → needle ``|*|``
    non ``||``.
    """
    if not (timeframe or "").strip():
        await pattern_quality_cache.invalidate_all()
        await trade_plan_backtest_cache.invalidate_all()
        await variant_best_cache.invalidate_all()
        logger.info(
            "opportunity lookup cache: invalidate_all (pipeline senza timeframe esplicito)",
        )
        return

    def _norm(x: str) -> str:
        """Coerente con ``n()`` in ``opportunity_lookup_key``: vuoto → '*'."""
        s = x.strip()
        return s if s else "*"

    needle = f"|{_norm(provider)}|{_norm(exchange)}|{_norm(timeframe)}|"
    await pattern_quality_cache.invalidate_keys_containing(needle)
    await trade_plan_backtest_cache.invalidate_keys_containing(needle)
    await variant_best_cache.invalidate_keys_containing(needle)
    logger.info(
        "opportunity lookup cache: invalidate per provider=%s exchange=%s timeframe=%s",
        provider,
        exchange,
        timeframe,
    )


async def all_opportunity_lookup_cache_stats() -> dict[str, Any]:
    return {
        "pattern_quality": pattern_quality_cache.stats(),
        "trade_plan_backtest": trade_plan_backtest_cache.stats(),
        "variant_best": variant_best_cache.stats(),
    }
