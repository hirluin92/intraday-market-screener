/**
 * Soglie convenienza economica (trade worthiness) — tuning centralizzato.
 * Modificare qui senza toccare la logica in economicViability.ts.
 *
 * Pensate per conti piccoli (es. 250 €): min assoluti + % del conto (il più alto vince).
 */

export const ECONOMIC_VIABILITY_THRESHOLDS = {
  /** Piano minimo utile netto TP1 (EUR), prima della scala sul conto. */
  minNetProfitTp1FloorEur: 1.5,
  /** Piano minimo utile netto TP2 (EUR). */
  minNetProfitTp2FloorEur: 2.0,
  /**
   * Min TP1 netto = max(minNetProfitTp1FloorEur, accountCapital * questo).
   * Esempio: 250 € → 2 € minimo; 10k → 80 €.
   */
  minNetProfitTp1PctOfAccount: 0.008,
  minNetProfitTp2PctOfAccount: 0.012,

  /**
   * Sotto questo rapporto tra utile netto TP1 e minimo richiesto → "Non conviene".
   * Esempio: min 2 €, factor 0.45 → sotto 0.90 € è poor.
   */
  poorNetTp1VsMinRatio: 0.45,

  /**
   * Sotto il minimo assoluto ma sopra la soglia poor → "Marginale".
   * (Tra poorNetTp1VsMinRatio*min e min.)
   */
  marginalNetTp1VsMinRatio: 0.85,

  /** Se costi stimati / profitto lordo TP1 > questo → poor. */
  maxCostToGrossTp1RatioPoor: 0.42,
  /** Tra questo e poor → marginal. */
  maxCostToGrossTp1RatioMarginal: 0.22,

  /** R:R netto (TP1) sotto → poor. */
  poorNetRiskReward: 0.48,
  /** R:R netto sotto → marginal (se non già poor). */
  marginalNetRiskReward: 0.85,

  /** % conto allocata oltre la quale, con TP1 netto sotto soglia stretta → marginal. */
  highAllocationPct: 28,
  /** Soglia "stretta" in EUR per TP1 netto (oltre highAllocation). */
  tightNetTp1Eur: 4,

  /**
   * Sotto questa cifra il conto è considerato «piccolo» per messaggi UX dedicati
   * (card «Risposta diretta», spiegazioni in linguaggio semplice).
   */
  smallAccountCapitalEur: 500,
} as const;

export type EconomicViabilityThresholds = typeof ECONOMIC_VIABILITY_THRESHOLDS;
