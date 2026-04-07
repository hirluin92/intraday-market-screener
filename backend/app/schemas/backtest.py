from datetime import datetime
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
    win_rate_ci_lower: float | None = Field(
        default=None,
        description="Estremo inferiore IC 95% Wilson sul win rate (orizzonte 5 poi 3), percentuale 0–100.",
    )
    win_rate_ci_upper: float | None = Field(
        default=None,
        description="Estremo superiore IC 95% Wilson sul win rate (orizzonte 5 poi 3), percentuale 0–100.",
    )
    sample_reliability: str | None = Field(
        default=None,
        description="Affidabilità campione: insufficient | poor | fair | good | excellent.",
    )
    win_rate_pvalue: float | None = Field(
        default=None,
        description="p-value test binomiale one-sided WR > 50% (orizzonte primario 5→3).",
    )
    win_rate_significance: str | None = Field(
        default=None,
        description="Etichetta: *** | ** | * | ns.",
    )
    expectancy_r_pvalue: float | None = Field(
        default=None,
        description="p-value t-test one-sided sui return % all'orizzonte primario (media > 0).",
    )
    expectancy_r_significance: str | None = Field(
        default=None,
        description="Etichetta: *** | ** | * | ns.",
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
    win_rate_ci_lower: float | None = Field(
        default=None,
        description="IC 95% Wilson su tp1_or_tp2 / entry_triggered, percentuale 0–100.",
    )
    win_rate_ci_upper: float | None = Field(
        default=None,
        description="IC 95% Wilson su tp1_or_tp2 / entry_triggered, percentuale 0–100.",
    )
    sample_reliability: str | None = Field(
        default=None,
        description="Affidabilità campione (entry_triggered): insufficient | poor | fair | good | excellent.",
    )
    win_rate_pvalue: float | None = Field(
        default=None,
        description="p-value binomiale one-sided: TP1/TP2 vs 50% su entry_triggered.",
    )
    win_rate_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
    )
    expectancy_r_pvalue: float | None = Field(
        default=None,
        description="p-value t-test one-sided su R per segnale (0 se no ingresso).",
    )
    expectancy_r_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
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
    backtest_cost_rate_rt: float = Field(
        default=0.0,
        description=(
            "Tasso costo round-trip usato nella simulazione (fee + slippage, frazione notional). "
            "Es. 0.0015 = 0.15%. 0.0 indica simulazione senza costi (legacy)."
        ),
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
    tp_profile: str = Field(
        description="Profilo TP variante (es. tp_1.5_2.5, tp_2.0_3.0, tp_2.5_4.0).",
    )
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
    win_rate_ci_lower: float | None = Field(
        default=None,
        description="IC 95% Wilson su tp1_or_tp2 / entry_triggered, percentuale 0–100.",
    )
    win_rate_ci_upper: float | None = Field(
        default=None,
        description="IC 95% Wilson su tp1_or_tp2 / entry_triggered, percentuale 0–100.",
    )
    sample_reliability: str | None = Field(
        default=None,
        description="Affidabilità campione (entry_triggered): insufficient | poor | fair | good | excellent.",
    )
    win_rate_pvalue: float | None = Field(
        default=None,
        description="p-value binomiale one-sided: TP1/TP2 vs 50% su entry_triggered.",
    )
    win_rate_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
    )
    expectancy_r_pvalue: float | None = Field(
        default=None,
        description="p-value t-test one-sided su R per segnale (0 se no ingresso).",
    )
    expectancy_r_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
    )


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
    backtest_cost_rate_rt: float = Field(
        default=0.0,
        description="Tasso costo round-trip usato nella simulazione varianti (frazione notional).",
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


class SimulationEquityPoint(BaseModel):
    """Punto della curva equity (timestamp barra segnale / aggiornamento saldo)."""

    timestamp: datetime
    equity: float


class SimulationTradeRow(BaseModel):
    """Dettaglio singolo trade simulato (opzionale, solo con ``include_trades=true``)."""

    timestamp: datetime
    symbol: str
    pattern_name: str
    direction: str
    strength: float = Field(
        description="Forza pattern (CandlePattern.pattern_strength) al momento del segnale.",
    )
    horizon_bars: int = Field(description="Barre forward usate per il return firmato.")
    signed_return_pct: float = Field(description="Return % direzionale prima del clamp R.")
    pnl_r: float = Field(
        description="R dopo clamp [min,max], prima dei costi (scala REF_PCT_PER_R).",
    )
    pnl_r_net: float = Field(
        description="R netto sul risk_amount dopo costi (net / risk_amount).",
    )
    outcome: Literal["win", "loss", "flat"] = Field(
        description="win/loss da segno del forward %; flat se movimento nullo.",
    )
    capital_after: float


class BacktestSimulationResponse(BaseModel):
    """
    Simulazione in-sample: equity composta su segnali pattern storici (solo DB).
    I rendimenti si calcolano da candele come GET /backtest/patterns (nessun campo forward su CandlePattern).
    """

    initial_capital: float
    final_capital: float
    total_return_pct: float
    max_drawdown_pct: float
    total_trades: int
    skipped_trades: int = Field(
        default=0,
        description="Segnali esclusi (finestra forward insufficiente / serie mancante).",
    )
    win_rate: float = Field(
        description="Percentuale trade vincenti (0–100), coerente con direzione pattern.",
    )
    sharpe_ratio: float | None = Field(
        default=None,
        description="Euristico su rendimenti per trade (non annualizzato).",
    )
    equity_curve: list[SimulationEquityPoint]
    pattern_names_used: list[str] = Field(
        default_factory=list,
        description="Filtro effettivo (vuoto → tutti i pattern promoted per provider×TF).",
    )
    forward_horizons_used: tuple[int, ...] = Field(
        default=(5, 3, 10, 1),
        description="Ordine di tentativo orizzonti forward (barre) se +5 non disponibile.",
    )
    trades: list[SimulationTradeRow] = Field(
        default_factory=list,
        description="Elenco trade (solo se richiesto con include_trades=true).",
    )
    avg_simultaneous_trades: float = Field(
        default=0.0,
        description="Media trade eseguiti per barra (timestamp) con almeno un fill.",
    )
    max_simultaneous_observed: int = Field(
        default=0,
        description="Massimo numero di trade simultanei osservati su una singola barra.",
    )
    bars_with_trades: int = Field(
        default=0,
        description="Barre (timestamp distinti) con almeno un trade eseguito.",
    )
    expectancy_r: float | None = Field(
        default=None,
        description="Media R per trade (somma pnl_r / total_trades).",
    )
    win_rate_pvalue: float | None = Field(
        default=None,
        description="p-value test binomiale one-sided: win rate > 50%.",
    )
    win_rate_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
    )
    expectancy_pvalue: float | None = Field(
        default=None,
        description="p-value t-test one-sided su pnl_r: expectancy > 0.",
    )
    expectancy_significance: str | None = Field(
        default=None,
        description="*** | ** | * | ns.",
    )
    profit_factor: float | None = Field(
        default=None,
        description="Somma R su trade vincenti / somma |R| su trade perdenti (solo R≠0).",
    )
    trades_skipped_by_regime: int = Field(
        default=0,
        description="Trade potenziali saltati per filtro regime daily (SPY o BTC/USDT a seconda del provider).",
    )
    regime_filter_active: bool = Field(
        default=False,
        description="True se il filtro regime daily è stato applicato (indicatori regime presenti nel DB).",
    )
    cooldown_bars_used: int = Field(
        default=0,
        description="Valore cooldown_bars applicato (0 = disattivo).",
    )
    trades_skipped_by_cooldown: int = Field(
        default=0,
        description="Segnali esclusi per anti-overlap sulla stessa serie (symbol+timeframe+provider).",
    )
    note: str | None = None


