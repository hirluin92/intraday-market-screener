/**
 * Soglie convenienza economica (trade worthiness) — tuning centralizzato.
 * Modificare qui senza toccare la logica in economicViability.ts.
 *
 * NOTA: con il sizing a leva, il notional è amplificato correttamente.
 * I conti piccoli con leva producono utili netti assoluti più bassi in €,
 * ma il rapporto rischio/rendimento (R:R) resta significativo.
 */

export const ECONOMIC_VIABILITY_THRESHOLDS = {
  /**
   * Piano minimo utile netto TP1 in EUR assoluti.
   * Abbassato: con leva 5× su 250 € il notional può essere 1250 €,
   * ma la puntata rischio rimane legata allo stop → TP1 netto ragionevole anche sotto 1 €.
   */
  minNetProfitTp1FloorEur: 0.5,
  /** Piano minimo utile netto TP2 (EUR). */
  minNetProfitTp2FloorEur: 0.8,

  /**
   * Min TP1 netto = max(floor, accountCapital × questo).
   * Scala col conto ma con floor basso per non bocciare tutto su conti piccoli.
   */
  minNetProfitTp1PctOfAccount: 0.004,
  minNetProfitTp2PctOfAccount: 0.006,

  /**
   * Sotto questo rapporto (utile netto TP1 / minimo) → "Non conviene".
   */
  poorNetTp1VsMinRatio: 0.3,

  /** Tra poorNetTp1VsMinRatio e 1.0 del minimo → "Marginale". */
  marginalNetTp1VsMinRatio: 0.75,

  /** Se costi stimati / profitto lordo TP1 > questo → poor. */
  maxCostToGrossTp1RatioPoor: 0.55,
  /** Tra questo e poor → marginal. */
  maxCostToGrossTp1RatioMarginal: 0.3,

  /**
   * R:R netto (TP1) sotto questo → poor.
   */
  poorNetRiskReward: 0.3,
  /** R:R netto sotto → marginal (se non già poor). */
  marginalNetRiskReward: 0.65,

  /** % margine allocato oltre la quale, con TP1 netto sotto soglia stretta → marginal. */
  highAllocationPct: 60,
  /** Soglia "stretta" in EUR per TP1 netto (oltre highAllocation). */
  tightNetTp1Eur: 2,

  /**
   * Sotto questa cifra il conto è considerato «piccolo».
   */
  smallAccountCapitalEur: 500,
} as const;

export type EconomicViabilityThresholds = typeof ECONOMIC_VIABILITY_THRESHOLDS;
