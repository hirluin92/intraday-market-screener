"""
Trade Plan Backtest v1 — validazione forward dei piani prodotti da **Trade Plan Engine v1.1**
(``app.services.trade_plan_engine.build_trade_plan_v1``).

Campi simulati dal piano: ``trade_direction``, ``entry_strategy``, ``entry_price``, ``stop_loss``,
``take_profit_1``, ``take_profit_2`` (livelli e strategia coerenti col motore v1.1).

- **Ingresso**: tocco del prezzo a ``entry_price``; per ``entry_strategy == close`` la ricerca
  parte dalla **prima barra dopo** il segnale (conferma dopo chiusura barra); per ``breakout`` /
  ``retest`` anche il bar del segnale è ammesso se il range tocca il livello.
- **Uscita**: stessa candela — stop prima (conservativo); poi TP1 prima di TP2 se entrambi
  toccati (si assume il target più vicino raggiunto per primo).

MVP: niente persistenza; aggregati on-demand come ``run_pattern_backtest``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    PATTERN_QUALITY_MIN_SAMPLE,
)
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import PatternBacktestAggregateRow, TradePlanBacktestAggregateRow, TradePlanBacktestResponse
from app.schemas.trade_plan import TradePlanV1
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
    final_opportunity_label_from_score,
)
from app.services.pattern_quality import (
    binomial_test_vs_50pct,
    pattern_quality_label_from_score,
    sample_reliability_label,
    significance_label,
    ttest_expectancy_vs_zero,
    wilson_confidence_interval,
)
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.trade_plan_engine import build_trade_plan_v1

# Finestre forward (barre dello stesso timeframe)
MAX_BARS_ENTRY_SCAN = 20
MAX_BARS_AFTER_ENTRY = 48

Outcome = Literal["stop", "tp1", "tp2", "timeout"]


@dataclass(frozen=True, slots=True)
class TradePlanExecutionResult:
    """Risultato simulazione forward con barre di ingresso/uscita (per tracking capitale)."""

    pnl_r: float
    outcome: Outcome
    entry_bar_index: int
    exit_bar_index: int
    entry_timestamp: datetime
    exit_timestamp: datetime


def _cost_r(entry: Decimal, risk: Decimal, cost_rate: float) -> float:
    """
    Costo round-trip espresso in R-multipli.

    cost_rate: frazione del notional (es. 0.0015 per 0.15% round-trip).
    risk: distanza assoluta entry→stop in unità di prezzo (già Decimal).

    Il costo è simmetrico: viene pagato sia all'apertura che alla chiusura
    indipendentemente dall'esito (stop, TP, timeout).
    """
    if risk <= 0 or entry <= 0:
        return 0.0
    return float(cost_rate) * float(entry / risk)


def _d(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _pattern_quality_pair(
    lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    pattern_name: str | None,
    timeframe: str,
) -> tuple[float | None, str]:
    if not pattern_name:
        return None, "unknown"
    agg = lookup.get((pattern_name, timeframe))
    if agg is None:
        return None, "unknown"
    score = agg.pattern_quality_score
    return score, pattern_quality_label_from_score(score)


def _touch_entry(c: Candle, entry: Decimal) -> bool:
    lo = _d(c.low)
    hi = _d(c.high)
    return lo <= entry <= hi


def _find_entry_bar(
    candles: list[Candle],
    start_idx: int,
    entry: Decimal,
    max_scan: int,
) -> int | None:
    end = min(start_idx + max_scan, len(candles))
    for i in range(start_idx, end):
        if _touch_entry(candles[i], entry):
            return i
    return None


def _entry_scan_start_idx(pattern_idx: int, entry_strategy: str) -> int:
    """
    v1.1: strategia «close» = ingresso dopo la chiusura del bar segnale → niente fill sullo stesso bar.
    Breakout/retest: si può toccare il livello già sul bar del pattern.
    """
    es = (entry_strategy or "close").lower()
    if es == "close":
        return pattern_idx + 1
    return pattern_idx


def _simulate_long_after_entry(
    candles: list[Candle],
    entry_idx: int,
    *,
    entry: Decimal,
    stop: Decimal,
    tp1: Decimal,
    tp2: Decimal,
    max_bars: int,
    cost_rate: float = 0.0,
) -> tuple[Outcome, float, int]:
    """
    Long: stop sotto; TP sopra (tp1 più vicino, tp2 più lontano).
    Stessa candela: stop prima; poi TP1 prima di TP2 se entrambi toccati (conservativo).
    Ritorna anche l'indice della candela di uscita.
    """
    risk = entry - stop
    cr = _cost_r(entry, risk, cost_rate)
    if risk <= 0:
        return "stop", -(1.0 + cr), entry_idx
    end = min(entry_idx + max_bars, len(candles))
    for k in range(entry_idx, end):
        c = candles[k]
        lo, hi = _d(c.low), _d(c.high)
        # Stop ha priorità su qualsiasi TP (conservativo).
        if lo <= stop:
            return "stop", -(1.0 + cr), k
        # TP2 (più lontano) controllato PRIMA di TP1: se hi >= tp2 > tp1,
        # senza questo ordine il check su tp1 scatterebbe sempre per primo
        # e tp2 risulterebbe irraggiungibile come outcome separato.
        if hi >= tp2:
            return "tp2", float((tp2 - entry) / risk) - cr, k
        if hi >= tp1:
            return "tp1", float((tp1 - entry) / risk) - cr, k
    last_k = entry_idx if end <= entry_idx else end - 1
    return "timeout", -cr, last_k


def _simulate_short_after_entry(
    candles: list[Candle],
    entry_idx: int,
    *,
    entry: Decimal,
    stop: Decimal,
    tp1: Decimal,
    tp2: Decimal,
    max_bars: int,
    cost_rate: float = 0.0,
) -> tuple[Outcome, float, int]:
    """
    Short: stop sopra; TP sotto (tp1 più vicino al prezzo, tp2 più lontano in basso).
    Stessa candela: stop prima; poi TP1 prima di TP2 se entrambi toccati (conservativo).
    Ritorna anche l'indice della candela di uscita.
    """
    risk = stop - entry
    cr = _cost_r(entry, risk, cost_rate)
    if risk <= 0:
        return "stop", -(1.0 + cr), entry_idx
    end = min(entry_idx + max_bars, len(candles))
    for k in range(entry_idx, end):
        c = candles[k]
        lo, hi = _d(c.low), _d(c.high)
        # Stop ha priorità su qualsiasi TP (conservativo).
        if hi >= stop:
            return "stop", -(1.0 + cr), k
        # TP2 (più lontano per short = prezzo più basso) controllato PRIMA di TP1:
        # senza questo ordine il check su tp1 scatterebbe sempre per primo
        # e tp2 risulterebbe irraggiungibile come outcome separato.
        if lo <= tp2:
            return "tp2", float((entry - tp2) / risk) - cr, k
        if lo <= tp1:
            return "tp1", float((entry - tp1) / risk) - cr, k
    last_k = entry_idx if end <= entry_idx else end - 1
    return "timeout", -cr, last_k


def _eligible_plan(plan: TradePlanV1) -> bool:
    if plan.trade_direction not in ("long", "short"):
        return False
    if (
        plan.stop_loss is None
        or plan.take_profit_1 is None
        or plan.take_profit_2 is None
        or plan.entry_price is None
    ):
        return False
    return True


def _simulate_one(
    candles: list[Candle],
    pattern_idx: int,
    plan: TradePlanV1,
    cost_rate: float = 0.0,
) -> tuple[bool, Outcome | None, float | None]:
    """
    Ritorna (entry_triggered, outcome, r_multiple).
    Usa ``plan.trade_direction`` per il ramo long/short e ``plan.entry_strategy`` per l’inizio
    della finestra di ricerca ingresso (v1.1).
    """
    if not _eligible_plan(plan):
        return False, None, None
    assert plan.entry_price is not None
    assert plan.stop_loss is not None
    assert plan.take_profit_1 is not None
    assert plan.take_profit_2 is not None

    entry_px = _d(plan.entry_price)
    stop = _d(plan.stop_loss)
    tp1 = _d(plan.take_profit_1)
    tp2 = _d(plan.take_profit_2)

    scan_from = _entry_scan_start_idx(pattern_idx, plan.entry_strategy)
    entry_bar = _find_entry_bar(candles, scan_from, entry_px, MAX_BARS_ENTRY_SCAN)
    if entry_bar is None:
        return False, None, None

    if plan.trade_direction == "long":
        out, r, _exit_k = _simulate_long_after_entry(
            candles,
            entry_bar,
            entry=entry_px,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY,
            cost_rate=cost_rate,
        )
        return True, out, r
    out, r, _exit_k = _simulate_short_after_entry(
        candles,
        entry_bar,
        entry=entry_px,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        max_bars=MAX_BARS_AFTER_ENTRY,
        cost_rate=cost_rate,
    )
    return True, out, r


def _simulate_one_with_timing(
    candles: list[Candle],
    pattern_idx: int,
    plan: TradePlanV1,
    cost_rate: float = 0.0,
) -> TradePlanExecutionResult | None:
    """
    Come ``_simulate_one`` ma con timestamp barra ingresso/uscita reali dalla serie candele.
    """
    if not _eligible_plan(plan):
        return None
    assert plan.entry_price is not None
    assert plan.stop_loss is not None
    assert plan.take_profit_1 is not None
    assert plan.take_profit_2 is not None

    entry_px = _d(plan.entry_price)
    stop = _d(plan.stop_loss)
    tp1 = _d(plan.take_profit_1)
    tp2 = _d(plan.take_profit_2)

    scan_from = _entry_scan_start_idx(pattern_idx, plan.entry_strategy)
    entry_bar = _find_entry_bar(candles, scan_from, entry_px, MAX_BARS_ENTRY_SCAN)
    if entry_bar is None:
        return None

    if plan.trade_direction == "long":
        out, r, exit_k = _simulate_long_after_entry(
            candles,
            entry_bar,
            entry=entry_px,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY,
            cost_rate=cost_rate,
        )
    else:
        out, r, exit_k = _simulate_short_after_entry(
            candles,
            entry_bar,
            entry=entry_px,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY,
            cost_rate=cost_rate,
        )

    ec = candles[entry_bar]
    xc = candles[exit_k]
    return TradePlanExecutionResult(
        pnl_r=r,
        outcome=out,
        entry_bar_index=entry_bar,
        exit_bar_index=exit_k,
        entry_timestamp=ec.timestamp,
        exit_timestamp=xc.timestamp,
    )


def simulate_trade_plan_forward(
    candles: list[Candle],
    pattern_idx: int,
    plan: TradePlanV1,
    cost_rate: float = 0.0,
) -> tuple[bool, Outcome | None, float | None]:
    """API pubblica per altri moduli (es. variant backtest) senza importare simboli privati."""
    return _simulate_one(candles, pattern_idx, plan, cost_rate=cost_rate)


def trade_plan_eligible_for_simulation(plan: TradePlanV1) -> bool:
    return _eligible_plan(plan)


def build_trade_plan_v1_for_stored_pattern(
    pat: CandlePattern,
    candle: Candle,
    ctx: CandleContext,
    pq_lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
) -> TradePlanV1:
    """
    Stessa pipeline di ``run_trade_plan_backtest`` per un singolo segnale:
    scoring contesto + ``build_trade_plan_v1`` (livelli da Trade Plan Engine v1.1).
    """
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
    pq_score, pq_label = _pattern_quality_pair(pq_lookup, pat.pattern_name, pat.timeframe)
    base_final = compute_final_opportunity_score(
        screener_score=scored.screener_score,
        score_direction=scored.score_direction,
        latest_pattern_direction=pat.direction,
        pattern_quality_score=pq_score,
        pattern_quality_label=pq_label,
        latest_pattern_strength=pat.pattern_strength,
    )
    final, _tf_ok, tf_gate, _tf_f = apply_pattern_timeframe_policy(
        has_pattern=True,
        pattern_quality_score=pq_score,
        _pattern_quality_label=pq_label,
        base_final_opportunity_score=base_final,
    )
    final_lbl = final_opportunity_label_from_score(final)

    return build_trade_plan_v1(
        final_opportunity_label=final_lbl,
        final_opportunity_score=final,
        score_direction=scored.score_direction,
        latest_pattern_direction=pat.direction,
        latest_pattern_name=pat.pattern_name,
        candle_expansion=ctx.candle_expansion,
        pattern_timeframe_gate_label=tf_gate,
        volatility_regime=ctx.volatility_regime,
        market_regime=ctx.market_regime,
        candle_high=candle.high,
        candle_low=candle.low,
        candle_close=candle.close,
    )


def compute_trade_plan_execution_from_pattern_row(
    pat: CandlePattern,
    candle: Candle,
    ctx: CandleContext,
    clist: list[Candle],
    idx: int,
    pq_lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    cost_rate: float,
) -> TradePlanExecutionResult | None:
    """
    Simulazione forward con barre ingresso/uscita (stesso motore di ``_simulate_one``).
    ``None`` se piano non idoneo o ingresso non triggerato.
    """
    plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)
    if not _eligible_plan(plan):
        return None
    return _simulate_one_with_timing(clist, idx, plan, cost_rate=cost_rate)


def compute_trade_plan_pnl_from_pattern_row(
    pat: CandlePattern,
    candle: Candle,
    ctx: CandleContext,
    clist: list[Candle],
    idx: int,
    pq_lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    cost_rate: float,
) -> tuple[float, Outcome] | None:
    """
    R (multiplo) e outcome forward come ``run_trade_plan_backtest`` / ``_simulate_one``.
    ``None`` se piano non idoneo o ingresso non triggerato. I costi sono già inclusi in R (``_cost_r``).
    """
    ex = compute_trade_plan_execution_from_pattern_row(
        pat, candle, ctx, clist, idx, pq_lookup, cost_rate
    )
    if ex is None:
        return None
    return ex.pnl_r, ex.outcome


async def run_trade_plan_backtest(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
    cost_rate: float = BACKTEST_TOTAL_COST_RATE_DEFAULT,
) -> TradePlanBacktestResponse:
    stmt = (
        select(CandlePattern, Candle, CandleContext)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
        .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
    )
    conds = []
    if exchange is not None:
        conds.append(CandlePattern.exchange == exchange)
    if provider is not None:
        conds.append(CandlePattern.provider == provider)
    if asset_type is not None:
        conds.append(CandlePattern.asset_type == asset_type)
    if symbol is not None:
        conds.append(CandlePattern.symbol == symbol)
    if timeframe is not None:
        conds.append(CandlePattern.timeframe == timeframe)
    if pattern_name is not None:
        conds.append(CandlePattern.pattern_name == pattern_name)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(CandlePattern.timestamp.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.all())
    patterns_evaluated = len(rows)
    if not rows:
        return TradePlanBacktestResponse(
            aggregates=[],
            trade_plan_engine_version="1.1",
            patterns_evaluated=0,
            eligible_trade_plans=0,
            backtest_cost_rate_rt=cost_rate,
        )

    # Nota: quality lookup calcolata sull'INTERO storico disponibile (nessun dt_to).
    # Introduce un look-ahead bias moderato: i pattern di backtest più vecchi ricevono
    # un pq_score calcolato su campioni successivi a loro stessi. Per un'analisi
    # rigorosa senza look-ahead usare run_simulation con use_temporal_quality=True.
    pq_lookup = await pattern_quality_lookup_by_name_tf(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )

    series_keys: set[tuple[str, str, str]] = set()
    for p, _, _ in rows:
        series_keys.add((p.exchange, p.symbol, p.timeframe))

    or_parts = [
        and_(Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf)
        for ex, sym, tf in series_keys
    ]
    c_stmt = select(Candle).where(or_(*or_parts)).order_by(
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.timestamp.asc(),
    )
    c_result = await session.execute(c_stmt)
    all_candles = list(c_result.scalars().all())

    by_series: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
    for c in all_candles:
        by_series[(c.exchange, c.symbol, c.timeframe)].append(c)

    id_to_index: dict[tuple[str, str, str], dict[int, int]] = {}
    for key, clist in by_series.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    # bucket -> lists for aggregation
    bucket: dict[
        tuple[str, str, str, str],
        dict[str, list],
    ] = defaultdict(
        lambda: {
            "r_list": [],
            "r_per_signal": [],
            "entry_touch": 0,
            "stop": 0,
            "tp1": 0,
            "tp2": 0,
            "timeout": 0,
            "sample": 0,
        },
    )

    eligible = 0

    for pat, candle, ctx in rows:
        key_s = (pat.exchange, pat.symbol, pat.timeframe)
        clist = by_series.get(key_s)
        idx_map = id_to_index.get(key_s)
        if not clist or not idx_map:
            continue
        idx = idx_map.get(candle.id)
        if idx is None:
            continue

        plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)

        if not _eligible_plan(plan):
            continue
        eligible += 1

        bkey = (pat.pattern_name, pat.timeframe, pat.provider, pat.asset_type)
        bucket[bkey]["sample"] += 1

        entry_ok, outcome, r_mult = _simulate_one(clist, idx, plan, cost_rate=cost_rate)
        if not entry_ok:
            bucket[bkey]["r_per_signal"].append(0.0)
            continue
        bucket[bkey]["entry_touch"] += 1
        assert outcome is not None and r_mult is not None
        bucket[bkey]["r_list"].append(r_mult)
        bucket[bkey]["r_per_signal"].append(r_mult)
        if outcome == "stop":
            bucket[bkey]["stop"] += 1
        elif outcome == "tp1":
            bucket[bkey]["tp1"] += 1
        elif outcome == "tp2":
            bucket[bkey]["tp2"] += 1
        else:
            bucket[bkey]["timeout"] += 1

    aggregates: list[TradePlanBacktestAggregateRow] = []
    for key in sorted(bucket.keys()):
        pn, tf, prov, at = key
        data = bucket[key]
        n = data["sample"]
        et = data["entry_touch"]
        rlist: list[float] = data["r_list"]
        r_per_signal: list[float] = data["r_per_signal"]
        sum_r = sum(rlist)
        avg_r = sum_r / et if et else None
        expectancy_per_signal = sum_r / n if n else None
        tp1_or_tp2 = data["tp1"] + data["tp2"]
        sh = data["stop"]

        tpb_rel = sample_reliability_label(et)
        if et < PATTERN_QUALITY_MIN_SAMPLE:
            ci_lo = ci_hi = None
        else:
            ci_lo, ci_hi = wilson_confidence_interval(tp1_or_tp2, et)

        win_p = binomial_test_vs_50pct(tp1_or_tp2, et) if et > 0 else None
        win_sig = significance_label(win_p) if win_p is not None else None
        exp_p: float | None = None
        exp_sig: str | None = None
        if len(r_per_signal) >= 2:
            _, exp_p = ttest_expectancy_vs_zero(r_per_signal)
            exp_sig = significance_label(exp_p)

        aggregates.append(
            TradePlanBacktestAggregateRow(
                pattern_name=pn,
                timeframe=tf,
                provider=prov,
                asset_type=at,
                sample_size=n,
                entry_triggered=et,
                stop_hits=sh,
                tp1_hits=data["tp1"],
                tp2_hits=data["tp2"],
                tp1_or_tp2_hits=tp1_or_tp2,
                timed_out=data["timeout"],
                entry_trigger_rate=(et / n) if n else None,
                stop_rate_of_sample=(sh / n) if n else None,
                stop_rate_given_entry=(sh / et) if et else None,
                tp1_rate_given_entry=(data["tp1"] / et) if et else None,
                tp2_rate_given_entry=(data["tp2"] / et) if et else None,
                tp1_or_tp2_rate_given_entry=(tp1_or_tp2 / et) if et else None,
                avg_r=round(avg_r, 4) if avg_r is not None else None,
                expectancy_r=round(expectancy_per_signal, 4) if expectancy_per_signal is not None else None,
                win_rate_ci_lower=ci_lo,
                win_rate_ci_upper=ci_hi,
                sample_reliability=tpb_rel,
                win_rate_pvalue=win_p,
                win_rate_significance=win_sig,
                expectancy_r_pvalue=exp_p,
                expectancy_r_significance=exp_sig,
            )
        )

    return TradePlanBacktestResponse(
        aggregates=aggregates,
        trade_plan_engine_version="1.1",
        patterns_evaluated=patterns_evaluated,
        eligible_trade_plans=eligible,
        backtest_cost_rate_rt=cost_rate,
    )


# Stesso limite dell’aggregato pattern quality: universo allineato alle opportunità.
TRADE_PLAN_BACKTEST_LOOKUP_LIMIT = 5000


async def trade_plan_backtest_lookup_by_bucket(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    cost_rate: float = BACKTEST_TOTAL_COST_RATE_DEFAULT,
) -> dict[tuple[str, str, str, str], TradePlanBacktestAggregateRow]:
    """
    Mappa (pattern_name, timeframe, provider, asset_type) → riga aggregata backtest trade plan.
    Chiavi assenti = nessun dato per quel bucket nello storico valutato.
    """
    resp = await run_trade_plan_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=None,
        limit=TRADE_PLAN_BACKTEST_LOOKUP_LIMIT,
        cost_rate=cost_rate,
    )
    return {
        (a.pattern_name, a.timeframe, a.provider, a.asset_type): a
        for a in resp.aggregates
    }
