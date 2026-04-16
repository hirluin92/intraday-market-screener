"use client";

import { CheckCircle2, Eye, Filter, Minus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { DecisionFilter, DirFilter, TfFilter } from "@/hooks/useOpportunityFilters";
import type { OpportunitySortBy } from "@/lib/opportunitySort";

interface Counts {
  execute: number;
  monitor: number;
  discard: number;
  total: number;
}

interface FilterPillsProps {
  decisionFilter: DecisionFilter;
  setDecisionFilter: (v: DecisionFilter) => void;
  tfFilter: TfFilter;
  setTfFilter: (v: TfFilter) => void;
  dirFilter: DirFilter;
  setDirFilter: (v: DirFilter) => void;
  sortBy: OpportunitySortBy;
  setSortBy: (v: OpportunitySortBy) => void;
  counts?: Counts;
  /** compact = inside header (decision only), full = standalone row (all groups) */
  mode?: "compact" | "full";
}

function SegmentButton({
  active,
  onClick,
  children,
  className,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
        active
          ? "bg-surface-3 text-fg shadow-sm"
          : "text-fg-2 hover:bg-surface-2 hover:text-fg",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function FilterPills({
  decisionFilter,
  setDecisionFilter,
  tfFilter,
  setTfFilter,
  dirFilter,
  setDirFilter,
  counts,
  mode = "full",
}: FilterPillsProps) {
  const decisionOptions: {
    id: DecisionFilter;
    label: string;
    Icon?: React.ElementType;
    count?: number;
    badgeCls?: string;
  }[] = [
    { id: "all", label: "Tutti", count: counts?.total },
    {
      id: "execute",
      label: "Esegui",
      Icon: CheckCircle2,
      count: counts?.execute,
      badgeCls: counts?.execute ? "bg-bull/15 text-bull border-bull/20" : undefined,
    },
    {
      id: "monitor",
      label: "Monitor",
      Icon: Eye,
      count: counts?.monitor,
      badgeCls: counts?.monitor ? "bg-warn/15 text-warn border-warn/20" : undefined,
    },
    {
      id: "discard",
      label: "Scarta",
      Icon: Minus,
      count: counts?.discard,
    },
  ];

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        mode === "compact" && "gap-1",
      )}
      role="group"
      aria-label="Filtri opportunità"
    >
      {/* Decision filter — segment control */}
      <div className="inline-flex rounded-lg border border-line bg-canvas p-0.5">
        {decisionOptions.map(({ id, label, Icon, count, badgeCls }) => (
          <SegmentButton
            key={id}
            active={decisionFilter === id}
            onClick={() => setDecisionFilter(id)}
          >
            {Icon && (
              <Icon
                className={cn(
                  "h-3 w-3",
                  id === "execute" && decisionFilter === id && "text-bull",
                  id === "monitor" && decisionFilter === id && "text-warn",
                )}
                aria-hidden
              />
            )}
            {mode === "full" && label}
            {count !== undefined && count > 0 && (
              <Badge
                variant="outline"
                className={cn(
                  "h-4 min-w-4 px-1 font-mono text-[10px] tabular-nums",
                  badgeCls,
                )}
              >
                {count}
              </Badge>
            )}
          </SegmentButton>
        ))}
      </div>

      {/* TF + Direction — only in full mode */}
      {mode === "full" && (
        <>
          <div
            className="inline-flex rounded-lg border border-line bg-canvas p-0.5"
            role="group"
            aria-label="Filtro timeframe"
          >
            {(["all", "1h", "5m"] as TfFilter[]).map((tf) => (
              <SegmentButton
                key={tf}
                active={tfFilter === tf}
                onClick={() => setTfFilter(tf)}
              >
                {tf === "all" ? <Filter className="h-3 w-3" aria-hidden /> : tf}
              </SegmentButton>
            ))}
          </div>

          <div
            className="inline-flex rounded-lg border border-line bg-canvas p-0.5"
            role="group"
            aria-label="Filtro direzione"
          >
            {(
              [
                { id: "all" as DirFilter, label: "Dir." },
                { id: "bullish" as DirFilter, label: "Bull ▲" },
                { id: "bearish" as DirFilter, label: "Bear ▼" },
              ] as const
            ).map(({ id, label }) => (
              <SegmentButton
                key={id}
                active={dirFilter === id}
                onClick={() => setDirFilter(id)}
                className={cn(
                  id === "bullish" && dirFilter === "bullish" && "text-bull",
                  id === "bearish" && dirFilter === "bearish" && "text-bear",
                )}
              >
                {label}
              </SegmentButton>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

