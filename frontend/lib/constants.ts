/** Pattern validati OOS (nomi). La validità effettiva dipende dal timeframe — usare `isPatternValidatedForTimeframe`. */
export const VALIDATED_PATTERNS_OPERATIONAL = [
  "compression_to_expansion_transition",
  "rsi_momentum_continuation",
] as const;

const VALIDATED_1H = new Set<string>(VALIDATED_PATTERNS_OPERATIONAL);
const VALIDATED_5M = new Set<string>(["rsi_momentum_continuation"]);

/** Coerente con backend: set per TF (1h vs 5m). */
export function isPatternValidatedForTimeframe(
  patternName: string | null | undefined,
  timeframe: string,
): boolean {
  if (!patternName?.trim()) return false;
  const pn = patternName.trim();
  const tf = timeframe.trim();
  if (tf === "1h") return VALIDATED_1H.has(pn);
  if (tf === "5m") return VALIDATED_5M.has(pn);
  return false;
}
