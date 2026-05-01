"""
Performance KPIs — aggregati da executed_signals.

Endpoints:
  GET /api/v1/performance/kpis          — metriche aggregate (home dashboard)
  GET /api/v1/performance/live-monitor  — monitor completo con equity curve e alert
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session

router = APIRouter(prefix="/performance", tags=["performance"])

# Outcomes che contano come WIN
_WIN_OUTCOMES = {"tp1", "tp2", "tp"}
# Outcomes da escludere dalle metriche (dati non affidabili)
_SKIP_OUTCOMES = {"stale_lost", "stale"}
# Outcomes validi (hanno realized_r)
_VALID_OUTCOMES = {"stop", "tp1", "tp2", "tp", "eod", "timeout"}

# Valori attesi dal backtest (Config TRIPLO, OOS 2022–2026)
_BACKTEST_EXPECTED = {
    "1h": {"avg_r": 0.975, "win_rate_pct": 69.0},
    "5m": {"avg_r": 0.705, "win_rate_pct": 55.0},
    "all": {"avg_r": 0.840, "win_rate_pct": 62.0},
}

# Soglie alert
_ALERT_MIN_TRADES_WEAK   = 30
_ALERT_MIN_TRADES_FULL   = 50
_ALERT_AVG_R_WEAK        = 0.10
_ALERT_WR_MIN_PCT        = 35.0
_ALERT_STREAK_LOSS       = 8


def _risk_eur(entry: float, stop: float, qty: float | None) -> float:
    if not qty or qty <= 0:
        return 0.0
    return abs(entry - stop) * qty


def _compute_stats(trades: list[dict]) -> dict:
    """Calcola stats aggregate su una lista di trade chiuse valide."""
    valid = [t for t in trades if t.get("realized_r") is not None
             and t.get("close_outcome") not in _SKIP_OUTCOMES]
    if not valid:
        return {"n": 0, "avg_r": None, "total_r": None, "win_rate_pct": None,
                "max_dd_r": None, "best_r": None, "worst_r": None}

    rs = [float(t["realized_r"]) for t in valid]
    wins = [r for r in rs if r > 0]
    total_r = sum(rs)
    avg_r = total_r / len(rs)

    # Max drawdown in R
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)

    return {
        "n": len(valid),
        "avg_r": round(avg_r, 4),
        "total_r": round(total_r, 4),
        "win_rate_pct": round(len(wins) / len(valid) * 100, 1),
        "max_dd_r": round(max_dd, 4),
        "best_r": round(max(rs), 4),
        "worst_r": round(min(rs), 4),
    }


def _max_consecutive_losses(rs: list[float]) -> int:
    max_streak = cur = 0
    for r in rs:
        if r <= 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return max_streak


def _current_loss_streak(rs: list[float]) -> int:
    streak = 0
    for r in reversed(rs):
        if r <= 0:
            streak += 1
        else:
            break
    return streak


@router.get("/kpis")
async def performance_kpis(
    days: int = Query(30, ge=1, le=365, description="Finestra temporale in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    KPI aggregate per la home dashboard.
    Calcola: P&L oggi, win rate, drawdown corrente, posizioni aperte.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await session.execute(text("""
        SELECT id, symbol, timeframe, direction, tws_status, close_outcome,
               realized_r, entry_price, stop_price, quantity_tp1,
               executed_at, closed_at
        FROM executed_signals
        WHERE executed_at >= :since
        ORDER BY executed_at
    """), {"since": since})
    rows = result.mappings().all()

    if not rows:
        return {
            "pnl_today_eur": None,
            "win_rate_pct": None,
            "drawdown_current_pct": None,
            "open_positions": 0,
            "total_trades": 0,
            "closed_trades": 0,
            "note": "Nessun trade nel periodo.",
        }

    # Posizioni aperte (tws_status lowercase nel DB)
    open_positions = sum(
        1 for r in rows
        if r["tws_status"] in ("submitted", "partial_fill_resized", "filled")
        and r["closed_at"] is None
        and r["close_outcome"] not in _SKIP_OUTCOMES
    )

    # Trade chiuse valide
    closed = [
        r for r in rows
        if r["closed_at"] is not None
        and r["close_outcome"] not in _SKIP_OUTCOMES
        and r["realized_r"] is not None
    ]

    # Win rate
    wins = [r for r in closed if float(r["realized_r"]) > 0]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else None

    # P&L oggi in EUR
    closed_today = [r for r in closed if r["closed_at"] >= today_start]
    pnl_today: float | None = None
    if closed_today:
        pnl_today = round(sum(
            float(r["realized_r"]) * _risk_eur(
                float(r["entry_price"]), float(r["stop_price"]), r["quantity_tp1"]
            )
            for r in closed_today
        ), 2)

    # Max drawdown % sulla equity cumulativa EUR
    drawdown_pct: float | None = None
    if len(closed) >= 2:
        equity = peak = max_dd = 0.0
        for r in closed:
            pnl = float(r["realized_r"]) * _risk_eur(
                float(r["entry_price"]), float(r["stop_price"]), r["quantity_tp1"]
            )
            equity += pnl
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        drawdown_pct = round(max_dd, 2)

    # Avg R totale
    rs = [float(r["realized_r"]) for r in closed]
    avg_r = round(sum(rs) / len(rs), 4) if rs else None

    return {
        "pnl_today_eur": pnl_today,
        "win_rate_pct": win_rate,
        "avg_r": avg_r,
        "total_r": round(sum(rs), 4) if rs else None,
        "drawdown_current_pct": drawdown_pct,
        "open_positions": open_positions,
        "total_trades": len([r for r in rows if r["close_outcome"] not in _SKIP_OUTCOMES]),
        "closed_trades": len(closed),
        "note": (
            f"Win rate su {len(closed)} trade chiuse. "
            f"P&L calcolato su {len(closed_today)} trade di oggi."
        ),
    }


@router.get("/live-monitor")
async def performance_live_monitor(
    days: int = Query(90, ge=1, le=730, description="Finestra storica in giorni"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Monitor completo con equity curve, per-timeframe stats, alert, e confronto backtest.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    # ── Query principale ───────────────────────────────────────────────────────
    result = await session.execute(text("""
        SELECT id, symbol, timeframe, direction, pattern_name,
               tws_status, close_outcome, close_cause,
               realized_r, entry_price, stop_price, take_profit_1,
               quantity_tp1, close_fill_price,
               executed_at, closed_at,
               sl_order_id, tp_order_id
        FROM executed_signals
        WHERE executed_at >= :since
          AND close_outcome NOT IN ('stale_lost', 'stale')
        ORDER BY COALESCE(closed_at, executed_at)
    """), {"since": since})
    rows = result.mappings().all()

    # Partizioni
    closed_all = [r for r in rows
                  if r["closed_at"] is not None and r["realized_r"] is not None]
    closed_1h = [r for r in closed_all if r["timeframe"] == "1h"]
    closed_5m = [r for r in closed_all if r["timeframe"] == "5m"]
    open_pos   = [r for r in rows
                  if r["closed_at"] is None
                  and r["tws_status"] in ("submitted", "partial_fill_resized", "filled")]

    today_closed = [r for r in closed_all if r["closed_at"] >= today_start]
    week_closed  = [r for r in closed_all if r["closed_at"] >= week_start]

    # ── Stats aggregate ────────────────────────────────────────────────────────
    stats_all = _compute_stats([dict(r) for r in closed_all])
    stats_1h  = _compute_stats([dict(r) for r in closed_1h])
    stats_5m  = _compute_stats([dict(r) for r in closed_5m])

    # ── Equity curve ─────────────────────────────────────────────────────────
    equity_curve = []
    cum_r = 0.0
    for r in closed_all:
        rr = float(r["realized_r"])
        cum_r += rr
        equity_curve.append({
            "trade_n": len(equity_curve) + 1,
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "realized_r": round(rr, 4),
            "cum_r": round(cum_r, 4),
            "outcome": r["close_outcome"],
            "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
        })

    # ── Streak ──────────────────────────────────────────────────────────────
    rs_all = [float(r["realized_r"]) for r in closed_all]
    max_loss_streak = _max_consecutive_losses(rs_all)
    cur_loss_streak = _current_loss_streak(rs_all)

    # ── Alert ───────────────────────────────────────────────────────────────
    alerts: list[dict] = []
    n = stats_all["n"] or 0
    avg_r_val = stats_all["avg_r"]
    wr_val = stats_all["win_rate_pct"]

    if n >= _ALERT_MIN_TRADES_WEAK and avg_r_val is not None and avg_r_val < _ALERT_AVG_R_WEAK:
        severity = "critical" if (n >= _ALERT_MIN_TRADES_FULL and avg_r_val <= 0) else "warning"
        alerts.append({
            "severity": severity,
            "code": "AVG_R_WEAK" if severity == "warning" else "AVG_R_NEGATIVE",
            "message": (
                f"avg_R={avg_r_val:+.3f}R dopo {n} trade — "
                + ("edge assente, valutare stop" if severity == "critical"
                   else "edge debole, monitorare")
            ),
        })

    if n >= _ALERT_MIN_TRADES_FULL and wr_val is not None and wr_val < _ALERT_WR_MIN_PCT:
        alerts.append({
            "severity": "warning",
            "code": "WIN_RATE_LOW",
            "message": f"WR={wr_val:.1f}% sotto soglia {_ALERT_WR_MIN_PCT:.0f}% dopo {n} trade",
        })

    if cur_loss_streak >= _ALERT_STREAK_LOSS:
        alerts.append({
            "severity": "warning",
            "code": "LOSS_STREAK",
            "message": f"{cur_loss_streak} loss consecutive in corso (max storico: {max_loss_streak})",
        })

    # ── Daily breakdown (ultimi 14 giorni) ─────────────────────────────────
    daily: dict[str, dict] = {}
    for r in closed_all:
        if r["closed_at"] is None:
            continue
        day = r["closed_at"].astimezone(timezone.utc).date().isoformat()
        if day not in daily:
            daily[day] = {"n": 0, "wins": 0, "total_r": 0.0}
        rr = float(r["realized_r"])
        daily[day]["n"] += 1
        daily[day]["wins"] += 1 if rr > 0 else 0
        daily[day]["total_r"] = round(daily[day]["total_r"] + rr, 4)

    daily_list = sorted(
        [{"date": d, **v, "wr_pct": round(v["wins"] / v["n"] * 100, 1) if v["n"] else 0}
         for d, v in daily.items()],
        key=lambda x: x["date"],
        reverse=True,
    )[:14]

    # ── Posizioni aperte dettaglio ─────────────────────────────────────────
    open_details = []
    for r in open_pos:
        entry = float(r["entry_price"])
        stop  = float(r["stop_price"])
        risk  = abs(entry - stop)
        is_long = (r["direction"] or "").lower() == "bullish"
        open_details.append({
            "id": r["id"],
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "direction": r["direction"],
            "pattern_name": r["pattern_name"],
            "entry_price": entry,
            "stop_price": stop,
            "take_profit_1": float(r["take_profit_1"]) if r["take_profit_1"] else None,
            "trail_step1_at": round(entry + 0.50 * risk if is_long else entry - 0.50 * risk, 4),
            "trail_step2_at": round(entry + 1.00 * risk if is_long else entry - 1.00 * risk, 4),
            "sl_order_id": r["sl_order_id"],
            "tp_order_id": r["tp_order_id"],
            "tws_status": r["tws_status"],
            "executed_at": r["executed_at"].isoformat() if r["executed_at"] else None,
        })

    # ── Confronto backtest ─────────────────────────────────────────────────
    def _vs_backtest(tf: str, stats: dict) -> dict | None:
        exp = _BACKTEST_EXPECTED.get(tf)
        if not exp or stats["n"] == 0:
            return None
        avg_r = stats["avg_r"]
        wr = stats["win_rate_pct"]
        return {
            "expected_avg_r": exp["avg_r"],
            "actual_avg_r": avg_r,
            "delta_avg_r": round(avg_r - exp["avg_r"], 4) if avg_r is not None else None,
            "expected_wr_pct": exp["win_rate_pct"],
            "actual_wr_pct": wr,
            "delta_wr_pct": round(wr - exp["win_rate_pct"], 1) if wr is not None else None,
            "sample_note": f"{stats['n']} trade (campione {'sufficiente' if stats['n'] >= 30 else 'ridotto'})",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "open_positions": open_details,
        "slot_usage": {
            "total": len(open_pos),
            "max": 5,
            "n_1h": sum(1 for r in open_pos if r["timeframe"] == "1h"),
            "n_5m": sum(1 for r in open_pos if r["timeframe"] == "5m"),
            "slots_1h_max": 3,
            "slots_5m_max": 2,
        },
        "summary": {
            "all": stats_all,
            "1h": stats_1h,
            "5m": stats_5m,
            "today": _compute_stats([dict(r) for r in today_closed]),
            "last_7d": _compute_stats([dict(r) for r in week_closed]),
        },
        "vs_backtest": {
            "all": _vs_backtest("all", stats_all),
            "1h":  _vs_backtest("1h",  stats_1h),
            "5m":  _vs_backtest("5m",  stats_5m),
        },
        "streak": {
            "current_loss_streak": cur_loss_streak,
            "max_loss_streak_historical": max_loss_streak,
        },
        "alerts": alerts,
        "daily_breakdown": daily_list,
        "equity_curve": equity_curve,
        "outcome_distribution": {
            outcome: sum(1 for r in closed_all if r["close_outcome"] == outcome)
            for outcome in {r["close_outcome"] for r in closed_all if r["close_outcome"]}
        },
    }
