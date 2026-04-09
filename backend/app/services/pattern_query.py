"""Read stored `CandlePattern` rows from the database (MVP)."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    PATTERNS_BLOCKED,
    VALIDATED_PATTERNS_OPERATIONAL,
)
from app.models.candle_pattern import CandlePattern

# Chiave serie per la confluence lookup: (exchange, symbol, timeframe)
_SeriesKey = tuple[str, str, str]

# Timestamp effettivo per l'ordinamento principale:
#
# I pattern bloccati (WR < 40%) ricevono una penalità di 8 ore: un segnale
# validato vecchio fino a 8 barre (8h su 1h TF) batte un pattern bloccato
# apparso sulla candela più recente.
# I pattern in sviluppo ricevono una penalità di 4 ore.
#
#   validated  → timestamp reale          (penalità 0h)
#   development→ timestamp - 4h           (penalità 4h)
#   blocked    → timestamp - 8h           (penalità 8h)
_EFFECTIVE_TIMESTAMP = CandlePattern.timestamp - case(
    (
        CandlePattern.pattern_name.in_(list(VALIDATED_PATTERNS_OPERATIONAL)),
        text("interval '0 hours'"),
    ),
    (
        CandlePattern.pattern_name.in_(list(PATTERNS_BLOCKED)),
        text("interval '8 hours'"),
    ),
    else_=text("interval '4 hours'"),
)

# Priorità secondaria (tie-break a parità di timestamp effettivo):
#   0 → validato | 1 → sviluppo | 2 → bloccato
_PATTERN_PRIORITY = case(
    (CandlePattern.pattern_name.in_(list(VALIDATED_PATTERNS_OPERATIONAL)), 0),
    (CandlePattern.pattern_name.in_(list(PATTERNS_BLOCKED)), 2),
    else_=1,
)


async def list_stored_patterns(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
) -> list[CandlePattern]:
    """Recent pattern rows, newest bar first."""
    stmt = select(CandlePattern).order_by(CandlePattern.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(CandlePattern.exchange == exchange)
    if provider is not None:
        stmt = stmt.where(CandlePattern.provider == provider)
    if asset_type is not None:
        stmt = stmt.where(CandlePattern.asset_type == asset_type)
    if symbol is not None:
        stmt = stmt.where(CandlePattern.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CandlePattern.timeframe == timeframe)
    if pattern_name is not None:
        stmt = stmt.where(CandlePattern.pattern_name == pattern_name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_concurrent_patterns_per_series(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    since_hours: int = 168,
) -> dict[_SeriesKey, int]:
    """
    Per ogni (exchange, symbol, timeframe) ritorna il numero di pattern VALIDATI
    distinti rilevati nella stessa barra (max timestamp per serie).

    Usato dallo screener live per il filtro confluenza: un segnale viene promosso
    a "execute" solo se almeno SIGNAL_MIN_CONFLUENCE pattern distinti sono attivi
    contemporaneamente sul simbolo → minor rumore, maggiore convinzione.

    Conta solo pattern in VALIDATED_PATTERNS_OPERATIONAL (esclude bloccati e in
    sviluppo) per garantire che confluenza = più segnali di qualità, non pattern
    non validati che «inquinano» il conteggio.

    `since_hours` limita la scansione per evitare full table scan su tabelle grandi.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    conditions: list = [
        CandlePattern.pattern_name.in_(list(VALIDATED_PATTERNS_OPERATIONAL)),
        CandlePattern.timestamp >= since_dt,
    ]
    if exchange is not None:
        conditions.append(CandlePattern.exchange == exchange)
    if provider is not None:
        conditions.append(CandlePattern.provider == provider)
    if asset_type is not None:
        conditions.append(CandlePattern.asset_type == asset_type)
    if symbol is not None:
        conditions.append(CandlePattern.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandlePattern.timeframe == timeframe)

    # Sottoqury: max timestamp per serie (solo pattern validati)
    max_ts_subq = (
        select(
            CandlePattern.exchange.label("exc"),
            CandlePattern.symbol.label("sym"),
            CandlePattern.timeframe.label("tf"),
            func.max(CandlePattern.timestamp).label("max_ts"),
        )
        .where(and_(*conditions))
        .group_by(
            CandlePattern.exchange,
            CandlePattern.symbol,
            CandlePattern.timeframe,
        )
        .subquery("mts")
    )

    # Query principale: conta pattern distinti alla barra corrente (max_ts)
    stmt = (
        select(
            CandlePattern.exchange,
            CandlePattern.symbol,
            CandlePattern.timeframe,
            func.count(func.distinct(CandlePattern.pattern_name)).label("cnt"),
        )
        .join(
            max_ts_subq,
            and_(
                CandlePattern.exchange == max_ts_subq.c.exc,
                CandlePattern.symbol == max_ts_subq.c.sym,
                CandlePattern.timeframe == max_ts_subq.c.tf,
                CandlePattern.timestamp == max_ts_subq.c.max_ts,
            ),
        )
        .where(and_(*conditions))
        .group_by(
            CandlePattern.exchange,
            CandlePattern.symbol,
            CandlePattern.timeframe,
        )
    )
    result = await session.execute(stmt)
    return {
        (row.exchange, row.symbol, row.timeframe): int(row.cnt) for row in result
    }


async def list_latest_pattern_per_series(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    since_hours: int = 168,
) -> list[CandlePattern]:
    """
    One row per (exchange, symbol, timeframe): the pattern row with latest `timestamp`,
    tie-breaking by stronger `pattern_strength` then `pattern_name` for determinism.

    `since_hours` limits the scan window to avoid full table scans on large datasets.
    168h (7 giorni) copre weekend + festivi per timeframe 1d; su 1h copre 7 giorni (168 barre).
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    conditions = [CandlePattern.timestamp >= since_dt]
    if exchange is not None:
        conditions.append(CandlePattern.exchange == exchange)
    if provider is not None:
        conditions.append(CandlePattern.provider == provider)
    if asset_type is not None:
        conditions.append(CandlePattern.asset_type == asset_type)
    if symbol is not None:
        conditions.append(CandlePattern.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandlePattern.timeframe == timeframe)

    inner = (
        select(
            CandlePattern.id,
            func.row_number()
            .over(
                partition_by=(
                    CandlePattern.exchange,
                    CandlePattern.symbol,
                    CandlePattern.timeframe,
                ),
                order_by=(
                    _EFFECTIVE_TIMESTAMP.desc(),
                    _PATTERN_PRIORITY.asc(),
                    CandlePattern.pattern_strength.desc(),
                    CandlePattern.pattern_name.asc(),
                ),
            )
            .label("rn"),
        )
        .select_from(CandlePattern)
    )
    if conditions:
        inner = inner.where(and_(*conditions))
    subq = inner.subquery()

    stmt = (
        select(CandlePattern)
        .join(subq, CandlePattern.id == subq.c.id)
        .where(subq.c.rn == 1)
        .order_by(
            CandlePattern.exchange,
            CandlePattern.symbol,
            CandlePattern.timeframe,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
