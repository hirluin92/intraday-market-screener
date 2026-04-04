/**
 * Valutazione convenienza economica del trade rispetto al capitale e ai costi (solo frontend).
 * Usa l'output di computePositionSizingPreview + input utente.
 */

import type { PositionSizingPreview, PositionSizingUserInput } from "./positionSizing";
import { ECONOMIC_VIABILITY_THRESHOLDS } from "./economicViabilityConfig";

export { ECONOMIC_VIABILITY_THRESHOLDS } from "./economicViabilityConfig";

export type EconomicViabilityStatus = "good" | "marginal" | "poor";

/** Codice stabile per filtri lista / API future (allineato a good | marginal | poor). */
export type EconomicVerdictTier =
  | "economically_viable"
  | "economically_borderline"
  | "economically_not_viable";

export function mapViabilityStatusToEconomicTier(status: EconomicViabilityStatus): EconomicVerdictTier {
  if (status === "good") return "economically_viable";
  if (status === "marginal") return "economically_borderline";
  return "economically_not_viable";
}

/** Giudizio sintetico per la card «Risposta diretta» (UI retail). */
export type SimpleEconomicVerdictLabel = "Conveniente" | "Borderline" | "Non conveniente";

export type SimpleEconomicVerdict = {
  /** Allineato a `EconomicViabilityStatus`. */
  verdictKey: EconomicViabilityStatus;
  verdictTier: EconomicVerdictTier;
  verdictLabel: SimpleEconomicVerdictLabel;
  /** Motivi in italiano semplice (include regole economiche + contesto operativo). */
  economicReason: string[];
};

const CAP_HINT =
  "Il limite «Max % conto per trade» blocca la size: alzare il rischio % non aumenta la puntata finché resti al tetto notional.";

const LEVERAGE_HINT =
  "La puntata è limitata dal tetto di leva (notional vs conto): alzare solo il rischio % non aumenta la size finché la leva resta vincolante.";

/**
 * Valutazione economica «semplice» per la UI principale: riusa `computeEconomicViability` e aggiunge
 * spiegazioni pratiche (cap notional, conto piccolo) senza duplicare le soglie.
 */
export function computeSimpleEconomicVerdict(
  preview: PositionSizingPreview,
  _user: PositionSizingUserInput,
  viability: EconomicViabilityResult,
): SimpleEconomicVerdict {
  const economicReason = [...viability.reasons];

  if (preview.positionSizingCappedByNotional && !economicReason.some((r) => r.includes("Max % conto"))) {
    economicReason.push(CAP_HINT);
  }

  if (preview.positionSizingCappedByLeverage && !economicReason.some((r) => r.toLowerCase().includes("leva"))) {
    economicReason.push(LEVERAGE_HINT);
  }

  const verdictLabel: SimpleEconomicVerdictLabel =
    viability.status === "good"
      ? "Conveniente"
      : viability.status === "marginal"
        ? "Borderline"
        : "Non conveniente";

  if (economicReason.length === 0) {
    economicReason.push(viability.summary);
  }

  return {
    verdictKey: viability.status,
    verdictTier: mapViabilityStatusToEconomicTier(viability.status),
    verdictLabel,
    economicReason,
  };
}

export type EconomicViabilityResult = {
  /** good = «Conviene», marginal = «Marginale», poor = «Non conviene». */
  status: EconomicViabilityStatus;
  /** true solo se status === «good» (conviene in senso stretto). */
  economicallyViable: boolean;
  /**
   * true se good o marginal (il trade ha ancora senso da valutare).
   * false solo per poor.
   */
  economicallyWorthConsidering: boolean;
  /** Etichetta breve UI. */
  label: "Conviene" | "Marginale" | "Non conviene";
  /** Frase principale (1 riga). */
  summary: string;
  /** Elenco motivi (poor prima, poi marginal). */
  reasons: string[];
  /** Minimi calcolati per trasparenza (EUR). */
  minNetProfitTp1Required: number;
  minNetProfitTp2Required: number;
};

