"use client";

import type {
  DecisionFilter,
  DirFilter,
  TfFilter,
} from "@/hooks/useOpportunityFilters";
import type { OpportunitySortBy } from "@/lib/opportunitySort";

function pillClass(active: boolean, accent?: "execute" | "monitor" | "warn"): string {
  const base =
    "rounded-full border px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-neutral)]";
  if (!active) {
    return `${base} border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)] hover:border-[var(--border-active)]`;
  }
  if (accent === "execute") {
    return `${base} border-[var(--accent-bull)] bg-[var(--accent-bull)]/15 text-[var(--accent-bull)] shadow-[var(--glow-bull)]`;
  }
  if (accent === "monitor") {
    return `${base} border-amber-400/80 bg-amber-500/15 text-amber-200`;
  }
  if (accent === "warn") {
    return `${base} border-[var(--accent-bear)]/60 bg-[var(--accent-bear)]/10 text-[var(--accent-bear)]`;
  }
  return `${base} border-[var(--accent-neutral)] bg-[var(--accent-neutral)]/15 text-[var(--text-primary)]`;
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
}

export function FilterPills({
  decisionFilter,
  setDecisionFilter,
  tfFilter,
  setTfFilter,
  dirFilter,
  setDirFilter,
}: FilterPillsProps) {
  return (
    <section aria-label="Filtri rapidi" className="flex flex-wrap gap-2">
      <span className="w-full text-xs font-medium text-[var(--text-muted)]">Decisione</span>
      {(
        [
          ["all", "Tutti"],
          ["execute", "✅ Esegui"],
          ["monitor", "👁 Monitora"],
          ["discard", "Scarta"],
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          className={pillClass(
            decisionFilter === id,
            id === "execute" ? "execute" : id === "monitor" ? "monitor" : id === "discard" ? "warn" : undefined,
          )}
          onClick={() => setDecisionFilter(id)}
        >
          {label}
        </button>
      ))}
      <span className="mx-1 w-full sm:w-auto sm:pl-2" />
      <span className="w-full text-xs font-medium text-[var(--text-muted)] sm:w-auto">Timeframe</span>
      {(
        [
          ["all", "Tutti"],
          ["1h", "1h"],
          ["5m", "5m"],
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          className={pillClass(tfFilter === id)}
          onClick={() => setTfFilter(id)}
        >
          {label}
        </button>
      ))}
      <span className="mx-1 w-full sm:w-auto sm:pl-2" />
      <span className="w-full text-xs font-medium text-[var(--text-muted)] sm:w-auto">Direzione</span>
      {(
        [
          ["all", "Tutti"],
          ["bearish", "Bearish"],
          ["bullish", "Bullish"],
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          className={pillClass(dirFilter === id)}
          onClick={() => setDirFilter(id)}
        >
          {label}
        </button>
      ))}
    </section>
  );
}
