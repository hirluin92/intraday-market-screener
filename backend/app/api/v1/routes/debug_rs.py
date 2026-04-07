"""
Endpoint di debug RS vs SPY — rimuovere quando non più necessario.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.candle_feature import CandleFeature
from app.services.indicator_extraction import _load_spy_returns, _normalize_ts

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/rs/{symbol}")
async def debug_rs(
    symbol: str,
    timeframe: str = Query(default="1h", description="Timeframe serie simbolo"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Verifica caricamento rendimenti SPY allineati ai timestamp del simbolo."""
    stmt = (
        select(CandleFeature.timestamp)
        .where(
            CandleFeature.symbol == symbol,
            CandleFeature.provider == "yahoo_finance",
            CandleFeature.timeframe == timeframe,
        )
        .order_by(CandleFeature.timestamp.desc())
        .limit(10)
    )
    result = await session.execute(stmt)
    timestamps = [row[0] for row in result.fetchall()]

    spy_returns = await _load_spy_returns(
        session,
        provider="yahoo_finance",
        timeframe=timeframe,
        timestamps=timestamps,
    )

    sample = []
    for ts in timestamps[:5]:
        kn = _normalize_ts(ts)
        sample.append(
            {
                "ts": ts.isoformat(),
                "ts_norm": kn.isoformat(),
                "spy_ret": spy_returns.get(kn),
            }
        )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamps_checked": len(timestamps),
        "spy_returns_found": len(spy_returns),
        "sample": sample,
    }
