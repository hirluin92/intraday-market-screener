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
  /** operable | monitor | discard */
  operational_decision?: "operable" | "monitor" | "discard";
  decision_rationale?: string[];
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
  /** operable | monitor | discard (o alias IT: operabile, da_monitorare, scartare) */
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
};

export type BacktestPatternsResponse = {
  aggregates: BacktestAggregateRow[];
  patterns_evaluated: number;
};

export async function fetchBacktestPatterns(params: {
  symbol?: string;
  timeframe?: string;
  pattern_name?: string;
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
