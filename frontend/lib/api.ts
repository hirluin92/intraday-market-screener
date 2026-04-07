/**
 * Centralized API client for the backend (see NEXT_PUBLIC_API_URL).
 */

import { publicEnv } from "./env";

const base = publicEnv.apiUrl.replace(/\/$/, "");

/** Piano trade v1 (API /api/v1/screener/opportunities) */
export type TradePlanV1 = {
  trade_direction: "long" | "short" | "none";
  entry_strategy: "breakout" | "retest" | "close";
  entry_price: string | null;
  stop_loss: string | null;
  take_profit_1: string | null;
  take_profit_2: string | null;
  risk_reward_ratio: string | null;
  invalidation_note: string;
};

export type OpportunityRow = {
  asset_type?: string;
  provider?: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  market_metadata?: Record<string, unknown> | null;
  timestamp: string;
  context_timestamp: string;
  pattern_timestamp: string | null;
  /** Barre tra pattern e ultimo contesto (stesso TF). */
  pattern_age_bars?: number | null;
  /** True se l’età supera la soglia per il timeframe (pattern «vecchio»). */
  pattern_stale?: boolean;
  /** Soglia in barre per questo TF (coerente con pattern_stale). */
  pattern_stale_threshold_bars?: number;
  market_regime: string;
  volatility_regime: string;
  candle_expansion: string;
  direction_bias: string;
  screener_score: number;
  score_label: string;
  score_direction: string;
  latest_pattern_name: string | null;
  latest_pattern_strength: string | number | null;
  latest_pattern_direction: string | null;
  pattern_quality_score: number | null;
  pattern_quality_label: string;
  final_opportunity_score: number;
  final_opportunity_label: string;
  pattern_timeframe_quality_ok: boolean | null;
  pattern_timeframe_gate_label: string;
  pattern_timeframe_filtered_candidate: boolean;
  /** True se supera le regole MVP alert (derivato lato API). */
  alert_candidate: boolean;
  /** alta_priorita | media_priorita | nessun_alert */
  alert_level: string;
  trade_plan?: TradePlanV1 | null;
  /** Score dopo policy TF, prima aggiustamento Trade Plan Backtest v1 */
  final_opportunity_score_before_trade_plan_backtest?: number | null;
  trade_plan_backtest_score_delta?: number;
  trade_plan_backtest_adjustment_label?: string;
  trade_plan_backtest_expectancy_r?: number | null;
  trade_plan_backtest_sample_size?: number | null;
  /** high | medium | low | unknown — cautela da TPB, non filtro */
  operational_confidence?: string;
  /** Label best variant (entry|stop|tp) se bucket trovato in backtest varianti. */
  selected_trade_plan_variant?: string | null;
  selected_trade_plan_variant_status?: string | null;
  selected_trade_plan_variant_sample_size?: number | null;
  selected_trade_plan_variant_expectancy_r?: number | null;
  /** Livelli da parametri variant backtest oppure motore standard. */
  trade_plan_source?: "variant_backtest" | "default_fallback";
  /** Se default_fallback: codice motivo (no_pattern | no_variant_bucket | …). */
  trade_plan_fallback_reason?: string | null;
  /** execute | monitor | discard (legacy: operable) */
  operational_decision?: "execute" | "operable" | "monitor" | "discard";
  decision_rationale?: string[];
  /** Regime SPY 1d (bullish | bearish | neutral | unknown) */
  regime_spy?: string;
  /** Direzione pattern coerente con filtro regime (Yahoo) */
  regime_direction_ok?: boolean;
  /** True se (latest_pattern_name, timeframe) è nella lista validata OOS */
  pattern_is_validated?: boolean;
  /** operational | development | experimental */
  pattern_operational_status?: "operational" | "development" | "experimental";
  /** Ultimo close candela (DB) per la serie */
  current_price?: number | null;
  /** Distanza % vs entry del trade plan */
  price_distance_pct?: number | null;
  /** Prezzo oltre soglia vs entry / stop */
  price_stale?: boolean;
  price_stale_reason?: string | null;
};

