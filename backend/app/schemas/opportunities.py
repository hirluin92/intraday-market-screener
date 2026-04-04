from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.trade_plan import TradePlanV1


class OpportunityRow(BaseModel):
    """Latest context snapshot per series plus optional latest detected pattern (computed, not persisted)."""

    asset_type: str = Field(
        default="crypto",
        description="Instrument class (crypto | stock | etf | index).",
    )
    provider: str = Field(
        default="binance",
        description="Data provider id for this series.",
    )
    exchange: str = Field(description="Venue / exchange id (connector-specific).")
    symbol: str
    timeframe: str
    market_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional market/session metadata from stored context.",
    )
    timestamp: datetime = Field(
        description="Series context bar time; same as context_timestamp.",
    )
    context_timestamp: datetime = Field(
        description="Timestamp of the latest CandleContext row for this series.",
    )
    pattern_timestamp: datetime | None = Field(
        default=None,
        description="Timestamp of the latest CandlePattern row for this series, if any.",
    )
    pattern_age_bars: int | None = Field(
        default=None,
        description=(
            "Barre di ritardo tra pattern_timestamp e context_timestamp sullo stesso TF "
            "(0 = allineato alla barra di contesto). Null se nessun pattern o TF non parsabile."
        ),
    )
    pattern_stale: bool = Field(
        default=False,
        description=(
            "True se pattern_age_bars supera la soglia per il timeframe (pattern vecchio vs contesto)."
        ),
    )
    pattern_stale_threshold_bars: int = Field(
        default=5,
        description=(
            "Soglia in barre per questo timeframe (stessa usata per pattern_stale); "
            "allineata a STALE_THRESHOLD_BARS_BY_TIMEFRAME nel backend."
        ),
    )
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str
    screener_score: int = Field(
        description="Dominant directional score (0–12): stronger of long vs short leg.",
    )
    score_label: str = Field(
        description="Strength band + direction, e.g. strong_bullish, moderate_bearish, mild_neutral.",
    )
    score_direction: str = Field(
        description=(
            "Directional interpretation of the live screener context (headline score): "
            "bullish | bearish | neutral."
        ),
    )
    latest_pattern_name: str | None = None
    latest_pattern_strength: Decimal | None = Field(
        default=None,
        description="Strength of the latest pattern for this series, if any.",
    )
    latest_pattern_direction: str | None = Field(
        default=None,
        description=(
            "Direction implied by the latest detected pattern on this series: "
            "bullish | bearish | neutral, when a pattern exists."
        ),
    )
    pattern_quality_score: float | None = Field(
        default=None,
        description="Backtest quality 0–100 for (latest_pattern_name, timeframe), or null.",
    )
    pattern_quality_label: str = Field(
        default="unknown",
        description="high | medium | low | unknown (from score + backtest match).",
    )
    final_opportunity_score: float = Field(
        description=(
            "Score dopo policy TF + aggiustamento **soft** Trade Plan Backtest (ranking/display). "
            "Gli alert usano lo score pre-TPB (final_opportunity_score_before_trade_plan_backtest)."
        ),
    )
    final_opportunity_label: str = Field(
        description="strong | moderate | weak | minimal (band for final_opportunity_score).",
    )
    pattern_timeframe_quality_ok: bool | None = Field(
        default=None,
        description=(
            "True if backtest quality on this timeframe is acceptable for the pattern; "
            "False if marginal/poor/unknown; null if there is no pattern."
        ),
    )
    pattern_timeframe_gate_label: str = Field(
        description=(
            "na | ok | marginal | poor | unknown — outcome of pattern-timeframe quality policy."
        ),
    )
    pattern_timeframe_filtered_candidate: bool = Field(
        default=False,
        description=(
            "True when historical quality on this TF is clearly poor (heavy penalty applied)."
        ),
    )
    alert_candidate: bool = Field(
        description=(
            "True quando le regole MVP alert passano (allineamento, TF OK, banda qualità, "
            "soglia score). La soglia score si applica a **final_opportunity_score_before_trade_plan_backtest**, "
            "non al punteggio dopo l'aggiustamento soft TPB."
        ),
    )
    alert_level: str = Field(
        description=(
            "alta_priorita | media_priorita | nessun_alert — derived alert tier (v1, tunable in code)."
        ),
    )
    trade_plan: TradePlanV1 | None = Field(
        default=None,
        description="Piano operativo v1 derivato (rule-based, non persistito).",
    )
    final_opportunity_score_before_trade_plan_backtest: float | None = Field(
        default=None,
        description=(
            "Score dopo policy pattern–timeframe, prima dell'aggiustamento da Trade Plan Backtest v1."
        ),
    )
    trade_plan_backtest_score_delta: float = Field(
        default=0.0,
        description="Delta soft sul score (malus/bonus piccoli, limitati in modulo).",
    )
    trade_plan_backtest_adjustment_label: str = Field(
        default="none",
        description=(
            "Regole soft: no_pattern | no_bucket | neutral | soft_malus_exp | soft_bonus_exp | soft_malus_exp+…"
        ),
    )
    operational_confidence: str = Field(
        default="unknown",
        description=(
            "high | medium | low | unknown — cautela operativa da TPB (visibilità, non filtro duro)."
        ),
    )
    trade_plan_backtest_expectancy_r: float | None = Field(
        default=None,
        description="Expectancy R del bucket backtest (stesso universo filtri), se presente.",
    )
    trade_plan_backtest_sample_size: int | None = Field(
        default=None,
        description="Sample size del bucket backtest trade plan, se presente.",
    )
    selected_trade_plan_variant: str | None = Field(
        default=None,
        description="Label best variant (entry|stop|tp) se il piano usa variant backtest.",
    )
    selected_trade_plan_variant_status: str | None = Field(
        default=None,
        description="promoted | watchlist | rejected — stato del bucket best variant.",
    )
    selected_trade_plan_variant_sample_size: int | None = Field(
        default=None,
        description="Sample del bucket best variant (informativo).",
    )
    selected_trade_plan_variant_expectancy_r: float | None = Field(
        default=None,
        description="Expectancy R storica della best variant selezionata.",
    )
    trade_plan_source: Literal["variant_backtest", "default_fallback"] = Field(
        default="default_fallback",
        description="variant_backtest se parametri da best variant live; altrimenti motore standard.",
    )
    trade_plan_fallback_reason: str | None = Field(
        default=None,
        description=(
            "Se trade_plan_source=default_fallback: no_pattern | no_variant_bucket | "
            "variant_rejected | watchlist_insufficient_sample. Null se variant_backtest."
        ),
    )
    operational_decision: Literal["operable", "monitor", "discard"] = Field(
        default="monitor",
        description="Semaforo operativo: operable | monitor | discard.",
    )
    decision_rationale: list[str] = Field(
        default_factory=list,
        description="2–4 righe IT per UI «Perché» (motivazione sintetica).",
    )


class OpportunitiesResponse(BaseModel):
    opportunities: list[OpportunityRow]
    count: int
