"""
Monitoring endpoints: slippage backtest-vs-live, fill parziali e statistiche esecuzione.

Aggrega:
  /slippage-stats       : realized_R vs nominal_R (−1R) sulle chiusure da stop loss
  /fill-stats           : fill completi vs parziali vs rejected
  /execution-stats      : tasso di successo/fallimento dei tentativi di invio ordine a TWS
  /auto-execute-config  : configurazione corrente del motore di auto-esecuzione (read-only)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.core.trade_plan_variant_constants import _SLIPPAGE_R_THRESHOLD
from app.models.executed_signal import ExecutedSignal

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/slippage-stats")
async def slippage_stats(
    days: int = Query(30, ge=1, le=365, description="Finestra temporale in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Statistiche di slippage sui trade chiusi da stop loss.

    Confronta il realized_R (fill IBKR reale) con il nominal_R (−1R assunto
    dal backtester). Permette di misurare il disallineamento causato da gap
    overnight avversi.

    Restituisce:
    - total_stops: trade chiusi da stop nel periodo
    - stops_with_significant_slippage: realized_R < −1.10
    - overnight_gap_stops: close_cause = "overnight_gap"
    - overnight_gap_pct: percentuale sul totale degli stop
    - avg_realized_r: media del realized_R dai fill reali
    - avg_nominal_r: −1.0 (assunzione del backtester)
    - avg_r_degradation: avg_realized_r − avg_nominal_r (negativo = peggio del backtest)
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    q = (
        select(ExecutedSignal)
        .where(
            ExecutedSignal.close_outcome == "stop",
            ExecutedSignal.closed_at.is_not(None),
            ExecutedSignal.closed_at >= since,
        )
    )
    rows = (await session.execute(q)).scalars().all()

    total_stops = len(rows)

    if total_stops == 0:
        return {
            "period_days": days,
            "since": since.isoformat(),
            "total_stops": 0,
            "stops_with_significant_slippage": 0,
            "overnight_gap_stops": 0,
            "overnight_gap_pct": None,
            "avg_realized_r": None,
            "avg_nominal_r": -1.0,
            "avg_r_degradation": None,
            "note": "Nessun trade chiuso da stop nel periodo. poll_and_record_stop_fills() "
                    "inizia a popolare questi dati alla prima chiusura registrata via TWS.",
        }

    stops_with_slippage = sum(
        1 for r in rows if r.realized_r is not None and r.realized_r < _SLIPPAGE_R_THRESHOLD
    )
    overnight_gaps = sum(1 for r in rows if r.close_cause == "overnight_gap")
    realized_rs = [r.realized_r for r in rows if r.realized_r is not None]

    avg_realized_r = round(sum(realized_rs) / len(realized_rs), 4) if realized_rs else None
    avg_nominal_r = -1.0
    avg_r_degradation = (
        round(avg_realized_r - avg_nominal_r, 4) if avg_realized_r is not None else None
    )

    # Distribuzione per causa di chiusura
    cause_breakdown: dict[str, int] = {}
    for r in rows:
        cause = r.close_cause or "unknown"
        cause_breakdown[cause] = cause_breakdown.get(cause, 0) + 1

    return {
        "period_days": days,
        "since": since.isoformat(),
        "total_stops": total_stops,
        "stops_with_significant_slippage": stops_with_slippage,
        "overnight_gap_stops": overnight_gaps,
        "overnight_gap_pct": round(overnight_gaps / total_stops * 100, 1),
        "avg_realized_r": avg_realized_r,
        "avg_nominal_r": avg_nominal_r,
        "avg_r_degradation": avg_r_degradation,
        "cause_breakdown": cause_breakdown,
    }


@router.get("/fill-stats")
async def fill_stats(
    days: int = Query(30, ge=1, le=365, description="Finestra temporale in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Statistiche sui fill dei bracket order inviati al broker.

    Confronta fill completi, parziali e rejected per misurare la frequenza
    reale di fill parziali e identificare simboli con bassa liquidità.

    Restituisce:
    - total_orders: ordini bracket inviati nel periodo
    - full_fills: fill completati al 100%
    - partial_fills: fill parziali (filled < ordered)
    - partial_fill_pct: % parziali sul totale con fill noto
    - low_ratio_fills: fill parziali chiusi immediatamente (ratio < MIN_FILL_RATIO)
    - rejected: ordini cancelled/rejected senza fill
    - pending: ordini senza dati fill ancora (fill_qty IS NULL)
    - avg_fill_ratio: fill ratio medio sui parziali
    - symbols_with_most_partials: top 5 simboli per frequenza fill parziali
    """
    from app.core.trade_plan_variant_constants import MIN_FILL_RATIO  # noqa: PLC0415

    since = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(ExecutedSignal).where(ExecutedSignal.executed_at >= since)
    rows = (await session.execute(q)).scalars().all()

    total_orders = len(rows)
    if total_orders == 0:
        return {
            "period_days": days,
            "since": since.isoformat(),
            "total_orders": 0,
            "note": "Nessun ordine bracket nel periodo. I dati vengono popolati "
                    "da _handle_partial_fill_after_bracket() in auto_execute_service.",
        }

    full_fills = sum(
        1 for r in rows
        if r.filled_qty is not None and r.ordered_qty is not None
        and float(r.filled_qty) >= float(r.ordered_qty) * 0.999
        and not r.partial_fill
    )
    partial_fills = sum(1 for r in rows if r.partial_fill)
    rejected = sum(
        1 for r in rows
        if (r.tws_status or "").startswith("rejected")
    )
    low_ratio_fills = sum(
        1 for r in rows
        if r.partial_fill
        and r.filled_qty is not None
        and r.ordered_qty is not None
        and float(r.ordered_qty) > 0
        and float(r.filled_qty) / float(r.ordered_qty) < MIN_FILL_RATIO
    )
    pending = sum(1 for r in rows if r.filled_qty is None and r.ordered_qty is None)

    # Fill ratio medio sui parziali
    partial_ratios = [
        float(r.filled_qty) / float(r.ordered_qty)
        for r in rows
        if r.partial_fill and r.filled_qty is not None and r.ordered_qty is not None
        and float(r.ordered_qty) > 0
    ]
    avg_fill_ratio = round(sum(partial_ratios) / len(partial_ratios), 4) if partial_ratios else None

    fills_with_data = full_fills + partial_fills
    partial_fill_pct = (
        round(partial_fills / fills_with_data * 100, 1) if fills_with_data > 0 else None
    )

    # Top 5 simboli con più fill parziali
    symbol_partials: dict[str, int] = {}
    for r in rows:
        if r.partial_fill:
            symbol_partials[r.symbol] = symbol_partials.get(r.symbol, 0) + 1
    top_symbols = sorted(symbol_partials.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "period_days": days,
        "since": since.isoformat(),
        "total_orders": total_orders,
        "full_fills": full_fills,
        "partial_fills": partial_fills,
        "partial_fill_pct": partial_fill_pct,
        "low_ratio_fills": low_ratio_fills,
        "rejected": rejected,
        "pending": pending,
        "avg_fill_ratio_on_partials": avg_fill_ratio,
        "min_fill_ratio_threshold": MIN_FILL_RATIO,
        "symbols_with_most_partials": [
            {"symbol": s, "count": c} for s, c in top_symbols
        ],
    }


