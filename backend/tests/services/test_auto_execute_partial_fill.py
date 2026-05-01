"""
Unit test per la logica di gestione fill parziali in auto_execute_service.py.

Tutti i test mockano il TWSService e il DB così non richiedono connessione IBKR né Postgres.

Esegui con:
    cd backend
    python -m pytest tests/services/test_auto_execute_partial_fill.py -v
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.auto_execute_service import (
    MIN_FILL_RATIO,
    _handle_partial_fill_after_bracket,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_fill_result(
    status: str,
    filled_qty: float,
    ordered_qty: float,
    avg_fill_price: float = 150.0,
) -> dict:
    return {
        "status": status,
        "filled_qty": filled_qty,
        "ordered_qty": ordered_qty,
        "avg_fill_price": avg_fill_price,
    }


def _make_executed_signal(
    rec_id: int = 1,
    symbol: str = "AAPL",
    direction: str = "bullish",
    entry_price: float = 150.0,
    stop_price: float = 147.0,
    take_profit_price: float = 154.5,
    quantity: float = 10.0,
) -> MagicMock:
    rec = MagicMock()
    rec.id = rec_id
    rec.symbol = symbol
    rec.direction = direction
    rec.entry_price = Decimal(str(entry_price))
    rec.stop_price = Decimal(str(stop_price))
    rec.take_profit_1 = Decimal(str(take_profit_price))
    rec.tws_status = "Submitted"
    rec.partial_fill = False
    rec.filled_qty = None
    rec.ordered_qty = None
    return rec


# ─── Costanti ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_min_fill_ratio_is_30_pct(self):
        assert MIN_FILL_RATIO == pytest.approx(0.30)


# ─── compute_realized_r (riusato qui per coerenza) ────────────────────────────

class TestComputeRealizedR:
    def test_full_fill_no_slippage(self):
        from app.services.auto_execute_service import compute_realized_r
        # Stop nominale a 147 su entry 150 → risk=3
        # Fill esattamente a 147 → realized_R = (147-150)/3 = -1.0
        r = compute_realized_r(
            entry_price=150.0,
            stop_price=147.0,
            fill_price=147.0,
            direction="bullish",
        )
        assert r == pytest.approx(-1.0)

    def test_gap_fill_worse_than_stop(self):
        from app.services.auto_execute_service import compute_realized_r
        # Fill a 145.5 invece di 147 → slippage
        r = compute_realized_r(
            entry_price=150.0,
            stop_price=147.0,
            fill_price=145.5,
            direction="bullish",
        )
        assert r == pytest.approx(-1.5)


# ─── _handle_partial_fill_after_bracket ──────────────────────────────────────

@pytest.fixture
def mock_tws():
    tws = MagicMock()
    tws.is_connected = True
    tws.poll_entry_fill = AsyncMock()
    tws.cancel_order_by_id = AsyncMock(return_value=True)
    tws.place_tp_sl_standalone = AsyncMock(return_value={"errors": []})
    tws.place_market_close_order = AsyncMock(return_value={"status": "Submitted"})
    return tws


@pytest.fixture
def mock_rec():
    return _make_executed_signal()


async def _run_handler(
    tws,
    rec,
    *,
    rec_id: int = 1,
    entry_order_id: int = 101,
    sl_order_id: int | None = 102,
    tp_order_id: int | None = 103,
    ordered_qty: float = 10.0,
    symbol: str = "AAPL",
    action: str = "BUY",
    stop_price: float = 147.0,
    take_profit_price: float = 154.5,
):
    # get_tws_service è importato con local import dentro la funzione:
    # "from app.services.tws_service import get_tws_service"
    # → patch sul modulo sorgente (tws_service), non su auto_execute_service.
    # Stesso discorso per AsyncSessionLocal (importato da app.db.session).
    with (
        patch("app.services.tws_service.get_tws_service", return_value=tws),
        patch("app.db.session.AsyncSessionLocal") as mock_sl,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=rec)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_sl.return_value = mock_session

        await _handle_partial_fill_after_bracket(
            rec_id=rec_id,
            entry_order_id=entry_order_id,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            ordered_qty=ordered_qty,
            symbol=symbol,
            action=action,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )
        return mock_session


class TestFullFill:
    @pytest.mark.asyncio
    async def test_full_fill_no_resize(self, mock_tws, mock_rec):
        """Fill completo: DB aggiornato, nessun cancel/resize."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Filled", 10.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        assert mock_rec.partial_fill is False
        assert float(mock_rec.filled_qty) == pytest.approx(10.0)
        assert float(mock_rec.ordered_qty) == pytest.approx(10.0)
        mock_tws.cancel_order_by_id.assert_not_called()
        mock_tws.place_tp_sl_standalone.assert_not_called()
        mock_tws.place_market_close_order.assert_not_called()
        session.commit.assert_called_once()


