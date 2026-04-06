"""
Selezione della migliore variante di esecuzione per bucket (pattern, TF, provider, asset_type).

Usa i risultati di ``run_trade_plan_variant_backtest`` (righe flat per variante).
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    TRADE_PLAN_VARIANT_MIN_SAMPLE,
    TRADE_PLAN_VARIANT_PROMOTED_MIN_SAMPLE,
)
from app.schemas.backtest import (
    OperationalVariantStatus,
    TradePlanVariantBestResponse,
    TradePlanVariantBestRow,
    TradePlanVariantRow,
    TradePlanVariantStatusCounts,
)
from app.services.trade_plan_variant_backtest import run_trade_plan_variant_backtest


def _rank_key(r: TradePlanVariantRow) -> tuple[bool, float, int, float, float]:
    """
    Ordine di preferenza (tuple per max):
    0) expectancy > 0 prima di qualsiasi expectancy <= 0 (penalizzazione forte)
    1) expectancy più alta
    2) sample_size più alto
    3) stop_rate_given_entry più basso
    4) tp1_or_tp2_rate_given_entry più alto
    """
    exp = r.expectancy_r if r.expectancy_r is not None else -1e9
    sr = r.stop_rate_given_entry if r.stop_rate_given_entry is not None else 1.0
    tr = r.tp1_or_tp2_rate_given_entry if r.tp1_or_tp2_rate_given_entry is not None else 0.0
    positive_expectancy = exp > 0
    return (positive_expectancy, exp, r.sample_size, -sr, tr)


def pick_best_variant_for_bucket(rows: list[TradePlanVariantRow]) -> TradePlanVariantRow | None:
    """
    Tra le varianti dello stesso bucket:
    - per il ranking principale usano solo righe con sample_size >= TRADE_PLAN_VARIANT_MIN_SAMPLE;
    - se nessuna le supera, si usa la variante con sample_size massimo (tutte «non affidabili»).
    """
    if not rows:
        return None
    reliable = [r for r in rows if r.sample_size >= TRADE_PLAN_VARIANT_MIN_SAMPLE]
    pool = reliable if reliable else rows
    return max(pool, key=_rank_key)


def classify_operational_status(r: TradePlanVariantRow) -> OperationalVariantStatus:
    if r.sample_size < TRADE_PLAN_VARIANT_MIN_SAMPLE:
        return "rejected"
    if r.expectancy_r is None or r.expectancy_r <= 0:
        return "rejected"
    if r.sample_size >= TRADE_PLAN_VARIANT_PROMOTED_MIN_SAMPLE:
        return "promoted"
    return "watchlist"


def trade_plan_variant_row_to_best_row(r: TradePlanVariantRow) -> TradePlanVariantBestRow:
    return TradePlanVariantBestRow(
        pattern_name=r.pattern_name,
        timeframe=r.timeframe,
        provider=r.provider,
        asset_type=r.asset_type,
        best_variant_label=r.variant_label,
        entry_strategy=r.entry_strategy,
        stop_profile=r.stop_profile,
        tp_profile=r.tp_profile,
        sample_size=r.sample_size,
        entry_trigger_rate=r.entry_trigger_rate,
        stop_rate_given_entry=r.stop_rate_given_entry,
        tp1_or_tp2_rate_given_entry=r.tp1_or_tp2_rate_given_entry,
        avg_r=r.avg_r,
        expectancy_r=r.expectancy_r,
        operational_status=classify_operational_status(r),
    )


def build_best_rows_from_variant_rows(
    rows: list[TradePlanVariantRow],
) -> list[TradePlanVariantBestRow]:
    by_bucket: dict[tuple[str, str, str, str], list[TradePlanVariantRow]] = defaultdict(list)
    for r in rows:
        k = (r.pattern_name, r.timeframe, r.provider, r.asset_type)
        by_bucket[k].append(r)

    out: list[TradePlanVariantBestRow] = []
    for _k, bucket_rows in sorted(by_bucket.items()):
        best = pick_best_variant_for_bucket(bucket_rows)
        if best is None:
            continue
        out.append(trade_plan_variant_row_to_best_row(best))
    return out


def count_by_operational_status(rows: list[TradePlanVariantBestRow]) -> TradePlanVariantStatusCounts:
    p = w = rej = 0
    for r in rows:
        if r.operational_status == "promoted":
            p += 1
        elif r.operational_status == "watchlist":
            w += 1
        else:
            rej += 1
    return TradePlanVariantStatusCounts(promoted=p, watchlist=w, rejected=rej)


def filter_best_rows_by_scope(
    rows: list[TradePlanVariantBestRow],
    scope: str,
) -> list[TradePlanVariantBestRow]:
    """
    scope:
    - promoted_watchlist: solo promoted e watchlist (default UI)
    - all: nessun filtro
    - promoted | watchlist | rejected: singolo stato
    """
    s = scope.strip().lower()
    if s in ("", "all"):
        return rows
    if s == "promoted_watchlist":
        return [r for r in rows if r.operational_status in ("promoted", "watchlist")]
    if s in ("promoted", "watchlist", "rejected"):
        return [r for r in rows if r.operational_status == s]
    return rows


_TF_ORDER = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")


def build_insights(rows: list[TradePlanVariantBestRow]) -> list[str]:
    """Euristiche leggere su timeframe, sample e stato (testo IT)."""
    if not rows:
        return ["Nessun bucket disponibile per insight automatici."]

    by_tf: dict[str, list[TradePlanVariantBestRow]] = defaultdict(list)
    for r in rows:
        by_tf[r.timeframe].append(r)

    def tf_sort_key(tf: str) -> tuple[int, str]:
        try:
            return (_TF_ORDER.index(tf), tf)
        except ValueError:
            return (99, tf)

    insights: list[str] = []

    scored: list[tuple[str, int, float, int]] = []
    for tf, lst in by_tf.items():
        good = sum(1 for r in lst if r.operational_status in ("promoted", "watchlist"))
        avg_s = sum(r.sample_size for r in lst) / len(lst)
        scored.append((tf, good, avg_s, len(lst)))
    scored.sort(key=lambda x: (-x[1], -x[2], tf_sort_key(x[0])))
    best_tf: str | None = scored[0][0] if scored and scored[0][1] > 0 else None
    if best_tf is not None:
        insights.append(
            f"I bucket più robusti oggi sono concentrati su {best_tf}.",
        )

    weak_msgs: list[str] = []
    for tf, lst in sorted(by_tf.items(), key=lambda kv: tf_sort_key(kv[0])):
        if tf == best_tf:
            continue
        avg_s = sum(r.sample_size for r in lst) / len(lst)
        prom_wl = sum(1 for r in lst if r.operational_status in ("promoted", "watchlist"))
        if len(lst) >= 2 and (avg_s < float(TRADE_PLAN_VARIANT_MIN_SAMPLE) or prom_wl == 0):
            weak_msgs.append(
                f"I {tf} hanno pochi campioni o risultati contrastanti.",
            )
    insights.extend(weak_msgs[:2])

    if "15m" in by_tf:
        lst15 = by_tf["15m"]
        reliable_n = sum(1 for r in lst15 if r.sample_size >= TRADE_PLAN_VARIANT_MIN_SAMPLE)
        good_stat = sum(1 for r in lst15 if r.operational_status in ("promoted", "watchlist"))
        if reliable_n == 0 or good_stat == 0:
            insights.append(
                "I 15m risultano ancora non affidabili per il trade plan variant backtest.",
            )

    out: list[str] = []
    seen: set[str] = set()
    for line in insights:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out[:6]


async def run_trade_plan_variant_best(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
    status_scope: str = "promoted_watchlist",
    operational_status: str | None = None,
    cost_rate: float = BACKTEST_TOTAL_COST_RATE_DEFAULT,
) -> TradePlanVariantBestResponse:
    """Esegue il backtest varianti completo e restituisce la migliore variante per bucket."""
    v = await run_trade_plan_variant_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
        cost_rate=cost_rate,
    )
    all_best = build_best_rows_from_variant_rows(v.rows)
    counts = count_by_operational_status(all_best)
    insights = build_insights(all_best)

    scope = status_scope.strip().lower()
    if operational_status and operational_status.strip():
        scope = operational_status.strip().lower()
    filtered = filter_best_rows_by_scope(all_best, scope)

    return TradePlanVariantBestResponse(
        rows=filtered,
        total_buckets_evaluated=len(all_best),
        counts_by_status=counts,
        insights=insights,
        patterns_evaluated=v.patterns_evaluated,
        min_sample_for_reliable_rank=TRADE_PLAN_VARIANT_MIN_SAMPLE,
        trade_plan_engine_version=v.trade_plan_engine_version,
        backtest_cost_rate_rt=cost_rate,
    )
