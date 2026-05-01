"""
Symbol universe sets — validated, blocked, and data-collection symbol lists.
"""

from app.core.uk_universe import UK_SYMBOLS_FTSE100_TOP30 as _UK_30  # noqa: E402

# ── UK / LSE ─────────────────────────────────────────────────────────────────
VALIDATED_SYMBOLS_UK: frozenset[str] = frozenset()

_UK_SYMBOLS_BLOCKED_A8: frozenset[str] = frozenset({"LLOY", "TSCO", "VOD", "LAND", "ULVR"})
DATA_COLLECTION_SYMBOLS_UK: frozenset[str] = frozenset(_UK_30) - _UK_SYMBOLS_BLOCKED_A8

# ── Yahoo Finance 1h ─────────────────────────────────────────────────────────
SYMBOLS_BLOCKED_YAHOO_1H: frozenset[str] = frozenset({
    "REGN", "BMRN",
    "SPY",
    "DIA",
})

SYMBOLS_DATA_COLLECTION_YAHOO_1H: frozenset[str] = frozenset({
    "MARA",
    "CLSK",
    "RIOT",
    "UPST",
    "AFRM",
    "HIMS",
    "AVGO",
})

VALIDATED_SYMBOLS_YAHOO: frozenset[str] = frozenset(
    {
        "GOOGL", "TSLA", "AMD", "META", "NVDA", "NFLX",
        "COIN", "MSTR", "HOOD", "SOFI", "SCHW",
        "RBLX", "SHOP", "ZS", "NET", "MDB", "CELH", "PLTR", "HPE", "SMCI", "DELL",
        "ACHR", "ASTS", "JOBY", "RKLB", "NNE", "OKLO", "WULF", "APLD", "SMR", "RXRX",
        "NVO", "LLY", "MRNA",
        "NKE", "TGT",
        "MP", "NEM",
        "WMT",
        "MU", "LUNR", "CAT", "GS",
        "HON", "ICE", "CVX", "VRTX",
    }
)

SCHEDULER_SYMBOLS_YAHOO_1H: list[tuple[str, str]] = [
    ("GOOGL", "1h"), ("TSLA", "1h"), ("AMD", "1h"), ("META", "1h"), ("NVDA", "1h"), ("NFLX", "1h"),
    ("COIN", "1h"), ("MSTR", "1h"), ("HOOD", "1h"), ("SHOP", "1h"), ("SOFI", "1h"),
    ("ZS", "1h"), ("NET", "1h"), ("CELH", "1h"), ("RBLX", "1h"), ("PLTR", "1h"),
    ("HPE", "1h"), ("MDB", "1h"), ("SMCI", "1h"), ("DELL", "1h"),
    ("ACHR", "1h"), ("ASTS", "1h"), ("JOBY", "1h"), ("RKLB", "1h"), ("NNE", "1h"),
    ("OKLO", "1h"), ("WULF", "1h"), ("APLD", "1h"), ("SMR", "1h"), ("RXRX", "1h"),
    ("NVO", "1h"), ("LLY", "1h"), ("MP", "1h"), ("MRNA", "1h"), ("NKE", "1h"),
    ("TGT", "1h"), ("NEM", "1h"), ("SCHW", "1h"), ("WMT", "1h"),
    ("MU", "1h"), ("LUNR", "1h"), ("CAT", "1h"), ("GS", "1h"),
    ("AVGO", "1h"),
    ("HON", "1h"), ("ICE", "1h"), ("CVX", "1h"), ("VRTX", "1h"),
    ("SPY", "1h"),
    ("MARA", "1h"), ("CLSK", "1h"), ("RIOT", "1h"), ("UPST", "1h"), ("AFRM", "1h"), ("HIMS", "1h"),
]

