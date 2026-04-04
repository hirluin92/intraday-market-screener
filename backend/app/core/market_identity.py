"""
Market identity (asset-agnostic).

- ``asset_type``: classe di strumento (crypto, stock, etf, index).
- ``provider``: origine dati / connettore logico (es. ``binance`` per OHLCV ccxt crypto).
- ``exchange`` (colonne DB esistenti): venue / id exchange lato connettore (es. ``binance`` per spot
  crypto). Mantenuto per compatibilità; non assume più che sia *sempre* una crypto exchange in senso
  stretto — altri venue potranno mappare altri mercati.

``market_metadata`` (JSON opzionale): hook per sessioni di trading, timezone mercato, mic, ecc.
"""

from __future__ import annotations

from typing import Literal

# Supported asset classes (extend as new providers are added).
AssetType = Literal["crypto", "stock", "etf", "index"]

DEFAULT_ASSET_TYPE_CRYPTO: AssetType = "crypto"

# Data provider id for the current Binance + ccxt ingestion path.
DEFAULT_PROVIDER_BINANCE: str = "binance"

# Stored in ``exchange`` column for Binance spot rows (ccxt exchange id).
DEFAULT_VENUE_BINANCE: str = "binance"
