import type { OpportunityRow } from "@/lib/api";

/** Id stabile per espansione card: simbolo + timeframe + provider + exchange. */
export function opportunityCardId(row: OpportunityRow): string {
  const p = row.provider ?? "";
  const e = row.exchange ?? "";
  return `${row.symbol}|${row.timeframe}|${p}|${e}`;
}
