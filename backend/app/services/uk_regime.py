"""
Regime filter UK basato su ^FTSE 1d (FTSE 100 index, Yahoo Finance).

Replica la stessa formula del regime filter USA (SPY 1d EMA50 ±2%) per garantire
confrontabilità metodologica dei risultati USA vs UK.

Formula (identica a USA):
    price_vs_ema50_pct = (close − EMA50) / EMA50 × 100
    > +2%  → bullish  (solo segnali long)
    < −2%  → bearish  (solo segnali short / pattern contro-trend bullish)
    ±2%    → neutral  (entrambe le direzioni)

Provider: Yahoo Finance (stesso di SPY per USA).
ISF/ISF.GB via IBKR non risolve come contratto Stock — ^FTSE Yahoo Finance
è il proxy affidabile per il regime: non viene mai tradato.

Funzioni pubbliche:
    get_uk_regime(session, timestamp)    → str: "bullish" | "bearish" | "neutral"
    get_uk_regime_snapshot(session)      → dict con metriche per /health/uk-status
    load_uk_regime_filter(session, ...)  → RegimeFilter (per build_validation_dataset)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_indicator import CandleIndicator
from app.services.regime_filter_service import (
    REGIME_EXCHANGE_UK,
    REGIME_PROVIDER_UK,
    REGIME_SYMBOL_UK,
    REGIME_TIMEFRAME_DAILY,
    RegimeFilter,
    load_regime_filter,
)


async def get_uk_regime(
    session: AsyncSession,
    timestamp: datetime | None = None,
    *,
    variant: str = "ema50",
) -> str:
    """
    Ritorna il regime UK alla data specificata.

    Se timestamp è None usa "adesso" (UTC).
    Se ^FTSE non ha dati in DB ritorna "neutral" (fail-open, non blocca segnali).
    """
    ts = timestamp or datetime.now(timezone.utc)
    rf = await load_regime_filter(session, provider="ibkr", variant=variant)
    if rf is None or not rf.has_data:
        return "neutral"
    return rf.get_regime_label(ts)


async def get_uk_regime_snapshot(session: AsyncSession) -> dict:
    """
    Ritorna un dict con le metriche correnti del regime UK per l'endpoint /health/uk-status.

    Struttura output:
    {
        "current": "bullish" | "bearish" | "neutral" | "no_data",
        "anchor_symbol": "^FTSE",
        "anchor_last_close": float | None,
        "anchor_ema50": float | None,
        "anchor_price_vs_ema50_pct": float | None,
        "anchor_last_date": "2026-04-17" | None,
        "formula": "close > EMA50 +2% → bullish (mirror SPY USA)"
    }
    """
    result: dict = {
        "current": "no_data",
        "anchor_symbol": REGIME_SYMBOL_UK,
        "anchor_last_close": None,
        "anchor_ema50": None,
        "anchor_price_vs_ema50_pct": None,
        "anchor_last_date": None,
        "formula": "price_vs_ema50_pct > +2% → bullish | < -2% → bearish (mirror SPY USA)",
    }

    try:
        # Leggi le ultime N barre daily di ISF.L (cerca negli ultimi 30 giorni)
        dt_to = datetime.now(timezone.utc)
        dt_from = dt_to - timedelta(days=30)

        stmt = (
            select(CandleIndicator)
            .where(
                and_(
                    CandleIndicator.symbol == REGIME_SYMBOL_UK,
                    CandleIndicator.timeframe == REGIME_TIMEFRAME_DAILY,
                    CandleIndicator.provider == REGIME_PROVIDER_UK,
                    CandleIndicator.exchange == REGIME_EXCHANGE_UK,
                    CandleIndicator.timestamp >= dt_from,
                    CandleIndicator.timestamp <= dt_to,
                )
            )
            .order_by(CandleIndicator.timestamp.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalars().first()

        if row is None:
            return result

        # Costruisci RegimeFilter con questa singola barra per calcolare il label
        rf = RegimeFilter([row], variant="ema50")
        ts_ref = row.timestamp
        if isinstance(ts_ref, datetime):
            ts_ref = ts_ref if ts_ref.tzinfo else ts_ref.replace(tzinfo=timezone.utc)

        result["current"] = rf.get_regime_label(ts_ref + timedelta(hours=1))
        ema50_f = float(row.ema_50) if row.ema_50 is not None else None
        pct_f = float(row.price_vs_ema50_pct) if row.price_vs_ema50_pct is not None else None
        # close ≈ ema50 × (1 + pct/100) — derivato dagli indicatori (CandleIndicator non ha 'close')
        close_derived = (
            round(ema50_f * (1 + pct_f / 100.0), 2)
            if ema50_f is not None and pct_f is not None
            else None
        )
        result["anchor_last_close"] = close_derived
        result["anchor_ema50"] = ema50_f
        result["anchor_price_vs_ema50_pct"] = pct_f
        ts_date = ts_ref.date() if isinstance(ts_ref, datetime) else None
        result["anchor_last_date"] = ts_date.isoformat() if ts_date else None

    except Exception:
        import logging  # noqa: PLC0415
        logging.getLogger(__name__).exception("get_uk_regime_snapshot failed")
        result["current"] = "error"

    return result


async def load_uk_regime_filter(
    session: AsyncSession,
    *,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
    variant: str = "ema50",
) -> RegimeFilter | None:
    """
    Carica il regime filter UK (ISF.L 1d) per un range di date.

    Wrapper di load_regime_filter(provider="ibkr") — usato in build_validation_dataset.py
    e ovunque sia necessario il gate regime UK su un range storico.
    """
    return await load_regime_filter(
        session,
        provider="ibkr",
        dt_from=dt_from,
        dt_to=dt_to,
        variant=variant,
    )
