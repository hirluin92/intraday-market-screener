"""
Universo simboli UK (London Stock Exchange) per lo screener.
Top 30 FTSE 100 selezionati per liquidità e capitalizzazione.

Ticker IBKR per LSE: simbolo standard (es. "AZN", "HSBA"), exchange="LSE", currency="GBP".

Particolarità prezzi UK:
  I prezzi UK sono quotati in penny (pence, GBp) — 1/100 di sterlina.
  Es. "AZN" a 12500 GBp = £125.00 GBP.
  Il tick size è espresso anch'esso in pence (vedi tick_size.py → "uk_stock").

Conflitti simbolo con universo USA (da gestire in Fase 2 con flag exchange):
  "BA"  → BAE Systems su LSE, MA Boeing su NYSE (ticker identico).
           Disambiguare sempre passando exchange="LSE" per UK, exchange="SMART" per USA.
  "RIO" → Rio Tinto ha primo listing su LSE ("RIO") e ADR su NYSE ("RIO").
           Non nell'universo USA attuale ma attenzione se espanso.

Stato: Fase 1 — solo definizione universo. Lo scheduler non ancora esteso per UK (Fase 2).
"""

from __future__ import annotations

# ── Top 30 FTSE 100 per liquidità e capitalizzazione ─────────────────────────
# Ticker IBKR LSE (senza suffisso .L usato da Yahoo Finance).
UK_SYMBOLS_FTSE100_TOP30: list[str] = [
    # Healthcare / Pharma
    "AZN",   # AstraZeneca
    "GSK",   # GSK

    # Banking / Finance
    "HSBA",  # HSBC
    "BARC",  # Barclays
    "LLOY",  # Lloyds Banking Group
    "NWG",   # NatWest Group
    "STAN",  # Standard Chartered

    # Energy / Oil
    "SHEL",  # Shell
    "BP.",   # BP  ← ticker IBKR LSE è "BP." (con punto), come BA. e RR.

    # Mining / Materials
    "RIO",   # Rio Tinto  ← anche ADR NYSE "RIO" (vedi nota conflitti sopra)
    "AAL",   # Anglo American
    "GLEN",  # Glencore
    "ANTO",  # Antofagasta

    # Consumer / Retail
    "ULVR",  # Unilever
    "DGE",   # Diageo
    "RKT",   # Reckitt Benckiser
    "TSCO",  # Tesco
    "SBRY",  # Sainsbury's
    "NXT",   # Next

    # Telecom / Media
    "VOD",   # Vodafone
    "BT.A",  # BT Group (ticker IBKR con punto — verificare mapping)
    "REL",   # RELX

    # Industrials / Defence
    "BA.",   # BAE Systems  ← ticker IBKR LSE è "BA." (con punto), NON "BA" (Boeing NYSE)
    "RR.",   # Rolls-Royce  ← ticker IBKR LSE è "RR." (con punto)
    "CRH",   # CRH

    # Real Estate
    "BLND",  # British Land
    "LAND",  # Land Securities

    # Tech / Other
    "EXPN",  # Experian
    "BATS",  # British American Tobacco  ← sostituisce AHT (migrata su NYSE)
    "PRU",   # Prudential
]

# Set per lookup O(1)
UK_SYMBOLS_SET: frozenset[str] = frozenset(UK_SYMBOLS_FTSE100_TOP30)

# Provider da usare per l'ingestion UK via IBKR TWS
UK_PROVIDER = "ibkr"
UK_EXCHANGE = "LSE"
UK_CURRENCY = "GBP"

# Override currency per simboli che richiedono una currency diversa da UK_CURRENCY="GBP".
# Tutti i 30 simboli FTSE usano GBP — lasciato vuoto per futura estensione se necessario.
UK_SYMBOL_CURRENCY_OVERRIDES: dict[str, str] = {}

# Timeframe di trading UK (1h) e timeframe per il regime anchor (1d)
UK_TIMEFRAMES: list[str] = ["1h"]          # simboli trading
UK_REGIME_TIMEFRAME: str = "1d"            # solo per ISF.L, regime detection

# ── Regime anchor UK ──────────────────────────────────────────────────────────
# iShares Core FTSE 100 UCITS ETF — quotato LSE, replica FTSE 100 con
# tracking error <0.1% annuo. Usato come proxy macro per il regime filter UK
# in sostituzione di SPY per il mercato USA.
#
# NON È UN SIMBOLO DI TRADING: non deve mai comparire in ordini, segnali o
# portafoglio. Usato SOLO per calcolare il regime giornaliero BULLISH/BEARISH
# su cui condizionare i pattern contro-trend UK (engulfing_bullish, macd/rsi_divergence_bull).
#
# Ticker Yahoo Finance: "^FTSE" — stesso provider di SPY per USA.
# ISF/ISF.GB via IBKR non risolvono come contratto Stock (richiede secType='ETF').
# ^FTSE Yahoo Finance è il proxy affidabile per il regime: non viene mai tradato.
UK_REGIME_ANCHOR: str = "^FTSE"          # regime anchor — NON per trade (Yahoo Finance)
