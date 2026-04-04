from typing import Literal

from pydantic import BaseModel, Field


class PatternBacktestAggregateRow(BaseModel):
    """Aggregated forward returns by pattern label and timeframe (on-demand, no persistence)."""

    pattern_name: str
    timeframe: str
    sample_size: int = Field(
        description="Patterns with at least +1 forward candle (same count basis for horizon 1).",
    )
    sample_size_3: int = Field(description="Patterns with at least +3 forward candles.")
    sample_size_5: int = Field(description="Patterns with at least +5 forward candles.")
    sample_size_10: int = Field(description="Patterns with at least +10 forward candles.")
    avg_return_1: float | None = None
    avg_return_3: float | None = None
    avg_return_5: float | None = None
    avg_return_10: float | None = None
    win_rate_1: float | None = Field(
        default=None,
        description="Share of wins at horizon 1 (0–1). Direction-aware.",
    )
    win_rate_3: float | None = None
    win_rate_5: float | None = None
    win_rate_10: float | None = None
    pattern_quality_score: float | None = Field(
        default=None,
        description="Heuristic 0–100 from win rate, avg return, and sample depth (horizon 5→3).",
    )


class PatternBacktestResponse(BaseModel):
    aggregates: list[PatternBacktestAggregateRow]
    patterns_evaluated: int = Field(
        description="Stored pattern rows used as signals (after filters, before horizon drops).",
    )


class TradePlanBacktestAggregateRow(BaseModel):
    """Statistiche aggregate da simulazione forward dei trade plan (Trade Plan Engine v1.1)."""

    pattern_name: str
    timeframe: str
    provider: str
    asset_type: str
    sample_size: int = Field(
        description="Trade plan idonei (direzione long/short con livelli) inclusi nel bucket.",
    )
    entry_triggered: int = Field(
        description="Conteggio in cui il prezzo ha toccato entry entro la finestra di ingresso.",
    )
    stop_hits: int = Field(description="Uscite per stop (dopo ingresso).")
    tp1_hits: int = Field(
        description="Prima uscita al take profit 1 (escluso TP2 come prima uscita).",
    )
    tp2_hits: int = Field(
        description="Prima uscita al take profit 2 (target più lontano).",
    )
    tp1_or_tp2_hits: int = Field(
        default=0,
        description="tp1_hits + tp2_hits (almeno un target raggiunto come prima uscita).",
    )
    timed_out: int = Field(
        description="Ingresso avvenuto ma nessun livello colpito entro max barre forward.",
    )
    entry_trigger_rate: float | None = Field(
        default=None,
        description="entry_triggered / sample_size (0–1).",
    )
    stop_rate_of_sample: float | None = Field(
        default=None,
        description="stop_hits / sample_size (condizionato ai piani idonei, non solo agli ingressi).",
    )
    stop_rate_given_entry: float | None = Field(
        default=None,
        description="stop_hits / entry_triggered.",
    )
    tp1_rate_given_entry: float | None = Field(
        default=None,
        description="tp1_hits / entry_triggered.",
    )
    tp2_rate_given_entry: float | None = Field(
        default=None,
        description="tp2_hits / entry_triggered.",
    )
    tp1_or_tp2_rate_given_entry: float | None = Field(
        default=None,
        description="(tp1_hits + tp2_hits) / entry_triggered.",
    )
    avg_r: float | None = Field(
        default=None,
        description="Media R su trade con ingresso effettivo (timeout = 0 R).",
    )
    expectancy_r: float | None = Field(
        default=None,
        description="Expectancy per segnale: somma R / sample_size (0 R se ingresso non triggerato).",
    )


class TradePlanBacktestResponse(BaseModel):
    aggregates: list[TradePlanBacktestAggregateRow]
    trade_plan_engine_version: str = Field(
        default="1.1",
        description="Versione motore livelli (trade_plan_engine.build_trade_plan_v1).",
    )
    patterns_evaluated: int = Field(
        description="Righe pattern lette (filtri applicati).",
    )
    eligible_trade_plans: int = Field(
        description="Piani con direzione operativa e livelli numerici (simulabili).",
    )


class TradePlanVariantRow(BaseModel):
    """Una riga = bucket (pattern, TF, provider, asset) × variante di esecuzione."""

    pattern_name: str
    timeframe: str
    provider: str
    asset_type: str
    variant_label: str = Field(
        description="Es. breakout|structural|tp_1.5_2.5",
    )
    entry_strategy: str
    stop_profile: str
    tp_profile: str = Field(description="tp_1.5_2.5 | tp_1.5_2.0 | tp_1.0_2.0")
    sample_size: int
    entry_triggered: int
    stop_hits: int
    tp1_hits: int
    tp2_hits: int
    tp1_or_tp2_hits: int
    timed_out: int
    entry_trigger_rate: float | None = None
    stop_rate_given_entry: float | None = None
    tp1_or_tp2_rate_given_entry: float | None = None
    avg_r: float | None = None
    expectancy_r: float | None = None


class TradePlanVariantBacktestResponse(BaseModel):
    """Confronto varianti di esecuzione per gli stessi bucket (analisi on-demand, no DB)."""

    rows: list[TradePlanVariantRow]
    execution_variant_count: int = Field(
        description="Numero di combinazioni entry×stop×TP (fisso per v1).",
    )
    patterns_evaluated: int = Field(description="Righe pattern lette dopo i filtri.")
    trade_plan_engine_version: str = Field(
        default="1.1",
        description="Motore livelli base (v1.1) + varianti esecuzione esplicite.",
    )


OperationalVariantStatus = Literal["promoted", "watchlist", "rejected"]


class TradePlanVariantBestRow(BaseModel):
    """Migliore variante per bucket + metriche e stato operativo."""

    pattern_name: str
    timeframe: str
    provider: str
    asset_type: str
    best_variant_label: str
    entry_strategy: str
    stop_profile: str
    tp_profile: str
    sample_size: int
    entry_trigger_rate: float | None = None
    stop_rate_given_entry: float | None = None
    tp1_or_tp2_rate_given_entry: float | None = None
    avg_r: float | None = None
    expectancy_r: float | None = None
    operational_status: OperationalVariantStatus


class TradePlanVariantStatusCounts(BaseModel):
    """Conteggi bucket per stato operativo (prima del filtro di visualizzazione)."""

    promoted: int = 0
    watchlist: int = 0
    rejected: int = 0


class TradePlanVariantBestResponse(BaseModel):
    """Sintesi operativa: una riga per bucket con la variante scelta."""

    rows: list[TradePlanVariantBestRow]
    total_buckets_evaluated: int = Field(
        description="Numero totale di bucket distinti (pattern×TF×provider×asset), senza filtro stato.",
    )
    counts_by_status: TradePlanVariantStatusCounts = Field(
        description="Conteggi per stato su tutti i bucket valutati.",
    )
    insights: list[str] = Field(
        default_factory=list,
        description="Messaggi sintetici automatici (euristica su sample e stato).",
    )
    patterns_evaluated: int = Field(
        description="Pattern storici valutati (come backtest varianti).",
    )
    min_sample_for_reliable_rank: int = Field(
        default=20,
        description="Soglia minima sample per ranking affidabile tra varianti.",
    )
    trade_plan_engine_version: str = Field(default="1.1")
