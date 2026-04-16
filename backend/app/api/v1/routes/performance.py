"""
Performance KPIs — aggregati da executed_signals.

Endpoint: GET /api/v1/performance/kpis

Metriche:
  pnl_today_eur        — P&L realizzato oggi (sum realized_r × risk_per_trade_eur)
  win_rate_30d_pct     — % trade chiuse in profitto negli ultimi 30 gg
  drawdown_current_pct — max drawdown dal peak della curva equity recente
  open_positions       — trade con tws_status=Filled e non ancora chiuse
  total_trades_30d     — trade totali (chiuse + aperte) negli ultimi 30 gg
  closed_trades_30d    — solo trade chiuse negli ultimi 30 gg
  note                 — info su limitazioni del calcolo
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.executed_signal import ExecutedSignal

router = APIRouter(prefix="/performance", tags=["performance"])


def _risk_eur(sig: ExecutedSignal) -> float:
    """
    Rischio monetario per trade = (entry - stop) × qty_tp1.
    Usato per convertire realized_r → EUR.
    Ritorna 0 se i dati mancano.
    """
    try:
        entry = float(sig.entry_price)
        stop  = float(sig.stop_price)
        qty   = float(sig.quantity_tp1 or 0)
        risk  = abs(entry - stop) * qty
        return risk if risk > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


@router.get("/kpis")
async def performance_kpis(
    days: int = Query(30, ge=1, le=365, description="Finestra temporale in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    KPI di performance aggregati dalle trade registrate in executed_signals.

    Calcoli client-derivabili con i dati disponibili:
    - P&L oggi: sum(realized_r × risk_eur) sui trade chiusi oggi
    - Win rate: (trade chiuse con close_outcome tp1/tp2) / (trade chiuse totali) × 100
    - Drawdown: max drawdown percentuale sulla curva equity cumulativa
    - Posizioni aperte: count(tws_status='Filled' AND closed_at IS NULL)

    Limitazione: realized_r è popolato solo dopo la chiusura (pollata da TWS).
    Trade ancora aperte non contribuiscono al P&L realizzato.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    q = select(ExecutedSignal).where(ExecutedSignal.executed_at >= since)
    rows = (await session.execute(q)).scalars().all()

    if not rows:
        return {
            "pnl_today_eur": None,
            "win_rate_30d_pct": None,
            "drawdown_current_pct": None,
            "open_positions": 0,
            "total_trades_30d": 0,
            "closed_trades_30d": 0,
            "note": "Nessun trade nel periodo. I dati vengono popolati dall'auto-execute service.",
        }

    # ── Posizioni aperte ──────────────────────────────────────────────────────
    open_positions = sum(
        1 for r in rows
        if r.tws_status in ("Filled", "PreSubmitted", "Submitted")
        and r.closed_at is None
        and r.close_outcome is None
    )

    # ── Trade chiuse nel periodo ──────────────────────────────────────────────
    closed = [r for r in rows if r.closed_at is not None and r.close_outcome is not None]

    # ── Win rate ──────────────────────────────────────────────────────────────
    wins = [r for r in closed if r.close_outcome in ("tp1", "tp2", "timeout") and (r.realized_r or 0) > 0]
    win_rate_30d = round(len(wins) / len(closed) * 100, 1) if closed else None

    # ── P&L oggi realizzato ───────────────────────────────────────────────────
    closed_today = [
        r for r in closed
        if r.closed_at is not None and r.closed_at >= today_start
    ]
    pnl_today: float | None = None
    if closed_today:
        pnl_today = sum(
            (r.realized_r or 0) * _risk_eur(r)
            for r in closed_today
        )
        pnl_today = round(pnl_today, 2)

    # ── Drawdown corrente (equity cumulativa) ──────────────────────────────────
    # Ordina i trade chiusi per closed_at e costruisce equity cumulativa
    drawdown_pct: float | None = None
    sorted_closed = sorted(closed, key=lambda r: r.closed_at)  # type: ignore[arg-type]
    if len(sorted_closed) >= 2:
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in sorted_closed:
            pnl = (r.realized_r or 0) * _risk_eur(r)
            equity += pnl
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        drawdown_pct = round(max_dd, 2) if max_dd > 0 else 0.0

    return {
        "pnl_today_eur": pnl_today,
        "win_rate_30d_pct": win_rate_30d,
        "drawdown_current_pct": drawdown_pct,
        "open_positions": open_positions,
        "total_trades_30d": len(rows),
        "closed_trades_30d": len(closed),
        "note": (
            f"P&L calcolato su {len(closed_today)} trade chiuse oggi. "
            f"Win rate su {len(closed)} trade chiuse negli ultimi {days}gg. "
            "realized_r disponibile solo dopo chiusura registrata da TWS poll."
        ) if rows else None,
    }
