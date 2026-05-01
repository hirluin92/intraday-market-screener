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
    Cache in-memory con TTL e stale-while-revalidate per scadenza naturale.

    Comportamento:
    - Hit valido (TTL non scaduto): ritorna immediatamente.
    - Scaduto per TTL (chiave presente ma expires_at nel passato): ritorna il valore
      precedente (stale) immediatamente E avvia un recompute in background. Così
      nessuna richiesta frontend viene bloccata su una chiave che scade per TTL.
    - Miss completo (chiave eliminata o mai calcolata): blocca e calcola.

    Le operazioni di invalidazione esplicita (invalidate_all, invalidate_keys_containing)
    ELIMINANO le chiavi dallo store (comportamento originale), così i dati invalidati
    vengono ricalcolati in modo bloccante alla prima richiesta successiva.
    Le chiavi ALL/ALL non vengono mai toccate dalle invalidazioni per-job (le needle
    specifiche non matchano i wildcard), quindi scadono solo per TTL e beneficiano
    del path stale-while-revalidate senza bloccare.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.opportunity_lookup_cache_ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._recomputing: set[str] = set()
        self._global_lock = asyncio.Lock()

    async def get_or_compute(
        self,
        key: str,
        compute: Callable[[], Coroutine[Any, Any, T]] | Callable[[], Awaitable[T]],
    ) -> T:
        now = time.monotonic()

        # Fast path (hit valido) + stale-while-revalidate (TTL scaduto ma chiave presente).
        if key in self._store:
            value, expires_at = self._store[key]
            if now < expires_at:
                return value  # type: ignore[return-value]

            # Stale-while-revalidate: TTL scaduto ma chiave presente.
            # Avvia UN SOLO recompute in background e ritorna subito il valore vecchio (stale).
            #
            # ensure_future è dentro il lock: garantisce che il task venga creato
            # atomicamente con il flag _recomputing. Se fosse fuori, una cancellazione
            # tra add(key) e ensure_future lascerebbe la chiave in _recomputing per sempre
            # (il finally di _background_recompute non girerebbe mai).
            async with self._global_lock:
                already = key in self._recomputing
                if not already:
                    self._recomputing.add(key)
                    asyncio.ensure_future(
                        self._background_recompute(key, compute)  # type: ignore[arg-type]
                    )
            logger.debug("Cache TTL scaduto per '%s' — stale servito, recompute in background", key)
            return value  # type: ignore[return-value]

        # Miss: chiave eliminata (invalidazione esplicita) o mai calcolata.
        # Blocca su un lock per-chiave per evitare stampede:
        # N richieste concurrent sulla stessa chiave mancante aspettano tutte il lock,
        # la prima calcola e scrive nello store, le successive trovano il valore già
        # presente al double-check dentro il lock e ritornano senza ricalcolare.
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            key_lock = self._locks[key]

        async with key_lock:
            now = time.monotonic()
            if key in self._store:
                value, expires_at = self._store[key]
                if now < expires_at:
                    return value  # type: ignore[return-value]

            logger.debug("Cache miss per chiave '%s' — calcolo bloccante", key)
            value = await self._do_compute(key, compute)  # type: ignore[arg-type]
            # Rimuovi il lock per-key dopo il compute: non serve più finché la chiave
            # è nello store valida. Verrà ricreato se la chiave viene eliminata.
            async with self._global_lock:
                self._locks.pop(key, None)
            return value  # type: ignore[return-value]

    async def _do_compute(
        self,
        key: str,
        compute: Callable[[], Awaitable[Any]],
    ) -> Any:
        t0 = time.monotonic()
        try:
            value = await compute()
        except Exception:
            logger.exception("Cache compute fallito per chiave '%s'", key)
            raise
        elapsed = time.monotonic() - t0
        logger.info("Cache: calcolato '%s' in %.2fs, TTL=%ds", key, elapsed, self._ttl)
        self._store[key] = (value, time.monotonic() + self._ttl)
        return value

    async def _background_recompute(
        self,
        key: str,
        compute: Callable[[], Awaitable[Any]],
    ) -> None:
        try:
            await self._do_compute(key, compute)
            logger.debug("Cache: background recompute completato per '%s'", key)
        except Exception:
            logger.warning("Cache: background recompute fallito per '%s' — stale rimane", key)
        finally:
            async with self._global_lock:
                self._recomputing.discard(key)

    async def invalidate_keys_containing(self, needle: str) -> None:
        """Elimina le chiavi che contengono ``needle`` (comportamento originale).

        La chiave viene rimossa: la prossima richiesta ricalcola in modo bloccante.
        Non tocca le chiavi wildcard (es. all/all) che non contengono la needle.
        """
        async with self._global_lock:
            to_del = [k for k in list(self._store.keys()) if needle in k]
            for k in to_del:
                self._store.pop(k, None)
                self._locks.pop(k, None)
        if to_del:
            logger.info("Cache: invalidate %d chiavi contenenti %r", len(to_del), needle)

    async def invalidate_all(self) -> None:
        """Elimina tutte le chiavi (comportamento originale).

        Usato raramente: preferire invalidate_keys_containing per invalidazioni chirurgiche.
        """
        async with self._global_lock:
            n = len(self._store)
            self._store.clear()
            self._locks.clear()
            self._recomputing.clear()
        logger.info("Cache: eliminate tutte le %d chiavi", n)

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
            "recomputing": len(self._recomputing),
            "ttl_seconds": self._ttl,
        }


pattern_quality_cache = TTLCache()
trade_plan_backtest_cache = TTLCache(ttl_seconds=settings.backtest_cache_ttl_seconds)
variant_best_cache = TTLCache(ttl_seconds=settings.backtest_cache_ttl_seconds)


async def invalidate_opportunity_lookups_after_pipeline(
    *,
    provider: str,
    exchange: str,
    timeframe: str | None,
) -> None:
    """
    Dopo un pipeline refresh, invalida solo pattern_quality_cache.

    trade_plan_backtest_cache e variant_best_cache NON vengono invalidate: entrambe
    calcolano statistiche su 2+ anni di dati storici che non cambiano significativamente
    con un nuovo candle. Hanno TTL lungo (backtest_cache_ttl_seconds, default 3600s) e
    vengono aggiornate in background via stale-while-revalidate quando scadono.

    Invalidare tpb e var ad ogni ciclo pipeline causava ricalcoli bloccanti di ~90s
    (70s tpb + 20s var) inside il job timeout, rendendo impossibili i cicli 5m.

    Nota: le chiavi cache usano ``"*"`` per valori None/vuoti (funzione ``n()`` in
    ``opportunity_lookup_key``). La needle deve usare la stessa normalizzazione.
    """
    if not (timeframe or "").strip():
        await pattern_quality_cache.invalidate_all()
        logger.info(
            "opportunity lookup cache: pq invalidate_all (pipeline senza timeframe esplicito)",
        )
        return

    def _norm(x: str) -> str:
        s = x.strip()
        return s if s else "*"

    needle = f"|{_norm(provider)}|{_norm(exchange)}|{_norm(timeframe)}|"
    await pattern_quality_cache.invalidate_keys_containing(needle)
    logger.info(
        "opportunity lookup cache: pq invalidate per provider=%s exchange=%s timeframe=%s",
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
