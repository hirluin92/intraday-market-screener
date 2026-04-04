/**
 * Snapshot economico + sizing per una riga opportunità (solo frontend).
 * Usa TradePlanV1 già presente nell’API: nessun endpoint nuovo.
 */

import type { TradePlanV1 } from "./api";
import {
  computeEconomicViability,
  computeSimpleEconomicVerdict,
  type EconomicVerdictTier,
  type EconomicViabilityResult,
  type SimpleEconomicVerdict,
} from "./economicViability";
import {
  computePositionSizingPreview,
  type PositionSizingPreview,
  type PositionSizingUserInput,
  type SizingLimitReason,
} from "./positionSizing";

export type OpportunityEconomicSnapshot = {
  preview: PositionSizingPreview;
  viability: EconomicViabilityResult;
  simple: SimpleEconomicVerdict;
};

/** Nomi allineati al contratto desiderato (stessi numeri di `PositionSizingPreview`). */
export type RecommendedSizingFlat = {
  recommended_position_notional: number;
  recommended_size_units: number;
  estimated_loss_at_stop_eur: number;
  estimated_net_tp1_eur: number | null;
  estimated_net_tp2_eur: number | null;
  effective_risk_pct_of_account: number | null;
  account_allocation_pct: number;
  sizing_limited_by: SizingLimitReason;
};

export function flattenRecommendedSizing(
  preview: PositionSizingPreview,
  accountCapital: number,
): RecommendedSizingFlat | null {
  if (!preview.ok) return null;
  const effectiveRiskPct =
    accountCapital > 0 ? (preview.estimatedLossAtStopWithCosts / accountCapital) * 100 : null;
  return {
    recommended_position_notional: preview.notionalPositionValue,
    recommended_size_units: preview.positionSizeUnits,
    estimated_loss_at_stop_eur: preview.estimatedLossAtStopWithCosts,
    estimated_net_tp1_eur: preview.estimatedNetProfitAtTp1,
    estimated_net_tp2_eur: preview.estimatedNetProfitAtTp2,
    effective_risk_pct_of_account: effectiveRiskPct,
    account_allocation_pct: preview.accountCapitalPctAllocated,
    sizing_limited_by: preview.sizingLimitedBy,
  };
}

export function computeOpportunityEconomicSnapshot(
  plan: TradePlanV1 | null | undefined,
  input: PositionSizingUserInput,
): OpportunityEconomicSnapshot | null {
  if (!plan || plan.trade_direction === "none") return null;
  const preview = computePositionSizingPreview(input, plan);
  const viability = computeEconomicViability(preview, input);
  const simple = computeSimpleEconomicVerdict(preview, input, viability);
  return { preview, viability, simple };
}

export function computeRecommendedSizingFlat(
  plan: TradePlanV1 | null | undefined,
  input: PositionSizingUserInput,
): RecommendedSizingFlat | null {
  const snap = computeOpportunityEconomicSnapshot(plan, input);
  if (!snap?.preview.ok) return null;
  return flattenRecommendedSizing(snap.preview, input.accountCapital);
}

/** Filtro lista opportunità (layer economico sopra al ranking tecnico). */
export type EconomicListFilterMode = "all" | "good_only" | "good_or_marginal";

export function economicTierSortRank(tier: EconomicVerdictTier): number {
  if (tier === "economically_viable") return 0;
  if (tier === "economically_borderline") return 1;
  return 2;
}

export function rowMatchesEconomicFilter(
  snap: OpportunityEconomicSnapshot | null,
  mode: EconomicListFilterMode,
): boolean {
  if (mode === "all") return true;
  if (!snap || !snap.preview.ok) return false;
  const tier = snap.simple.verdictTier;
  if (mode === "good_only") return tier === "economically_viable";
  return tier !== "economically_not_viable";
}
