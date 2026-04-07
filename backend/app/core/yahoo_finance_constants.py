"""
Timeframe e universo MVP per ingestione Yahoo Finance (v1).

Estendere qui nuovi simboli / intervalli quando si aggiungono mercati (es. EU) senza
toccare lo schema candele.
"""

from typing import Literal

# Intervalli supportati in questa versione (affidabilità yfinance + limiti storici).
# Mappati in ``yahoo_finance_ingestion`` verso stringhe ``interval``/``period`` yfinance.
# Intraday 5m/15m: period max 60 giorni (yfinance); 1h: 730d; 1d: 10y.
YAHOO_ALLOWED_TIMEFRAMES: tuple[str, ...] = ("1d", "1h", "15m", "5m")
YAHOO_ALLOWED_TIMEFRAMES_SET: frozenset[str] = frozenset(YAHOO_ALLOWED_TIMEFRAMES)

DEFAULT_YAHOO_TIMEFRAMES: tuple[str, ...] = ("1d", "1h")

# Universo MVP: ETF di indice e blue chip US (ticker Yahoo = simbolo US).
DEFAULT_YAHOO_SYMBOLS: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "IWM",
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
    "AMD",
    "GOOGL",
    "GS",
    "JPM",
    "META",
    "NFLX",
    "TSLA",
)
# Estensioni on-demand (POST pipeline/refresh con symbol=…): devono essere in YAHOO_SYMBOL_ASSET_TYPE.

YahooAssetKind = Literal["stock", "etf"]

# Classificazione strumento per ``asset_type`` su DB (SPY/QQQ/IWM = etf; resto stock).
YAHOO_SYMBOL_ASSET_TYPE: dict[str, YahooAssetKind] = {
    "SPY": "etf",
    "QQQ": "etf",
    "IWM": "etf",
    "AAPL": "stock",
    "NVDA": "stock",
    "MSFT": "stock",
    "AMZN": "stock",
    "AMD": "stock",
    "GOOGL": "stock",
    "GS": "stock",
    "JPM": "stock",
    "META": "stock",
    "NFLX": "stock",
    "TSLA": "stock",
    "MSTR": "stock",
    "COIN": "stock",
    "HOOD": "stock",
    "PLTR": "stock",
    "RBLX": "stock",
    "SHOP": "stock",
    "SQ": "stock",
    "UBER": "stock",
    "SNAP": "stock",
    "RIVN": "stock",
    "ARM": "stock",
    "SMCI": "stock",
    "DELL": "stock",
    "HPE": "stock",
    "CRWD": "stock",
    "ZS": "stock",
    "PANW": "stock",
    "NET": "stock",
    "DDOG": "stock",
    "SNOW": "stock",
    "MDB": "stock",
    "CELH": "stock",
    "IONQ": "stock",
    "RXRX": "stock",
    "WOLF": "stock",
    "JOBY": "stock",
    "ACHR": "stock",
    "LUNR": "stock",
    "RKLB": "stock",
    "ASTS": "stock",
    "OKLO": "stock",
    "NNE": "stock",
    "SMR": "stock",
    "VKTX": "stock",
    "APLD": "stock",
    "CORZ": "stock",
    "WULF": "stock",
    # Banche / finanza / retail / energy / materie / biotech (whitelist ingest)
    "BAC": "stock",
    "C": "stock",
    "MS": "stock",
    "WFC": "stock",
    "SCHW": "stock",
    "SOFI": "stock",
    "LLY": "stock",
    "NVO": "stock",
    "MRNA": "stock",
    "BNTX": "stock",
    "ABBV": "stock",
    "PFE": "stock",
    "WMT": "stock",
    "TGT": "stock",
    "COST": "stock",
    "NKE": "stock",
    "XOM": "stock",
    "CVX": "stock",
    "OXY": "stock",
    "SLB": "stock",
    "GOLD": "stock",
    "NEM": "stock",
    "FCX": "stock",
    "MP": "stock",
    "TQQQ": "etf",
    "SQQQ": "etf",
    "ARKK": "etf",
    "ARKG": "etf",
    # Batch 4 — Difesa, industriali, semiconduttori, biotech, finanza
    "LMT": "stock",
    "RTX": "stock",
    "NOC": "stock",
    "GD": "stock",
    "BA": "stock",
    "CAT": "stock",
    "DE": "stock",
    "HON": "stock",
    "GE": "stock",
    "MMM": "stock",
    "AVGO": "stock",
    "QCOM": "stock",
    "MU": "stock",
    "AMAT": "stock",
    "LRCX": "stock",
    "KLAC": "stock",
    "ON": "stock",
    "TXN": "stock",
    "REGN": "stock",
    "GILD": "stock",
    "BIIB": "stock",
    "VRTX": "stock",
    "BMRN": "stock",
    "BLK": "stock",
    "ICE": "stock",
    "CME": "stock",
    "SPGI": "stock",
    "V": "stock",
    "MA": "stock",
}

ALLOWED_YAHOO_SYMBOLS: frozenset[str] = frozenset(YAHOO_SYMBOL_ASSET_TYPE.keys())

# Venue unico per righe Yahoo US in colonna ``exchange`` (coerente con market_identity).
YAHOO_VENUE_LABEL: str = "YAHOO_US"

# Valore colonna ``provider`` / id connettore API (allineato a ``MarketDataIngestRequest``).
YAHOO_FINANCE_PROVIDER_ID: str = "yahoo_finance"
