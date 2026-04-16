"use client";

import { useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  fetchBacktestSimulation,
  fetchOutOfSample,
  fetchWalkForward,
  type SimulationParams,
} from "@/lib/api";

const WF_TIMEOUT_MS = 125_000; // 125s — slightly above 120s backend timeout

/**
 * Wraps the 3 simulation endpoints as TanStack mutations.
 * Walk-forward has a client-side AbortController + timeout.
 */
export function useSimulation() {
  const wfAbortRef = useRef<AbortController | null>(null);

  const equity = useMutation({
    mutationFn: (params: SimulationParams) => fetchBacktestSimulation(params),
  });

  const oos = useMutation({
    mutationFn: (params: SimulationParams) => fetchOutOfSample(params),
  });

  const walkForward = useMutation({
    mutationFn: async (params: SimulationParams) => {
      const controller = new AbortController();
      wfAbortRef.current = controller;
      const timer = setTimeout(() => controller.abort("timeout"), WF_TIMEOUT_MS);
      try {
        return await fetchWalkForward(params);
      } finally {
        clearTimeout(timer);
        wfAbortRef.current = null;
      }
    },
  });

  const cancelWalkForward = () => {
    wfAbortRef.current?.abort("user_cancel");
    wfAbortRef.current = null;
  };

  return { equity, oos, walkForward, cancelWalkForward };
}
