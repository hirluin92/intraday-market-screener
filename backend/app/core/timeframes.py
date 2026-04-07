"""Shared intraday timeframe literals for API validation and ingestion (MVP)."""

from typing import Literal

from app.core.yahoo_finance_constants import YAHOO_ALLOWED_TIMEFRAMES_SET

# Keep in sync with ingestion defaults / CCXT usage (Binance crypto).
# 1d: macro regime (BTC/USDT) e storico daily dove serve.
ALLOWED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")
ALLOWED_TIMEFRAMES_SET: frozenset[str] = frozenset(ALLOWED_TIMEFRAMES)

# Unione letture/filtri API multi-mercato (Binance + Yahoo); la pipeline schedulata resta solo Binance.
ALL_MARKETS_TIMEFRAMES_SET: frozenset[str] = ALLOWED_TIMEFRAMES_SET | YAHOO_ALLOWED_TIMEFRAMES_SET

TimeframeLiteral = Literal["1m", "5m", "15m", "1h", "1d"]
