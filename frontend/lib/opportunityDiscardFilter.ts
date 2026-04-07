import type { OpportunityRow } from "@/lib/api";

/**
 * Scarti “fuori universo” (scheduler su simboli non validati): nascosti in UI.
 * Pattern non operativo nell’universo: restano visibili.
 */
export function isDiscardedOutOfUniverse(opp: OpportunityRow): boolean {
  const first = opp.decision_rationale?.[0] ?? "";
  const lower = first.toLowerCase();
  return lower.includes("universo validato") || lower.includes("timeframe");
}
