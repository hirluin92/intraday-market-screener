"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchBacktestPatterns, fetchOpportunities } from "@/lib/api";

const STALE_MS = 5 * 60_000;

export function useDiagnosticPatterns() {
  return useQuery({
    queryKey: ["diagnostica", "patterns"],
    queryFn: () => fetchBacktestPatterns({ limit: 500 }),
    staleTime: STALE_MS,
    retry: 2,
  });
}

export function useDiagnosticOpportunities() {
  return useQuery({
    queryKey: ["diagnostica", "opportunities"],
    queryFn: () => fetchOpportunities({ limit: 500 }),
    staleTime: STALE_MS,
    retry: 2,
  });
}
