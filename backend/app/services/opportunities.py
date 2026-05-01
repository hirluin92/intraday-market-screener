"""
Combine latest context snapshots with latest stored pattern per series (MVP, no persistence).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    opportunity_lookup_key,
    pattern_quality_cache,
    trade_plan_backtest_cache,
    variant_best_cache,
)
from app.core.config import settings
from app.core.hour_filters import is_equity_market_active
from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    SIGNAL_MIN_CONFLUENCE,
)
from app.models.candle_context import CandleContext
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import PatternBacktestAggregateRow
from app.schemas.opportunities import OpportunityRow
from app.schemas.screener import RankedScreenerRow
from app.services.context_query import (
    dedupe_latest_contexts_prefer_freshest_candle,
    list_latest_context_per_series,
)
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_query import (
    count_concurrent_patterns_per_series,
    list_latest_pattern_per_series,
)
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
    final_opportunity_label_from_score,
)
from app.services.alert_candidates import compute_alert_candidate_fields
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy
from app.services.pattern_operational_ui import (
    pattern_is_validated_for_ui,
    pattern_operational_status_for_ui,
)
from app.services.pattern_quality import pattern_quality_label_from_score
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.trade_plan_backtest import trade_plan_backtest_lookup_by_bucket
from app.services.trade_plan_live_adjustment import adjust_final_score_for_trade_plan_backtest
from app.services.trade_plan_live_variant import (
    LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
    build_live_trade_plan_for_opportunity,
    load_best_variant_lookup_for_live,
)
from app.services.ml_signal_scorer import build_signal_feature_dict, is_enabled as ml_is_enabled, score_signal
from app.services.operational_decision import map_decision_filter_param
from app.services.opportunity_validator import validate_opportunity
from app.services.indicator_query import get_indicator_for_candle_timestamp
from app.services.regime_filter_service import RegimeFilter, load_regime_filter
from app.services.pattern_staleness import (
    compute_pattern_staleness_fields,
    stale_threshold_bars,
)
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ── VIX cache: aggiornato al massimo ogni ora per le chiamate live ─────────────
_vix_history_cache: dict[str, float] = {}
_vix_cache_ts: float = 0.0
_VIX_CACHE_TTL_S: float = 3600.0
_vix_lock = asyncio.Lock()

# ── IBKR spread cache: conid → {spread_pct, volume_live, ts}; TTL 2 min ────────
# Evita N chiamate a IBKR per lo stesso simbolo nel medesimo ciclo di refresh.
_spread_cache: dict[str, dict] = {}
_SPREAD_CACHE_TTL_S: float = 120.0


async def _get_vix_history() -> dict[str, float]:
    """Ritorna la storia VIX (cache con TTL 1h). Non blocca se yfinance fallisce."""
    import time  # noqa: PLC0415
    global _vix_history_cache, _vix_cache_ts
    now = time.monotonic()
    if now - _vix_cache_ts < _VIX_CACHE_TTL_S and _vix_history_cache:
        return _vix_history_cache
    async with _vix_lock:
        now = time.monotonic()
        if now - _vix_cache_ts < _VIX_CACHE_TTL_S and _vix_history_cache:
            return _vix_history_cache
        try:
            import yfinance as yf  # noqa: PLC0415

            def _dl() -> dict[str, float]:
                # yf.download() per indici come ^VIX produce KeyError('chart') in alcune
                # versioni di yfinance. Ticker.history() usa un path diverso ed è stabile.
                df = yf.Ticker("^VIX").history(period="14mo", auto_adjust=False)
                if df is None or df.empty:
                    return {}
                close_col = next((c for c in ("Adj Close", "Close") if c in df.columns), df.columns[0])
                return {idx.strftime("%Y-%m-%d"): float(v) for idx, v in zip(df.index, df[close_col])}

            data = await asyncio.to_thread(_dl)
            if data:
                _vix_history_cache = data
                _vix_cache_ts = now
        except Exception as exc:
            logger.debug("_get_vix_history: %s", exc)
    return _vix_history_cache


async def _get_ibkr_spread(symbol: str) -> dict[str, float | None]:
    """
    Ritorna bid/ask spread% e volume live per un simbolo.

    Priorità:
      1. TWS API (ib_insync) — dati streaming reali, se TWS_ENABLED=true
      2. Client Portal REST — snapshot su richiesta, se IBKR_ENABLED=true
      3. None — se nessuno disponibile

    Cache per TTL 2 min per simbolo (evita N chiamate nel medesimo ciclo).
    Non-blocking: restituisce valori None in caso di errore.
    """
    import time  # noqa: PLC0415

    _EMPTY: dict[str, float | None] = {"spread_pct": None, "volume_live": None, "bid": None, "ask": None}

    if settings.ibkr_max_spread_pct <= 0.0:
        return _EMPTY

    # Crypto (Binance) non sono stock — TWS restituirebbe Error 200, Gateway non li conosce
    _CRYPTO_SUFFIXES = ("/USDT", "/BTC", "/ETH", "/BUSD", "/USD")
    if any(symbol.upper().endswith(s) for s in _CRYPTO_SUFFIXES):
        return _EMPTY

    sym_clean = symbol.replace("/USDT", "").replace("/USD", "")
    cache_key = sym_clean
    now = time.monotonic()
    cached = _spread_cache.get(cache_key)
    if cached and now - cached.get("ts", 0) < _SPREAD_CACHE_TTL_S:
        return cached

    # ── Tentativo 1: TWS API (dati delayed se non abbonato real-time) ─────
    try:
        from app.services.tws_service import get_tws_service  # noqa: PLC0415

        tws = get_tws_service()
        if tws is not None and tws.is_connected:
            quote = await tws.get_live_quote(sym_clean)
            if quote is not None and quote.spread_pct is not None:
                entry = {
                    "spread_pct": quote.spread_pct,
                    "volume_live": quote.volume,
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "source": "tws",
                    "ts": now,
                }
                _spread_cache[cache_key] = entry
                return entry
    except Exception as exc:
        logger.debug("TWS spread check %s: %s", symbol, exc)

    # TWS non disponibile o nessun dato — cache _EMPTY per evitare re-tentativo
    _spread_cache[cache_key] = {**_EMPTY, "ts": now}
    return _EMPTY


def _trade_plan_price_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _price_stale_fields(
    current_price: float,
    entry_price: float,
    direction: str,
    threshold_pct: float,
    stop_loss: float | None,
) -> tuple[bool, float, str | None]:
    """
    Ritorna (is_stale, distance_pct, motivo IT).
    Long: scaduto se prezzo > soglia % sopra entry o <= stop.
    Short: scaduto se prezzo > soglia % sotto entry (move già avvenuto) o >= stop.
    """
    if entry_price <= 0:
        return False, 0.0, None
    distance_pct = (current_price - entry_price) / entry_price * 100.0
    dist_round = round(distance_pct, 2)
    d = direction.lower()
    if d in ("bullish", "long"):
        if stop_loss is not None and current_price <= stop_loss:
            return True, dist_round, "Prezzo a o sotto lo stop — segnale invalidato"
        if distance_pct > threshold_pct:
            return (
                True,
                dist_round,
                f"Prezzo salito {distance_pct:.1f}% sopra entry — momento ottimale passato",
            )
        return False, dist_round, None
    if d in ("bearish", "short"):
        if stop_loss is not None and current_price >= stop_loss:
            return True, dist_round, "Prezzo a o sopra lo stop — segnale invalidato"
        if distance_pct < -threshold_pct:
            return (
                True,
                dist_round,
                f"Prezzo sceso {abs(distance_pct):.1f}% sotto entry — momento ottimale passato",
            )
        return False, dist_round, None
    return False, dist_round, None


def _pattern_key(p: CandlePattern) -> tuple[str, str, str]:
    return (p.exchange, p.symbol, p.timeframe)


def _pattern_quality_pair(
    lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    pattern_name: str | None,
    timeframe: str,
) -> tuple[float | None, str]:
    """Match (latest_pattern_name, timeframe) to on-demand backtest aggregates."""
    if not pattern_name:
        return None, "unknown"
    agg = lookup.get((pattern_name, timeframe))
    if agg is None:
        return None, "unknown"
    score = agg.pattern_quality_score
    return score, pattern_quality_label_from_score(score)


def _pre_enrich_sort(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Ordinamento prima dell’arricchimento trade plan (solo score + recency)."""

    def key(r: OpportunityRow) -> tuple:
        ts = r.context_timestamp.timestamp()
        return (-r.final_opportunity_score, -ts)

    return sorted(rows, key=key)


