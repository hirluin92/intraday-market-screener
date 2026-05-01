"""
Mappa tick size per simbolo/asset class e helper di arrotondamento.

Fonte specifiche di mercato:
- Azioni / ETF USA (NYSE, NASDAQ): tick $0.01 per prezzi >= $1,
  $0.0001 per prezzi < $1 (regola SEC per penny stock).
- Crypto spot Binance: tick variabile per simbolo.
  Fonte: https://www.binance.com/en/trade-rule (PRICE_FILTER → tickSize).
- Azioni UK (London Stock Exchange): tick variabile per fascia di prezzo.
  Fonte: LSE Tick Size Regime (valori in pence, GBp).
  ATTENZIONE: i prezzi UK sono espressi in pence (1/100 di sterlina).
  Es. AZN a 12500 GBp = £125.00 GBP.

Aggiungere nuovi simboli crypto nella costante CRYPTO_TICK_SIZES quando
si espande l'universo; per simboli non in mappa viene usato il fallback
conservativo 0.0001 con warning in log.
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Literal

logger = logging.getLogger(__name__)

# ── Azioni / ETF USA ──────────────────────────────────────────────────────────
US_STOCK_TICK_HIGH = Decimal("0.01")       # prezzi >= $1
US_STOCK_TICK_LOW = Decimal("0.0001")      # prezzi < $1 (penny stock)
US_STOCK_PRICE_THRESHOLD = Decimal("1.00")

# ── Crypto spot Binance ───────────────────────────────────────────────────────
# Aggiornare manualmente se Binance cambia i tick size di un simbolo.
CRYPTO_TICK_SIZES: dict[str, Decimal] = {
    "BTC/USDT":  Decimal("0.01"),
    "ETH/USDT":  Decimal("0.01"),
    "BNB/USDT":  Decimal("0.01"),
    "SOL/USDT":  Decimal("0.01"),
    "XRP/USDT":  Decimal("0.0001"),
    "ADA/USDT":  Decimal("0.0001"),
    "AVAX/USDT": Decimal("0.01"),
    "DOT/USDT":  Decimal("0.001"),
    "LINK/USDT": Decimal("0.001"),
    "LTC/USDT":  Decimal("0.01"),
    "WLD/USDT":  Decimal("0.0001"),
    "MATIC/USDT": Decimal("0.0001"),
    "DOGE/USDT": Decimal("0.00001"),
    "SHIB/USDT": Decimal("0.0000001"),
    # aggiungi qui quando espandi universo crypto
}

# Fallback conservativo per crypto non in mappa
_CRYPTO_TICK_FALLBACK = Decimal("0.0001")

# ── Azioni UK (London Stock Exchange) ────────────────────────────────────────
# Tick size LSE per fascia di prezzo in pence (GBp).
# Fonte: LSE Tick Size Regime (livelli semplificati per FTSE 100/250).
# ATTENZIONE: i prezzi IBKR per LSE sono in pence, non in sterline.
# Es. AZN ≈ 12500 GBp → fascia >= 5000p → tick 1.0p.
UK_STOCK_TICK_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    # (soglia_min_pence_inclusa, tick_size_pence)
    (Decimal("5000"),  Decimal("1.0")),    # >= 5000p  (>= £50)
    (Decimal("1000"),  Decimal("0.5")),    # 1000-4999p
    (Decimal("500"),   Decimal("0.1")),    # 500-999p
    (Decimal("100"),   Decimal("0.05")),   # 100-499p
    (Decimal("0"),     Decimal("0.01")),   # < 100p (penny stocks UK)
)

# ── Asset class non gestite in questa versione ────────────────────────────────
# Futures, FX, obbligazioni: non supportati; usano fallback generico 0.01.


def get_uk_stock_tick_size(price_pence: Decimal) -> Decimal:
    """
    Restituisce il tick size LSE (in pence) per il prezzo dato (espresso in pence).

    Fascia LSE Tick Size Regime (FTSE 100/250):
      >= 5000p  → 1.0p
      1000-4999p → 0.5p
      500-999p   → 0.1p
      100-499p   → 0.05p
      < 100p     → 0.01p

    Args:
        price_pence: prezzo in GBp (pence). Es. AZN 12500 = £125.00.

    Returns:
        Decimal tick size in pence (sempre > 0).
    """
    for threshold, tick in UK_STOCK_TICK_BANDS:
        if price_pence >= threshold:
            return tick
    return Decimal("0.01")  # fallback conservativo


def get_tick_size(symbol: str, price: Decimal, asset_class: str) -> Decimal:
    """
    Restituisce il tick size appropriato per il simbolo dato il prezzo corrente.

    Args:
        symbol:      es. "AAPL", "BTC/USDT", "AZN"
        price:       prezzo di riferimento (in USD per US stocks/crypto, in GBp per UK stocks)
        asset_class: "us_stock" | "crypto" | "etf" | "uk_stock"

    Returns:
        Decimal tick size (sempre > 0).
    """
    if asset_class in ("us_stock", "etf"):
        return US_STOCK_TICK_HIGH if price >= US_STOCK_PRICE_THRESHOLD else US_STOCK_TICK_LOW

    if asset_class == "uk_stock":
        return get_uk_stock_tick_size(price)

    if asset_class == "crypto":
        tick = CRYPTO_TICK_SIZES.get(symbol.upper() if symbol else "")
        if tick is None:
            logger.warning(
                "tick_size: simbolo crypto '%s' non in CRYPTO_TICK_SIZES — "
                "uso fallback %s. Aggiungere alla mappa per precisione.",
                symbol, _CRYPTO_TICK_FALLBACK,
            )
            return _CRYPTO_TICK_FALLBACK
        return tick

    # Fallback generico (futures, FX, asset class sconosciuta)
    return Decimal("0.01")


def round_to_tick(
    price: Decimal,
    tick_size: Decimal,
    direction: Literal["up", "down", "nearest"],
) -> Decimal:
    """
    Arrotonda il prezzo al multiplo di tick_size più vicino nella direzione data.

    Args:
        price:     prezzo da arrotondare
        tick_size: granularità (es. Decimal("0.01"))
        direction:
            "down"    — arrotonda per difetto (ROUND_DOWN)
                        es. stop long: 182.347 → 182.34
            "up"      — arrotonda per eccesso (ROUND_UP)
                        es. TP long: 185.673 → 185.68
            "nearest" — arrotonda al più vicino (ROUND_HALF_UP)
                        es. entry: 182.505 → 182.51

    Returns:
        Decimal arrotondato al tick size.
    """
    if tick_size <= 0:
        return price
    multiplier = price / tick_size
    if direction == "down":
        rounded = multiplier.quantize(Decimal("1"), rounding=ROUND_DOWN)
    elif direction == "up":
        rounded = multiplier.quantize(Decimal("1"), rounding=ROUND_UP)
    else:  # nearest
        rounded = multiplier.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return rounded * tick_size


def resolve_asset_class(*, symbol: str, exchange: str) -> str:
    """
    Determina l'asset class da symbol ed exchange per selezionare il tick size corretto.

    Regole:
    - exchange "BINANCE" o symbol con "/" (es. "BTC/USDT") → "crypto"
    - exchange "LSE" (London Stock Exchange) → "uk_stock"
    - exchange US noti (NASDAQ, NYSE, AMEX, SMART) o provider yahoo_finance → "us_stock"
    - Sconosciuto → warning + fallback "us_stock"

    Returns:
        "us_stock" | "crypto" | "etf" | "uk_stock"
    """
    ex = (exchange or "").upper().strip()
    sym = (symbol or "").upper().strip()

    if ex == "BINANCE" or "/" in sym:
        return "crypto"

    if ex == "LSE":
        return "uk_stock"

    if ex in ("NASDAQ", "NYSE", "AMEX", "SMART", "YAHOO_FINANCE", "YAHOO_US", "YAHOO", "ALPACA_US", "ALPACA", ""):
        return "us_stock"

    logger.warning(
        "tick_size.resolve_asset_class: exchange '%s' non riconosciuto per symbol '%s' "
        "— uso fallback 'us_stock'. Aggiungere alla mappa se necessario.",
        exchange, symbol,
    )
    return "us_stock"