class TestPartialFillAboveThreshold:
    @pytest.mark.asyncio
    async def test_partial_fill_7_of_10_resizes(self, mock_tws, mock_rec):
        """Fill parziale 7/10 (70% > 30%): cancella SL/TP originali, reinvia dimensionati su 7."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Filled", 7.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        assert mock_rec.partial_fill is True
        assert float(mock_rec.filled_qty) == pytest.approx(7.0)
        # Deve cancellare entrambi gli ordini originali (sl=102, tp=103)
        assert mock_tws.cancel_order_by_id.call_count == 2
        # Deve reinviare SL/TP standalone dimensionati su 7
        mock_tws.place_tp_sl_standalone.assert_called_once()
        call_kwargs = mock_tws.place_tp_sl_standalone.call_args.kwargs
        assert call_kwargs["quantity"] == pytest.approx(7.0)
        assert call_kwargs["close_action"] == "SELL"  # BUY entry → SELL close
        mock_tws.place_market_close_order.assert_not_called()
        assert mock_rec.tws_status == "partial_fill_resized"

    @pytest.mark.asyncio
    async def test_partial_fill_timeout_still_resizes(self, mock_tws, mock_rec):
        """Fill parziale via Timeout (60s scaduti): stesso comportamento del parziale normale."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Timeout", 5.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        assert mock_rec.partial_fill is True
        assert mock_tws.place_tp_sl_standalone.call_count == 1
        call_kwargs = mock_tws.place_tp_sl_standalone.call_args.kwargs
        assert call_kwargs["quantity"] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_short_partial_fill_uses_buy_close(self, mock_tws, mock_rec):
        """Short: fill parziale → close action deve essere BUY (non SELL)."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Filled", 6.0, 10.0)

        session = await _run_handler(
            mock_tws, mock_rec,
            action="SELL",  # short entry
        )

        call_kwargs = mock_tws.place_tp_sl_standalone.call_args.kwargs
        assert call_kwargs["close_action"] == "BUY"


class TestPartialFillBelowThreshold:
    @pytest.mark.asyncio
    async def test_fill_ratio_too_low_closes_position(self, mock_tws, mock_rec):
        """Fill 2/10 (20% < 30%): chiusura immediata con market order."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Filled", 2.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        assert mock_rec.partial_fill is True
        # Deve cancellare SL/TP originali
        assert mock_tws.cancel_order_by_id.call_count == 2
        # Deve chiudere con market order
        mock_tws.place_market_close_order.assert_called_once()
        call_kwargs = mock_tws.place_market_close_order.call_args.kwargs
        assert call_kwargs["quantity"] == pytest.approx(2.0)
        assert call_kwargs["action"] == "SELL"
        # NON deve resize
        mock_tws.place_tp_sl_standalone.assert_not_called()
        assert mock_rec.tws_status == "partial_fill_closed"

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_resizes_not_closes(self, mock_tws, mock_rec):
        """Fill ratio esattamente al 30%: resize (non chiusura)."""
        # MIN_FILL_RATIO = 0.30; 3/10 = 0.30 → NON deve chiudere
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Filled", 3.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        # 3/10 = 0.30, non < 0.30 → resize
        mock_tws.place_tp_sl_standalone.assert_called_once()
        mock_tws.place_market_close_order.assert_not_called()


class TestRejectedOrder:
    @pytest.mark.asyncio
    async def test_cancelled_order_no_fill_cleans_up(self, mock_tws, mock_rec):
        """Ordine cancelled con 0 fill: cancella SL/TP, aggiorna tws_status."""
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Cancelled", 0.0, 10.0)

        session = await _run_handler(mock_tws, mock_rec)

        assert mock_rec.partial_fill is False
        assert mock_tws.cancel_order_by_id.call_count == 2
        mock_tws.place_tp_sl_standalone.assert_not_called()
        mock_tws.place_market_close_order.assert_not_called()
        assert "rejected" in mock_rec.tws_status

    @pytest.mark.asyncio
    async def test_rejected_order_cleans_up(self, mock_tws, mock_rec):
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Rejected", 0.0, 10.0)

        await _run_handler(mock_tws, mock_rec)

        assert mock_tws.cancel_order_by_id.call_count == 2

    @pytest.mark.asyncio
    async def test_cancelled_with_partial_fill_triggers_resize(self, mock_tws, mock_rec):
        """Cancelled ma con fill parziale esistente (IBKR può cancellare dopo fill parziale)."""
        # filled=4 > 0 → trattato come parziale, non come rejected pulito
        mock_tws.poll_entry_fill.return_value = _make_fill_result("Cancelled", 4.0, 10.0)

        await _run_handler(mock_tws, mock_rec)

        # filled > 0 e not is_rejected (perché filled > 0.01) → percorso parziale
        assert mock_rec.partial_fill is True


class TestTWSNotConnected:
    @pytest.mark.asyncio
    async def test_tws_not_connected_no_action(self):
        """Se TWS non è connesso, il task esce silenziosamente senza DB access."""
        tws = MagicMock()
        tws.is_connected = False

        with (
            patch("app.services.tws_service.get_tws_service", return_value=tws),
            patch("app.db.session.AsyncSessionLocal") as mock_sl,
        ):
            await _handle_partial_fill_after_bracket(
                rec_id=1, entry_order_id=101,
                sl_order_id=102, tp_order_id=103,
                ordered_qty=10.0, symbol="AAPL",
                action="BUY", stop_price=147.0, take_profit_price=154.5,
            )
            mock_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_tws_none_no_action(self):
        with (
            patch("app.services.tws_service.get_tws_service", return_value=None),
            patch("app.db.session.AsyncSessionLocal") as mock_sl,
        ):
            await _handle_partial_fill_after_bracket(
                rec_id=1, entry_order_id=101,
                sl_order_id=None, tp_order_id=None,
                ordered_qty=10.0, symbol="AAPL",
                action="BUY", stop_price=147.0, take_profit_price=154.5,
            )
            mock_sl.assert_not_called()
