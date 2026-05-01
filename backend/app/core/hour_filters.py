"""Filtri orari UTC per sessione di mercato — Yahoo Finance (US), LSE (UK), crypto 24/7."""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache

# ── Finestre di attività con buffer (+1h pre/post apertura) ──────────────────
#
# US (NYSE/NASDAQ):
#   EDT (estate): mercato 13:30–20:00 UTC → finestra buffered 12–21 UTC
#   EST (inverno): mercato 14:30–21:00 UTC → finestra buffered 13–22 UTC
#   Unione conservativa: 12–22 UTC (ore incluse: 12, 13, …, 21)
#
# LSE:
#   BST (estate, UTC+1): mercato 07:00–15:30 UTC → finestra buffered 06–16 UTC
#   GMT (inverno, UTC):  mercato 08:00–16:30 UTC → finestra buffered 07–17 UTC
#   Unione conservativa: 06–17 UTC (ore incluse: 6, 7, …, 17)
#
_MARKET_ACTIVE_START_UTC_US: int = 12   # ora inclusa
_MARKET_ACTIVE_END_UTC_US: int = 21     # ora inclusa

_MARKET_ACTIVE_START_UTC_LSE: int = 6   # ora inclusa
_MARKET_ACTIVE_END_UTC_LSE: int = 17    # ora inclusa

# ── Sessione US (NYSE/NASDAQ) ─────────────────────────────────────────────────
# Escluse: pranzo NY (~17 UTC = 13:00 ET) e after hours (~21 UTC = 17:00 ET).
# Le ore rimanenti coprono la sessione regolare 14:30-21:00 UTC (09:30-16:00 ET).
EXCLUDED_HOURS_UTC_US: frozenset[int] = frozenset({17, 21})

# Alias backward-compat: il vecchio nome è ancora usabile da codice esterno.
EXCLUDED_HOURS_UTC_YAHOO = EXCLUDED_HOURS_UTC_US

# ── Sessione UK (London Stock Exchange) ───────────────────────────────────────
# LSE opera 08:00-16:30 London Time.
# In estate (BST = UTC+1): 07:00-15:30 UTC.
# In inverno (GMT = UTC):  08:00-16:30 UTC.
#
# Approccio conservativo: escludo solo le ore definitivamente NON operative in
# nessuna stagione, cioè quelle fuori dall'unione delle due finestre:
#   Unione operative: 07:00-16:30 UTC → ore 7-16 incluse (17 è già fuori in BST).
#   Esclusioni sicure: 0-6 UTC e 17-23 UTC.
#
# Questo garantisce che barre durante l'apertura BST (07:00 UTC) non vengano
# scartate in estate. L'ultima mezz'ora di chiusura (16:00-16:30 UK) è ad alta
# volatilità/bid-ask ampio — inclusa per osservazione ma da valutare in Fase 3.
EXCLUDED_HOURS_UTC_LSE: frozenset[int] = frozenset(
    {0, 1, 2, 3, 4, 5, 6, 17, 18, 19, 20, 21, 22, 23}
)


def get_excluded_hours_for_exchange(exchange: str) -> frozenset[int]:
    """
    Restituisce il set di ore UTC escluse (non operative) per l'exchange dato.

    Args:
        exchange: stringa exchange (es. "LSE", "YAHOO_US", "SMART", "").

    Returns:
        frozenset di ore intere (0-23) non operative. Empty frozenset per mercati 24/7.
    """
    ex = (exchange or "").upper().strip()
    if ex == "LSE":
        return EXCLUDED_HOURS_UTC_LSE
    # Default: sessione US (NYSE/NASDAQ/YAHOO_US/SMART/ALPACA_US o sconosciuto)
    return EXCLUDED_HOURS_UTC_US


