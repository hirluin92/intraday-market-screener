"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { OpportunityRow } from "@/lib/api";
import { opportunityCardId } from "@/lib/opportunityCardId";
import { isDiscardedOutOfUniverse } from "@/lib/opportunityDiscardFilter";
import { sortOpportunityGroup, type OpportunitySortBy } from "@/lib/opportunitySort";

// Re-export types used across components
export type DecisionFilter = "all" | "execute" | "monitor" | "discard";
export type TfFilter = "all" | "1h" | "5m";
export type DirFilter = "all" | "bullish" | "bearish";

interface UseOpportunityFiltersOptions {
  rows: OpportunityRow[];
  isLoading?: boolean;
}

// Tiny helper — same as the one that used to live inline in page.tsx
function clientFilter(
  rows: OpportunityRow[],
  decision: DecisionFilter,
  tf: TfFilter,
  dir: DirFilter,
): OpportunityRow[] {
  return rows.filter((r) => {
    const d = (r.operational_decision ?? "monitor") as DecisionFilter;
    if (decision !== "all" && d !== decision) return false;
    if (tf !== "all" && r.timeframe !== tf) return false;
    if (dir !== "all") {
      const pat = (r.latest_pattern_direction ?? "").toLowerCase();
      if (dir === "bullish" && pat !== "bullish") return false;
      if (dir === "bearish" && pat !== "bearish") return false;
    }
    return true;
  });
}

