"""
Combine latest context snapshots with latest stored pattern per series (MVP, no persistence).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_pattern import CandlePattern
from app.schemas.opportunities import OpportunityRow
from app.services.context_query import list_latest_context_per_series
from app.services.pattern_query import list_latest_pattern_per_series
from app.services.screener_scoring import SnapshotForScoring, score_snapshot


def _pattern_key(p: CandlePattern) -> tuple[str, str, str]:
    return (p.exchange, p.symbol, p.timeframe)


def _sort_opportunities(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Pattern present first, then score desc, then timestamp desc."""
    return sorted(
        rows,
        key=lambda r: (
            0 if r.latest_pattern_name is not None else 1,
            -r.screener_score,
            -r.timestamp.timestamp(),
        ),
    )


async def list_opportunities(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    timeframe: str | None,
    limit: int,
) -> list[OpportunityRow]:
    contexts: list[CandleContext] = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    )
    latest_patterns: list[CandlePattern] = await list_latest_pattern_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    )
    by_series: dict[tuple[str, str, str], CandlePattern] = {
        _pattern_key(p): p for p in latest_patterns
    }

    out: list[OpportunityRow] = []
    for ctx in contexts:
        snap = SnapshotForScoring(
            exchange=ctx.exchange,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            timestamp=ctx.timestamp,
            market_regime=ctx.market_regime,
            volatility_regime=ctx.volatility_regime,
            candle_expansion=ctx.candle_expansion,
            direction_bias=ctx.direction_bias,
        )
        points, label = score_snapshot(snap)
        p = by_series.get((ctx.exchange, ctx.symbol, ctx.timeframe))
        out.append(
            OpportunityRow(
                exchange=ctx.exchange,
                symbol=ctx.symbol,
                timeframe=ctx.timeframe,
                timestamp=ctx.timestamp,
                market_regime=ctx.market_regime,
                volatility_regime=ctx.volatility_regime,
                candle_expansion=ctx.candle_expansion,
                direction_bias=ctx.direction_bias,
                screener_score=points,
                score_label=label,
                latest_pattern_name=p.pattern_name if p is not None else None,
                latest_pattern_strength=p.pattern_strength if p is not None else None,
                latest_pattern_direction=p.direction if p is not None else None,
            )
        )

    ranked = _sort_opportunities(out)
    return ranked[:limit]