def get_excluded_hours_for_provider(provider: str) -> frozenset[int] | None:
    """
    Restituisce il set di ore UTC escluse per il provider dato.

    Returns:
        frozenset di ore escluse, oppure None per provider 24/7 (crypto Binance).
    """
    if provider == "binance":
        return None  # crypto 24/7, nessuna esclusione
    if provider == "ibkr":
        return EXCLUDED_HOURS_UTC_LSE  # ibkr = UK/LSE in questo sistema
    # yahoo_finance, alpaca → sessione US
    return EXCLUDED_HOURS_UTC_US


def hour_utc(dt: datetime) -> int:
    """Ora 0–23 in UTC (timestamp naive → interpretato come UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).hour
    return dt.astimezone(timezone.utc).hour


def is_equity_market_active(provider: str, now: datetime | None = None) -> bool:
    """
    Controlla se il mercato equity del provider è probabilmente aperto in questo momento.

    Controlla tre condizioni in sequenza (fast-path prima):
    1. **Weekend** — sabato e domenica i mercati equity sono sempre chiusi.
    2. **Festività** — usa ``pandas_market_calendars`` con calendario NYSE (US) o
       XLON (LSE/UK) per verificare se oggi è un giorno di trading.
       Il risultato è cached per (calendario, data) → al massimo una query al giorno.
    3. **Finestra oraria** — l'ora UTC corrente deve ricadere nella finestra operativa
       del mercato (con buffer di +1h pre/post rispetto agli orari ufficiali, per coprire
       sia EDT estate che EST inverno).

    - ``binance``: sempre True (crypto 24/7)
    - ``yahoo_finance`` / ``alpaca`` → NYSE: Mon–Fri, non festività, ora UTC in [12, 21]
    - ``ibkr`` (LSE) → XLON: Mon–Fri, non festività, ora UTC in [6, 17]
    - provider sconosciuto: True (conservativo, non blocca mai)

    Args:
        provider: stringa provider (es. "yahoo_finance", "alpaca", "binance", "ibkr").
        now: datetime di riferimento (default: ``datetime.now(timezone.utc)``).

    Returns:
        True se la pipeline per quel provider ha senso girare ora.
    """
    if provider == "binance":
        return True  # crypto 24/7

    dt = (now if now is not None else datetime.now(timezone.utc)).astimezone(timezone.utc)

    # 1. Weekend (fast path, nessuna import)
    if dt.weekday() >= 5:  # 5=sabato, 6=domenica
        return False

    # 2. Ora UTC nella finestra operativa del mercato
    h = dt.hour
    if provider == "ibkr":
        if not (_MARKET_ACTIVE_START_UTC_LSE <= h <= _MARKET_ACTIVE_END_UTC_LSE):
            return False
        calendar_name = "XLON"
    elif provider in {"yahoo_finance", "alpaca"}:
        if not (_MARKET_ACTIVE_START_UTC_US <= h <= _MARKET_ACTIVE_END_UTC_US):
            return False
        calendar_name = "NYSE"
    else:
        return True  # provider sconosciuto: conservativo

    # 3. Festività — cached per (calendario, data UTC)
    return _is_trading_day(calendar_name, dt.date())


@lru_cache(maxsize=512)
def _is_trading_day(calendar_name: str, d: date) -> bool:
    """
    Ritorna True se ``d`` è un giorno di trading per il calendario indicato.

    Il risultato è cached con ``lru_cache``: la stessa (calendario, data) viene
    interrogata al massimo una volta per processo (tipicamente una volta al giorno).
    Usa ``pandas_market_calendars`` con regole festività puramente locali (no network).

    Args:
        calendar_name: nome calendario mcal (es. "NYSE", "XLON").
        d: data da verificare.

    Returns:
        True se è un giorno di trading, False se è festività o weekend.
    """
    try:
        import pandas_market_calendars as mcal  # noqa: PLC0415

        cal = mcal.get_calendar(calendar_name)
        schedule = cal.schedule(
            start_date=d.isoformat(),
            end_date=d.isoformat(),
        )
        return not schedule.empty
    except Exception:
        # Se pandas_market_calendars non è installato o fallisce, comportamento conservativo.
        return True