export function useOpportunityFilters({ rows, isLoading = false }: UseOpportunityFiltersOptions) {
  const searchParams = useSearchParams();

  // ── Primary filters ──────────────────────────────────────────────────────
  const [decisionFilter, setDecisionFilterRaw] = useState<DecisionFilter>("all");
  const [tfFilter, setTfFilter] = useState<TfFilter>("all");
  const [dirFilter, setDirFilter] = useState<DirFilter>("all");
  const [sortBy, setSortBy] = useState<OpportunitySortBy>("default");

  // ── Card expansion ───────────────────────────────────────────────────────
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const skipFilterClearRef = useRef(false);

  // Clear expansion when filters change (unless deep link bypasses it)
  useEffect(() => {
    if (skipFilterClearRef.current) {
      skipFilterClearRef.current = false;
      return;
    }
    setExpandedCardId(null);
  }, [decisionFilter, tfFilter, dirFilter]);

  const setDecisionFilter = useCallback((v: DecisionFilter) => {
    setDecisionFilterRaw(v);
  }, []);

  // ── Discarded visibility ─────────────────────────────────────────────────
  const [showDiscarded, setShowDiscarded] = useState(false);
  const toggleShowDiscarded = useCallback(
    () => setShowDiscarded((v) => !v),
    [],
  );

  // ── Executed signals table ───────────────────────────────────────────────
  const [signalsExpanded, setSignalsExpanded] = useState(true);
  const [signalsStatusFilter, setSignalsStatusFilter] = useState<
    "all" | "open" | "closed" | "skipped" | "cancelled"
  >("open");

  // ── Deep link handler ────────────────────────────────────────────────────
  const [deepLinkHandled, setDeepLinkHandled] = useState(false);

  const focusSymbol = searchParams?.get("symbol");
  const focusTimeframe = searchParams?.get("timeframe");
  const focusProvider = searchParams?.get("provider");
  const focusExchange = searchParams?.get("exchange");
  const shouldExpandFromUrl = searchParams?.get("expand") === "true";

  useEffect(() => {
    if (!shouldExpandFromUrl || !focusSymbol?.trim() || isLoading || deepLinkHandled) return;
    if (rows.length === 0) return;

    const sym = focusSymbol.trim().toUpperCase();
    const target = rows.find((o) => {
      const os = String(o.symbol).toUpperCase();
      if (os !== sym) return false;
      if (focusTimeframe && o.timeframe !== focusTimeframe) return false;
      if (focusProvider && (o.provider ?? "") !== focusProvider) return false;
      if (
        focusExchange != null &&
        focusExchange !== "" &&
        (o.exchange ?? "") !== focusExchange
      ) return false;
      return true;
    });

    if (!target) { setDeepLinkHandled(true); return; }

    skipFilterClearRef.current = true;
    setDecisionFilterRaw("all");
    if (focusTimeframe === "1h" || focusTimeframe === "5m") {
      setTfFilter(focusTimeframe);
    } else {
      setTfFilter("all");
    }
    setDirFilter("all");

    const cid = opportunityCardId(target);
    if (target.operational_decision === "discard") {
      setShowDiscarded(true);
    }

    let t1: number | undefined;
    let t2: number | undefined;
    let t3: number | undefined;

    t1 = window.setTimeout(() => {
      if (target.operational_decision !== "discard") {
        setExpandedCardId(cid);
      }
      setDeepLinkHandled(true);
      t2 = window.setTimeout(() => {
        const el = document.getElementById(`card-${cid}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add(
            "ring-2",
            "ring-yellow-400",
            "ring-offset-2",
            "ring-offset-[var(--bg-base)]",
          );
          t3 = window.setTimeout(() => {
            el.classList.remove(
              "ring-2",
              "ring-yellow-400",
              "ring-offset-2",
              "ring-offset-[var(--bg-base)]",
            );
          }, 3000);
        }
      }, 400);
    }, 0);

    return () => {
      if (t1) window.clearTimeout(t1);
      if (t2) window.clearTimeout(t2);
      if (t3) window.clearTimeout(t3);
    };
  }, [
    shouldExpandFromUrl,
    focusSymbol,
    focusTimeframe,
    focusProvider,
    focusExchange,
    isLoading,
    rows,
    deepLinkHandled,
  ]);

  // ── Derived data ─────────────────────────────────────────────────────────

  const filtered = useMemo(
    () => clientFilter(rows, decisionFilter, tfFilter, dirFilter),
    [rows, decisionFilter, tfFilter, dirFilter],
  );

  const executeRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "execute"),
    [filtered],
  );
  const monitorRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "monitor"),
    [filtered],
  );
  const discardRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "discard"),
    [filtered],
  );
  const discardRowsInUniverse = useMemo(
    () => discardRows.filter((r) => !isDiscardedOutOfUniverse(r)),
    [discardRows],
  );

  const executeRowsSorted = useMemo(
    () => sortOpportunityGroup(executeRows, sortBy),
    [executeRows, sortBy],
  );
  const monitorRowsSorted = useMemo(
    () => sortOpportunityGroup(monitorRows, sortBy),
    [monitorRows, sortBy],
  );
  const discardRowsSorted = useMemo(
    () => sortOpportunityGroup(discardRowsInUniverse, sortBy),
    [discardRowsInUniverse, sortBy],
  );

  const totalExecute = useMemo(
    () => rows.filter((r) => r.operational_decision === "execute").length,
    [rows],
  );

  const counts = useMemo(
    () => ({
      execute: rows.filter((r) => r.operational_decision === "execute").length,
      monitor: rows.filter((r) => r.operational_decision === "monitor").length,
      discard: rows.filter(
        (r) =>
          r.operational_decision === "discard" && !isDiscardedOutOfUniverse(r),
      ).length,
      total: rows.length,
    }),
    [rows],
  );

  const showExecuteBlock = decisionFilter === "all" || decisionFilter === "execute";
  const showMonitorBlock = decisionFilter === "all" || decisionFilter === "monitor";
  const showDiscardBlock = decisionFilter === "all" || decisionFilter === "discard";

  const emptyExecute =
    showExecuteBlock &&
    executeRows.length === 0 &&
    !isLoading &&
    rows.length > 0;

  return {
    // Primary filter state
    decisionFilter,
    setDecisionFilter,
    tfFilter,
    setTfFilter,
    dirFilter,
    setDirFilter,
    sortBy,
    setSortBy,

    // Card expansion
    expandedCardId,
    setExpandedCardId,

    // Visibility toggles
    showDiscarded,
    toggleShowDiscarded,

    // Signals table state
    signalsExpanded,
    setSignalsExpanded,
    signalsStatusFilter,
    setSignalsStatusFilter,

    // Derived filtered + sorted data
    filtered,
    sorted: {
      execute: executeRowsSorted,
      monitor: monitorRowsSorted,
      discard: discardRowsSorted,
    },
    counts,
    totalExecute,

    // Visibility block flags
    showExecuteBlock,
    showMonitorBlock,
    showDiscardBlock,
    emptyExecute,
  };
}
