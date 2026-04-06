"""
Scarica e interpola i funding rate Binance Futures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
_SYMBOL_MAP = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
}

# Soglie per funding bias
_FUNDING_BEARISH_THRESHOLD = 0.0001  # 0.01% per periodo = ~109% annuo
_FUNDING_BULLISH_THRESHOLD = -0.00005  # -0.005% per periodo


def funding_bias_from_rate(rate: float) -> str:
    if rate > _FUNDING_BEARISH_THRESHOLD:
        return "bearish"
    if rate < _FUNDING_BULLISH_THRESHOLD:
        return "bullish"
    return "neutral"


async def fetch_funding_rates(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
) -> list[tuple[datetime, float]]:
    """
    Scarica i funding rate Binance Futures per un simbolo e intervallo temporale.
    Ritorna lista di (timestamp_utc, funding_rate).
    """
    binance_symbol = _SYMBOL_MAP.get(symbol)
    if binance_symbol is None:
        return []

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    results: list[tuple[datetime, float]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _BINANCE_FUTURES_URL,
                params={
                    "symbol": binance_symbol,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data:
                ts = datetime.fromtimestamp(
                    item["fundingTime"] / 1000,
                    tz=timezone.utc,
                )
                rate = float(item["fundingRate"])
                results.append((ts, rate))
    except Exception as exc:
        logger.warning("Funding rate fetch failed for %s: %s", symbol, exc)

    return results


def assign_funding_to_candles(
    candle_timestamps: list[datetime],
    funding_data: list[tuple[datetime, float]],
) -> list[float | None]:
    """
    Per ogni candela, assegna il funding rate più recente con fundingTime <= timestamp candela.
    Last-value-carried-forward tra un pagamento e l'altro (ogni 8h).
    """
    if not funding_data:
        return [None] * len(candle_timestamps)

    sorted_funding = sorted(funding_data, key=lambda x: x[0])
    result: list[float | None] = []
    j = -1
    for ts in candle_timestamps:
        while j + 1 < len(sorted_funding) and sorted_funding[j + 1][0] <= ts:
            j += 1
        if j < 0:
            result.append(None)
        else:
            result.append(sorted_funding[j][1])
    return result
