"""
Estensibilità provider dati di mercato (MVP).

Il path attuale usa ``MarketDataIngestionService`` + ccxt (crypto). Un secondo provider
(es. azioni/ETF via API dedicate) può implementare un contratto simile senza cambiare il resto
dell’architettura in questa milestone.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketDataProvider(Protocol):
    """Hook futuro: ingest OHLCV o barre per ``asset_type`` / venue."""

    provider_id: str
    default_asset_type: str
