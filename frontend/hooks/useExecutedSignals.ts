"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchExecutedSignals } from "@/lib/api";

export const EXECUTED_SIGNALS_KEY = ["screener", "executed-signals", "main"] as const;

export function useExecutedSignals(limit = 100) {
  return useQuery({
    queryKey: [...EXECUTED_SIGNALS_KEY, limit],
    queryFn: () => fetchExecutedSignals(limit),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}
