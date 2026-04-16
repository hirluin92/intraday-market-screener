"use client";

import { RefreshCw, Settings, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UseIBKRStatusResult } from "@/hooks/useIBKRStatus";
import type { DecisionFilter, DirFilter, TfFilter } from "@/hooks/useOpportunityFilters";
import type { OpportunitySortBy } from "@/lib/opportunitySort";
import { FilterPills } from "./FilterPills";
import { RegimeBadge } from "./RegimeBadge";

interface Counts {
  execute: number;
  monitor: number;
  discard: number;
  total: number;
}

interface OpportunitiesHeaderProps {
  ibkr: UseIBKRStatusResult;
  regime?: string;
  isLoading: boolean;
  isFetching?: boolean;
  autoRefresh: boolean;
  onAutoRefreshChange: (v: boolean) => void;
  secondsToRefresh: number;
  lastUpdate: Date | null;
  onRefresh: () => void;
  totalExecute: number;
  timeLabelReady: boolean;
  onPipelineOpen: () => void;
  onPreferencesOpen: () => void;
  counts: Counts;
  decisionFilter: DecisionFilter;
  setDecisionFilter: (v: DecisionFilter) => void;
  tfFilter: TfFilter;
  setTfFilter: (v: TfFilter) => void;
  dirFilter: DirFilter;
  setDirFilter: (v: DirFilter) => void;
  sortBy: OpportunitySortBy;
  setSortBy: (v: OpportunitySortBy) => void;
}

export function OpportunitiesHeader({
  ibkr,
  regime,
  isLoading,
  isFetching,
  autoRefresh,
  onAutoRefreshChange,
  secondsToRefresh,
  lastUpdate,
  onRefresh,
  totalExecute,
  timeLabelReady,
  onPipelineOpen,
  onPreferencesOpen,
  counts,
  decisionFilter,
  setDecisionFilter,
  tfFilter,
  setTfFilter,
  dirFilter,
  setDirFilter,
  sortBy,
  setSortBy,
}: OpportunitiesHeaderProps) {
  const ibkrStatus = ibkr.data;
  const ibkrError = !!ibkr.error && !ibkr.isLoading;

  return (
    <header
      className="sticky top-0 z-20"
      style={{
        background: "hsla(228, 15%, 8%, 0.70)",
        backdropFilter: "blur(20px) saturate(160%)",
        WebkitBackdropFilter: "blur(20px) saturate(160%)",
        borderBottom: "1px solid hsla(0, 0%, 100%, 0.07)",
      }}
    >
      {/* ── Main row ─────────────────────────────────────────────────── */}
      <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-3 px-4 py-2 sm:px-6">
        {/* Left: FilterPills (decision filter compact) + TF/Dir below on mobile */}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2 shrink-0" aria-hidden>
              <span className="absolute h-2 w-2 animate-pulse-live rounded-full bg-bull" />
            </span>
            <span className="font-mono text-[10px] font-semibold text-bull">LIVE</span>
          </div>

          <FilterPills
            decisionFilter={decisionFilter}
            setDecisionFilter={setDecisionFilter}
            tfFilter={tfFilter}
            setTfFilter={setTfFilter}
            dirFilter={dirFilter}
            setDirFilter={setDirFilter}
            sortBy={sortBy}
            setSortBy={setSortBy}
            counts={counts}
            mode="compact"
          />

          {/* IBKR status inline pill */}
          {ibkrError && (
            <Badge variant="outline" className="border-warn/40 bg-warn/10 text-warn font-mono text-[10px]">
              ⚠ IBKR
            </Badge>
          )}
          {ibkrStatus?.enabled && ibkrStatus.authenticated && (
            <Badge variant="outline" className="border-bull/30 bg-bull/10 text-bull font-mono text-[10px]">
              ● {ibkrStatus.paper_trading ? "PAPER" : "LIVE"}
              {ibkrStatus.auto_execute && " · AUTO"}
            </Badge>
          )}
          {ibkrStatus?.enabled && !ibkrStatus.authenticated && (
            <Badge variant="outline" className="border-bear/30 bg-bear/10 text-bear font-mono text-[10px]">
              ● IBKR disconnesso
            </Badge>
          )}

          <RegimeBadge regime={regime} />

          {totalExecute > 0 && (
            <Badge
              className={cn(
                "font-mono tabular-nums",
                "border-bull/40 bg-bull/10 text-bull animate-glow-execute",
              )}
              variant="outline"
              aria-label={`${totalExecute} segnali execute`}
            >
              {totalExecute} ESEGUI
            </Badge>
          )}
        </div>

        {/* Center: countdown + refresh */}
        <div className="flex shrink-0 items-center gap-2">
          <span
            className="font-mono text-xs tabular-nums text-fg-3"
            aria-live="polite"
            aria-atomic="true"
          >
            {timeLabelReady && lastUpdate
              ? lastUpdate.toLocaleTimeString("it-IT", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })
              : "—"}
          </span>

          {autoRefresh && (
            <span
              className="font-mono text-xs tabular-nums text-fg-3"
              aria-live="polite"
              suppressHydrationWarning
            >
              <span className="text-fg-2">{secondsToRefresh}s</span>
            </span>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onRefresh}
            disabled={isLoading}
            aria-label="Aggiorna opportunità"
            title="Aggiorna opportunità"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", isFetching && "animate-spin")}
              aria-hidden
            />
          </Button>

          <label className="flex cursor-pointer items-center gap-1 text-xs text-fg-2">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => onAutoRefreshChange(e.target.checked)}
              className="h-3 w-3 rounded border-line bg-surface-2 accent-bull"
            />
            <span className="hidden sm:inline">Auto</span>
          </label>
        </div>

        {/* Right: Preferenze (hidden ≥xl) + Strumenti */}
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="xl:hidden h-8 gap-1.5 text-xs text-fg-2"
            onClick={onPreferencesOpen}
            aria-label="Apri preferenze"
          >
            <Settings className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Preferenze</span>
          </Button>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs text-fg-2"
            onClick={onPipelineOpen}
            aria-label="Apri strumenti pipeline"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Strumenti</span>
          </Button>
        </div>
      </div>

      {/* ── Secondary row: TF + Direction filters ─────────────────────── */}
      <div className="mx-auto flex max-w-[1440px] items-center gap-2 border-t border-line/50 px-4 py-1.5 sm:px-6">
        <FilterPills
          decisionFilter={decisionFilter}
          setDecisionFilter={setDecisionFilter}
          tfFilter={tfFilter}
          setTfFilter={setTfFilter}
          dirFilter={dirFilter}
          setDirFilter={setDirFilter}
          sortBy={sortBy}
          setSortBy={setSortBy}
          counts={counts}
          mode="full"
        />
      </div>
    </header>
  );
}
