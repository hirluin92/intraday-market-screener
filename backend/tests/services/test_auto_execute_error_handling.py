"""
Test della gestione errori in execute_signal() (auto_execute_service.py).

Copre i 3 path di fallimento introdotti dal fix:
  1. Eccezione Python durante place_bracket_order        → status="error", tws_status="exception"
  2. TWS ritorna {"error": ...} (disconnesso/timeout)    → status="error", tws_status="tws_unavailable"
  3. Errori critici IBKR nel log (es. 201 rejected)      → status="error", tws_status="rejected"
  4. Solo messaggi informativi (2104/2106)               → status="executed", tws_status="submitted"
  5. Mix critico + informativo                           → status="error" (il critico vince)
  6. Risposta senza entry order_id                       → status="error", tws_status="no_order_id"
  7. Successo normale                                    → status="executed", tws_status="submitted"

E il classificatore is_critical_ibkr_error() di ibkr_error_codes.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.auto_execute_service import execute_signal
from app.services.ibkr_error_codes import is_critical_ibkr_error


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_tws_result(
    entry_order_id: int = 100,
    errors: list[str] | None = None,
) -> dict:
    """Costruisce un dict TWS result valido come ritornato da place_bracket_order."""
    return {
        "symbol": "AAPL",
        "action": "BUY",
        "quantity": 5,
        "entry_price": 180.0,
        "take_profit_price": 185.0,
        "stop_price": 177.0,
        "account": "DU12345",
        "entry": {
            "order_id": entry_order_id,
            "type": "LMT",
            "action": "BUY",
            "qty": 5,
            "lmt_price": 180.0,
            "tif": "GTC",
            "status": "PreSubmitted",
            "filled": 0,
            "avg_fill": 0,
        },
        "take_profit": {
            "order_id": entry_order_id + 1,
            "type": "LMT",
            "action": "SELL",
            "qty": 5,
            "lmt_price": 185.0,
            "tif": "GTC",
            "status": "PreSubmitted",
            "filled": 0,
            "avg_fill": 0,
        },
        "stop_loss": {
            "order_id": entry_order_id + 2,
            "type": "STP",
            "action": "SELL",
            "qty": 5,
            "aux_price": 177.0,
            "tif": "GTC",
            "status": "PreSubmitted",
            "filled": 0,
            "avg_fill": 0,
        },
        "errors": errors or [],
    }


async def _call_execute_signal(mock_place_bracket_order_return=None, mock_place_bracket_order_side_effect=None):
    """
    Chiama execute_signal() con tutti i guard rails bypassati (TWS mock).
    Ritorna il result dict.
    """
    mock_tws = MagicMock()
    mock_tws.is_connected = True
    mock_tws.get_open_positions = AsyncMock(return_value=[])
    mock_tws.get_net_liquidation = AsyncMock(return_value=50000.0)

    if mock_place_bracket_order_side_effect is not None:
        mock_tws.place_bracket_order = AsyncMock(side_effect=mock_place_bracket_order_side_effect)
    else:
        mock_tws.place_bracket_order = AsyncMock(return_value=mock_place_bracket_order_return)

    with (
        patch("app.services.auto_execute_service.settings") as mock_settings,
        patch("app.services.auto_execute_service.get_tws_service", return_value=mock_tws),  # noqa: SIM117
    ):
        mock_settings.tws_enabled = True
        mock_settings.ibkr_auto_execute = True
        mock_settings.ibkr_margin_account = False
        mock_settings.ibkr_max_simultaneous_positions = 5
        mock_settings.ibkr_slots_1h = 3
        mock_settings.ibkr_slots_5m = 2
        mock_settings.ibkr_max_risk_per_trade_pct = 0.01

        result = await execute_signal(
            symbol="AAPL",
            direction="bullish",
            entry_price=180.0,
            stop_price=177.0,
            take_profit_price=185.0,
            pattern_name="engulfing_bullish",
            strength=0.85,
        )
    return result


# ── Test classificatore is_critical_ibkr_error ────────────────────────────────

class TestIsCriticalIbkrError:
    def test_info_code_2104_not_critical(self):
        assert is_critical_ibkr_error("Error 2104, reqId -1: Market data farm connection is OK") is False

    def test_info_code_2106_not_critical(self):
        assert is_critical_ibkr_error("Error 2106, reqId -1: HMDS data farm connection is OK") is False

    def test_info_code_2158_not_critical(self):
        assert is_critical_ibkr_error("Error 2158, reqId -1: Sec-def data farm connection is OK") is False

    def test_info_code_399_not_critical(self):
        assert is_critical_ibkr_error("Error 399, reqId 55: Order message: Warning 0: Your order will not be placed at the exchange until...") is False

    def test_critical_code_201_rejected(self):
        assert is_critical_ibkr_error("Error 201, reqId 12: Order rejected - insufficient margin") is True

    def test_critical_code_203_not_allowed(self):
        assert is_critical_ibkr_error("Error 203, reqId 13: The security is not available or allowed for this account") is True

    def test_critical_code_354_not_subscribed(self):
        assert is_critical_ibkr_error("Error 354, reqId 14: Requested market data is not subscribed") is True

    def test_empty_string_not_critical(self):
        assert is_critical_ibkr_error("") is False

    def test_none_like_empty_not_critical(self):
        assert is_critical_ibkr_error("   ") is False

    def test_keyword_rejected_critical(self):
        assert is_critical_ibkr_error("Order rejected: margin insufficient") is True

    def test_keyword_cannot_find_critical(self):
        assert is_critical_ibkr_error("Cannot find order 9999") is True

    def test_unknown_code_with_no_keyword_not_critical(self):
        # Codice sconosciuto (99999) senza keyword critico → non critico
        assert is_critical_ibkr_error("Error 99999, reqId 1: Some unknown informational message") is False

    def test_mix_critical_keyword_and_info_code(self):
        # Il codice è informativo MA il testo contiene "rejected" → critico per keyword
        # (edge case: testo costruito male che non dovrebbe accadere in pratica)
        assert is_critical_ibkr_error("Error 2104: order rejected for some reason") is False
        # Il codice 2104 è in IBKR_INFO_CODES → False, il codice ha precedenza sul keyword


# ── Test execute_signal ────────────────────────────────────────────────────────

class TestExecuteSignalErrorHandling:

    async def test_exception_during_place_bracket(self):
        """Eccezione Python → status=error, tws_status=exception."""
        result = await _call_execute_signal(
            mock_place_bracket_order_side_effect=RuntimeError("connection reset by peer")
        )
        assert result["status"] == "error"
        assert result["tws_status"] == "exception"
        assert "connection reset by peer" in result["reason"]

    async def test_tws_disconnected_returns_error_dict(self):
        """TWS ritorna {"error": ...} senza eccezione → tws_unavailable."""
        result = await _call_execute_signal(
            mock_place_bracket_order_return={"error": "TWS non connesso"}
        )
        assert result["status"] == "error"
        assert result["tws_status"] == "tws_unavailable"
        assert "TWS non connesso" in result["reason"]

    async def test_critical_ibkr_error_in_errors_list(self):
        """Errore critico IBKR (201 rejected) → status=error, tws_status=rejected."""
        tws_result = _make_tws_result(errors=["Error 201, reqId 100: Order rejected - margin insufficient"])
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "error"
        assert result["tws_status"] == "rejected"
        assert "201" in result["reason"] or "rejected" in result["reason"].lower()

    async def test_only_info_errors_do_not_block_order(self):
        """Solo messaggi informativi (2104, 2106) → order passa, status=executed."""
        tws_result = _make_tws_result(errors=[
            "Error 2104, reqId -1: Market data farm connection is OK",
            "Error 2106, reqId -1: HMDS data farm connection is OK",
        ])
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "executed"
        assert result["tws_status"] == "submitted"

    async def test_mix_critical_and_info_errors(self):
        """Mix critico + informativo → il critico vince, status=error."""
        tws_result = _make_tws_result(errors=[
            "Error 2104, reqId -1: Market data farm connection is OK",
            "Error 201, reqId 100: Order rejected - insufficient funds",
        ])
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "error"
        assert result["tws_status"] == "rejected"

    async def test_no_entry_order_id_in_response(self):
        """TWS risponde senza order_id nell'entry → no_order_id."""
        tws_result = _make_tws_result()
        tws_result["entry"]["order_id"] = None  # simula risposta incompleta
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "error"
        assert result["tws_status"] == "no_order_id"

    async def test_entry_order_missing_entirely(self):
        """TWS risponde senza chiave 'entry' → no_order_id."""
        tws_result = _make_tws_result()
        del tws_result["entry"]
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "error"
        assert result["tws_status"] == "no_order_id"

    async def test_success_normal_flow(self):
        """Successo normale → status=executed, tws_status=submitted."""
        tws_result = _make_tws_result()
        result = await _call_execute_signal(mock_place_bracket_order_return=tws_result)
        assert result["status"] == "executed"
        assert result["tws_status"] == "submitted"
        assert result["symbol"] == "AAPL"
        assert result["action"] == "BUY"
        assert result["tws_result"] is tws_result
