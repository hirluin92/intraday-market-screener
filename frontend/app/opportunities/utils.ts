import type { OpportunityRow } from "@/lib/api";

/**
 * Extracts the current SPY regime from the first row that carries one.
 * Prefers a row whose symbol includes "SPY", falls back to any row with regime.
 * Moved from inline in page.tsx.
 */
export function pickRegimeSpy(rows: OpportunityRow[]): string | undefined {
  const withRegime = rows.filter(
    (r) => r.regime_spy && r.regime_spy !== "n/a",
  );
  if (withRegime.length === 0) return undefined;
  const spy = withRegime.find((r) =>
    String(r.symbol).toUpperCase().includes("SPY"),
  );
  return (spy ?? withRegime[0]).regime_spy;
}
