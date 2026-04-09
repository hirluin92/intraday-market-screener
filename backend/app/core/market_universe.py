"""
Registro universo di mercato (MVP) per scheduler e screener.

Fonte dati: definizioni statiche versionate nel repo. In futuro si puÃ² sostituire con
tabella DB senza cambiare i consumatori (``iter_scheduler_jobs``, ecc.).

Estensione: aggiungere voci a ``MARKET_UNIVERSE_REGISTRY`` o filtrare con
``PIPELINE_UNIVERSE_TAGS`` in settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.timeframes import ALLOWED_TIMEFRAMES
from app.core.yahoo_finance_constants import (
    YAHOO_FINANCE_PROVIDER_ID,
    YAHOO_VENUE_LABEL,
)

ProviderId = Literal["binance", "yahoo_finance", "alpaca"]
AssetKind = Literal["crypto", "stock", "etf", "index"]


def _exchange_for_provider(provider: ProviderId) -> str:
    return YAHOO_VENUE_LABEL if provider == YAHOO_FINANCE_PROVIDER_ID else "binance"


@dataclass(frozen=True, slots=True)
class MarketUniverseEntry:
    """Uno strumento configurato con i timeframe che lo scheduler puÃ² aggiornare."""

    symbol: str
    provider: ProviderId
    asset_type: AssetKind
    enabled: bool
    supported_timeframes: tuple[str, ...]
    priority: int = 0
    tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SchedulerPipelineJob:
    """Una coppia (simbolo, timeframe) giÃ  risolta per un ciclo scheduler."""

    symbol: str
    timeframe: str
    provider: ProviderId
    exchange: str
    asset_type: AssetKind
    priority: int
    tags: frozenset[str]


# --- Registro default: crypto Binance + MVP Yahoo (ETF e stock US) ---
MARKET_UNIVERSE_REGISTRY: tuple[MarketUniverseEntry, ...] = (
    MarketUniverseEntry(
        symbol="BTC/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=10,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="ETH/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=10,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="BNB/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=15,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="SOL/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=15,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="XRP/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=15,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="DOGE/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=15,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="ADA/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=15,
        tags=frozenset({"crypto", "binance", "majors"}),
    ),
    MarketUniverseEntry(
        symbol="MATIC/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=25,
        tags=frozenset({"crypto", "binance", "alt"}),
    ),
    MarketUniverseEntry(
        symbol="WLD/USDT",
        provider="binance",
        asset_type="crypto",
        enabled=True,
        supported_timeframes=ALLOWED_TIMEFRAMES,
        priority=25,
        tags=frozenset({"crypto", "binance", "alt"}),
    ),
    MarketUniverseEntry(
        symbol="SPY",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="QQQ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="IWM",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="AAPL",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NVDA",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MSFT",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="AMZN",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="AMD",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="GOOGL",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="GS",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="JPM",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="META",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NFLX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="TSLA",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MSTR",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="COIN",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="HOOD",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="PLTR",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="RBLX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SHOP",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SQ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="UBER",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SNAP",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="RIVN",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="ARM",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SMCI",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="DELL",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="HPE",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="CRWD",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="ZS",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="PANW",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NET",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="DDOG",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SNOW",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MDB",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="CELH",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="IONQ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="RXRX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="WOLF",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="JOBY",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="ACHR",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="LUNR",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="RKLB",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="ASTS",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="OKLO",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NNE",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SMR",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="VKTX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="APLD",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="CORZ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="WULF",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="BAC",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="C",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MS",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="WFC",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SCHW",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SOFI",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="LLY",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NVO",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MRNA",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="BNTX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="ABBV",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="PFE",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="WMT",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="TGT",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="COST",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NKE",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="XOM",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="CVX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="OXY",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="SLB",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="GOLD",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="NEM",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="FCX",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="MP",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="stock",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=30,
        tags=frozenset({"yahoo", "stock", "us", "yahoo_stock"}),
    ),
    MarketUniverseEntry(
        symbol="TQQQ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="SQQQ",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="ARKK",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
    MarketUniverseEntry(
        symbol="ARKG",
        provider=YAHOO_FINANCE_PROVIDER_ID,
        asset_type="etf",
        enabled=True,
        supported_timeframes=("5m", "15m", "1h", "1d"),
        priority=20,
        tags=frozenset({"yahoo", "etf", "us", "yahoo_etf"}),
    ),
)


def validate_registry_timeframes() -> list[str]:
    """Ritorna messaggi di errore se un timeframe non Ã¨ ammesso per il provider."""
    from app.core.timeframes import ALLOWED_TIMEFRAMES_SET
    from app.core.yahoo_finance_constants import YAHOO_ALLOWED_TIMEFRAMES_SET

    errs: list[str] = []
    for e in MARKET_UNIVERSE_REGISTRY:
        allowed = (
            ALLOWED_TIMEFRAMES_SET
            if e.provider == "binance"
            else YAHOO_ALLOWED_TIMEFRAMES_SET
        )
        for tf in e.supported_timeframes:
            if tf not in allowed:
                errs.append(
                    f"{e.symbol} ({e.provider}): unsupported timeframe {tf!r} "
                    f"(allowed: {sorted(allowed)})",
                )
    return errs


def iter_scheduler_jobs(
    *,
    tag_filter: frozenset[str] | None = None,
) -> list[SchedulerPipelineJob]:
    """
    Espande il registro in job (symbol Ã— timeframe). Ordinati per priority, simbolo, TF.

    ``tag_filter``: se non vuoto, **ogni** tag richiesto deve essere presente sulla voce
    (subset: ``tag_filter <= entry.tags``). Esempi:

    - ``etf`` â†’ solo strumenti con tag ``etf`` (ETF Yahoo, non gli stock).
    - ``yahoo,etf`` â†’ stesso effetto preciso per gli ETF US (entrambi richiesti).
    - ``yahoo_etf`` â†’ alias esplicito per una sola run solo ETF Yahoo.
    - ``yahoo`` da solo â†’ tutto ciÃ² che ha tag ``yahoo`` (ETF + stock).
    """
    out: list[SchedulerPipelineJob] = []
    for entry in MARKET_UNIVERSE_REGISTRY:
        if not entry.enabled:
            continue
        if tag_filter:
            if not tag_filter <= entry.tags:
                continue
        ex = _exchange_for_provider(entry.provider)
        for tf in entry.supported_timeframes:
            out.append(
                SchedulerPipelineJob(
                    symbol=entry.symbol,
                    timeframe=tf,
                    provider=entry.provider,
                    exchange=ex,
                    asset_type=entry.asset_type,
                    priority=entry.priority,
                    tags=entry.tags,
                ),
            )
    out.sort(key=lambda j: (j.priority, j.symbol, j.timeframe))
    return out

