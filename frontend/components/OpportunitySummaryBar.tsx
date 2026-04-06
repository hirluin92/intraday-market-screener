"use client";

import type { OpportunityRow } from "@/lib/api";
import {
  displayOperationalDecisionListLabel,
  operationalDecisionBadgePillClass,
} from "@/lib/displayLabels";

type DecisionCounts = {
  execute: number;
  monitor: number;
  discard: number;
  total: number;
};

function countDecisions(rows: OpportunityRow[]): DecisionCounts {
  let execute = 0;
  let monitor = 0;
  let discard = 0;
  for (const r of rows) {
    if (r.operational_decision === "execute" || r.operational_decision === "operable")
      execute++;
    else if (r.operational_decision === "monitor") monitor++;
    else discard++;
  }
  return { execute, monitor, discard, total: rows.length };
}

export function OpportunitySummaryBar({ rows }: { rows: OpportunityRow[] }) {
  const counts = countDecisions(rows);
  if (counts.total === 0) return null;

  const segments: [string, number][] = [
    ["execute", counts.execute],
    ["monitor", counts.monitor],
    ["discard", counts.discard],
  ];

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50/80 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-950/40"
      aria-label="Riepilogo decisioni operative"
    >
      <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
        {counts.total} serie:
      </span>
      {segments.map(([dec, n]) => (
        <span
          key={dec}
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums ${operationalDecisionBadgePillClass(dec)}`}
          title={`${n} ${displayOperationalDecisionListLabel(dec)}`}
        >
          {n} {displayOperationalDecisionListLabel(dec)}
        </span>
      ))}
    </div>
  );
}
