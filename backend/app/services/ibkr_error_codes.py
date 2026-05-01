"""
Classificazione codici errore IBKR/TWS API.

Reference: https://interactivebrokers.github.io/tws-api/message_codes.html

Usato da execute_signal() in auto_execute_service.py per distinguere errori
critici (ordine rifiutato → non salvare come "executed") da messaggi informativi
(notifiche di stato connessione → ignorare, non bloccare l'ordine).
"""

from __future__ import annotations

import re

# ── Codici INFORMATIVI ────────────────────────────────────────────────────────
# Notifiche normali di stato connessione/dati. NON sono rifiuti dell'ordine.
IBKR_INFO_CODES: frozenset[int] = frozenset({
    2100,  # New account data requested from TWS
    2103,  # Market data farm connection is broken (poi 2104 al ripristino)
    2104,  # Market data farm connection is OK
    2105,  # HMDS data farm connection is broken (poi 2106 al ripristino)
    2106,  # HMDS data farm connection is OK
    2107,  # HMDS data farm connection is inactive (available on demand)
    2108,  # Market data farm connection is inactive (available on demand)
    2150,  # Invalid position trade derived value
    2158,  # Sec-def data farm connection is OK
    10167, # Requested market data is not subscribed. Displaying delayed market data
    10349, # Cross currency combo order is not supported for the exchange
    399,   # Order message: warning generico (es. "order will not be placed until open")
    202,   # Order Canceled - già gestito, solo notifica
})

# ── Codici CRITICI ────────────────────────────────────────────────────────────
# L'ordine è stato rifiutato, annullato per errore, o non è eseguibile.
# Questi causano il ritorno di status="error" in execute_signal().
IBKR_CRITICAL_CODES: frozenset[int] = frozenset({
    110,   # The price does not conform to the minimum price variation (tick size)
    200,   # No security definition has been found for the request
    201,   # Order rejected - reason specificata nel messaggio
    203,   # The security is not available or allowed for this account
    321,   # Server error when validating an API client request
    354,   # Requested market data is not subscribed (no delayed fallback)
    404,   # No trading permissions for the security in this account
    478,   # Symbol is no longer valid
    10006, # Requested market data is not subscribed (routing)
    10147, # OrderId X that needs to be cancelled is not found
    10148, # OrderId X that needs to be cancelled cannot be cancelled
    10197, # The account does not have trading permissions for this product
    10289, # Order size is smaller than the minimum
    135,   # Cannot find order (race condition parent/child)
})

# ── Keywords critici come fallback se il codice numerico non è riconosciuto ──
_CRITICAL_KEYWORDS: tuple[str, ...] = (
    "rejected",
    "cannot find",
    "not available",
    "not allowed",
    "insufficient",
    "invalid",
    "no longer valid",
    "not subscribed",
    "no trading permission",
    "minimum price variation",
    "smaller than the minimum",
    "no security definition",
)


def is_critical_ibkr_error(error_text: str) -> bool:
    """
    Determina se un messaggio di errore TWS è critico (ordine rifiutato/non eseguibile)
    o solo informativo (notifica di stato connessione).

    Logica:
    1. Estrae il codice numerico dal testo (formato "Error CODE," o "errorCode=CODE")
    2. Se il codice è in IBKR_INFO_CODES → False (non critico)
    3. Se il codice è in IBKR_CRITICAL_CODES → True (critico)
    4. Se il codice è sconosciuto, usa fallback su keyword → True se match

    Args:
        error_text: testo dell'errore come ritornato da ib_insync,
                    es. "Error 201, reqId 12345: Order rejected - margin insufficient"

    Returns:
        True  → errore critico, l'ordine deve essere considerato fallito.
        False → messaggio informativo, non blocca l'ordine.
    """
    if not error_text:
        return False

    text_lower = error_text.lower()

    match = re.search(r"(?:error|code[=:])\s*(\d+)", text_lower)
    if match:
        code = int(match.group(1))
        if code in IBKR_INFO_CODES:
            return False
        if code in IBKR_CRITICAL_CODES:
            return True
        # Codice numerico presente ma non in nessuna mappa: usa keyword

    return any(kw in text_lower for kw in _CRITICAL_KEYWORDS)
