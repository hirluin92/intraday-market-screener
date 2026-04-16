"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchMarketDataCandles,
  fetchMarketDataContext,
  fetchMarketDataFeatures,
  fetchMarketDataPatterns,
  fetchOpportunities,
} from "@/lib/api";

const STALE_MS = 5 * 60_000; // 5 min — matches pipeline scan interval

export interface SeriesParams {
  symbol: string;
  exchange: string;
  timeframe: string;
  provider?: string;
  asset_type?: string;
}

// ── Query keys ────────────────────────────────────────────────────────────────

export function seriesQueryKeys(p: SeriesParams) {
  const base = [p.symbol, p.timeframe, p.exchange, p.provider ?? "", p.asset_type ?? ""] as const;
  return {
    snapshot: ["series", "snapshot", ...base] as const,
    candles:  ["series", "candles",  ...base] as const,
    features: ["series", "features", ...base] as const,
    context:  ["series", "context",  ...base] as const,
    patterns: ["series", "patterns", ...base] as const,
    all:      ["series", ...base] as const,
  };
}

// ── Opportunity snapshot (contains trade plan + decision) ─────────────────────

export function useSeriesSnapshot(p: SeriesParams) {
  return useQuery({
    queryKey: seriesQueryKeys(p).snapshot,
    queryFn: () =>
      fetchOpportunities({
        symbol: p.symbol,
        timeframe: p.timeframe,
        exchange: p.exchange,
        provider: p.provider,
        asset_type: p.asset_type,
        limit: 5,
      }).then((r) => r.opportunities[0] ?? null),
    staleTime: STALE_MS,
    retry: 2,
  });
}

// ── Candles ───────────────────────────────────────────────────────────────────

export function useSeriesCandles(p: SeriesParams, limit = 200) {
  return useQuery({
    queryKey: [...seriesQueryKeys(p).candles, limit] as const,
    queryFn: () =>
      fetchMarketDataCandles({ ...p, limit }).then((r) => r.candles),
    staleTime: STALE_MS,
    retry: 2,
  });
}

// ── Features ─────────────────────────────────────────────────────────────────

export function useSeriesFeatures(p: SeriesParams, limit = 50) {
  return useQuery({
    queryKey: [...seriesQueryKeys(p).features, limit] as const,
    queryFn: () =>
      fetchMarketDataFeatures({ ...p, limit }).then((r) => r.features),
    staleTime: STALE_MS,
    retry: 2,
  });
}

// ── Context ───────────────────────────────────────────────────────────────────

export function useSeriesContext(p: SeriesParams, limit = 20) {
  return useQuery({
    queryKey: [...seriesQueryKeys(p).context, limit] as const,
    queryFn: () =>
      fetchMarketDataContext({ ...p, limit }).then((r) => r.contexts),
    staleTime: STALE_MS,
    retry: 2,
  });
}

// ── Patterns ──────────────────────────────────────────────────────────────────

export function useSeriesPatterns(p: SeriesParams, limit = 50) {
  return useQuery({
    queryKey: [...seriesQueryKeys(p).patterns, limit] as const,
    queryFn: () =>
      fetchMarketDataPatterns({ ...p, limit }).then((r) => r.patterns),
    staleTime: STALE_MS,
    retry: 2,
  });
}

// ── Invalidate all series queries (used by refresh button) ────────────────────

export function useInvalidateSeries(p: SeriesParams) {
  const qc = useQueryClient();
  return () =>
    qc.invalidateQueries({ queryKey: seriesQueryKeys(p).all });
}
