"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchExecutedSignals,
  fetchOpportunities,
  type ExecutedSignalRow,
  type OpportunityRow,
} from "@/lib/api";
import { publicEnv } from "@/lib/env";
import { useIBKRStatus } from "./useIBKRStatus";
import type { ActivityItem, PerformanceKPIs } from "@/lib/schemas/dashboard";

// ── Pipeline status ───────────────────────────────────────────────────────────
// GET /api/v1/pipeline/status → does NOT exist yet.
// Only POST /api/v1/pipeline/refresh is available.
// TODO backend: add GET /api/v1/pipeline/status returning { last_run_at, in_progress, last_result }

export function usePipelineStatus() {
  return {
    data: null,
    isLoading: false,
    error: null,
    placeholder: true,
    placeholderNote: "TODO backend: GET /api/v1/pipeline/status (mancante)",
  };
}

// ── Dashboard opportunities (regime + top signals, single fetch) ──────────────

export function useDashboardOpportunities() {
  return useQuery({
    queryKey: ["screener", "opportunities", "dashboard"],
    queryFn: () => fetchOpportunities({ limit: 20 }),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

// ── Regime SPY — derived from opportunities ───────────────────────────────────

export function useRegimeSPY() {
  const { data, isLoading, error } = useDashboardOpportunities();

  const regime = useMemo(() => {
    if (!data?.opportunities) return null;
    const withRegime = data.opportunities.filter(
      (r) => r.regime_spy && r.regime_spy !== "n/a" && r.regime_spy !== "unknown",
    );
    const spyRow = withRegime.find((r) =>
      String(r.symbol).toUpperCase().includes("SPY"),
    );
    return (spyRow ?? withRegime[0])?.regime_spy ?? null;
  }, [data]);

  return { regime, isLoading, error };
}

// ── Top signals (execute) — derived from opportunities ───────────────────────

export function useTopSignals(max = 5) {
  const { data, isLoading, error, refetch } = useDashboardOpportunities();

  const topSignals = useMemo<OpportunityRow[]>(() => {
    if (!data?.opportunities) return [];
    return data.opportunities
      .filter((r) => r.operational_decision === "execute")
      .slice(0, max);
  }, [data, max]);

  return { data: topSignals, isLoading, error, refetch };
}

// ── Activity feed — from executed signals ─────────────────────────────────────

function signalToActivityItem(sig: ExecutedSignalRow): ActivityItem {
  const isBull = sig.direction === "bullish" || sig.direction === "long";
  const isOpen = sig.tws_status === "Filled";
  const isSkipped = sig.tws_status === "skipped";
  const isCancelled =
    sig.tws_status === "Cancelled" || sig.tws_status === "cancelled" || !!sig.error;

  let type: ActivityItem["type"] = "signal_executed";
  let variant: ActivityItem["variant"] = isBull ? "bull" : "bear";

  if (isSkipped) {
    type = "signal_skipped";
    variant = "warn";
  } else if (isCancelled) {
    type = "signal_cancelled";
    variant = "bear";
  }

  const dir = isBull ? "▲ LONG" : "▼ SHORT";
  const pattern = (sig.pattern_name ?? "").replace(/_/g, " ");

  const title = `${sig.symbol} ${sig.timeframe} ${dir}`;
  const description = isSkipped
    ? `Skipped — ${pattern}`
    : isCancelled
      ? sig.error ?? `Cancellato — ${pattern}`
      : isOpen
        ? `Eseguito @ ${sig.entry_price.toFixed(2)} — ${pattern}`
        : `${sig.tws_status} — ${pattern}`;

  return {
    id: String(sig.id),
    type,
    timestamp: sig.executed_at,
    title,
    description,
    variant,
  };
}

export function useActivityFeed(maxItems = 10) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["screener", "executed-signals", "activity"],
    queryFn: () => fetchExecutedSignals(maxItems * 2),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const items = useMemo<ActivityItem[]>(() => {
    if (!data?.signals) return [];
    return data.signals
      .slice(0, maxItems)
      .map(signalToActivityItem);
  }, [data, maxItems]);

  return { items, isLoading, error, refetch };
}

// ── Performance KPIs ──────────────────────────────────────────────────────────
// Open positions: real (from executed-signals count Filled)
// P&L oggi: MISSING endpoint → placeholder
// Drawdown: MISSING endpoint → placeholder
// Esecuzioni: real (from monitoring/execution-stats)
//
// TODO backend:
//   GET /api/v1/performance/kpis → { pnl_today_eur, win_rate_30d_pct, drawdown_current_pct }

async function fetchExecutionStats(days: number) {
  const url = `${publicEnv.apiUrl}/api/v1/monitoring/execution-stats?days=${days}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`execution-stats HTTP ${res.status}`);
  return res.json() as Promise<{
    total_attempts: number;
    successfully_submitted: number;
    success_rate_pct: number | null;
  }>;
}

export function usePerformanceKPIs(): PerformanceKPIs {
  const signalsQuery = useQuery({
    queryKey: ["screener", "executed-signals", "perf"],
    queryFn: () => fetchExecutedSignals(200),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const execStatsQuery = useQuery({
    queryKey: ["monitoring", "execution-stats", "30d"],
    queryFn: () => fetchExecutionStats(30),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const openPositions = useMemo(() => {
    if (!signalsQuery.data) return null;
    return signalsQuery.data.signals.filter(
      (s) => s.tws_status === "Filled",
    ).length;
  }, [signalsQuery.data]);

  const totalOrders = execStatsQuery.data?.total_attempts ?? null;

  return {
    openPositions: {
      value: openPositions,
      label: "Posizioni aperte",
    },
    totalOrders30d: {
      value: totalOrders,
      label: "Ordini 30gg",
    },
    pnlToday: {
      value: null,
      label: "P&L oggi",
      placeholder: true,
      placeholderNote: "TODO backend: GET /api/v1/performance/kpis",
    },
    drawdown: {
      value: null,
      label: "Drawdown",
      placeholder: true,
      placeholderNote: "TODO backend: GET /api/v1/performance/kpis",
    },
  };
}

// ── Aggregator ────────────────────────────────────────────────────────────────

export function useDashboardData() {
  const ibkr = useIBKRStatus();
  const pipeline = usePipelineStatus();
  const { regime, isLoading: regimeLoading, error: regimeError } = useRegimeSPY();
  const topSignals = useTopSignals(5);
  const activity = useActivityFeed(10);
  const performance = usePerformanceKPIs();

  return {
    ibkr,
    pipeline,
    regime: { value: regime, isLoading: regimeLoading, error: regimeError },
    topSignals,
    activity,
    performance,
  };
}
