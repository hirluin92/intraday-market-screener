"""
Analisi post-trade — autopsia dei trade eseguiti.

Endpoint principale:
  GET  /api/v1/analysis/trade-autopsy/{signal_id}
  GET  /api/v1/analysis/trade-autopsy
  POST /api/v1/analysis/simulate-execute

Restituisce l'immagine completa di un trade per studiare in seguito
perché ha preso lo SL invece del TP:
  - Record ExecutedSignal con i campi di chiusura
  - Snapshot contesto al momento dell'entrata (regime, score, ML, SPY, ...)
  - Snapshot indicatori tecnici all'entrata (RSI, EMA, ATR, VWAP, CVD, ...)
  - Candele dalla finestra pre-entry fino alla chiusura (o alle ultime N barre)

GET /api/v1/analysis/trade-autopsy  — lista riassuntiva di tutti i trade
  con campi chiave + realized_r per filtrare/ordinare fuori dall'app.

POST /api/v1/analysis/simulate-execute  — dry run completo del flusso di esecuzione:
  esegue tutti i controlli reali (TWS connesso?, short ok?, sizing, open positions)
  e restituisce cosa succederebbe, senza inviare ordini.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.candle import Candle
from app.models.executed_signal import ExecutedSignal

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_field(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _sig_to_dict(sig: ExecutedSignal) -> dict[str, Any]:
    """Serializza ExecutedSignal in dizionario leggibile."""
    return {
        "id":               sig.id,
        "symbol":           sig.symbol,
        "timeframe":        sig.timeframe,
        "provider":         sig.provider,
        "exchange":         sig.exchange,
        "direction":        sig.direction,
        "pattern_name":     sig.pattern_name,
        "pattern_strength": sig.pattern_strength,
        "opportunity_score": sig.opportunity_score,
        # Prezzi piano
        "entry_price":      float(sig.entry_price) if sig.entry_price else None,
        "stop_price":       float(sig.stop_price) if sig.stop_price else None,
        "take_profit_1":    float(sig.take_profit_1) if sig.take_profit_1 else None,
        "take_profit_2":    float(sig.take_profit_2) if sig.take_profit_2 else None,
        "quantity_tp1":     sig.quantity_tp1,
        "quantity_tp2":     sig.quantity_tp2,
        # Order tracking
        "entry_order_id":   sig.entry_order_id,
        "tp_order_id":      sig.tp_order_id,
        "tp2_order_id":     sig.tp2_order_id,
        "sl_order_id":      sig.sl_order_id,
        "sl2_order_id":     sig.sl2_order_id,
        "tws_status":       sig.tws_status,
        "error":            sig.error,
        "executed_at":      sig.executed_at.isoformat() if sig.executed_at else None,
        # Chiusura
        "closed_at":        sig.closed_at.isoformat() if sig.closed_at else None,
        "close_fill_price": float(sig.close_fill_price) if sig.close_fill_price else None,
        "realized_r":       sig.realized_r,
        "close_outcome":    sig.close_outcome,
        "close_cause":      sig.close_cause,
        # Fill tracking
        "partial_fill":     sig.partial_fill,
        "filled_qty":       float(sig.filled_qty) if sig.filled_qty else None,
        "ordered_qty":      float(sig.ordered_qty) if sig.ordered_qty else None,
    }


def _candle_to_dict(c: Candle) -> dict[str, Any]:
    return {
        "timestamp": c.timestamp.isoformat() if c.timestamp else None,
        "open":      float(c.open) if c.open else None,
        "high":      float(c.high) if c.high else None,
        "low":       float(c.low) if c.low else None,
        "close":     float(c.close) if c.close else None,
        "volume":    float(c.volume) if c.volume else None,
    }


# ── Endpoint: singola autopsia ────────────────────────────────────────────────

@router.get("/trade-autopsy/{signal_id}")
async def get_trade_autopsy(
    signal_id: int,
    candles_before: int = Query(
        default=30,
        ge=5,
        le=200,
        description="Numero di candele pre-entry da includere per il contesto visivo.",
    ),
    candles_after: int = Query(
        default=20,
        ge=0,
        le=100,
        description=(
            "Numero di candele post-chiusura da includere (utile per vedere cosa è successo dopo). "
            "0 = solo fino alla chiusura."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Autopsia completa di un trade eseguito.

    Restituisce:
    - `signal`: tutti i campi del trade (prezzi, ordini, chiusura, P&L)
    - `entry_context`: snapshot del contesto operativo al momento dell'entrata
      (regime, score, confluence, ML, SPY, spread, rationale, ...)
    - `entry_indicators`: snapshot degli indicatori tecnici all'entrata
      (RSI, EMA, ATR, VWAP, swing, FVG, Order Block, CVD, funding, RS vs SPY, ...)
    - `candles`: candele OHLCV dalla finestra pre-entry fino alla chiusura
      (o fino alle ultime `candles_after` barre dopo la chiusura)
    - `analysis_summary`: riepilogo automatico dei fattori di rischio
    """
    # 1. Carica il record
    sig: ExecutedSignal | None = await session.get(ExecutedSignal, signal_id)
    if sig is None:
        raise HTTPException(status_code=404, detail=f"Trade {signal_id} non trovato")

    # 2. Snapshot contesto e indicatori
    entry_context = _parse_json_field(sig.entry_context_json)
    entry_indicators = _parse_json_field(sig.entry_indicators_json)

    # 3. Finestra candele
    entry_time = sig.executed_at
    if entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=timezone.utc)

    close_time = sig.closed_at
    if close_time is not None and close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)

    # Stima durata barra per calcolare il lookback pre-entry
    _tf_minutes = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
    }
    bar_minutes = _tf_minutes.get(sig.timeframe, 60)
    lookback_start = entry_time - timedelta(minutes=bar_minutes * candles_before)

    # Se il trade non è ancora chiuso, prendi candles_after barre dopo l'entry
    if close_time is None:
        candle_end = entry_time + timedelta(minutes=bar_minutes * (candles_after + 5))
    else:
        candle_end = close_time + timedelta(minutes=bar_minutes * (candles_after + 1))

    candles_stmt = (
        select(Candle)
        .where(
            Candle.symbol == sig.symbol,
            Candle.provider == sig.provider,
            Candle.timeframe == sig.timeframe,
            Candle.timestamp >= lookback_start,
            Candle.timestamp <= candle_end,
        )
        .order_by(Candle.timestamp.asc())
    )
    candle_rows = (await session.execute(candles_stmt)).scalars().all()
    candles = [_candle_to_dict(c) for c in candle_rows]

    # 4. Riepilogo automatico dei fattori di rischio
    analysis_summary = _build_analysis_summary(sig, entry_context, entry_indicators)

    return {
        "signal":            _sig_to_dict(sig),
        "entry_context":     entry_context,
        "entry_indicators":  entry_indicators,
        "candles":           candles,
        "candles_count":     len(candles),
        "analysis_summary":  analysis_summary,
    }


