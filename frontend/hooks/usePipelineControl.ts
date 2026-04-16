"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { postPipelineRefresh, type PipelineRefreshRequest } from "@/lib/api";
import { OPPORTUNITIES_QUERY_KEY } from "./useOpportunities";

const TIMEFRAME_OPTIONS = ["", "1m", "5m", "15m", "1h", "1d"] as const;

/**
 * Manages pipeline refresh form state + POST action.
 * Replaces the 9 useState items for pipeline form in page.tsx.
 * Invalidates opportunities query on success so the list auto-updates.
 */
export function usePipelineControl() {
  const queryClient = useQueryClient();

  // Dialog open state
  const [dialogOpen, setDialogOpen] = useState(false);

  // Form state
  const [provider, setProvider] = useState<"binance" | "yahoo_finance">("binance");
  const [exchangeOverride, setExchangeOverride] = useState("");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [ingestLimit, setIngestLimit] = useState(2500);
  const [extractLimit, setExtractLimit] = useState(5000);
  const [lookback, setLookback] = useState(50);

  // Action state
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setIsRefreshing(true);
    setMessage(null);
    setError(null);

    const body: PipelineRefreshRequest = {
      provider,
      ingest_limit: ingestLimit,
      extract_limit: extractLimit,
      lookback,
    };
    if (exchangeOverride.trim()) body.exchange = exchangeOverride.trim();
    if (symbol.trim()) body.symbol = symbol.trim();
    if (timeframe.trim()) body.timeframe = timeframe.trim();

    try {
      await postPipelineRefresh(body);
      setMessage("Aggiornamento pipeline completato.");
      await queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsRefreshing(false);
    }
  }

  return {
    dialogOpen,
    openDialog: () => setDialogOpen(true),
    closeDialog: () => setDialogOpen(false),
    // Form fields
    provider,   setProvider,
    exchangeOverride, setExchangeOverride,
    symbol,     setSymbol,
    timeframe,  setTimeframe,
    ingestLimit, setIngestLimit,
    extractLimit, setExtractLimit,
    lookback,   setLookback,
    // Action
    isRefreshing,
    message,
    error,
    refresh,
    timeframeOptions: TIMEFRAME_OPTIONS,
  };
}
