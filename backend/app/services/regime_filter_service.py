"""
Filtro di regime SPY 1d (price_vs_ema50_pct): direzioni consentite per timestamp di barra.
Usato dalla simulazione equity — nessuna query extra in runtime (cache caricata una volta).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.yahoo_finance_constants import YAHOO_VENUE_LABEL
from app.models.candle_indicator import CandleIndicator


def _d(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_allowed_directions_from_pct(
    price_vs_ema50_pct: float,
    _price_vs_ema20_pct: float | None = None,
) -> frozenset[str]:
    """
    Regime BULLISH forte (SPY > EMA50 oltre 2%) → solo bullish.
    Regime BEARISH forte (SPY < EMA50 oltre 2%) → solo bearish.
    Zona neutra ±2% → entrambe.
    """
    if price_vs_ema50_pct > 2.0:
        return frozenset({"bullish"})
    if price_vs_ema50_pct < -2.0:
        return frozenset({"bearish"})
    return frozenset({"bullish", "bearish"})


class RegimeFilter:
    """Cache date UTC → riga SPY 1d."""

    def __init__(self, daily_indicators: list[CandleIndicator]) -> None:
        self._by_date: dict[str, CandleIndicator] = {}
        for ind in daily_indicators:
            ts = ind.timestamp
            if isinstance(ts, datetime):
                d = ts.date() if ts.tzinfo else ts.replace(tzinfo=timezone.utc).date()
            else:
                d = ts.date()
            key = d.isoformat()
            prev = self._by_date.get(key)
            if prev is None or ind.timestamp > prev.timestamp:
                self._by_date[key] = ind

    @property
    def has_data(self) -> bool:
        return bool(self._by_date)

    def get_allowed_directions(self, timestamp: datetime) -> frozenset[str]:
        ind = self._indicator_for_trade_ts(timestamp)
        if ind is None:
            return frozenset({"bullish", "bearish"})
        pct = _d(ind.price_vs_ema50_pct)
        if pct is None:
            return frozenset({"bullish", "bearish"})
        return get_allowed_directions_from_pct(pct)

    def get_regime_label(self, timestamp: datetime) -> str:
        dirs = self.get_allowed_directions(timestamp)
        if dirs == frozenset({"bullish"}):
            return "bullish"
        if dirs == frozenset({"bearish"}):
            return "bearish"
        return "neutral"

    def _indicator_for_trade_ts(self, timestamp: datetime) -> CandleIndicator | None:
        if not self._by_date:
            return None
        ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        d: date = ts.date()
        for days_back in range(0, 7):
            check = (d - timedelta(days=days_back)).isoformat()
            if check in self._by_date:
                return self._by_date[check]
        return None


async def load_regime_filter(
    session: AsyncSession,
    *,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
) -> RegimeFilter | None:
    """Carica SPY 1d Yahoo. None se nessuna riga (fallback: tutte le direzioni)."""
    conditions = [
        CandleIndicator.symbol == "SPY",
        CandleIndicator.timeframe == "1d",
        CandleIndicator.provider == "yahoo_finance",
        CandleIndicator.exchange == YAHOO_VENUE_LABEL,
    ]
    if dt_from is not None:
        conditions.append(CandleIndicator.timestamp >= dt_from - timedelta(days=14))
    if dt_to is not None:
        conditions.append(CandleIndicator.timestamp <= dt_to + timedelta(days=2))

    stmt = (
        select(CandleIndicator)
        .where(and_(*conditions))
        .order_by(CandleIndicator.timestamp.asc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return None
    return RegimeFilter(rows)