def _build_analysis_summary(
    sig: ExecutedSignal,
    ctx: dict[str, Any] | None,
    ind: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Genera un riepilogo testuale/strutturato dei fattori di rischio rilevanti.

    Utile come punto di partenza per l'analisi: identifica automaticamente
    le condizioni potenzialmente sfavorevoli al momento dell'entrata.
    """
    flags: list[str] = []
    metrics: dict[str, Any] = {}

    if ctx:
        # Regime di mercato
        regime = ctx.get("market_regime", "")
        direction = sig.direction or ""
        if regime == "bearish" and direction == "bullish":
            flags.append("Regime bearish con entrata long")
        elif regime == "bullish" and direction == "bearish":
            flags.append("Regime bullish con entrata short")
        metrics["market_regime"] = regime
        metrics["volatility_regime"] = ctx.get("volatility_regime")

        # SPY regime
        spy = ctx.get("regime_spy", "unknown")
        regime_ok = ctx.get("regime_direction_ok", True)
        if not regime_ok:
            flags.append(f"Regime SPY sfavorevole ({spy}) rispetto alla direzione")
        metrics["regime_spy"] = spy

        # Spread
        spread = ctx.get("bid_ask_spread_pct")
        if spread is not None and spread > 0.4:
            flags.append(f"Spread elevato al momento dell'entrata ({spread:.2f}%)")
        metrics["bid_ask_spread_pct"] = spread

        # Volume
        vol_ratio = ctx.get("live_volume_ratio")
        if vol_ratio is not None and vol_ratio < 0.4:
            flags.append(f"Volume basso (ratio vs MA20 = {vol_ratio:.2f})")
        metrics["live_volume_ratio"] = vol_ratio

        # ML score
        ml = ctx.get("ml_score")
        if ml is not None and ml < 0.45:
            flags.append(f"ML score basso ({ml:.2f}) — probabilità TP1 stimata insufficiente")
        metrics["ml_score"] = ml

        # Confluence
        conf = ctx.get("confluence_count", 1)
        if conf == 1:
            flags.append("Confluenza minima (1 pattern) — segnale debole")
        metrics["confluence_count"] = conf

        # Backtest expectancy
        exp_r = ctx.get("trade_plan_backtest_expectancy_r")
        if exp_r is not None and exp_r < 0.1:
            flags.append(f"Expectancy storica bassa ({exp_r:.2f}R)")
        metrics["backtest_expectancy_r"] = exp_r

        # Pattern age
        age = ctx.get("pattern_age_bars")
        if age is not None and age > 2:
            flags.append(f"Pattern vecchio ({age} barre prima dell'entrata)")
        metrics["pattern_age_bars"] = age

        # Price distance
        dist = ctx.get("price_distance_pct")
        if dist is not None and abs(dist) > 1.5:
            flags.append(f"Prezzo lontano dall'entry ({dist:+.2f}%) al momento dell'esecuzione")
        metrics["price_distance_at_entry_pct"] = dist

        # Score
        metrics["final_opportunity_score"] = ctx.get("final_opportunity_score")
        metrics["operational_confidence"] = ctx.get("operational_confidence")

    if ind:
        # RSI
        rsi = ind.get("rsi_14")
        if rsi is not None:
            if sig.direction == "bullish" and rsi > 70:
                flags.append(f"RSI in ipercomprato ({rsi:.1f}) su entrata long")
            elif sig.direction == "bearish" and rsi < 30:
                flags.append(f"RSI in ipervenduto ({rsi:.1f}) su entrata short")
        metrics["rsi_14"] = rsi

        # CVD trend
        cvd_trend = ind.get("cvd_trend")
        if cvd_trend:
            if sig.direction == "bullish" and cvd_trend in ("down", "declining"):
                flags.append(f"CVD trend negativo ({cvd_trend}) su entrata long")
            elif sig.direction == "bearish" and cvd_trend in ("up", "rising"):
                flags.append(f"CVD trend positivo ({cvd_trend}) su entrata short")
        metrics["cvd_trend"] = cvd_trend

        # Volume ratio
        vr = ind.get("volume_ratio_vs_ma20")
        if vr is not None and vr < 0.5:
            flags.append(f"Volume candela basso (ratio {vr:.2f} vs MA20)")
        metrics["volume_ratio_vs_ma20"] = vr

        # ATR (volatilità)
        metrics["atr_14"] = ind.get("atr_14")

        # Posizione nel range strutturale
        pos_in_range = ind.get("price_position_in_range")
        metrics["price_position_in_range"] = pos_in_range

        # FVG / Order Block
        metrics["in_fvg_bullish"] = ind.get("in_fvg_bullish")
        metrics["in_fvg_bearish"] = ind.get("in_fvg_bearish")
        metrics["in_ob_bullish"]  = ind.get("in_ob_bullish")
        metrics["in_ob_bearish"]  = ind.get("in_ob_bearish")

        # RS vs SPY
        metrics["rs_signal"] = ind.get("rs_signal")

    # Outcome
    outcome = sig.close_outcome
    realized_r = sig.realized_r
    if outcome == "stop":
        if sig.close_cause == "overnight_gap":
            flags.append("Chiusura da gap notturno — stop raggiunto overnight")
        else:
            flags.append("Trade chiuso da stop loss")

    return {
        "outcome":        outcome,
        "realized_r":     realized_r,
        "risk_flags":     flags,
        "risk_flag_count": len(flags),
        "key_metrics":    metrics,
        "has_snapshot":   ctx is not None,
        "has_indicators": ind is not None,
        "note": (
            "Snapshot contesto/indicatori disponibile solo per trade eseguiti "
            "dopo il deploy della funzione di autopsia."
            if ctx is None else None
        ),
    }


# ── Endpoint: lista riassuntiva ───────────────────────────────────────────────

@router.get("/trade-autopsy")
async def list_trade_autopsies(
    limit: int = Query(default=100, ge=1, le=500),
    outcome: str | None = Query(
        default=None,
        description="Filtra per close_outcome: stop | tp1 | tp2 | timeout | open",
    ),
    symbol: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Lista riassuntiva di tutti i trade con i dati chiave per l'analisi.

    Ogni elemento include: signal id, symbol, timeframe, direction, pattern,
    prezzi piano, realized_r, close_outcome, close_cause, e i flag di rischio
    automatici calcolati dal snapshot contesto/indicatori.

    Utile per:
    - Esportare in CSV per analisi statistiche
    - Filtrare i trade SL per studio dei pattern di fallimento
    - Confrontare trade vincenti vs perdenti sulle stesse condizioni
    """
    stmt = select(ExecutedSignal).order_by(desc(ExecutedSignal.executed_at)).limit(limit)

    if symbol:
        stmt = stmt.where(ExecutedSignal.symbol == symbol.strip().upper())

    if outcome == "open":
        stmt = stmt.where(
            ExecutedSignal.closed_at.is_(None),
            ExecutedSignal.tws_status.in_(["Filled", "PreSubmitted", "Submitted"]),
        )
    elif outcome in ("stop", "tp1", "tp2", "timeout"):
        stmt = stmt.where(ExecutedSignal.close_outcome == outcome)

    rows = (await session.execute(stmt)).scalars().all()

    items = []
    for sig in rows:
        ctx = _parse_json_field(sig.entry_context_json)
        ind = _parse_json_field(sig.entry_indicators_json)
        summary = _build_analysis_summary(sig, ctx, ind)
        items.append({
            "id":              sig.id,
            "symbol":          sig.symbol,
            "timeframe":       sig.timeframe,
            "direction":       sig.direction,
            "pattern_name":    sig.pattern_name,
            "executed_at":     sig.executed_at.isoformat() if sig.executed_at else None,
            "closed_at":       sig.closed_at.isoformat() if sig.closed_at else None,
            "entry_price":     float(sig.entry_price) if sig.entry_price else None,
            "stop_price":      float(sig.stop_price) if sig.stop_price else None,
            "take_profit_1":   float(sig.take_profit_1) if sig.take_profit_1 else None,
            "realized_r":      sig.realized_r,
            "close_outcome":   sig.close_outcome,
            "close_cause":     sig.close_cause,
            "tws_status":      sig.tws_status,
            "has_snapshot":    ctx is not None,
            "risk_flags":      summary["risk_flags"],
            "risk_flag_count": summary["risk_flag_count"],
            "key_metrics":     summary["key_metrics"],
        })

    wins   = [x for x in items if x["close_outcome"] in ("tp1", "tp2") and (x["realized_r"] or 0) > 0]
    losses = [x for x in items if x["close_outcome"] == "stop"]
    open_  = [x for x in items if not x["close_outcome"]]

    return {
        "trades":       items,
        "count":        len(items),
        "summary": {
            "wins":          len(wins),
            "losses":        len(losses),
            "open":          len(open_),
            "win_rate_pct":  round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else None,
            "total_r":       round(sum((x["realized_r"] or 0) for x in items if x["realized_r"] is not None), 2),
            "avg_r_wins":    round(sum((x["realized_r"] or 0) for x in wins) / len(wins), 3) if wins else None,
            "avg_r_losses":  round(sum((x["realized_r"] or 0) for x in losses) / len(losses), 3) if losses else None,
        },
    }


# ── Endpoint: dry-run / simulazione esecuzione ───────────────────────────────

class SimulateExecuteRequest(BaseModel):
    symbol: str
    direction: str = "bullish"
    entry_price: float
    stop_price: float
    take_profit_price: float
    pattern_name: str = "test_pattern"
    strength: float = 0.80


@router.post("/simulate-execute")
async def simulate_execute(body: SimulateExecuteRequest) -> dict[str, Any]:
    """
    Dry run completo del flusso di auto-esecuzione.

    Esegue TUTTI i controlli reali che il sistema farebbe per un vero ordine:
    - TWS connesso?
    - IBKR_AUTO_EXECUTE abilitato?
    - Short permesso (margin account)?
    - Posizione già aperta sullo stesso simbolo?
    - NetLiquidation disponibile?
    - Sizing calcolato (quante azioni?)
    - Parametri bracket order (entry LMT + TP LMT + SL STP)

    NON invia nessun ordine reale. Mostra esattamente cosa succederebbe.

    Utile per:
    - Verificare che il sistema sia configurato correttamente
    - Controllare il sizing prima di abilitare il live
    - Diagnosticare perché un ordine viene skippato
    """
    from app.core.config import settings  # noqa: PLC0415
    from app.services.auto_execute_service import calculate_position_size  # noqa: PLC0415

    sym = body.symbol.strip().upper()
    direction = body.direction.strip().lower()
    entry = body.entry_price
    stop = body.stop_price
    tp = body.take_profit_price

    steps: list[dict[str, Any]] = []
    result_status = "would_execute"

    # ── Step 1: Configurazione ───────────────────────────────────────────
    cfg = {
        "tws_enabled":         getattr(settings, "tws_enabled", False),
        "ibkr_auto_execute":   settings.ibkr_auto_execute,
        "ibkr_margin_account": getattr(settings, "ibkr_margin_account", False),
        "ibkr_paper_trading":  getattr(settings, "ibkr_paper_trading", True),
        "tws_host":            getattr(settings, "tws_host", "?"),
        "tws_port":            getattr(settings, "tws_port", 7497),
        "risk_pct_per_trade":  getattr(settings, "ibkr_max_risk_per_trade_pct", 1.0),
        "max_capital":         getattr(settings, "ibkr_max_capital", 0),
    }
    steps.append({"step": "config", "ok": True, "data": cfg})

    if not cfg["tws_enabled"]:
        steps.append({"step": "tws_enabled_check", "ok": False, "reason": "TWS_ENABLED=false → ordine non verrebbe inviato"})
        result_status = "would_skip"
    else:
        steps.append({"step": "tws_enabled_check", "ok": True, "reason": "TWS_ENABLED=true ✓"})

    if not cfg["ibkr_auto_execute"]:
        steps.append({"step": "auto_execute_check", "ok": False, "reason": "IBKR_AUTO_EXECUTE=false → ordine non verrebbe inviato"})
        result_status = "would_skip"
    else:
        steps.append({"step": "auto_execute_check", "ok": True, "reason": "IBKR_AUTO_EXECUTE=true ✓"})

    if direction == "bearish" and not cfg["ibkr_margin_account"]:
        steps.append({"step": "short_check", "ok": False, "reason": "Short non disponibile: IBKR_MARGIN_ACCOUNT=false"})
        result_status = "would_skip"
    else:
        steps.append({"step": "short_check", "ok": True, "reason": f"Direzione {direction} permessa ✓"})

    # ── Step 2: Connessione TWS ──────────────────────────────────────────
    tws_connected = False
    open_positions: list[dict] = []
    net_liq: float | None = None

    if cfg["tws_enabled"]:
        try:
            from app.services.tws_service import get_tws_service  # noqa: PLC0415
            tws = get_tws_service()
            tws_connected = tws is not None and tws.is_connected
            steps.append({
                "step": "tws_connection",
                "ok": tws_connected,
                "reason": "TWS connesso ✓" if tws_connected else
                          f"TWS NON connesso su {cfg['tws_host']}:{cfg['tws_port']} — "
                          "ordine reale verrebbe bloccato. Aprire TWS con paper account e abilitare API socket.",
            })

            if tws_connected:
                open_positions = await tws.get_open_positions()
                steps.append({
                    "step": "open_positions",
                    "ok": True,
                    "data": {"count": len(open_positions), "symbols": [p.get("symbol") for p in open_positions]},
                    "reason": f"{len(open_positions)} posizioni aperte",
                })

                # Controllo duplicato sullo stesso simbolo
                duplicate = any(p.get("symbol", "").upper() == sym for p in open_positions)
                if duplicate:
                    steps.append({"step": "duplicate_check", "ok": False, "reason": f"Posizione già aperta su {sym} → ordine skippato"})
                    result_status = "would_skip"
                else:
                    steps.append({"step": "duplicate_check", "ok": True, "reason": f"Nessuna posizione aperta su {sym} ✓"})

                # NetLiquidation per sizing reale
                net_liq = await tws.get_net_liquidation(currency="USD")
                steps.append({
                    "step": "net_liquidation",
                    "ok": net_liq is not None and net_liq > 0,
                    "data": {"net_liq_usd": net_liq},
                    "reason": f"NetLiquidation = ${net_liq:,.2f}" if net_liq else
                              "NetLiquidation non disponibile → ordine reale verrebbe bloccato",
                })
                if not net_liq or net_liq <= 0:
                    result_status = "would_skip"
            else:
                result_status = "would_error"
        except Exception as exc:
            steps.append({"step": "tws_connection", "ok": False, "reason": f"Eccezione TWS: {exc}"})
            result_status = "would_error"

    # ── Step 3: Sizing ───────────────────────────────────────────────────
    capital_for_sizing = net_liq or cfg["max_capital"]
    risk_pct = cfg["risk_pct_per_trade"]
    size = calculate_position_size(
        capital=capital_for_sizing,
        risk_pct=risk_pct,
        entry_price=entry,
        stop_price=stop,
    )
    risk_amount = capital_for_sizing * (risk_pct / 100.0)
    stop_distance = abs(entry - stop)
    r_ratio = abs(tp - entry) / stop_distance if stop_distance > 0 else None

    steps.append({
        "step": "sizing",
        "ok": size >= 1,
        "data": {
            "capital_used": capital_for_sizing,
            "capital_source": "net_liquidation" if net_liq else "ibkr_max_capital_fallback",
            "risk_pct": risk_pct,
            "risk_amount_usd": round(risk_amount, 2),
            "stop_distance": round(stop_distance, 4),
            "size_shares": size,
            "notional_usd": round(size * entry, 2),
            "r_ratio": round(r_ratio, 2) if r_ratio else None,
        },
        "reason": f"{size} azioni (rischio ${risk_amount:.0f} / distanza ${stop_distance:.4f})" if size >= 1
                  else f"Size troppo piccola ({size}) — stop troppo ampio rispetto al capitale",
    })
    if size < 1:
        result_status = "would_skip"

    # ── Step 4: Parametri bracket order ─────────────────────────────────
    action = "BUY" if direction == "bullish" else "SELL"
    bracket_params = {
        "symbol":     sym,
        "action":     action,
        "quantity":   size,
        "entry_lmt":  entry,
        "tp_lmt":     tp,
        "sl_stp":     stop,
        "exchange":   "SMART",
        "currency":   "USD",
        "order_type": "bracket (entry LMT + TP LMT GTC + SL STP GTC)",
    }
    steps.append({
        "step": "bracket_order_params",
        "ok": True,
        "data": bracket_params,
        "reason": f"Ordine pronto: {action} {size} {sym} @ {entry} | SL {stop} | TP {tp}",
    })

    # ── Riepilogo finale ─────────────────────────────────────────────────
    ok_count   = sum(1 for s in steps if s.get("ok"))
    fail_count = sum(1 for s in steps if not s.get("ok"))

    return {
        "dry_run":        True,
        "result_status":  result_status,
        "result_label": {
            "would_execute": "✅ L'ordine VERREBBE inviato a TWS",
            "would_skip":    "⚠️  L'ordine verrebbe SKIPPATO (vedi steps falliti)",
            "would_error":   "❌ L'ordine fallirebbe con ERRORE (TWS non connesso)",
        }.get(result_status, result_status),
        "input": {
            "symbol": sym, "direction": direction,
            "entry": entry, "stop": stop, "tp": tp,
            "pattern": body.pattern_name, "strength": body.strength,
        },
        "steps_ok":    ok_count,
        "steps_fail":  fail_count,
        "steps":       steps,
        "tws_connected": tws_connected,
        "note": (
            "TWS non connesso: avvia TWS con il paper account, abilita "
            f"API socket su porta {cfg['tws_port']}, poi riprova."
            if not tws_connected and cfg["tws_enabled"] else None
        ),
    }
