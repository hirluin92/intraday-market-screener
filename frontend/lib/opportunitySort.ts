import type { OpportunityRow } from "@/lib/api";

import { opportunityCardId } from "./opportunityCardId";

export type OpportunitySortBy = "default" | "symbol" | "rr" | "strength";

function strengthNumeric(row: OpportunityRow): number {
  const s = row.latest_pattern_strength;
  if (s == null) return 0;
  const n = typeof s === "number" ? s : Number(s);
  if (!Number.isFinite(n)) return 0;
  return n <= 1 ? n * 100 : n;
}

function parseRr(row: OpportunityRow): number {
  const raw = row.trade_plan?.risk_reward_ratio;
  if (raw == null) return 0;
  const n = typeof raw === "number" ? raw : parseFloat(String(raw));
  return Number.isFinite(n) ? n : 0;
}

/** Ordinamento secondario dentro un gruppo (execute / monitor / discard). «Decisione» = default (score poi tie-break). */
export function sortOpportunityGroup(
  rows: OpportunityRow[],
  sortBy: OpportunitySortBy,
): OpportunityRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    let cmp = 0;
    if (sortBy === "symbol") {
      cmp = a.symbol.localeCompare(b.symbol, "it", { sensitivity: "base" });
    } else if (sortBy === "rr") {
      cmp = parseRr(b) - parseRr(a);
    } else if (sortBy === "strength") {
      cmp = strengthNumeric(b) - strengthNumeric(a);
    } else {
      cmp = (b.final_opportunity_score ?? 0) - (a.final_opportunity_score ?? 0);
    }
    if (cmp !== 0) return cmp;
    return opportunityCardId(a).localeCompare(opportunityCardId(b));
  });
  return copy;
}
