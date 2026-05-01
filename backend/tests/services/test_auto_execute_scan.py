"""
Test di run_auto_execute_scan e maybe_ibkr_auto_execute_after_pipeline.

Copre:
  1. Scan con 1 provider + 1 timeframe → itera 1 combinazione
  2. Scan con 2 provider + 2 timeframe → itera 4 combinazioni
  3. 5m disabilitato di default → segnali 5m non vengono mai eseguiti dallo scan
  4. Cap globale MAX_ORDERS_PER_SCAN raggiunto → scan si interrompe
  5. Errore list_opportunities su una combo → loggato, non blocca le altre
  6. Hook per-simbolo: 7 segnali validi → esegue MAX_ORDERS_PER_HOOK_INVOCATION e logga cap
  7. Hook: provider non in lista abilitata → non chiama list_opportunities
  8. Hook: timeframe non in lista abilitata → non chiama list_opportunities
  9. Scan: nessuna combinazione abilitata → skip silenzioso
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.auto_execute_service import (
    MAX_ORDERS_PER_HOOK_INVOCATION,
    MAX_ORDERS_PER_SCAN,
    maybe_ibkr_auto_execute_after_pipeline,
    run_auto_execute_scan,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_opp(decision: str = "execute") -> MagicMock:
    opp = MagicMock()
    opp.operational_decision = decision
    opp.symbol = "AAPL"
    opp.timeframe = "1h"
    opp.provider = "yahoo_finance"
    opp.exchange = "SMART"
    opp.trade_plan = MagicMock()
    opp.trade_plan.entry_price = 180.0
    opp.trade_plan.stop_loss = 177.0
    opp.trade_plan.take_profit_1 = 185.0
    opp.trade_plan.take_profit_2 = None
    opp.latest_pattern_direction = "bullish"
    opp.latest_pattern_strength = 0.85
    opp.latest_pattern_name = "engulfing_bullish"
    opp.final_opportunity_score = 72.0
    return opp


def _patch_scan_deps(
    *,
    tws_enabled: bool = True,
    ibkr_auto_execute: bool = True,
    timeframes: str = "1h",
    providers: str = "yahoo_finance,binance",
    rows_by_combo: dict | None = None,
    execute_and_save_ok: bool = True,
):
    """
    Patcha le dipendenze di run_auto_execute_scan e ritorna i mock usati.
    rows_by_combo: {(provider, timeframe): [list_of_opps]} — default rows vuote.
    """
    rows_by_combo = rows_by_combo or {}

    async def _list_opps(_session, *, provider, timeframe, **_kw):
        return rows_by_combo.get((provider, timeframe), [])

    return {
        "settings": MagicMock(
            tws_enabled=tws_enabled,
            ibkr_auto_execute=ibkr_auto_execute,
            auto_execute_providers_list=providers.split(",") if providers else [],
            auto_execute_timeframes_list=timeframes.split(",") if timeframes else [],
        ),
        "list_opportunities": AsyncMock(side_effect=_list_opps),
        "execute_and_save": AsyncMock(return_value=execute_and_save_ok),
    }


# ── Test run_auto_execute_scan ─────────────────────────────────────────────────

class TestRunAutoExecuteScan:

    async def test_single_combo_called_once(self):
        """1 provider + 1 timeframe → list_opportunities chiamata 1 volta."""
        mocks = _patch_scan_deps(providers="yahoo_finance", timeframes="1h")

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service._execute_and_save", mocks["execute_and_save"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        mocks["list_opportunities"].assert_called_once()
        _, kwargs = mocks["list_opportunities"].call_args
        assert kwargs["provider"] == "yahoo_finance"
        assert kwargs["timeframe"] == "1h"

    async def test_two_providers_two_timeframes_four_combinations(self):
        """2 provider × 2 timeframe → 4 chiamate a list_opportunities."""
        mocks = _patch_scan_deps(providers="yahoo_finance,binance", timeframes="1h,5m")

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service._execute_and_save", mocks["execute_and_save"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        assert mocks["list_opportunities"].call_count == 4
        combos = {
            (kw["provider"], kw["timeframe"])
            for _, kw in mocks["list_opportunities"].call_args_list
        }
        assert ("yahoo_finance", "1h") in combos
        assert ("yahoo_finance", "5m") in combos
        assert ("binance", "1h") in combos
        assert ("binance", "5m") in combos

    async def test_5m_not_in_default_timeframes(self):
        """Default 1h only → nessuna chiamata con timeframe=5m."""
        mocks = _patch_scan_deps(providers="yahoo_finance", timeframes="1h")

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service._execute_and_save", mocks["execute_and_save"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        called_tfs = [kw["timeframe"] for _, kw in mocks["list_opportunities"].call_args_list]
        assert "5m" not in called_tfs

    async def test_global_cap_stops_scan(self):
        """
        Quando total_executed >= MAX_ORDERS_PER_SCAN → scan si interrompe,
        non vengono processate le opportunità rimanenti.
        """
        opps = [_make_opp() for _ in range(MAX_ORDERS_PER_SCAN + 5)]
        mocks = _patch_scan_deps(
            providers="yahoo_finance",
            timeframes="1h",
            rows_by_combo={("yahoo_finance", "1h"): opps},
            execute_and_save_ok=True,
        )

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service._execute_and_save", mocks["execute_and_save"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        # Cap raggiunto → al massimo MAX_ORDERS_PER_SCAN esecuzioni
        assert mocks["execute_and_save"].call_count <= MAX_ORDERS_PER_SCAN

    async def test_error_in_one_combo_continues_others(self):
        """Eccezione su yahoo_finance/1h → binance/1h viene ancora processata."""
        call_count = {"n": 0}

        async def _list_opps_raise(_session, *, provider, timeframe, **_kw):
            call_count["n"] += 1
            if provider == "yahoo_finance":
                raise RuntimeError("DB timeout simulato")
            return []

        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance", "binance"],
            auto_execute_timeframes_list=["1h"],
        )

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", AsyncMock(side_effect=_list_opps_raise)),
            patch("app.services.auto_execute_service._execute_and_save", AsyncMock(return_value=False)),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        # Entrambi i provider vengono tentati nonostante l'errore sul primo
        assert call_count["n"] == 2

    async def test_tws_disabled_returns_immediately(self):
        """tws_enabled=False → scan non parte, nessuna chiamata."""
        mocks = _patch_scan_deps(tws_enabled=False)

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        mocks["list_opportunities"].assert_not_called()

    async def test_no_enabled_combos_skips_silently(self):
        """Lista timeframe o provider vuota → skip silenzioso."""
        mocks = _patch_scan_deps(timeframes="")

        with (
            patch("app.services.auto_execute_service.settings", mocks["settings"]),
            patch("app.services.auto_execute_service.list_opportunities", mocks["list_opportunities"]),
            patch("app.services.auto_execute_service.AsyncSessionLocal"),
        ):
            await run_auto_execute_scan()

        mocks["list_opportunities"].assert_not_called()


# ── Test maybe_ibkr_auto_execute_after_pipeline ───────────────────────────────

class TestMaybeIbkrAutoExecuteAfterPipeline:

    def _make_body(self, provider="yahoo_finance", symbol="AAPL", timeframe="1h", exchange="SMART"):
        body = MagicMock()
        body.provider = provider
        body.symbol = symbol
        body.timeframe = timeframe
        body.exchange = exchange
        return body

    async def test_provider_not_in_list_returns_immediately(self):
        """Provider non abilitato → non chiama list_opportunities."""
        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance"],
            auto_execute_timeframes_list=["1h"],
        )
        mock_list_opps = AsyncMock(return_value=[])

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", mock_list_opps),
        ):
            await maybe_ibkr_auto_execute_after_pipeline(
                MagicMock(), self._make_body(provider="binance")
            )

        mock_list_opps.assert_not_called()

    async def test_timeframe_not_in_list_returns_immediately(self):
        """Timeframe non abilitato (5m) → non chiama list_opportunities."""
        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance"],
            auto_execute_timeframes_list=["1h"],
        )
        mock_list_opps = AsyncMock(return_value=[])

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", mock_list_opps),
        ):
            await maybe_ibkr_auto_execute_after_pipeline(
                MagicMock(), self._make_body(timeframe="5m")
            )

        mock_list_opps.assert_not_called()

    async def test_hook_executes_up_to_cap(self):
        """
        7 segnali execute validi → esegue al massimo MAX_ORDERS_PER_HOOK_INVOCATION.
        """
        n_opps = MAX_ORDERS_PER_HOOK_INVOCATION + 2
        opps = [_make_opp() for _ in range(n_opps)]
        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance"],
            auto_execute_timeframes_list=["1h"],
        )
        mock_execute = AsyncMock(return_value=True)

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", AsyncMock(return_value=opps)),
            patch("app.services.auto_execute_service._execute_and_save", mock_execute),
        ):
            await maybe_ibkr_auto_execute_after_pipeline(
                MagicMock(), self._make_body()
            )

        assert mock_execute.call_count == MAX_ORDERS_PER_HOOK_INVOCATION

    async def test_hook_executes_all_when_within_cap(self):
        """3 segnali validi con cap=5 → tutti e 3 vengono inviati (no break prematuro)."""
        opps = [_make_opp() for _ in range(3)]
        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance"],
            auto_execute_timeframes_list=["1h"],
        )
        mock_execute = AsyncMock(return_value=True)

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", AsyncMock(return_value=opps)),
            patch("app.services.auto_execute_service._execute_and_save", mock_execute),
        ):
            await maybe_ibkr_auto_execute_after_pipeline(
                MagicMock(), self._make_body()
            )

        # Tutti e 3 devono essere processati — nessun break prematuro al primo
        assert mock_execute.call_count == 3

    async def test_hook_skips_non_execute_opps(self):
        """Segnali con operational_decision != 'execute' vengono ignorati."""
        opps = [
            _make_opp(decision="monitor"),
            _make_opp(decision="execute"),
            _make_opp(decision="discard"),
            _make_opp(decision="execute"),
        ]
        mock_settings = MagicMock(
            tws_enabled=True,
            ibkr_auto_execute=True,
            auto_execute_providers_list=["yahoo_finance"],
            auto_execute_timeframes_list=["1h"],
        )
        mock_execute = AsyncMock(return_value=True)

        with (
            patch("app.services.auto_execute_service.settings", mock_settings),
            patch("app.services.auto_execute_service.list_opportunities", AsyncMock(return_value=opps)),
            patch("app.services.auto_execute_service._execute_and_save", mock_execute),
        ):
            await maybe_ibkr_auto_execute_after_pipeline(
                MagicMock(), self._make_body()
            )

        # Solo i 2 con decision="execute"
        assert mock_execute.call_count == 2
