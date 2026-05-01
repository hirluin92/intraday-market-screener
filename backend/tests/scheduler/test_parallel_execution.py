"""
Test che verifica la parallelizzazione di _prewarm_opportunities_cache
e run_auto_execute_scan nel pipeline scheduler.

Copre:
  1. Le due funzioni girano in parallelo (wall time ≈ max, non somma)
  2. Un'eccezione in prewarm non blocca auto_execute (e viceversa)
  3. Un'eccezione in auto_execute viene loggata ma non propaga
  4. L'ordine sequenziale rispetto a poll_and_record_stop_fills è conservato
     (poll deve girare DOPO il gather, non in parallelo)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Importiamo la funzione da testare
from app.scheduler.pipeline_scheduler import _run_scheduled_pipeline_cycle


# ── Helper: sostituisce il ciclo pipeline principale con un no-op ──────────────

def _patch_pipeline_cycle(
    *,
    prewarm_sleep: float = 0.0,
    autoexec_sleep: float = 0.0,
    prewarm_raises: Exception | None = None,
    autoexec_raises: Exception | None = None,
    stop_fills_sleep: float = 0.0,
):
    """
    Patcha tutte le dipendenze di _run_scheduled_pipeline_cycle:
      - _resolve_scheduler_jobs → lista vuota (nessun job da eseguire)
      - _prewarm_opportunities_cache → sleep configurabile
      - run_auto_execute_scan → sleep configurabile
      - poll_and_record_stop_fills → sleep configurabile
    Ritorna i mock per ispezione.
    """
    async def _fake_prewarm():
        if prewarm_raises:
            raise prewarm_raises
        await asyncio.sleep(prewarm_sleep)

    async def _fake_autoexec():
        if autoexec_raises:
            raise autoexec_raises
        await asyncio.sleep(autoexec_sleep)

    async def _fake_stop_fills(_session):
        await asyncio.sleep(stop_fills_sleep)

    mocks = {
        "prewarm": AsyncMock(side_effect=_fake_prewarm),
        "autoexec": AsyncMock(side_effect=_fake_autoexec),
        "stop_fills": AsyncMock(side_effect=_fake_stop_fills),
    }
    return mocks


# ── Test di parallelismo ───────────────────────────────────────────────────────

class TestParallelPrewarmAutoExecute:

    async def test_parallel_execution_is_faster_than_sequential(self):
        """
        Prewarm: 0.3s, auto_execute: 0.3s.
        In parallelo: ~0.3s. In sequenziale: ~0.6s.
        Il test verifica che il tempo totale sia < 0.5s (parallelismo confermato).
        """
        SLEEP = 0.3
        started = {}

        async def _fake_prewarm():
            started["prewarm"] = time.monotonic()
            await asyncio.sleep(SLEEP)

        async def _fake_autoexec():
            started["autoexec"] = time.monotonic()
            await asyncio.sleep(SLEEP)

        mock_settings = MagicMock(
            pipeline_scheduler_source="explicit",
            tws_enabled=False,  # auto_execute sarà no-op, ma usiamo il wrapper
            ibkr_auto_execute=False,
        )

        with (
            patch("app.scheduler.pipeline_scheduler._resolve_scheduler_jobs", return_value=[]),
            patch("app.scheduler.pipeline_scheduler._prewarm_opportunities_cache", _fake_prewarm),
            patch("app.services.auto_execute_service.run_auto_execute_scan", _fake_autoexec),
            patch("app.services.auto_execute_service.poll_and_record_stop_fills", AsyncMock()),
            patch("app.scheduler.pipeline_scheduler.settings", mock_settings),
            patch("app.scheduler.pipeline_scheduler.AsyncSessionLocal"),
        ):
            t0 = time.monotonic()
            await _run_scheduled_pipeline_cycle()
            elapsed = time.monotonic() - t0

        # In parallelo: elapsed ≈ SLEEP (0.3s). In sequenziale: ≈ 2×SLEEP (0.6s).
        # Tolleranza 0.15s per overhead asyncio/test.
        assert elapsed < SLEEP * 1.5 + 0.15, (
            f"Atteso esecuzione parallela (<{SLEEP * 1.5 + 0.15:.2f}s), "
            f"ottenuto {elapsed:.3f}s — le due funzioni potrebbero girare sequenzialmente"
        )
        # Entrambe sono partite (non una sola)
        assert "prewarm" in started, "prewarm non è stata chiamata"
        assert "autoexec" in started, "auto_execute non è stata chiamata"
        # Le due funzioni sono partite quasi simultaneamente (< 0.05s di distanza)
        start_diff = abs(started["prewarm"] - started["autoexec"])
        assert start_diff < 0.05, (
            f"prewarm e auto_execute non sono partite in parallelo "
            f"(distanza start: {start_diff:.3f}s)"
        )

    async def test_prewarm_exception_does_not_block_auto_execute(self):
        """
        Eccezione in prewarm → auto_execute viene comunque chiamata.
        """
        autoexec_called = {"called": False}

        async def _fake_prewarm():
            raise RuntimeError("prewarm fallito (simulato)")

        async def _fake_autoexec():
            autoexec_called["called"] = True

        mock_settings = MagicMock(pipeline_scheduler_source="explicit")

        with (
            patch("app.scheduler.pipeline_scheduler._resolve_scheduler_jobs", return_value=[]),
            patch("app.scheduler.pipeline_scheduler._prewarm_opportunities_cache", _fake_prewarm),
            patch("app.services.auto_execute_service.run_auto_execute_scan", _fake_autoexec),
            patch("app.services.auto_execute_service.poll_and_record_stop_fills", AsyncMock()),
            patch("app.scheduler.pipeline_scheduler.settings", mock_settings),
            patch("app.scheduler.pipeline_scheduler.AsyncSessionLocal"),
        ):
            # Non deve sollevare eccezione (return_exceptions=True nel gather)
            await _run_scheduled_pipeline_cycle()

        assert autoexec_called["called"], "auto_execute non è stata chiamata nonostante prewarm sia fallita"

    async def test_auto_execute_exception_does_not_block_prewarm(self):
        """
        Eccezione in auto_execute → prewarm viene completata e non si propaga.
        """
        prewarm_completed = {"done": False}

        async def _fake_prewarm():
            await asyncio.sleep(0.01)
            prewarm_completed["done"] = True

        async def _fake_autoexec():
            raise RuntimeError("auto_execute fallito (simulato)")

        mock_settings = MagicMock(pipeline_scheduler_source="explicit")

        with (
            patch("app.scheduler.pipeline_scheduler._resolve_scheduler_jobs", return_value=[]),
            patch("app.scheduler.pipeline_scheduler._prewarm_opportunities_cache", _fake_prewarm),
            patch("app.services.auto_execute_service.run_auto_execute_scan", _fake_autoexec),
            patch("app.services.auto_execute_service.poll_and_record_stop_fills", AsyncMock()),
            patch("app.scheduler.pipeline_scheduler.settings", mock_settings),
            patch("app.scheduler.pipeline_scheduler.AsyncSessionLocal"),
        ):
            await _run_scheduled_pipeline_cycle()

        assert prewarm_completed["done"], "prewarm non è stata completata nonostante l'eccezione in auto_execute"

    async def test_poll_stop_fills_runs_after_gather(self):
        """
        poll_and_record_stop_fills deve girare DOPO il gather (non in parallelo).
        Verifica l'ordine: gather completato prima che poll inizi.
        """
        timeline = []

        async def _fake_prewarm():
            await asyncio.sleep(0.02)
            timeline.append("prewarm_end")

        async def _fake_autoexec():
            await asyncio.sleep(0.02)
            timeline.append("autoexec_end")

        async def _fake_stop_fills(_session):
            timeline.append("poll_start")

        mock_settings = MagicMock(pipeline_scheduler_source="explicit")

        with (
            patch("app.scheduler.pipeline_scheduler._resolve_scheduler_jobs", return_value=[]),
            patch("app.scheduler.pipeline_scheduler._prewarm_opportunities_cache", _fake_prewarm),
            patch("app.services.auto_execute_service.run_auto_execute_scan", _fake_autoexec),
            patch("app.services.auto_execute_service.poll_and_record_stop_fills", _fake_stop_fills),
            patch("app.scheduler.pipeline_scheduler.settings", mock_settings),
            patch("app.scheduler.pipeline_scheduler.AsyncSessionLocal"),
        ):
            await _run_scheduled_pipeline_cycle()

        # poll deve iniziare DOPO che prewarm E autoexec sono finiti
        assert "poll_start" in timeline
        poll_idx = timeline.index("poll_start")
        assert "prewarm_end" in timeline
        assert "autoexec_end" in timeline
        prewarm_idx = timeline.index("prewarm_end")
        autoexec_idx = timeline.index("autoexec_end")

        assert poll_idx > prewarm_idx, "poll è partito prima che prewarm finisse"
        assert poll_idx > autoexec_idx, "poll è partito prima che auto_execute finisse"
