"use client";

import { useQueries } from "@tanstack/react-query";

import { publicEnv } from "@/lib/env";
import type { IbkrStatus } from "@/lib/api";

export const IBKR_STATUS_KEY = ["ibkr", "status"] as const;
export const TWS_STATUS_KEY  = ["ibkr", "tws-status"] as const;

async function fetchIbkrStatusQuery(): Promise<IbkrStatus> {
  const res = await fetch(`${publicEnv.apiUrl}/api/v1/ibkr/status`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`IBKR status HTTP ${res.status}`);
  return res.json() as Promise<IbkrStatus>;
}

async function fetchTWSStatusQuery(): Promise<IbkrStatus> {
  const res = await fetch(`${publicEnv.apiUrl}/api/v1/ibkr/tws/status`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`TWS status HTTP ${res.status}`);
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
 * Polls both GET /api/v1/ibkr/status (Gateway REST) and
 * GET /api/v1/ibkr/tws/status (ib_insync socket) every 30s.
 *
 * Priority logic:
 *   - If Gateway is enabled (ibkr_enabled=true): use its `authenticated` field.
 *   - If Gateway is disabled but TWS is enabled: use TWS `connected` as primary.
 *     This covers TWS-only mode where IBKR_ENABLED=false and TWS_ENABLED=true.
 *
 * Without this, a TWS disconnection is invisible in the UI while the Gateway
 * REST endpoint still reports "connected" — silent order execution failure.
 *
 * TanStack Query deduplicates: IBKRStatusBanner + IBKRStatusPill share cache.
 */
export function useIBKRStatus(): UseIBKRStatusResult {
  const results = useQueries({
    queries: [
      {
        queryKey: IBKR_STATUS_KEY,
        queryFn: fetchIbkrStatusQuery,
        refetchInterval: 30_000,
        staleTime: 20_000,
        retry: 2,
        retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 8_000),
      },
      {
        queryKey: TWS_STATUS_KEY,
        queryFn: fetchTWSStatusQuery,
        refetchInterval: 30_000,
        staleTime: 20_000,
        retry: 2,
        retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 8_000),
      },
    ],
  });

  const [gwQuery, twsQuery] = results;
  const gwData  = gwQuery.data  ?? null;
  const twsData = twsQuery.data ?? null;

  const isLoading    = gwQuery.isLoading || twsQuery.isLoading;
  const error        = (gwQuery.error || twsQuery.error) as Error | null;
  const dataUpdatedAt = Math.max(gwQuery.dataUpdatedAt ?? 0, twsQuery.dataUpdatedAt ?? 0);

  // Merge: TWS fields override Gateway when Gateway is disabled
  const merged: IbkrStatus | null = (() => {
    if (!gwData && !twsData) return null;
    const base: IbkrStatus = { ...(gwData ?? {}), ...(twsData ?? {}) };
    // tws_connected surfaces the socket state explicitly for consumers
    base.tws_connected = twsData?.connected ?? twsData?.authenticated ?? false;
    return base;
  })();

  let connectionStatus: IBKRConnectionStatus = "unknown";

  if (!isLoading) {
    if (error && !merged) {
      connectionStatus = "error";
    } else if (!merged) {
      connectionStatus = "unknown";
    } else {
      // TWS-only mode: Gateway returns {enabled:false} but TWS may be connected
      const gwEnabled  = gwData?.enabled !== false;
      const twsEnabled = twsData?.enabled === true;

      if (gwEnabled) {
        // Gateway REST path
        if (gwData?.authenticated === true) connectionStatus = "connected";
        else if (gwData?.authenticated === false) connectionStatus = "disconnected";
        else connectionStatus = "unknown";
      } else if (twsEnabled) {
        // TWS-only path
        if (twsData?.connected === true || twsData?.authenticated === true) connectionStatus = "connected";
        else connectionStatus = "disconnected";
      } else {
        connectionStatus = "disabled";
      }
    }
  }

  return {
    connectionStatus,
    data: merged,
    isLoading,
    error,
    lastUpdated: dataUpdatedAt ? new Date(dataUpdatedAt) : null,
  };
}
