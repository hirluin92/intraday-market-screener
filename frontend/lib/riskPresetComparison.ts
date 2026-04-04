/**
 * Confronto automatico tra più livelli di rischio (% conto) per position sizing.
 * Riutilizza computePositionSizingPreview e computeEconomicViability senza duplicare formule.
 */

import type { TradePlanV1 } from "./api";
import { computeEconomicViability, type EconomicViabilityResult } from "./economicViability";
import {
  computePositionSizingPreview,
  type PositionSizingPreview,
  type PositionSizingUserInput,
} from "./positionSizing";

/** Preset predefiniti richiesti (ordine crescente = dal più prudente). */
export const DEFAULT_RISK_PRESET_PERCENTS: readonly number[] = [1, 2, 3, 4, 5];

export type RiskPresetRowStatus = "recommended" | "acceptable" | "poor";

export type RiskPresetComparisonRow = {
  riskPercent: number;
  preview: PositionSizingPreview;
  viability: EconomicViabilityResult;
  rowStatus: RiskPresetRowStatus;
};

export type RiskPresetComparisonResult = {
  rows: RiskPresetComparisonRow[];
  /**
   * Preset % più basso tra quelli economicamente validi (non «Non conviene»).
   * Conservativo: prima sicurezza (rischio minimo), poi convenienza già nella viability.
   */
  recommendedRiskPercent: number | null;
  recommendationMessage: string;
  /**
   * Tutti i preset sono limitati dal notional massimo (% conto): size e PnL coincidono tra le righe
   * mentre la colonna «rischio target» può ancora crescere (obiettivo % non raggiunto).
   */
  notionalCapBindsAllPresets: boolean;
};

function buildUserForPreset(
  base: PositionSizingUserInput,
  riskPercent: number,
): PositionSizingUserInput {
  return {
    ...base,
    riskMode: "percent",
    riskPercent,
  };
}

/**
 * Calcola una riga per ogni preset di rischio, con classificazione riga e preset consigliato.
 *
 * Regola consiglio: il **più basso** tra i preset con convenienza ≠ poor.
 * Se nessuno passa → nessun consiglio (messaggio esplicito).
 */
export function compareRiskPresets(
  baseUser: PositionSizingUserInput,
  plan: TradePlanV1,
  riskPercents: readonly number[] = DEFAULT_RISK_PRESET_PERCENTS,
): RiskPresetComparisonResult {
  const sortedPresets = [...riskPercents].sort((a, b) => a - b);

  const interim: {
    riskPercent: number;
    preview: PositionSizingPreview;
    viability: EconomicViabilityResult;
  }[] = [];

  for (const rp of sortedPresets) {
    const user = buildUserForPreset(baseUser, rp);
    const preview = computePositionSizingPreview(user, plan);
    const viability = computeEconomicViability(preview, user);
    interim.push({ riskPercent: rp, preview, viability });
  }

  /** Valido = non «poor» (good o marginal: supera il minimo di convenienza del modulo esistente). */
  const valid = interim.filter((r) => r.viability.status !== "poor");
  const recommendedRiskPercent =
    valid.length > 0 ? valid.reduce((min, r) => (r.riskPercent < min ? r.riskPercent : min), valid[0].riskPercent) : null;

  let recommendationMessage: string;
  if (recommendedRiskPercent == null) {
    recommendationMessage =
      "Nessun sizing consigliato per questo capitale con i parametri attuali: a tutti i preset provati (1%–5% del conto) la convenienza economica risulta «Non conviene». Prova ad alzare il capitale, ridurre fee/slippage, o valutare un altro setup.";
  } else {
    recommendationMessage =
      "È il preset più prudente tra quelli che superano le soglie minime di convenienza economica (esito diverso da «Non conviene»).";
  }

  const rows: RiskPresetComparisonRow[] = interim.map((r) => {
    let rowStatus: RiskPresetRowStatus;
    if (r.viability.status === "poor") {
      rowStatus = "poor";
    } else if (recommendedRiskPercent != null && r.riskPercent === recommendedRiskPercent) {
      rowStatus = "recommended";
    } else {
      rowStatus = "acceptable";
    }
    return { ...r, rowStatus };
  });

  const notionalCapBindsAllPresets =
    rows.length > 0 && rows.every((r) => r.preview.positionSizingCappedByNotional);

  return {
    rows,
    recommendedRiskPercent,
    recommendationMessage,
    notionalCapBindsAllPresets,
  };
}
