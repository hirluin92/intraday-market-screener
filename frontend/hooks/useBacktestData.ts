"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchBacktestPatterns,
  fetchTradePlanVariantBest,
  type TradePlanVariantStatusScope,
  type OperationalVariantStatus,
} from "@/lib/api";

// ── Backtest patterns ─────────────────────────────────────────────────────────

export interface BacktestPatternsParams {
  symbol?: string;
  timeframe?: string;
  pattern_name?: string;
  provider?: string;
  asset_type?: string;
}

export function useBacktestPatterns(params: BacktestPatternsParams = {}) {
  return useQuery({
    queryKey: ["backtest", "patterns", params],
    queryFn: () => fetchBacktestPatterns({ ...params, limit: 5000 }),
    staleTime: 5 * 60_000,
    retry: 2,
  });
}

// ── Trade plan lab ────────────────────────────────────────────────────────────

export interface TradePlanLabParams {
  timeframe?: string;
  provider?: string;
  asset_type?: string;
  status_scope?: TradePlanVariantStatusScope;
  operational_status?: OperationalVariantStatus | "";
}

export function useTradePlanLab(params: TradePlanLabParams = {}) {
  return useQuery({
    queryKey: ["trade-plan-lab", params],
    queryFn: () => fetchTradePlanVariantBest({ ...params, limit: 500 }),
    staleTime: 5 * 60_000,
    retry: 2,
  });
}
