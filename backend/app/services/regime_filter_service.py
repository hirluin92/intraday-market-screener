"""
Filtro di regime giornaliero: direzioni consentite per timestamp di barra.

- Yahoo / azioni-ETF: SPY 1d.
- Binance / crypto: BTC/USDT 1d (stesso schema di varianti su indicatori daily).

Varianti (``regime_variant``): ema50 (default), ema9_20, momentum5d, ema50_rsi.

Usato dalla simulazione equity e dalle opportunità — cache caricata una volta per richiesta.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.market_identity import DEFAULT_PROVIDER_BINANCE, DEFAULT_VENUE_BINANCE
from app.core.yahoo_finance_constants import YAHOO_VENUE_LABEL
from app.models.candle_indicator import CandleIndicator

REGIME_SYMBOL_BINANCE = "BTC/USDT"
REGIME_TIMEFRAME_DAILY = "1d"

REGIME_VARIANTS: frozenset[str] = frozenset(
    {"ema50", "ema9_20", "momentum5d", "ema50_rsi"},
)


def normalize_regime_variant(value: str | None) -> str:
    """Default ``ema50``; valori sconosciuti → ``ema50``."""
    s = (value or "ema50").strip().lower()
    return s if s in REGIME_VARIANTS else "ema50"


def _d(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _indicator_date_key(ind: CandleIndicator) -> date:
    ts = ind.timestamp
    if isinstance(ts, datetime):
        return ts.date() if ts.tzinfo else ts.replace(tzinfo=timezone.utc).date()
    return ts.date()


def get_allowed_directions_from_pct(
    price_vs_ema50_pct: float,
    _price_vs_ema20_pct: float | None = None,
) -> frozenset[str]:
    """
    Regime BULLISH forte (prezzo > EMA50 oltre 2%) → solo bullish.
    Regime BEARISH forte (prezzo < EMA50 oltre 2%) → solo bearish.
    Zona neutra ±2% → entrambe.
    """
    if price_vs_ema50_pct > 2.0:
        return frozenset({"bullish"})
    if price_vs_ema50_pct < -2.0:
        return frozenset({"bearish"})
    return frozenset({"bullish", "bearish"})


class RegimeFilter:
    """Cache date UTC → riga indicator daily (SPY o BTC)."""

    def __init__(
        self,
        daily_indicators: list[CandleIndicator],
        *,
        variant: str = "ema50",
    ) -> None:
        self._variant = normalize_regime_variant(variant)
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
    def variant(self) -> str:
        return self._variant

    @property
    def has_data(self) -> bool:
        return bool(self._by_date)

    def get_allowed_directions(self, timestamp: datetime) -> frozenset[str]:
        ind = self._indicator_for_trade_ts(timestamp)
        if ind is None:
            return frozenset({"bullish", "bearish"})
        v = self._variant
        if v == "ema9_20":
            return self._regime_ema9_20(ind)
        if v == "momentum5d":
            return self._regime_momentum5d(timestamp)
        if v == "ema50_rsi":
            return self._regime_ema50_rsi(ind)
        return self._regime_ema50(ind)

    def get_regime_label(self, timestamp: datetime) -> str:
        dirs = self.get_allowed_directions(timestamp)
        if dirs == frozenset({"bullish"}):
            return "bullish"
        if dirs == frozenset({"bearish"}):
            return "bearish"
        return "neutral"

    def _regime_ema50(self, ind: CandleIndicator) -> frozenset[str]:
        """Filtro legacy: price vs EMA50 ±2% (zona neutra = entrambe le direzioni)."""
        pct = _d(ind.price_vs_ema50_pct)
        if pct is None:
            return frozenset({"bullish", "bearish"})
        return get_allowed_directions_from_pct(pct)

    def _regime_ema9_20(self, ind: CandleIndicator) -> frozenset[str]:
        ema9 = _d(ind.ema_9)
        ema20 = _d(ind.ema_20)
        if ema9 is None or ema20 is None or ema9 <= 0 or ema20 <= 0:
            return frozenset({"bullish", "bearish"})
        if ema9 > ema20:
            return frozenset({"bullish"})
        return frozenset({"bearish"})

    def _regime_momentum5d(self, timestamp: datetime) -> frozenset[str]:
        """Momentum da variazione EMA9 vs prima riga disponibile 5–14 giorni prima (calendario)."""
        ind_now = self._indicator_for_trade_ts(timestamp)
        if ind_now is None:
            return frozenset({"bullish", "bearish"})
        e9_now = _d(ind_now.ema_9)
        if e9_now is None or e9_now <= 0:
            return frozenset({"bullish", "bearish"})
        d_now = _indicator_date_key(ind_now)
        ind_5d: CandleIndicator | None = None
        for days_back in range(5, 15):
            check = (d_now - timedelta(days=days_back)).isoformat()
            if check in self._by_date:
                ind_5d = self._by_date[check]
                break
        if ind_5d is None:
            return frozenset({"bullish", "bearish"})
        e9_past = _d(ind_5d.ema_9)
        if e9_past is None or e9_past <= 0:
            return frozenset({"bullish", "bearish"})
        momentum_pct = (e9_now - e9_past) / e9_past * 100.0
        if momentum_pct > 1.0:
            return frozenset({"bullish"})
        if momentum_pct < -1.0:
            return frozenset({"bearish"})
        # Zona neutrale (±1%): permetti entrambe le direzioni come le altre varianti.
        return frozenset({"bullish", "bearish"})

    def _regime_ema50_rsi(self, ind: CandleIndicator) -> frozenset[str]:
        """EMA50 ±2% come base; restringe con RSI14.

        Se EMA50 segnala una sola direzione ma l'RSI la contraddice (es. prezzo > EMA50 ma
        RSI < 40), il segnale è ambiguo: si ricade su entrambe le direzioni consentite
        invece di restituire un insieme vuoto che blocca tutti i segnali.
        """
        pct = _d(ind.price_vs_ema50_pct)
        if pct is None:
            return frozenset({"bullish", "bearish"})
        base = get_allowed_directions_from_pct(pct)
        rsi = _d(ind.rsi_14)
        if rsi is None:
            return base
        out = set(base)
        if rsi < 40.0 and "bullish" in out:
            out.discard("bullish")
        if rsi > 60.0 and "bearish" in out:
            out.discard("bearish")
        # Se RSI ha eliminato tutte le direzioni consentite dalla base EMA50
        # (es. bull market ma RSI < 40 = divergenza bearish) → segnale ambiguo,
        # consenti entrambe invece di bloccare tutto.
        if not out:
            return frozenset({"bullish", "bearish"})
        return frozenset(out)

    def _indicator_for_trade_ts(self, timestamp: datetime) -> CandleIndicator | None:
        if not self._by_date:
            return None
        ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        d: date = ts.date()
        for days_back in range(1, 8):
            check = (d - timedelta(days=days_back)).isoformat()
            if check in self._by_date:
                return self._by_date[check]
        return None


async def load_regime_filter(
    session: AsyncSession,
    *,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
    provider: str = "yahoo_finance",
    variant: str = "ema50",
) -> RegimeFilter | None:
    """
    Carica indicatori daily per il filtro regime.

    - ``yahoo_finance`` (default): SPY 1d Yahoo.
    - ``binance``: BTC/USDT 1d Binance (regime macro per le altcoin).

    Se non ci sono righe, ritorna None (fallback: tutte le direzioni consentite).
    """
    p = (provider or "yahoo_finance").strip().lower()
    v = normalize_regime_variant(variant)
    if p == "binance":
        conditions = [
            CandleIndicator.symbol == REGIME_SYMBOL_BINANCE,
            CandleIndicator.timeframe == REGIME_TIMEFRAME_DAILY,
            CandleIndicator.provider == DEFAULT_PROVIDER_BINANCE,
            CandleIndicator.exchange == DEFAULT_VENUE_BINANCE,
        ]
    else:
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
    return RegimeFilter(rows, variant=v)
