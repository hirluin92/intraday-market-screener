"""
Timeframe e universo MVP per ingestione Yahoo Finance (v1).

Estendere qui nuovi simboli / intervalli quando si aggiungono mercati (es. EU) senza
toccare lo schema candele.
"""

from typing import Literal

# Intervalli supportati in questa versione (affidabilità yfinance + limiti storici).
# Mappati in ``yahoo_finance_ingestion`` verso stringhe ``interval``/``period`` yfinance.
YAHOO_ALLOWED_TIMEFRAMES: tuple[str, ...] = ("1d", "1h", "5m")
YAHOO_ALLOWED_TIMEFRAMES_SET: frozenset[str] = frozenset(YAHOO_ALLOWED_TIMEFRAMES)

DEFAULT_YAHOO_TIMEFRAMES: tuple[str, ...] = ("1d", "1h")

# Universo MVP: ETF di indice e blue chip US (ticker Yahoo = simbolo US).
DEFAULT_YAHOO_SYMBOLS: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
)

YahooAssetKind = Literal["stock", "etf"]

# Classificazione strumento per ``asset_type`` su DB (SPY/QQQ/IWM/DIA = etf; resto stock).
YAHOO_SYMBOL_ASSET_TYPE: dict[str, YahooAssetKind] = {
    "SPY": "etf",
    "QQQ": "etf",
    "IWM": "etf",
    "DIA": "etf",
    "AAPL": "stock",
    "NVDA": "stock",
    "MSFT": "stock",
    "AMZN": "stock",
}

ALLOWED_YAHOO_SYMBOLS: frozenset[str] = frozenset(YAHOO_SYMBOL_ASSET_TYPE.keys())

# Venue unico per righe Yahoo US in colonna ``exchange`` (coerente con market_identity).
YAHOO_VENUE_LABEL: str = "YAHOO_US"

# Valore colonna ``provider`` / id connettore API (allineato a ``MarketDataIngestRequest``).
YAHOO_FINANCE_PROVIDER_ID: str = "yahoo_finance"