def _decision_sort_priority(r: OpportunityRow) -> int:
    """Operabile > Da monitorare > Scartare."""
    d = r.operational_decision or "monitor"
    if d == "execute":
        return 0
    if d == "monitor":
        return 1
    return 2


def _alert_level_priority(r: OpportunityRow) -> int:
    """Alta priorità > media > nessun alert."""
    a = (r.alert_level or "").lower()
    if a == "alta_priorita":
        return 0
    if a == "media_priorita":
        return 1
    return 2


def _post_enrich_sort(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Decisione (operabile > monitor > scarta), poi tier alert, poi score finale, poi recency."""

    def key(r: OpportunityRow) -> tuple:
        ts = r.context_timestamp.timestamp()
        return (
            _decision_sort_priority(r),
            _alert_level_priority(r),
            -r.final_opportunity_score,
            -ts,
        )

    return sorted(rows, key=key)


def _sort_ranked(rows: list[RankedScreenerRow]) -> list[RankedScreenerRow]:
    def key(r: RankedScreenerRow) -> tuple:
        ts = r.timestamp.timestamp()
        pq = r.pattern_quality_score
        pq_key = float("inf") if pq is None else -pq
        return (
            0 if r.latest_pattern_name is not None else 1,
            -r.screener_score,
            pq_key,
            -ts,
        )

    return sorted(rows, key=key)


async def list_opportunities(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
    decision: str | None = None,
    min_confluence_patterns: int | None = None,
) -> list[OpportunityRow]:
    # Le 3 operazioni iniziali sono indipendenti: girano in parallelo su sessioni proprie.
    # _fetch_contexts_and_dedupe raggruppa list_latest_context_per_series +
    # dedupe_latest_contexts_prefer_freshest_candle nella stessa sessione e nello
    # stesso slot del gather, così la query di deduplication (fetch candles per series)
    # gira in parallelo con patterns e confluence invece di aspettarle.
    async def _fetch_contexts_and_dedupe() -> tuple[list[CandleContext], dict]:
        async with AsyncSessionLocal() as s:
            ctxs = await list_latest_context_per_series(
                s, symbol=symbol, exchange=exchange, provider=provider,
                asset_type=asset_type, timeframe=timeframe,
            )
            return await dedupe_latest_contexts_prefer_freshest_candle(s, ctxs)

    async def _fetch_patterns() -> list[CandlePattern]:
        async with AsyncSessionLocal() as s:
            return await list_latest_pattern_per_series(
                s, symbol=symbol, exchange=exchange, provider=provider,
                asset_type=asset_type, timeframe=timeframe,
            )

    async def _fetch_confluence() -> dict[tuple[str, str, str], int]:
        try:
            async with AsyncSessionLocal() as s:
                return await count_concurrent_patterns_per_series(
                    s, symbol=symbol, exchange=exchange, provider=provider,
                    asset_type=asset_type, timeframe=timeframe,
                )
        except Exception:
            logger.exception("list_opportunities: count_concurrent_patterns_per_series failed; confluence=1 for all")
            return {}

    (contexts, candle_map), latest_patterns, confluence_map = await asyncio.gather(
        _fetch_contexts_and_dedupe(),
        _fetch_patterns(),
        _fetch_confluence(),
    )

    by_series: dict[tuple[str, str, str], CandlePattern] = {
        _pattern_key(p): p for p in latest_patterns
    }

    pq_key = opportunity_lookup_key(
        "pq",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )

    async def _compute_pq() -> dict[tuple[str, str], PatternBacktestAggregateRow]:
        # Sessione propria: sicuro per background recompute (stale-while-revalidate).
        async with AsyncSessionLocal() as s:
            return await pattern_quality_lookup_by_name_tf(
                s,
                symbol=symbol,
                exchange=exchange,
                provider=provider,
                asset_type=asset_type,
                timeframe=timeframe,
                dt_to=datetime.now(UTC),
            )

    tpb_key = opportunity_lookup_key(
        "tpb",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
    )

    async def _compute_tpb():
        async with AsyncSessionLocal() as s:
            return await trade_plan_backtest_lookup_by_bucket(
                s,
                symbol=symbol,
                exchange=exchange,
                provider=provider,
                asset_type=asset_type,
                timeframe=timeframe,
                cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
            )

    var_key = opportunity_lookup_key(
        "var",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
    )

    async def _compute_var():
        async with AsyncSessionLocal() as s:
            return await load_best_variant_lookup_for_live(
                s,
                symbol=symbol,
                exchange=exchange,
                provider=provider,
                asset_type=asset_type,
                timeframe=timeframe,
                limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
                cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
            )

    # Le 3 computazioni sono indipendenti: girare in parallelo riduce il tempo di
    # attesa al primo avvio (cache miss) da ~90s sequenziali a ~30s paralleli.
    _gather_results = await asyncio.gather(
        pattern_quality_cache.get_or_compute(key=pq_key, compute=_compute_pq),
        trade_plan_backtest_cache.get_or_compute(key=tpb_key, compute=_compute_tpb),
        variant_best_cache.get_or_compute(key=var_key, compute=_compute_var),
        return_exceptions=True,
    )
    pq_lookup = _gather_results[0] if not isinstance(_gather_results[0], BaseException) else {}
    tpb_lookup = _gather_results[1] if not isinstance(_gather_results[1], BaseException) else {}
    variant_lookup_raw = _gather_results[2] if not isinstance(_gather_results[2], BaseException) else {}
    if isinstance(_gather_results[0], BaseException):
        logger.exception("list_opportunities: pq_lookup compute failed: %s", _gather_results[0])
    if isinstance(_gather_results[1], BaseException):
        logger.exception("list_opportunities: tpb_lookup compute failed: %s", _gather_results[1])
    if isinstance(_gather_results[2], BaseException):
        logger.exception("list_opportunities: variant_lookup compute failed; default trade plans only: %s", _gather_results[2])

    # Lookup contesto per series key: usato nel secondo loop (enrichment + ML) per
    # ricavare il CandleContext corrispondente alla row in elaborazione senza dipendere
    # dalla variabile di loop del primo ciclo.
    ctx_by_series: dict[tuple[str, str, str, str], CandleContext] = {
        (c.provider, c.exchange, c.symbol, c.timeframe): c for c in contexts
    }

    out: list[OpportunityRow] = []
    for ctx in contexts:
        snap = SnapshotForScoring(
            exchange=ctx.exchange,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            timestamp=ctx.timestamp,
            market_regime=ctx.market_regime,
            volatility_regime=ctx.volatility_regime,
            candle_expansion=ctx.candle_expansion,
            direction_bias=ctx.direction_bias,
        )
        scored = score_snapshot(snap)
        p = by_series.get((ctx.exchange, ctx.symbol, ctx.timeframe))
        pn = p.pattern_name if p is not None else None
        pq_score, pq_label = _pattern_quality_pair(pq_lookup, pn, ctx.timeframe)
        pat_dir = p.direction if p is not None else None
        pat_strength = p.pattern_strength if p is not None else None
        base_final = compute_final_opportunity_score(
            screener_score=scored.screener_score,
            score_direction=scored.score_direction,
            latest_pattern_direction=pat_dir,
            pattern_quality_score=pq_score,
            pattern_quality_label=pq_label,
            latest_pattern_strength=pat_strength,
        )
        has_pat = pn is not None
        final, tf_ok, tf_gate, tf_filtered = apply_pattern_timeframe_policy(
            has_pattern=has_pat,
            pattern_quality_score=pq_score,
            _pattern_quality_label=pq_label,
            base_final_opportunity_score=base_final,
        )
        score_before_tpb = float(final)
        if not has_pat or pn is None:
            adjusted = score_before_tpb
            tpb_delta = 0.0
            tpb_label = "no_pattern"
            tpb_exp = None
            tpb_n = None
            tpb_conf = "unknown"
        else:
            bucket = tpb_lookup.get((pn, ctx.timeframe, ctx.provider, ctx.asset_type))
            if bucket is None and ctx.provider == "alpaca":
                bucket = tpb_lookup.get((pn, ctx.timeframe, "yahoo_finance", ctx.asset_type))
            adjusted, tpb_delta, tpb_label, tpb_exp, tpb_n, tpb_conf = (
                adjust_final_score_for_trade_plan_backtest(score_before_tpb, bucket)
            )
        final = adjusted
        final_lbl = final_opportunity_label_from_score(final)
        # Alert: soglie sullo score **prima** del soft TPB — il backtest trade plan non deve
        # sopprimere da solo le candidature (indicatore di cautela, non giudice finale).
        alert_candidate, alert_level = compute_alert_candidate_fields(
            score_direction=scored.score_direction,
            latest_pattern_direction=pat_dir,
            final_opportunity_score=score_before_tpb,
            pattern_quality_label=pq_label,
            pattern_timeframe_quality_ok=tf_ok,
        )
        pat_ts = p.timestamp if p is not None else None
        # Usa max(ctx.timestamp, now) come riferimento per la staleness:
        # a mercato chiuso ctx.timestamp è congelato all'ultima barra, quindi senza
        # questo fix un pattern delle 19:45 appare "1 barra fa" anche a mezzanotte.
        staleness_ref = max(ctx.timestamp, datetime.now(UTC))
        age_bars, pat_stale = compute_pattern_staleness_fields(
            staleness_ref,
            pat_ts,
            ctx.timeframe,
        )
        pat_stale_thresh = stale_threshold_bars(ctx.timeframe)

        # Staleness score decay: abbassa il ranking dei segnali vecchi in modo proporzionale.
        # Complementa la degradazione decisionale (execute→monitor) già esistente:
        # anche all'interno del blocco "MONITOR", un segnale fresco precede uno stale
        # perché ha score più alto.
        # Formula: per ogni barra oltre la soglia, score scende del 20% massimo.
        # Es: pattern 2 barre oltre soglia (age_beyond/thresh = 1.0) → -20%.
        #     pattern 1 barra oltre soglia → -10%.
        # Il label viene ricalcolato dopo il decay.
        if pat_stale and age_bars is not None and pat_stale_thresh:
            age_beyond = max(0, age_bars - pat_stale_thresh)
            decay_ratio = min(1.0, age_beyond / max(1, pat_stale_thresh))
            final = max(0.0, round(final * (1.0 - 0.20 * decay_ratio), 2))
            final_lbl = final_opportunity_label_from_score(final)

        pat_val = pattern_is_validated_for_ui(pn, ctx.timeframe)
        pat_op = pattern_operational_status_for_ui(pn, ctx.timeframe, pq_label)
        # Confluence count: numero pattern validati distinti attivi nella stessa barra.
        # Fallback a 1 se la serie non è nella map (nessun pattern validato → già "monitor").
        conf_count = confluence_map.get((ctx.exchange, ctx.symbol, ctx.timeframe), 1)
        out.append(
            OpportunityRow(
                asset_type=ctx.asset_type,
                provider=ctx.provider,
                exchange=ctx.exchange,
                symbol=ctx.symbol,
                timeframe=ctx.timeframe,
                market_metadata=ctx.market_metadata,
                timestamp=ctx.timestamp,
                context_timestamp=ctx.timestamp,
                pattern_timestamp=pat_ts,
                pattern_age_bars=age_bars,
                pattern_stale=pat_stale,
                pattern_stale_threshold_bars=pat_stale_thresh,
                market_regime=ctx.market_regime,
                volatility_regime=ctx.volatility_regime,
                candle_expansion=ctx.candle_expansion,
                direction_bias=ctx.direction_bias,
                screener_score=scored.screener_score,
                score_label=scored.score_label,
                score_direction=scored.score_direction,
                latest_pattern_name=pn,
                latest_pattern_strength=pat_strength,
                latest_pattern_direction=pat_dir,
                pattern_quality_score=pq_score,
                pattern_quality_label=pq_label,
                final_opportunity_score=final,
                final_opportunity_label=final_lbl,
                pattern_timeframe_quality_ok=tf_ok,
                pattern_timeframe_gate_label=tf_gate,
                pattern_timeframe_filtered_candidate=tf_filtered,
                alert_candidate=alert_candidate,
                alert_level=alert_level,
                trade_plan=None,
                final_opportunity_score_before_trade_plan_backtest=score_before_tpb,
                trade_plan_backtest_score_delta=tpb_delta,
                trade_plan_backtest_adjustment_label=tpb_label,
                trade_plan_backtest_expectancy_r=tpb_exp,
                trade_plan_backtest_sample_size=tpb_n,
                operational_confidence=tpb_conf,
                selected_trade_plan_variant=None,
                selected_trade_plan_variant_status=None,
                selected_trade_plan_variant_sample_size=None,
                selected_trade_plan_variant_expectancy_r=None,
                trade_plan_source="default_fallback",
                trade_plan_fallback_reason=None,
                confluence_count=conf_count,
                pattern_is_validated=pat_val,
                pattern_operational_status=pat_op,
            )
        )

    ranked = _pre_enrich_sort(out)

    # variant_lookup già calcolato in parallelo con pq/tpb sopra.
    variant_lookup = variant_lookup_raw

    regime_filter_yahoo: RegimeFilter | None = None
    try:
        regime_filter_yahoo = await load_regime_filter(session, provider="yahoo_finance")
    except Exception:
        logger.exception("list_opportunities: load_regime_filter (yahoo) failed; regime fields degraded")

    # Regime filter UK: ^FTSE 1d via Yahoo Finance (analogo a SPY per USA — Fase 4A).
    # None → PATTERNS_BEAR_REGIME_ONLY UK vengono forzati a "monitor" dal validator
    # (regime_label default = "neutral", non è "bearish" → safe-fail conservativo).
    regime_filter_ibkr: RegimeFilter | None = None
    _uk_regime_attempted = False
    try:
        from app.core.config import settings as _cfg_regime  # noqa: PLC0415
        if getattr(_cfg_regime, "enable_uk_market", False):
            _uk_regime_attempted = True
            regime_filter_ibkr = await load_regime_filter(session, provider="ibkr")
    except Exception:
        logger.exception("list_opportunities: load_regime_filter (ibkr/uk) failed; regime UK degraded")

    if _uk_regime_attempted and (regime_filter_ibkr is None or not regime_filter_ibkr.has_data):
        logger.warning(
            "UK regime filter (^FTSE 1d): nessun dato in DB — "
            "PATTERNS_BEAR_REGIME_ONLY UK (engulfing_bullish, macd/rsi_divergence_bull) "
            "forzati a 'monitor' per sicurezza. "
            "Eseguire batch_pipeline_uk --symbols '^FTSE' --timeframe 1d per ripopolare."
        )

    # ── Prefetch spread IBKR in parallelo (evita 76 chiamate seriali a TWS) ──────
    ibkr_spread_filter_active_global = (
        settings.ibkr_enabled and settings.ibkr_max_spread_pct > 0.0
    )
    if ibkr_spread_filter_active_global:
        spread_symbols = [
            r.symbol for r in ranked
            if r.latest_pattern_name and not any(
                r.symbol.upper().endswith(s) for s in ("/USDT", "/BTC", "/ETH", "/BUSD", "/USD")
            )
        ]
        if spread_symbols:
            # Timeout 6s per l'intera batch: evita blocchi lunghi quando
            # TWS è connesso ma i dati non sono disponibili (mercato chiuso).
            # I simboli non risolti entro 6s avranno spread=None nel loop sottostante.
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[_get_ibkr_spread(s) for s in spread_symbols], return_exceptions=True),
                    timeout=6.0,
                )
            except asyncio.TimeoutError:
                logger.debug("ibkr spread prefetch: timeout 6s — %d simboli non risolti", len(spread_symbols))

    # ── Prefetch prezzi live TWS in parallelo (evita chiamate seriali per ogni US stock) ──
    # Cache TTL 30s in tws_service: il gather popola la cache; il loop sottostante
    # legge dalla cache senza ulteriori round-trip a TWS.
    _tws_svc_global = None
    try:
        from app.services.tws_service import get_tws_service  # noqa: PLC0415
        _tws_svc_global = get_tws_service()
    except Exception:
        pass
    if _tws_svc_global is not None and _tws_svc_global.is_connected:
        us_stock_symbols = [
            r.symbol for r in ranked
            if (r.provider or "") == "yahoo_finance" and r.symbol
        ]
        if us_stock_symbols:
            try:
                # Timeout 8s: evita blocchi se TWS non risponde per alcuni simboli.
                await asyncio.wait_for(
                    asyncio.gather(
                        *[_tws_svc_global.get_last_price(s) for s in us_stock_symbols],
                        return_exceptions=True,
                    ),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                logger.debug(
                    "TWS live price prefetch: timeout 8s — %d simboli, prezzi non disponibili",
                    len(us_stock_symbols),
                )

    enriched: list[OpportunityRow] = []
    for r in ranked:
        c = candle_map.get((r.provider, r.exchange, r.symbol, r.timeframe))
        best_row = None
        if r.latest_pattern_name:
            best_row = variant_lookup.get(
                (r.latest_pattern_name, r.timeframe, r.provider, r.asset_type),
            )
            if best_row is None and r.provider == "alpaca":
                best_row = variant_lookup.get(
                    (r.latest_pattern_name, r.timeframe, "yahoo_finance", r.asset_type),
                )
        plan, sv, st, ss, se, src, fbr = build_live_trade_plan_for_opportunity(
            final_opportunity_label=r.final_opportunity_label,
            final_opportunity_score=r.final_opportunity_score,
            score_direction=r.score_direction,
            latest_pattern_direction=r.latest_pattern_direction,
            latest_pattern_name=r.latest_pattern_name,
            candle_expansion=r.candle_expansion,
            pattern_timeframe_gate_label=r.pattern_timeframe_gate_label,
            volatility_regime=r.volatility_regime,
            market_regime=r.market_regime,
            candle_high=c.high if c is not None else None,
            candle_low=c.low if c is not None else None,
            candle_close=c.close if c is not None else None,
            best_row=best_row,
            symbol=r.symbol or "",
            exchange=r.exchange or "",
        )
        row_with_plan = r.model_copy(
            update={
                "trade_plan": plan,
                "selected_trade_plan_variant": sv,
                "selected_trade_plan_variant_status": st,
                "selected_trade_plan_variant_sample_size": ss,
                "selected_trade_plan_variant_expectancy_r": se,
                "trade_plan_source": src,
                "trade_plan_fallback_reason": fbr,
            },
        )
        ts_ref = row_with_plan.pattern_timestamp or row_with_plan.context_timestamp
        if row_with_plan.provider == "binance":
            regime_spy = "n/a"
            regime_direction_ok = True
        elif regime_filter_yahoo is not None:
            regime_spy = regime_filter_yahoo.get_regime_label(ts_ref)
            if row_with_plan.provider == "yahoo_finance":
                allowed = regime_filter_yahoo.get_allowed_directions(ts_ref)
                d = (row_with_plan.latest_pattern_direction or "").strip().lower()
                regime_direction_ok = d in allowed if d in ("bullish", "bearish") else False
            else:
                regime_direction_ok = True
        else:
            regime_spy = "unknown"
            regime_direction_ok = True

        pat_str = row_with_plan.latest_pattern_strength
        pat_str_f = float(pat_str) if pat_str is not None else None
        _rf_val = (
            None
            # crypto Binance: 24/7, nessun regime filter
            if row_with_plan.provider == "binance"
            # UK IBKR/LSE: usa ISF.L 1d come regime anchor (analogo a SPY — Fase 4A)
            else regime_filter_ibkr if (
                row_with_plan.provider == "ibkr"
                and (row_with_plan.exchange or "").upper() == "LSE"
            )
            # IBKR non-LSE (es. futures, altri mercati): nessun regime filter
            else None if row_with_plan.provider == "ibkr"
            else regime_filter_yahoo
        )
        _tp_for_risk = row_with_plan.trade_plan
        _risk_pct_val: float | None = None
        if _tp_for_risk and _tp_for_risk.entry_price and _tp_for_risk.stop_loss:
            try:
                _risk_pct_val = float(
                    abs(_tp_for_risk.entry_price - _tp_for_risk.stop_loss)
                    / _tp_for_risk.entry_price * 100
                )
            except (TypeError, ZeroDivisionError):
                pass

        # TRIPLO config apr 2026: per 5m Alpaca midday (11-14 ET) il validator
        # necessita di price_position_in_range (running session H/L) per il filtro
        # al estremo del giorno. Caricato solo per alpaca 5m per evitare overhead.
        _ind_val = None
        if (
            row_with_plan.provider == "alpaca"
            and row_with_plan.timeframe == "5m"
            and ts_ref is not None
        ):
            try:
                _ind_val = await get_indicator_for_candle_timestamp(
                    session,
                    symbol=row_with_plan.symbol,
                    exchange=row_with_plan.exchange or "",
                    provider=row_with_plan.provider,
                    timeframe=row_with_plan.timeframe,
                    timestamp=ts_ref,
                )
            except Exception:
                pass  # fallback: ind=None → midday scartato per sicurezza

        v_dec, v_rationale = validate_opportunity(
            symbol=row_with_plan.symbol,
            timeframe=row_with_plan.timeframe,
            provider=row_with_plan.provider,
            exchange=row_with_plan.exchange,
            pattern_name=row_with_plan.latest_pattern_name,
            direction=row_with_plan.latest_pattern_direction,
            regime_filter=_rf_val,
            timestamp=ts_ref,
            pattern_strength=pat_str_f,
            confluence_count=row_with_plan.confluence_count,
            min_confluence_patterns=min_confluence_patterns,
            final_score=row_with_plan.final_opportunity_score,
            screener_score=row_with_plan.screener_score,
            risk_pct=_risk_pct_val,
            ind=_ind_val,
        )

        # ── Guard: trade plan senza livelli validi → non eseguibile ────────────
        # Se il piano ha trade_direction="none" o stop_loss=None (es. score_direction
        # neutro o in conflitto con pattern_direction), non ci sono parametri operativi.
        # Un segnale "execute" senza stop/TP non è operabile — demotare a "monitor".
        tp = row_with_plan.trade_plan
        if v_dec == "execute" and tp is not None and (
            tp.trade_direction == "none" or tp.stop_loss is None
        ):
            v_dec = "monitor"
            v_rationale = [
                "Piano di trade incompleto: direzione o stop non calcolabili "
                "(score_direction neutro o conflitto pattern/score).",
                "Attendere conferma direzionale prima di eseguire.",
                *list(v_rationale),
            ]

        threshold_pct = settings.opportunity_price_staleness_pct
        current_price: float | None = None
        price_distance_pct: float | None = None
        price_stale = False
        price_stale_reason: str | None = None
        price_source: str = "unavailable"

        # ── Prezzo live TWS (solo US stock, non crypto Binance) ──────────────
        # Priorità: prezzo live TWS (last trade o mid bid/ask, cache 30s)
        # Fallback: close dell'ultima candela completata nel DB.
        # Per Binance non esiste connessione TWS equivalente — si usa sempre candle close.
        # Il prefetch parallelo sopra ha già popolato la cache TWS: questa chiamata
        # è praticamente gratuita (hit cache, nessun round-trip a TWS).
        _is_us_stock = (row_with_plan.provider or "") == "yahoo_finance"
        if _is_us_stock and _tws_svc_global is not None and _tws_svc_global.is_connected:
            try:
                # cache_only=True: usa solo la cache del prefetch parallelo fatto sopra.
                # Evita round-trip sequenziali a TWS per ogni simbolo nel loop (fino a 100s
                # con 40+ US stock × 2.5s timeout). Simboli non in cache → fallback candle.
                _live_price = await _tws_svc_global.get_last_price(
                    row_with_plan.symbol, cache_only=True
                )
                if _live_price is not None:
                    current_price = _live_price
                    price_source = "live_tws"
            except Exception as _lp_exc:
                logger.debug(
                    "get_last_price skipped %s: %s", row_with_plan.symbol, _lp_exc
                )

        if current_price is None and c is not None:
            current_price = float(c.close)
            price_source = "candle_close"

        entry_f = _trade_plan_price_float(tp.entry_price) if tp else None
        stop_f = _trade_plan_price_float(tp.stop_loss) if tp else None
        direction = (row_with_plan.latest_pattern_direction or "bullish").strip().lower()

        # ── Staleness pattern: pattern vecchio degrada la decisione ─────────────
        # pattern_stale=True significa che il segnale è stato rilevato più di
        # stale_threshold_bars fa — il setup potrebbe già essere scaduto.
        if row_with_plan.pattern_stale:
            age = row_with_plan.pattern_age_bars or 0
            thresh = row_with_plan.pattern_stale_threshold_bars or 0
            stale_msg = (
                f"Pattern rilevato {age} barre fa (soglia: {thresh}) — "
                "il momento ottimale di ingresso potrebbe essere già passato."
            )
            if v_dec == "execute":
                v_dec = "monitor"
                v_rationale = [stale_msg, "Attendere nuovo segnale o retest.", *list(v_rationale)]
            elif v_dec == "monitor":
                v_rationale = [stale_msg, *list(v_rationale)]

        if current_price is not None and entry_f is not None and entry_f > 0:
            is_stale, dist_pct, stale_reason = _price_stale_fields(
                current_price,
                entry_f,
                direction,
                threshold_pct,
                stop_f,
            )
            price_distance_pct = dist_pct
            if is_stale:
                price_stale = True
                price_stale_reason = stale_reason
            if v_dec == "execute" and is_stale:
                reason_line = stale_reason or "Prezzo lontano dall'entry."
                v_dec = "monitor"
                v_rationale = [
                    reason_line,
                    "Attendere retest dell'entry o nuovo segnale.",
                    *list(v_rationale),
                ]
            # ── Fix 2: price_stale degrada anche monitor → discard ───────────
            # Se il prezzo è già oltre la soglia di staleness su un setup che
            # era solo "monitor" (non eseguibile), l'entry è definitivamente
            # scaduta — non ha senso mostrarlo come opportunità da monitorare.
            elif v_dec == "monitor" and is_stale and entry_f is not None:
                reason_line = stale_reason or "Prezzo lontano dall'entry."
                v_dec = "discard"
                v_rationale = [
                    reason_line,
                    "Entry scaduta — setup non più operabile. Attendere nuovo segnale.",
                    *list(v_rationale),
                ]

        # ── ML Score (opzionale, non-blocking) ────────────────────────────────
        ml_score: float | None = None
        ml_filter_active = ml_is_enabled() and settings.ml_min_score > 0.0
        if ml_is_enabled() and row_with_plan.latest_pattern_name:
            try:
                vix_hist = await _get_vix_history()
                _lat_pat = by_series.get(
                    (row_with_plan.exchange, row_with_plan.symbol, row_with_plan.timeframe)
                )
                # Usa il contesto corrispondente a questa row, non la variabile `ctx`
                # del primo loop (che punterebbe all'ultimo contesto elaborato).
                _ctx_for_row = ctx_by_series.get(
                    (row_with_plan.provider, row_with_plan.exchange, row_with_plan.symbol, row_with_plan.timeframe)
                )
                feat = build_signal_feature_dict(
                    pat=_lat_pat,
                    ind=None,    # CandleIndicator non caricato in questo path (fill 0)
                    ctx=_ctx_for_row,
                    candle=c,
                    regime_filter=_rf_val,
                    vix_history=vix_hist,
                    earnings_cal=None,   # non disponibile qui senza fetch aggiuntivo
                    n_open_positions=0,
                    capital_available_pct=100.0,
                    pq_score=row_with_plan.pattern_quality_score,
                    stop_distance_pct=(
                        float(abs(tp.entry_price - tp.stop_loss) / tp.entry_price * 100)
                        if tp and tp.entry_price and tp.stop_loss else None
                    ),
                )
                ml_score = score_signal(feat)
            except Exception as _ml_exc:
                logger.debug("ML score skipped for %s: %s", row_with_plan.symbol, _ml_exc)

        if ml_filter_active and ml_score is not None and v_dec == "execute":
            # Soglia direction-aware: SHORT in regime BEAR usa ml_min_score_short
            # (il modello è addestrato su dati prevalentemente BULL → punteggi SHORT sistematicamente
            # inferiori; soglia ridotta evita di bloccare segnali short legittimi in bear market)
            is_short_signal = (row_with_plan.latest_pattern_direction or "").lower() == "bearish"
            short_threshold = settings.ml_min_score_short if settings.ml_min_score_short > 0.0 else None
            effective_threshold = (
                short_threshold if (is_short_signal and short_threshold is not None)
                else settings.ml_min_score
            )
            if ml_score < effective_threshold:
                v_dec = "monitor"
                v_rationale = [
                    f"ML score {ml_score:.2f} sotto la soglia minima ({effective_threshold:.2f}).",
                    "Pattern valido ma probabilità ML insufficiente — attendere conferma.",
                    *list(v_rationale),
                ]

        # ── IBKR Spread Filter (opzionale, non-blocking) ──────────────────────
        bid_ask_spread_pct: float | None = None
        live_volume_ratio: float | None = None
        ibkr_spread_filter_active = (
            settings.ibkr_enabled and settings.ibkr_max_spread_pct > 0.0
        )
        if ibkr_spread_filter_active and row_with_plan.latest_pattern_name:
            try:
                snap = await _get_ibkr_spread(row_with_plan.symbol)
                bid_ask_spread_pct = snap.get("spread_pct")

                # Calcola live_volume_ratio se abbiamo volume IBKR e candle corrente
                vol_live = snap.get("volume_live")
                if vol_live is not None and c is not None:
                    avg_vol = float(getattr(c, "volume", 0) or 0)
                    if avg_vol > 0:
                        live_volume_ratio = round(vol_live / avg_vol, 3)

                # Demotion se spread troppo ampio
                if (
                    bid_ask_spread_pct is not None
                    and bid_ask_spread_pct > settings.ibkr_max_spread_pct
                    and v_dec == "execute"
                ):
                    v_dec = "monitor"
                    v_rationale = [
                        f"Spread bid/ask {bid_ask_spread_pct:.2f}% > soglia {settings.ibkr_max_spread_pct:.2f}%.",
                        "Liquidità insufficiente — slippage potenziale elevato.",
                        *list(v_rationale),
                    ]
            except Exception as _sp_exc:
                logger.debug("Spread check skipped %s: %s", row_with_plan.symbol, _sp_exc)

        enriched.append(
            row_with_plan.model_copy(
                update={
                    "operational_decision": v_dec,
                    "decision_rationale": v_rationale,
                    "regime_spy": regime_spy,
                    "regime_direction_ok": regime_direction_ok,
                    "current_price": current_price,
                    "price_source": price_source,
                    "price_distance_pct": price_distance_pct,
                    "price_stale": price_stale,
                    "price_stale_reason": price_stale_reason,
                    "ml_score": ml_score,
                    "ml_filter_active": ml_filter_active,
                    "bid_ask_spread_pct": bid_ask_spread_pct,
                    "live_volume_ratio": live_volume_ratio,
                    "ibkr_spread_filter_active": ibkr_spread_filter_active,
                },
            ),
        )
    decision_code = map_decision_filter_param(decision)
    if decision_code is not None:
        enriched = [x for x in enriched if x.operational_decision == decision_code]

    # ── Filtro orario: nascondi segnali execute equity a mercato chiuso ──────
    # Applicato solo quando decision="execute" (live trading).
    # Per decision=None/monitor: i segnali restano visibili per analisi e prewarm cache.
    # Cripto (binance) non viene mai filtrata (24/7).
    if decision == "execute":
        enriched = [
            x for x in enriched
            if is_equity_market_active(x.provider)
        ]

    ordered = _post_enrich_sort(enriched)
    return ordered[:limit]


async def list_ranked_screener(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[RankedScreenerRow]:
    async def _fetch_ctx_screener() -> list[CandleContext]:
        async with AsyncSessionLocal() as s:
            return await list_latest_context_per_series(
                s, symbol=symbol, exchange=exchange, provider=provider,
                asset_type=asset_type, timeframe=timeframe,
            )

    async def _fetch_pats_screener() -> list[CandlePattern]:
        async with AsyncSessionLocal() as s:
            return await list_latest_pattern_per_series(
                s, symbol=symbol, exchange=exchange, provider=provider,
                asset_type=asset_type, timeframe=timeframe,
            )

    contexts, latest_patterns = await asyncio.gather(
        _fetch_ctx_screener(),
        _fetch_pats_screener(),
    )

    by_series: dict[tuple[str, str, str], CandlePattern] = {
        _pattern_key(p): p for p in latest_patterns
    }
    pq_key_ranked = opportunity_lookup_key(
        "pq",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=None,
        timeframe=timeframe,
    )

    async def _compute_pq_ranked() -> dict[tuple[str, str], PatternBacktestAggregateRow]:
        async with AsyncSessionLocal() as s:
            return await pattern_quality_lookup_by_name_tf(
                s,
                symbol=symbol,
                exchange=exchange,
                provider=provider,
                asset_type=None,
                timeframe=timeframe,
                dt_to=datetime.now(UTC),
            )

    pq_lookup = await pattern_quality_cache.get_or_compute(
        key=pq_key_ranked,
        compute=_compute_pq_ranked,
    )

    out: list[RankedScreenerRow] = []
    for ctx in contexts:
        snap = SnapshotForScoring(
            exchange=ctx.exchange,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            timestamp=ctx.timestamp,
            market_regime=ctx.market_regime,
            volatility_regime=ctx.volatility_regime,
            candle_expansion=ctx.candle_expansion,
            direction_bias=ctx.direction_bias,
        )
        scored = score_snapshot(snap)
        p = by_series.get((ctx.exchange, ctx.symbol, ctx.timeframe))
        pn = p.pattern_name if p is not None else None
        pq_score, pq_label = _pattern_quality_pair(pq_lookup, pn, ctx.timeframe)
        out.append(
            RankedScreenerRow(
                asset_type=ctx.asset_type,
                provider=ctx.provider,
                exchange=ctx.exchange,
                symbol=ctx.symbol,
                timeframe=ctx.timeframe,
                market_metadata=ctx.market_metadata,
                timestamp=ctx.timestamp,
                market_regime=ctx.market_regime,
                volatility_regime=ctx.volatility_regime,
                candle_expansion=ctx.candle_expansion,
                direction_bias=ctx.direction_bias,
                screener_score=scored.screener_score,
                score_label=scored.score_label,
                score_direction=scored.score_direction,
                latest_pattern_name=pn,
                pattern_quality_score=pq_score,
                pattern_quality_label=pq_label,
            )
        )

    ranked = _sort_ranked(out)
    return ranked[:limit]
