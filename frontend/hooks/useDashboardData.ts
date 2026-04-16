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

async function fetchPipelineStatus() {
  const res = await fetch(`${publicEnv.apiUrl}/api/v1/pipeline/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`pipeline/status HTTP ${res.status}`);
  return res.json() as Promise<{
    last_run_at: string | null;
    status: "ok" | "stale" | "unknown";
    age_minutes: number | null;
    in_progress: boolean;
  }>;
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: fetchPipelineStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 2,
  });
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

// ── Performance KPIs — ora usa endpoint reale ─────────────────────────────────

async function fetchPerformanceKPIs(days = 30) {
  const url = `${publicEnv.apiUrl}/api/v1/performance/kpis?days=${days}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`performance/kpis HTTP ${res.status}`);
  return res.json() as Promise<{
    pnl_today_eur:        number | null;
    win_rate_30d_pct:     number | null;
    drawdown_current_pct: number | null;
    open_positions:       number;
    total_trades_30d:     number;
    closed_trades_30d:    number;
    note:                 string | null;
  }>;
}

export function usePerformanceKPIs(): PerformanceKPIs {
  const { data, isLoading } = useQuery({
    queryKey: ["performance", "kpis", 30],
    queryFn: () => fetchPerformanceKPIs(30),
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 2,
  });

  const pnl   = data?.pnl_today_eur        ?? null;
  const wr    = data?.win_rate_30d_pct      ?? null;
  const dd    = data?.drawdown_current_pct  ?? null;
  const open  = data?.open_positions        ?? null;

  return {
    openPositions: {
      value: isLoading ? null : open,
      label: "Posizioni aperte",
    },
    totalOrders30d: {
      value: isLoading ? null : (data?.closed_trades_30d ?? null),
      label: "Trade 30gg",
    },
    pnlToday: {
      value: isLoading ? null : pnl,
      label: "P&L oggi",
      placeholder: !isLoading && pnl === null && (data?.closed_trades_30d ?? 0) === 0,
      placeholderNote: "Nessun trade chiuso registrato",
    },
    drawdown: {
      value: isLoading ? null : dd,
      label: "Drawdown",
      placeholder: !isLoading && dd === null && (data?.closed_trades_30d ?? 0) === 0,
      placeholderNote: "Nessun trade chiuso registrato",
    },
    winRate30d: { value: wr, label: "Win Rate 30gg" },
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