export type OpportunitiesResponse = {
  opportunities: OpportunityRow[];
  count: number;
};

export type PipelineRefreshRequest = {
  provider?: "binance" | "yahoo_finance" | null;
  exchange?: string | null;
  symbol?: string | null;
  timeframe?: string | null;
  ingest_limit?: number;
  extract_limit?: number;
  lookback?: number;
};

export function seriesDetailHref(
  symbol: string,
  timeframe: string,
  exchange: string,
  opts?: { provider?: string; asset_type?: string },
): string {
  const q = new URLSearchParams();
  q.set("exchange", exchange);
  if (opts?.provider?.trim()) q.set("provider", opts.provider.trim());
  if (opts?.asset_type?.trim()) q.set("asset_type", opts.asset_type.trim());
  return `/opportunities/${encodeURIComponent(symbol)}/${encodeURIComponent(timeframe)}?${q.toString()}`;
}

export async function fetchOpportunities(params: {
  symbol?: string;
  timeframe?: string;
  exchange?: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
  /** execute | monitor | discard (o alias IT / operable) */
  decision?: string;
}): Promise<OpportunitiesResponse> {
  const url = new URL(`${base}/api/v1/screener/opportunities`);
  if (params.symbol?.trim()) {
    url.searchParams.set("symbol", params.symbol.trim());
  }
  if (params.timeframe?.trim()) {
    url.searchParams.set("timeframe", params.timeframe.trim());
  }
  if (params.exchange?.trim()) {
    url.searchParams.set("exchange", params.exchange.trim());
  }
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  if (params.decision?.trim()) {
    url.searchParams.set("decision", params.decision.trim());
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Risposta GET /api/v1/ibkr/status */
export type IbkrStatus = {
  enabled?: boolean;
  message?: string;
  paper_trading?: boolean;
  auto_execute?: boolean;
  authenticated?: boolean;
  account_id?: string;
  max_capital?: number;
  risk_per_trade_pct?: number;
  max_simultaneous_positions?: number;
  gateway_url?: string;
};

export async function fetchIbkrStatus(): Promise<IbkrStatus | null> {
  try {
    const res = await fetch(`${base}/api/v1/ibkr/status`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export type BacktestAggregateRow = {
  pattern_name: string;
  timeframe: string;
  sample_size: number;
  sample_size_3: number;
  sample_size_5: number;
  sample_size_10: number;
  avg_return_1: number | null;
  avg_return_3: number | null;
  avg_return_5: number | null;
  avg_return_10: number | null;
  win_rate_1: number | null;
  win_rate_3: number | null;
  win_rate_5: number | null;
  win_rate_10: number | null;
  pattern_quality_score: number | null;
  win_rate_ci_lower?: number | null;
  win_rate_ci_upper?: number | null;
  sample_reliability?: string | null;
  win_rate_pvalue?: number | null;
  win_rate_significance?: string | null;
  expectancy_r_pvalue?: number | null;
  expectancy_r_significance?: string | null;
};

export type BacktestPatternsResponse = {
  aggregates: BacktestAggregateRow[];
  patterns_evaluated: number;
};

export async function fetchBacktestPatterns(params: {
  symbol?: string;
  timeframe?: string;
  pattern_name?: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
}): Promise<BacktestPatternsResponse> {
  const url = new URL(`${base}/api/v1/backtest/patterns`);
  if (params.symbol?.trim()) {
    url.searchParams.set("symbol", params.symbol.trim());
  }
  if (params.timeframe?.trim()) {
    url.searchParams.set("timeframe", params.timeframe.trim());
  }
  if (params.pattern_name?.trim()) {
    url.searchParams.set("pattern_name", params.pattern_name.trim());
  }
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export type SimulationEquityPoint = {
  timestamp: string;
  equity: number;
};

export type SimulationTradeRow = {
  timestamp: string;
  symbol: string;
  pattern_name: string;
  direction: string;
  strength: number;
  horizon_bars: number;
  signed_return_pct: number;
  pnl_r: number;
  pnl_r_net: number;
  outcome: "win" | "loss" | "flat";
  capital_after: number;
};

export type BacktestSimulationResponse = {
  initial_capital: number;
  final_capital: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  total_trades: number;
  skipped_trades: number;
  win_rate: number;
  sharpe_ratio: number | null;
  /** Media R per trade (backend). */
  expectancy_r?: number | null;
  win_rate_pvalue?: number | null;
  win_rate_significance?: string | null;
  expectancy_pvalue?: number | null;
  expectancy_significance?: string | null;
  profit_factor?: number | null;
  equity_curve: SimulationEquityPoint[];
  pattern_names_used: string[];
  forward_horizons_used: number[];
  trades?: SimulationTradeRow[];
  avg_simultaneous_trades?: number;
  max_simultaneous_observed?: number;
  bars_with_trades?: number;
  trades_skipped_by_regime?: number;
  regime_filter_active?: boolean;
  cooldown_bars_used?: number;
  trades_skipped_by_cooldown?: number;
  note: string | null;
};

export type OOSSetMetrics = {
  period: string;
  total_trades: number;
  total_return_pct: number;
  win_rate: number;
  expectancy_r: number | null;
  max_drawdown_pct: number;
  sharpe_ratio: number | null;
  profit_factor: number | null;
};

export type OOSResult = {
  cutoff_date: string;
  train_set: OOSSetMetrics;
  test_set: OOSSetMetrics & {
    equity_curve: SimulationEquityPoint[];
    trades: SimulationTradeRow[];
  };
  performance_degradation_pct: number;
  oos_verdict:
    | "robusto"
    | "degradazione_moderata"
    | "possibile_overfitting";
  pattern_names_used: string[];
};

export type SimulationParams = {
  provider: string;
  timeframe: string;
  pattern_names?: string[];
  initial_capital?: number;
  risk_per_trade_pct?: number;
  cost_rate?: number;
  max_simultaneous?: number;
  include_trades?: boolean;
  pattern_row_limit?: number;
  /** Periodo relativo (1m, 3m, 6m, 1y, 2y, 3y); omesso o "all" = tutto lo storico. */
  period?: string;
  date_from?: string;
  date_to?: string;
  /** Filtro regime SPY 1d (default API: false se omesso). */
  use_regime_filter?: boolean;
  /** Barre di cooldown per serie dopo un trade (default API 3; 0 = disattivo). */
  cooldown_bars?: number;
  /** Ore UTC da escludere (solo Yahoo; Binance ignora). Ripetuto in query. */
  exclude_hours?: number[];
  include_hours?: number[];
  exclude_symbols?: string[];
  include_symbols?: string[];
};

export async function fetchBacktestSimulation(
  params: SimulationParams,
): Promise<BacktestSimulationResponse> {
  const url = new URL(`${base}/api/v1/backtest/simulation`);
  url.searchParams.set("provider", params.provider.trim());
  url.searchParams.set("timeframe", params.timeframe.trim());
  for (const p of params.pattern_names ?? []) {
    const t = p.trim();
    if (t) url.searchParams.append("pattern_names", t);
  }
  if (params.initial_capital != null) {
    url.searchParams.set("initial_capital", String(params.initial_capital));
  }
  if (params.risk_per_trade_pct != null) {
    url.searchParams.set("risk_per_trade_pct", String(params.risk_per_trade_pct));
  }
  if (params.cost_rate != null) {
    url.searchParams.set("cost_rate", String(params.cost_rate));
  }
  if (params.max_simultaneous != null) {
    url.searchParams.set("max_simultaneous", String(params.max_simultaneous));
  }
  if (params.include_trades != null) {
    url.searchParams.set("include_trades", String(params.include_trades));
  }
  if (params.pattern_row_limit != null) {
    url.searchParams.set("pattern_row_limit", String(params.pattern_row_limit));
  }
  if (params.period != null && params.period !== "" && params.period !== "all") {
    url.searchParams.set("period", params.period.trim());
  }
  if (params.date_from?.trim()) {
    url.searchParams.set("date_from", params.date_from.trim());
  }
  if (params.date_to?.trim()) {
    url.searchParams.set("date_to", params.date_to.trim());
  }
  if (params.use_regime_filter !== undefined) {
    url.searchParams.set(
      "use_regime_filter",
      String(params.use_regime_filter),
    );
  }
  if (params.cooldown_bars != null) {
    url.searchParams.set("cooldown_bars", String(params.cooldown_bars));
  }
  if (params.exclude_hours?.length) {
    for (const h of params.exclude_hours) {
      url.searchParams.append("exclude_hours", String(h));
    }
  }
  if (params.include_hours?.length) {
    for (const h of params.include_hours) {
      url.searchParams.append("include_hours", String(h));
    }
  }
  if (params.exclude_symbols?.length) {
    for (const s of params.exclude_symbols) {
      const t = s.trim();
      if (t) url.searchParams.append("exclude_symbols", t);
    }
  }
  if (params.include_symbols?.length) {
    for (const s of params.include_symbols) {
      const t = s.trim();
      if (t) url.searchParams.append("include_symbols", t);
    }
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Alias per la simulazione equity (stesso endpoint). */
export async function runSimulation(
  params: SimulationParams,
): Promise<BacktestSimulationResponse> {
  return fetchBacktestSimulation(params);
}

export type OutOfSampleParams = {
  provider: string;
  timeframe: string;
  pattern_names?: string[];
  cutoff_date?: string;
  initial_capital?: number;
  risk_per_trade_pct?: number;
  cost_rate?: number;
  max_simultaneous?: number;
  include_trades?: boolean;
  use_regime_filter?: boolean;
};

export type WalkForwardFoldRow = {
  fold_number: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  train_trades: number;
  test_trades: number;
  train_return_pct: number;
  test_return_pct: number;
  train_win_rate: number;
  test_win_rate: number;
  train_max_dd: number;
  test_max_dd: number;
  train_expectancy_r: number | null;
  test_expectancy_r: number | null;
  degradation_pct: number;
  verdict: "robusto" | "degradazione_moderata" | "possibile_overfitting";
};

export type WalkForwardResult = {
  n_folds: number;
  folds: WalkForwardFoldRow[];
  avg_test_return_pct: number;
  avg_test_win_rate: number;
  avg_degradation_pct: number;
  pct_folds_positive: number;
  overall_verdict:
    | "robusto"
    | "prevalentemente_robusto"
    | "degradazione_moderata"
    | "possibile_overfitting";
  date_range_start: string;
  date_range_end: string;
};

export type WalkForwardParams = {
  provider: string;
  timeframe: string;
  pattern_names?: string[];
  n_folds?: number;
  initial_capital?: number;
  risk_per_trade_pct?: number;
  cost_rate?: number;
  max_simultaneous?: number;
  use_regime_filter?: boolean;
  exclude_hours?: number[];
  include_hours?: number[];
  exclude_symbols?: string[];
  include_symbols?: string[];
  /** Timeout ms (default 120000). */
  timeoutMs?: number;
};

export async function fetchWalkForward(
  params: WalkForwardParams,
): Promise<WalkForwardResult> {
  const url = new URL(`${base}/api/v1/backtest/walk-forward`);
  url.searchParams.set("provider", params.provider.trim());
  url.searchParams.set("timeframe", params.timeframe.trim());
  for (const p of params.pattern_names ?? []) {
    const t = p.trim();
    if (t) url.searchParams.append("pattern_names", t);
  }
  if (params.n_folds != null) {
    url.searchParams.set("n_folds", String(params.n_folds));
  }
  if (params.initial_capital != null) {
    url.searchParams.set("initial_capital", String(params.initial_capital));
  }
  if (params.risk_per_trade_pct != null) {
    url.searchParams.set("risk_per_trade_pct", String(params.risk_per_trade_pct));
  }
  if (params.cost_rate != null) {
    url.searchParams.set("cost_rate", String(params.cost_rate));
  }
  if (params.max_simultaneous != null) {
    url.searchParams.set("max_simultaneous", String(params.max_simultaneous));
  }
  if (params.use_regime_filter !== undefined) {
    url.searchParams.set(
      "use_regime_filter",
      String(params.use_regime_filter),
    );
  }
  if (params.exclude_hours?.length) {
    for (const h of params.exclude_hours) {
      url.searchParams.append("exclude_hours", String(h));
    }
  }
  if (params.include_hours?.length) {
    for (const h of params.include_hours) {
      url.searchParams.append("include_hours", String(h));
    }
  }
  if (params.exclude_symbols?.length) {
    for (const s of params.exclude_symbols) {
      const t = s.trim();
      if (t) url.searchParams.append("exclude_symbols", t);
    }
  }
  if (params.include_symbols?.length) {
    for (const s of params.include_symbols) {
      const t = s.trim();
      if (t) url.searchParams.append("include_symbols", t);
    }
  }
  const timeoutMs = params.timeoutMs ?? 120_000;
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      cache: "no-store",
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `${res.status} ${res.statusText}`);
    }
    return res.json();
  } finally {
    clearTimeout(tid);
  }
}

export async function fetchOutOfSample(
  params: OutOfSampleParams,
): Promise<OOSResult> {
  const url = new URL(`${base}/api/v1/backtest/out-of-sample`);
  url.searchParams.set("provider", params.provider.trim());
  url.searchParams.set("timeframe", params.timeframe.trim());
  for (const p of params.pattern_names ?? []) {
    const t = p.trim();
    if (t) url.searchParams.append("pattern_names", t);
  }
  if (params.cutoff_date?.trim()) {
    url.searchParams.set("cutoff_date", params.cutoff_date.trim());
  }
  if (params.initial_capital != null) {
    url.searchParams.set("initial_capital", String(params.initial_capital));
  }
  if (params.risk_per_trade_pct != null) {
    url.searchParams.set("risk_per_trade_pct", String(params.risk_per_trade_pct));
  }
  if (params.cost_rate != null) {
    url.searchParams.set("cost_rate", String(params.cost_rate));
  }
  if (params.max_simultaneous != null) {
    url.searchParams.set("max_simultaneous", String(params.max_simultaneous));
  }
  if (params.include_trades != null) {
    url.searchParams.set("include_trades", String(params.include_trades));
  }
  if (params.use_regime_filter !== undefined) {
    url.searchParams.set(
      "use_regime_filter",
      String(params.use_regime_filter),
    );
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export type CandleRow = {
  id: number;
  symbol: string;
  exchange: string;
  timeframe: string;
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  created_at: string;
};

export type CandlesListResponse = {
  candles: CandleRow[];
  count: number;
};

export type FeatureRow = {
  id: number;
  candle_id: number;
  symbol: string;
  exchange: string;
  timeframe: string;
  timestamp: string;
  body_size: string;
  range_size: string;
  upper_wick: string;
  lower_wick: string;
  close_position_in_range: string;
  pct_return_1: string | null;
  volume_ratio_vs_prev: string | null;
  is_bullish: boolean;
  created_at: string;
};

export type FeaturesListResponse = {
  features: FeatureRow[];
  count: number;
};

export type ContextRow = {
  id: number;
  candle_feature_id: number;
  symbol: string;
  exchange: string;
  timeframe: string;
  timestamp: string;
  market_regime: string;
  volatility_regime: string;
  candle_expansion: string;
  direction_bias: string;
  created_at: string;
};

export type ContextListResponse = {
  contexts: ContextRow[];
  count: number;
};

export type PatternRow = {
  id: number;
  candle_feature_id: number;
  candle_context_id: number | null;
  symbol: string;
  exchange: string;
  timeframe: string;
  timestamp: string;
  pattern_name: string;
  pattern_strength: string;
  direction: string;
  created_at: string;
};

export type PatternsListResponse = {
  patterns: PatternRow[];
  count: number;
};

export async function fetchMarketDataCandles(params: {
  symbol: string;
  exchange: string;
  timeframe: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
}): Promise<CandlesListResponse> {
  const url = new URL(`${base}/api/v1/market-data/candles`);
  url.searchParams.set("symbol", params.symbol);
  url.searchParams.set("exchange", params.exchange);
  url.searchParams.set("timeframe", params.timeframe);
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMarketDataFeatures(params: {
  symbol: string;
  exchange: string;
  timeframe: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
}): Promise<FeaturesListResponse> {
  const url = new URL(`${base}/api/v1/market-data/features`);
  url.searchParams.set("symbol", params.symbol);
  url.searchParams.set("exchange", params.exchange);
  url.searchParams.set("timeframe", params.timeframe);
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMarketDataContext(params: {
  symbol: string;
  exchange: string;
  timeframe: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
}): Promise<ContextListResponse> {
  const url = new URL(`${base}/api/v1/market-data/context`);
  url.searchParams.set("symbol", params.symbol);
  url.searchParams.set("exchange", params.exchange);
  url.searchParams.set("timeframe", params.timeframe);
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMarketDataPatterns(params: {
  symbol: string;
  exchange: string;
  timeframe: string;
  provider?: string;
  asset_type?: string;
  limit?: number;
}): Promise<PatternsListResponse> {
  const url = new URL(`${base}/api/v1/market-data/patterns`);
  url.searchParams.set("symbol", params.symbol);
  url.searchParams.set("exchange", params.exchange);
  url.searchParams.set("timeframe", params.timeframe);
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export type OperationalVariantStatus = "promoted" | "watchlist" | "rejected";

export type TradePlanVariantBestRow = {
  pattern_name: string;
  timeframe: string;
  provider: string;
  asset_type: string;
  best_variant_label: string;
  entry_strategy: string;
  stop_profile: string;
  tp_profile: string;
  sample_size: number;
  entry_trigger_rate: number | null;
  stop_rate_given_entry: number | null;
  tp1_or_tp2_rate_given_entry: number | null;
  avg_r: number | null;
  expectancy_r: number | null;
  operational_status: OperationalVariantStatus;
};

export type TradePlanVariantStatusCounts = {
  promoted: number;
  watchlist: number;
  rejected: number;
};

export type TradePlanVariantBestResponse = {
  rows: TradePlanVariantBestRow[];
  total_buckets_evaluated: number;
  counts_by_status: TradePlanVariantStatusCounts;
  insights: string[];
  patterns_evaluated: number;
  min_sample_for_reliable_rank: number;
  trade_plan_engine_version: string;
  /** Tasso costo round-trip usato nel backtest (frazione notional). */
  backtest_cost_rate_rt?: number;
};

export type TradePlanVariantStatusScope =
  | "promoted_watchlist"
  | "all"
  | "promoted"
  | "watchlist"
  | "rejected";

export async function fetchTradePlanVariantBest(params: {
  symbol?: string;
  exchange?: string;
  timeframe?: string;
  pattern_name?: string;
  provider?: string;
  asset_type?: string;
  status_scope?: TradePlanVariantStatusScope;
  operational_status?: OperationalVariantStatus | "";
  limit?: number;
}): Promise<TradePlanVariantBestResponse> {
  const url = new URL(`${base}/api/v1/backtest/trade-plan-variants/best`);
  if (params.symbol?.trim()) {
    url.searchParams.set("symbol", params.symbol.trim());
  }
  if (params.exchange?.trim()) {
    url.searchParams.set("exchange", params.exchange.trim());
  }
  if (params.timeframe?.trim()) {
    url.searchParams.set("timeframe", params.timeframe.trim());
  }
  if (params.pattern_name?.trim()) {
    url.searchParams.set("pattern_name", params.pattern_name.trim());
  }
  if (params.provider?.trim()) {
    url.searchParams.set("provider", params.provider.trim());
  }
  if (params.asset_type?.trim()) {
    url.searchParams.set("asset_type", params.asset_type.trim());
  }
  if (params.status_scope) {
    url.searchParams.set("status_scope", params.status_scope);
  }
  if (params.operational_status?.trim()) {
    url.searchParams.set(
      "operational_status",
      params.operational_status.trim(),
    );
  }
  if (params.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function postPipelineRefresh(
  body: PipelineRefreshRequest,
): Promise<unknown> {
  const res = await fetch(`${base}/api/v1/pipeline/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}
