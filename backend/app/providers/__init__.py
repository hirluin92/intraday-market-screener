"""Provider di dati di mercato (estensioni future).

Implementazioni concrete (Binance ccxt, Yahoo Finance) vivono in ``app.services``;
questo package espone solo il contratto (:class:`MarketDataProvider`).
"""

from app.providers.base import MarketDataProvider

__all__ = ["MarketDataProvider"]