# ── Alpaca 5m ────────────────────────────────────────────────────────────────
# SPY/AAPL/MSFT/GOOGL/WMT/DELL: ATR% troppo basso, edge non sopravvive slippage live.
# META/TGT/SCHW: rimossi apr 2026 da audit universe (pool TRIPLO Config D):
#   - SCHW: avg_r D=-0.65R, WR 6.7% (n=15) — peggior simbolo dell'universo.
#   - META: rotto in OOS 2026 (n=0 trade), 2024 negativo (-0.26R), edge non stabile.
#   - TGT:  avg_r D=+0.28R, WR 40% (n=15) — marginale, sotto soglia break-even.
# Drop dei 3: pool 1,560→1,501 (-3.8% volume) | edge +1.06→+1.10R | MC mediana +5.2%.
SYMBOLS_BLOCKED_ALPACA_5M: frozenset[str] = frozenset({
    "SPY", "AAPL", "MSFT", "GOOGL", "WMT", "DELL",
    "META", "TGT", "SCHW",
    # Candidati in fase di onboarding (apr 2026): bloccati finché OOS non confermi edge.
    # Profilo verificato: ATR% 1d 3.9-6.7%, volume IEX 0.8-1.5M/d, prezzo $6-23.
    # Match settori top performer (EV, AI mid-cap, iGaming).
    "NIO", "SOUN",
})

SCHEDULER_SYMBOLS_ALPACA_5M: list[tuple[str, str]] = [
    ("META", "5m"), ("NVDA", "5m"), ("TSLA", "5m"), ("AMD", "5m"), ("NFLX", "5m"),
    ("COIN", "5m"), ("MSTR", "5m"), ("HOOD", "5m"), ("SHOP", "5m"), ("SOFI", "5m"),
    ("ZS", "5m"), ("NET", "5m"), ("CELH", "5m"), ("RBLX", "5m"), ("PLTR", "5m"),
    ("MDB", "5m"), ("SMCI", "5m"), ("DELL", "5m"),
    ("NVO", "5m"), ("LLY", "5m"), ("MRNA", "5m"), ("NKE", "5m"), ("TGT", "5m"), ("SCHW", "5m"),
    ("AMZN", "5m"),
    ("MU", "5m"), ("LUNR", "5m"), ("CAT", "5m"), ("GS", "5m"),
    # Onboarding apr 2026 — data collection only, blocklist runtime fino OOS:
    ("NIO", "5m"), ("RIVN", "5m"), ("DKNG", "5m"), ("SOUN", "5m"),
]

VALIDATED_SYMBOLS_ALPACA_5M: frozenset[str] = frozenset(
    sym for sym, _ in SCHEDULER_SYMBOLS_ALPACA_5M
    if sym not in SYMBOLS_BLOCKED_ALPACA_5M
)

# ── Yahoo Finance 1d (regime anchor US) ──────────────────────────────────────
# SPY 1d: unica candela giornaliera necessaria per il regime filter EMA50 US.
# Non viene tradato (bloccato in SYMBOLS_BLOCKED_YAHOO_1H): solo raccolta dati regime.
SCHEDULER_SYMBOLS_YAHOO_1D_REGIME: list[tuple[str, str]] = [
    ("SPY", "1d"),
]

# ── Binance crypto ───────────────────────────────────────────────────────────
VALIDATED_SYMBOLS_BINANCE: frozenset[str] = frozenset()  # disabilitato apr 2026

SCHEDULER_SYMBOLS_BINANCE_1H: list[tuple[str, str]] = [
    ("ETH/USDT", "1h"), ("DOGE/USDT", "1h"), ("ADA/USDT", "1h"),
    ("SOL/USDT", "1h"), ("WLD/USDT", "1h"), ("MATIC/USDT", "1h"),
]

SCHEDULER_SYMBOLS_BINANCE_5M: list[tuple[str, str]] = [
    ("ETH/USDT", "5m"), ("DOGE/USDT", "5m"), ("ADA/USDT", "5m"),
    ("SOL/USDT", "5m"), ("WLD/USDT", "5m"), ("MATIC/USDT", "5m"),
]

SCHEDULER_SYMBOLS_BINANCE_1D_REGIME: list[tuple[str, str]] = [
    ("BTC/USDT", "1d"),
]