function fmtEur(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Valuta se il trade ha senso economico per il conto indicato.
 * Non modifica il trade plan né le API backend.
 */
export function computeEconomicViability(
  preview: PositionSizingPreview,
  user: PositionSizingUserInput,
  cfg: typeof ECONOMIC_VIABILITY_THRESHOLDS = ECONOMIC_VIABILITY_THRESHOLDS,
): EconomicViabilityResult {
  const cap = Math.max(0, user.accountCapital);
  const minTp1 = Math.max(cfg.minNetProfitTp1FloorEur, cap * cfg.minNetProfitTp1PctOfAccount);
  const minTp2 = Math.max(cfg.minNetProfitTp2FloorEur, cap * cfg.minNetProfitTp2PctOfAccount);
  const poorLineTp1 = minTp1 * cfg.poorNetTp1VsMinRatio;

  const poor: string[] = [];
  const marginal: string[] = [];

  if (!preview.ok) {
    poor.push(
      "Preview non valida o vincoli non rispettati: non è possibile valutare la convenienza economica.",
    );
    return finalize("poor", poor, marginal, minTp1, minTp2);
  }

  const net1 = preview.estimatedNetProfitAtTp1;
  const net2 = preview.estimatedNetProfitAtTp2;
  const gross1 = preview.estimatedGrossProfitAtTp1;
  const costs = preview.estimatedTotalCosts;

  if (user.maxLeverage != null && user.maxLeverage > 0 && preview.impliedLeverage > user.maxLeverage + 1e-6) {
    poor.push(
      "Conviene solo con leva superiore a quella consentita: il trade non è compatibile con il limite impostato.",
    );
  }

  if (net1 == null) {
    marginal.push(
      "TP1 non disponibile o non favorevole: non si può stimare un utile netto sul primo target.",
    );
  } else {
    if (net1 < 0) {
      poor.push("Utile netto stimato a TP1 negativo dopo costi.");
    } else if (net1 < poorLineTp1) {
      poor.push(
        `TP1 netto troppo basso rispetto al conto (atteso almeno ~${fmtEur(poorLineTp1)} € per questo capitale; minimo pieno ${fmtEur(minTp1)} €).`,
      );
    } else if (net1 < minTp1) {
      marginal.push(
        `TP1 netto modesto (sotto il minimo indicativo ${fmtEur(minTp1)} € per ${fmtEur(cap)} € di conto).`,
      );
    }
  }

  if (gross1 != null && gross1 > 0 && costs > 0) {
    const ratio = costs / gross1;
    if (ratio >= cfg.maxCostToGrossTp1RatioPoor) {
      poor.push("Fee e slippage assorbono troppo del profitto lordo atteso a TP1.");
    } else if (ratio >= cfg.maxCostToGrossTp1RatioMarginal) {
      marginal.push("Costi stimati incidono in modo significativo sul profitto lordo a TP1.");
    }
  }

  if (preview.rrTp1Money != null && preview.estimatedLossAtStopWithCosts > 0) {
    if (preview.rrTp1Money < cfg.poorNetRiskReward) {
      poor.push(
        `Rapporto rischio/rendimento netto a TP1 debole (${preview.rrTp1Money.toFixed(2)}:1).`,
      );
    } else if (preview.rrTp1Money < cfg.marginalNetRiskReward) {
      marginal.push(`R:R netto a TP1 nella fascia bassa (${preview.rrTp1Money.toFixed(2)}:1).`);
    }
  }

  if (
    preview.accountCapitalPctAllocated > cfg.highAllocationPct &&
    net1 != null &&
    net1 < cfg.tightNetTp1Eur &&
    net1 >= 0
  ) {
    marginal.push(
      "Il trade richiede molto capitale impegnato per un utile netto atteso al TP1 ancora contenuto.",
    );
  }

  if (
    net1 != null &&
    net2 != null &&
    net1 < minTp1 &&
    net2 >= minTp2 &&
    poor.length === 0
  ) {
    marginal.push(
      "Il setup è tecnicamente valido ma l’utile netto diventa più sensato solo verso TP2: valuta il rischio fino al secondo target.",
    );
  }

  if (poor.length === 0 && marginal.length === 0) {
    // Messaggio positivo sintetico
    /* empty */
  }

  return finalize(
    poor.length > 0 ? "poor" : marginal.length > 0 ? "marginal" : "good",
    poor,
    marginal,
    minTp1,
    minTp2,
  );
}

function finalize(
  status: EconomicViabilityStatus,
  poor: string[],
  marginal: string[],
  minTp1: number,
  minTp2: number,
): EconomicViabilityResult {
  const label: EconomicViabilityResult["label"] =
    status === "good" ? "Conviene" : status === "marginal" ? "Marginale" : "Non conviene";

  const economicallyWorthConsidering = status !== "poor";
  const economicallyViable = status === "good";

  const reasons = [...poor, ...marginal];

  let summary: string;
  if (status === "good") {
    summary =
      "Per il capitale e i costi impostati, l’utile netto atteso e il rapporto rischio/rendito risultano ragionevoli.";
  } else if (status === "marginal") {
    summary =
      "Il setup può essere tecnicamente valido ma è economicamente poco efficiente per questo conto: valuta se ha senso operare.";
  } else {
    summary =
      "Per questo capitale l’utile netto atteso è troppo basso o i costi/rischio rendono il trade poco sensato.";
  }

  return {
    status,
    economicallyViable,
    economicallyWorthConsidering,
    label,
    summary,
    reasons: reasons.length > 0 ? reasons : [],
    minNetProfitTp1Required: minTp1,
    minNetProfitTp2Required: minTp2,
  };
}
