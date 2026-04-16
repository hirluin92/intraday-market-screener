"use client";

import { useQuery } from "@tanstack/react-query";

import { publicEnv } from "@/lib/env";
import type { IbkrStatus } from "@/lib/api";

export const IBKR_STATUS_KEY = ["ibkr", "status"] as const;

async function fetchIbkrStatusQuery(): Promise<IbkrStatus> {
  const res = await fetch(`${publicEnv.apiUrl}/api/v1/ibkr/status`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`IBKR status HTTP ${res.status}`);
  return res.json() as Promise<IbkrStatus>;
}

export type IBKRConnectionStatus =
  | "connected"
  | "disconnected"
  | "disabled"
  | "error"
  | "unknown";

export interface UseIBKRStatusResult {
  /** Human-readable connection status derived from enabled + authenticated fields. */
  connectionStatus: IBKRConnectionStatus;
  /** Raw backend payload — null while loading or on error. */
  data: IbkrStatus | null;
  isLoading: boolean;
  error: Error | null;
  /** Timestamp of last successful fetch (for "last heartbeat" display). */
  lastUpdated: Date | null;
}

/**
 * Unified IBKR status hook — replaces:
 *   - useIBKRHealth (polled /api/v1/health/ibkr every 30s via setInterval)
 *   - fetchIbkrStatus (called ad-hoc in opportunities/page.tsx)
 *
 * TanStack Query deduplicates requests: IBKRStatusBanner + IBKRStatusPill
 * (sidebar) both call this hook but produce only ONE network request per
 * refetchInterval window.
 *
 * Endpoint: GET /api/v1/ibkr/status
 * Interval:  30s (same as the old useIBKRHealth, consolidating the two polls)
 */
export function useIBKRStatus(): UseIBKRStatusResult {
  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: IBKR_STATUS_KEY,
    queryFn: fetchIbkrStatusQuery,
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8_000),
  });

  let connectionStatus: IBKRConnectionStatus = "unknown";

  if (!isLoading) {
    if (error) {
      connectionStatus = "error";
    } else if (!data) {
      connectionStatus = "unknown";
    } else if (data.enabled === false) {
      connectionStatus = "disabled";
    } else if (data.authenticated === true) {
      connectionStatus = "connected";
    } else if (data.authenticated === false) {
      connectionStatus = "disconnected";
    }
  }

  return {
    connectionStatus,
    data: data ?? null,
    isLoading,
    error: error as Error | null,
    lastUpdated: dataUpdatedAt ? new Date(dataUpdatedAt) : null,
  };
}