@router.get("/execution-stats")
async def execution_stats(
    days: int = Query(30, ge=1, le=365, description="Finestra temporale in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Statistiche di successo/fallimento dei tentativi di invio ordine a TWS.

    Aggrega tutti i record ExecutedSignal per tws_status, distinguendo:
    - Ordini effettivamente inviati e confermati da TWS (submitted, filled)
    - Ordini falliti per vari motivi (rejected, tws_unavailable, exception, no_order_id)
    - Ordini saltati dai guard rails prima dell'invio (skipped)

    Monitorare che `success_rate_pct` resti sopra il 95% in paper trading.
    Valori inferiori indicano problemi sistematici di connessione TWS o configurazione.

    Restituisce:
    - total_attempts: tutti i record nel periodo (inclusi falliti e skipped)
    - successfully_submitted: ordini con tws_status submitted o filled
    - failed_attempts: ordini falliti per errore TWS (rejected, unavailable, exception)
    - skipped_attempts: ordini bloccati dai guard rails (skipped)
    - success_rate_pct: submitted / (submitted + failed) — esclude skipped
    - breakdown_by_status: conteggio per ogni valore di tws_status
    - breakdown_by_symbol: top 10 simboli per numero di tentativi falliti
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(ExecutedSignal).where(ExecutedSignal.executed_at >= since)
    rows = (await session.execute(q)).scalars().all()

    total_attempts = len(rows)
    if total_attempts == 0:
        return {
            "period_days": days,
            "since": since.isoformat(),
            "total_attempts": 0,
            "note": "Nessun tentativo di esecuzione nel periodo.",
        }

    by_status: dict[str, int] = {}
    for r in rows:
        status = r.tws_status or "unknown"
        by_status[status] = by_status.get(status, 0) + 1

    _SUBMITTED_STATUSES = {"submitted", "filled", "PreSubmitted", "Submitted", "Filled"}
    _FAILED_STATUSES = {"rejected", "tws_unavailable", "exception", "no_order_id"}
    _SKIPPED_STATUSES = {"skipped", "error"}

    submitted = sum(by_status.get(s, 0) for s in _SUBMITTED_STATUSES)
    failed = sum(by_status.get(s, 0) for s in _FAILED_STATUSES)
    skipped = sum(by_status.get(s, 0) for s in _SKIPPED_STATUSES)

    actionable = submitted + failed
    success_rate_pct = round(submitted / actionable * 100, 2) if actionable > 0 else None

    # Top 10 simboli con più fallimenti
    symbol_failures: dict[str, int] = {}
    for r in rows:
        if (r.tws_status or "") in _FAILED_STATUSES:
            symbol_failures[r.symbol] = symbol_failures.get(r.symbol, 0) + 1
    top_failures = sorted(symbol_failures.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "period_days": days,
        "since": since.isoformat(),
        "total_attempts": total_attempts,
        "successfully_submitted": submitted,
        "failed_attempts": failed,
        "skipped_attempts": skipped,
        "success_rate_pct": success_rate_pct,
        "breakdown_by_status": dict(sorted(by_status.items(), key=lambda x: x[1], reverse=True)),
        "symbols_with_most_failures": [
            {"symbol": s, "count": c} for s, c in top_failures
        ],
        "note": (
            "success_rate_pct = submitted / (submitted + failed). "
            "I record 'skipped' sono esclusi dal calcolo (ordini bloccati dai guard rails, "
            "non errori di connessione). Valori < 95% indicano problemi sistematici TWS."
        ),
    }


@router.get("/auto-execute-config")
async def auto_execute_config() -> dict:
    """
    Configurazione corrente del motore di auto-esecuzione ordini (read-only).

    Mostra:
    - Timeframe abilitati per lo scan globale e per l'hook per-simbolo
    - Provider abilitati
    - Safety caps attivi
    - Flag di sistema (tws_enabled, ibkr_auto_execute, ibkr_paper_trading)

    Per modificare la configurazione, aggiornare le variabili d'ambiente e
    riavviare il backend (le settings sono caricate all'avvio da pydantic-settings).

    Note operative:
    - 5m è escluso di default: nessun dataset OOS disponibile per validazione.
      Aggiungere 'AUTO_EXECUTE_TIMEFRAMES_ENABLED=1h,5m' nel .env solo dopo aver
      costruito e validato un dataset 5m con metriche WR e avg_R misurate.
    - binance è incluso di default ma eseguirà ordini solo se tws_enabled=true
      e ibkr_auto_execute=true.
    """
    from app.services.auto_execute_service import (  # noqa: PLC0415
        MAX_ORDERS_PER_HOOK_INVOCATION,
        MAX_ORDERS_PER_SCAN,
    )

    return {
        "auto_execute_enabled": (
            getattr(settings, "tws_enabled", False) and settings.ibkr_auto_execute
        ),
        "tws_enabled": getattr(settings, "tws_enabled", False),
        "ibkr_auto_execute": settings.ibkr_auto_execute,
        "ibkr_paper_trading": settings.ibkr_paper_trading,
        "timeframes_enabled": settings.auto_execute_timeframes_list,
        "providers_enabled": settings.auto_execute_providers_list,
        "max_orders_per_scan": MAX_ORDERS_PER_SCAN,
        "max_orders_per_hook_invocation": MAX_ORDERS_PER_HOOK_INVOCATION,
        "ibkr_max_simultaneous_positions": settings.ibkr_max_simultaneous_positions,
        "note": (
            "Configurazione read-only. Modificare via env var + restart per applicare. "
            "5m escluso di default (AUTO_EXECUTE_TIMEFRAMES_ENABLED=1h): "
            "nessun validation set OOS disponibile."
        ),
    }