class OOSSetMetrics(BaseModel):
    """Metriche aggregate su un periodo (train o test) per validazione OOS."""

    period: str
    total_trades: int
    total_return_pct: float
    win_rate: float
    expectancy_r: float | None = None
    max_drawdown_pct: float
    sharpe_ratio: float | None = None
    profit_factor: float | None = None


class OOSTestSetMetrics(OOSSetMetrics):
    """Test set OOS: metriche + curva equity e trade opzionali."""

    equity_curve: list[SimulationEquityPoint] = Field(default_factory=list)
    trades: list[SimulationTradeRow] = Field(default_factory=list)


class OOSValidationResponse(BaseModel):
    """Confronto train vs test dopo split per data di cutoff."""

    cutoff_date: str
    train_set: OOSSetMetrics
    test_set: OOSTestSetMetrics
    performance_degradation_pct: float
    oos_verdict: Literal["robusto", "degradazione_moderata", "possibile_overfitting"]
    pattern_names_used: list[str] = Field(default_factory=list)
    leakage_prevented: bool = Field(
        default=True,
        description=(
            "True se il test set usa lo stesso quality lookup del train (solo dati pre-cutoff), "
            "senza leakage da pattern futuri."
        ),
    )
    train_quality_lookup_size: int = Field(
        default=0,
        description="Numero di chiavi (pattern_name, timeframe) nel lookup qualità train-only.",
    )
    note_oos: str = Field(
        default="",
        description="Nota sulla metodologia OOS (anti-leakage).",
    )


class WalkForwardFoldResponse(BaseModel):
    """Un fold walk-forward: metriche train vs test su segmenti temporali consecutivi."""

    fold_number: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_trades: int
    test_trades: int
    train_return_pct: float
    test_return_pct: float
    train_win_rate: float
    test_win_rate: float
    train_max_dd: float
    test_max_dd: float
    train_expectancy_r: float | None = None
    test_expectancy_r: float | None = None
    degradation_pct: float
    verdict: Literal["robusto", "degradazione_moderata", "possibile_overfitting"]


class WalkForwardResponse(BaseModel):
    """Sintesi walk-forward: più split train/test cronologici con quality lookup solo sul train."""

    n_folds: int
    folds: list[WalkForwardFoldResponse]
    avg_test_return_pct: float
    avg_test_win_rate: float
    avg_degradation_pct: float
    pct_folds_positive: float
    overall_verdict: Literal[
        "robusto",
        "prevalentemente_robusto",
        "degradazione_moderata",
        "possibile_overfitting",
    ]
    date_range_start: str
    date_range_end: str


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
    backtest_cost_rate_rt: float = Field(
        default=0.0,
        description="Tasso costo round-trip usato per la selezione best variant (frazione notional).",
    )