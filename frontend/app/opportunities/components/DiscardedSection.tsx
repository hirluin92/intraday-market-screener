"use client";

import type { OpportunityRow } from "@/lib/api";
import { opportunityCardId } from "@/lib/opportunityCardId";
import { DiscardedCard } from "./DiscardedCard";

interface DiscardedSectionProps {
  rows: OpportunityRow[];
  showDiscardBlock: boolean;
  showDiscarded: boolean;
  onToggle: () => void;
}

export function DiscardedSection({
  rows,
  showDiscardBlock,
  showDiscarded,
  onToggle,
}: DiscardedSectionProps) {
  if (!showDiscardBlock || rows.length === 0) return null;

  return (
    <section aria-label="Scartati nell'universo" className="mt-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 border-t border-[var(--border)] py-3 text-left text-sm text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
        aria-expanded={showDiscarded}
      >
        <span>
          {showDiscarded ? "▲" : "▼"} Nell&apos;universo ma pattern non operativo ({rows.length})
        </span>
      </button>
      {showDiscarded && (
        <div className="space-y-2 pb-2" role="list">
          {rows.map((row) => (
            <DiscardedCard key={opportunityCardId(row)} opportunity={row} />
          ))}
        </div>
      )}
    </section>
  );
}
