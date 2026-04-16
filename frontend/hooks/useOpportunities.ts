"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchOpportunities } from "@/lib/api";
import { recordExecuteListMax } from "@/lib/traderExecuteStats";

export const OPPORTUNITIES_QUERY_KEY = ["screener", "opportunities", "main"] as const;

const FETCH_LIMIT = 500;
const REFRESH_SEC = 60;

/**
 * TanStack Query wrapper for the main opportunities endpoint.
 *
 * Replaces:
 *   - fetchOpportunities() called inside load() every 60s (setInterval)
 *   - autoRefresh checkbox state
 *   - secondsToRefresh countdown (derived from dataUpdatedAt)
 *   - timeLabelReady hydration guard
 *   - recordExecuteListMax side effect
 */
export function useOpportunities() {
  const queryClient = useQueryClient();
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [timeLabelReady, setTimeLabelReady] = useState(false);
  const [secondsToRefresh, setSecondsToRefresh] = useState(REFRESH_SEC);

  useEffect(() => {
    setTimeLabelReady(true);
  }, []);

  const query = useQuery({
    queryKey: OPPORTUNITIES_QUERY_KEY,
    queryFn: async () => {
      const data = await fetchOpportunities({ limit: FETCH_LIMIT });
      const execN = data.opportunities.filter(
        (r) => r.operational_decision === "execute",
      ).length;
      recordExecuteListMax(execN);
      return data;
    },
    staleTime: 30_000,
    refetchInterval: autoRefresh ? REFRESH_SEC * 1000 : false,
    refetchIntervalInBackground: false,
  });

  // Countdown to next refetch
  useEffect(() => {
    if (!query.dataUpdatedAt) return;
    const updateCountdown = () => {
      const elapsed = (Date.now() - query.dataUpdatedAt) / 1000;
      setSecondsToRefresh(Math.max(0, REFRESH_SEC - Math.floor(elapsed)));
    };
    updateCountdown();
    const id = setInterval(updateCountdown, 1000);
    return () => clearInterval(id);
  }, [query.dataUpdatedAt]);

  const refetch = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
  }, [queryClient]);

  const lastUpdate = query.dataUpdatedAt ? new Date(query.dataUpdatedAt) : null;

  return {
    data: query.data,
    rows: query.data?.opportunities ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error ? (query.error instanceof Error ? query.error.message : String(query.error)) : null,
    refetch,
    lastUpdate,
    dataUpdatedAt: query.dataUpdatedAt,
    autoRefresh,
    setAutoRefresh,
    secondsToRefresh,
    timeLabelReady,
    REFRESH_SEC,
  };
}
