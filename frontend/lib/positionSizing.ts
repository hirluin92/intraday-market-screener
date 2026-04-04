/**
 * Position sizing e preview rischio/premio da TradePlanV1 (solo frontend, puro e testabile).
 *
 * feeRoundTripPercent: commissioni stimate round-trip sul notional (ingresso+uscita, un solo numero %).
 * slippagePercent: buffer prudenziale sul notional (slippage medio stimato sul trade).
 */

import type { TradePlanV1 } from "./api";

export type PositionSizingRiskMode = "percent" | "fixed";

/** Input utente (persistibile in localStorage). */
export type PositionSizingUserInput = {
  accountCapital: number;
  riskMode: PositionSizingRiskMode;
  /** Se riskMode === "percent" (es. 1 = 1%). */
  riskPercent: number;
  /** Se riskMode === "fixed" (valuta conto). */
  riskFixed: number;
  /** Fee round-trip sul notional, % (es. 0.1 = 0.1%). */
  feeRoundTripPercent: number;
  /** Slippage stimato sul notional, % (prudenziale). */
  slippagePercent: number;
  /** Leva massima ammessa (es. 5); null = non controllare. */
  maxLeverage: number | null;
  /** Massimo % del conto utilizzabile come notional per questo trade. */
  maxCapitalPercentPerTrade: number;
};

export const DEFAULT_POSITION_SIZING_INPUT: PositionSizingUserInput = {
  accountCapital: 10_000,
  riskMode: "percent",
  riskPercent: 1,
  riskFixed: 100,
  feeRoundTripPercent: 0.08,
  slippagePercent: 0.05,
  maxLeverage: 5,
  maxCapitalPercentPerTrade: 100,
};

/** Quale vincolo determina la size effettiva (il minimo tra i tetti). */
export type SizingLimitReason =
  | "risk_budget"
  | "max_account_allocation"
  | "leverage_cap"
  | "min_trade_size"
  | "unknown";

export type PositionSizingPreview = {
  ok: boolean;
  /** Rischio monetario massimo richiesto dalle impostazioni (prima del cap notional). */
  maxRiskMoney: number;
  /**
   * True se la size è stata ridotta dal massimo notional consentito (% conto allocabile).
   * In quel caso aumentare il «rischio %» non aumenta size/PnL finché il cap resta attivo:
   * la colonna maxRiskMoney resta un obiettivo teorico, mentre perdita a stop e utili riflettono la size effettiva.
   */
  positionSizingCappedByNotional: boolean;
  /** True se la size è stata ridotta dal limite di leva massima (notional/conto). */
  positionSizingCappedByLeverage: boolean;
  /** Vincolo attivo che ha fissato la size (dopo min tra rischio, allocazione, leva). */
  sizingLimitedBy: SizingLimitReason;
  stopDistanceAbs: number;
  stopDistancePct: number;
  positionSizeUnits: number;
  notionalPositionValue: number;
  estimatedLossAtStop: number;
  estimatedGrossProfitAtTp1: number | null;
  estimatedGrossProfitAtTp2: number | null;
  /** Perdita lorda a stop + costi stimati (fee+slippage sul notional). */
  estimatedLossAtStopWithCosts: number;
  /** Utile netto stimato a TP1/TP2 dopo costi. */
  estimatedNetProfitAtTp1: number | null;
  estimatedNetProfitAtTp2: number | null;
  rrTp1Money: number | null;
  rrTp2Money: number | null;
  /** % del conto coperta dal notional. */
  accountCapitalPctAllocated: number;
  /** notional / accountCapital (rapporto esposizione vs equity). */
  impliedLeverage: number;
  /** Costi totali stimati (fee+slippage) sul notional. */
  estimatedTotalCosts: number;
  warnings: string[];
};

function resolveSizingLimitedBy(sRisk: number, sCap: number, sLev: number): SizingLimitReason {
  if (!Number.isFinite(sRisk) || sRisk <= 0) return "unknown";
  const size = Math.min(sRisk, sCap, sLev);
  if (size <= 0 || !Number.isFinite(size)) return "unknown";
  const tol = 1e-9 * Math.max(size, 1);
  const at = (a: number) => Math.abs(size - a) <= tol;
  // In caso di pareggio: allocazione e leva hanno priorità esplicativa (vincoli operativi).
  if (at(sCap)) return "max_account_allocation";
  if (at(sLev)) return "leverage_cap";
  if (at(sRisk)) return "risk_budget";
  return "unknown";
}

function parsePrice(s: string | null | undefined): number | null {
  if (s == null || String(s).trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function grossPnlAtPrice(
  direction: "long" | "short",
  entry: number,
  exit: number,
  size: number,
): number {
  if (direction === "long") return (exit - entry) * size;
  return (entry - exit) * size;
}

/**
 * Calcola preview position sizing. Non modifica lo stato; output serializzabile.
 */
export function computePositionSizingPreview(
  user: PositionSizingUserInput,
  plan: TradePlanV1,
): PositionSizingPreview {
  const warnings: string[] = [];
  const dir = plan.trade_direction;
  const entry = parsePrice(plan.entry_price);
  const stop = parsePrice(plan.stop_loss);
  const tp1 = parsePrice(plan.take_profit_1);
  const tp2 = parsePrice(plan.take_profit_2);

  if (dir === "none" || !entry || !stop) {
    warnings.push("Direzione assente o prezzi ingresso/stop non validi: preview non applicabile.");
    return emptyPreview(warnings);
  }

  let stopDistanceAbs = Math.abs(entry - stop);
  if (stopDistanceAbs <= 0) {
    warnings.push("Distanza stop nulla: risk per unità non definito.");
    return emptyPreview(warnings);
  }

  if (dir === "long" && stop >= entry) {
    warnings.push("Long: lo stop deve essere sotto l’ingresso per definire il rischio.");
    return emptyPreview(warnings);
  }
  if (dir === "short" && stop <= entry) {
    warnings.push("Short: lo stop deve essere sopra l’ingresso per definire il rischio.");
    return emptyPreview(warnings);
  }

  const stopDistancePct = (stopDistanceAbs / entry) * 100;

  const cap = Math.max(0, user.accountCapital) * (user.maxCapitalPercentPerTrade / 100);

  let maxRiskMoney =
    user.riskMode === "percent"
      ? Math.max(0, user.accountCapital) * (user.riskPercent / 100)
      : Math.max(0, user.riskFixed);

  if (user.riskMode === "fixed" && user.riskFixed > user.accountCapital && user.accountCapital > 0) {
    warnings.push("Rischio fisso supera il capitale conto: riduci il valore o il capitale.");
  }
  if (user.accountCapital <= 0) {
    warnings.push("Capitale conto non positivo.");
  }

  const riskPerUnit = stopDistanceAbs;
  if (riskPerUnit <= 0) {
    warnings.push("Risk per unità ≤ 0.");
    return emptyPreview(warnings);
  }

  const sizeFromRisk = maxRiskMoney / riskPerUnit;
  const maxSizeFromCap = entry > 0 ? cap / entry : 0;
  const maxSizeFromLeverage =
    user.maxLeverage != null &&
    user.maxLeverage > 0 &&
    user.accountCapital > 0 &&
    entry > 0
      ? (user.accountCapital * user.maxLeverage) / entry
      : Number.POSITIVE_INFINITY;

  let positionSizeUnits = Math.min(sizeFromRisk, maxSizeFromCap, maxSizeFromLeverage);
  const sizingLimitedBy = resolveSizingLimitedBy(sizeFromRisk, maxSizeFromCap, maxSizeFromLeverage);

  const positionSizingCappedByNotional = sizingLimitedBy === "max_account_allocation";
  if (positionSizingCappedByNotional) {
    warnings.push("Size limitata dal massimo % del conto allocabile per trade.");
  }

  const positionSizingCappedByLeverage = sizingLimitedBy === "leverage_cap";
  if (positionSizingCappedByLeverage) {
    warnings.push(
      `Size limitata dalla leva massima impostata (${user.maxLeverage}× notional rispetto al conto).`,
    );
  }

  if (!Number.isFinite(positionSizeUnits) || positionSizeUnits <= 0) {
    warnings.push("Size non valida o zero: controlla rischio, stop e capitale allocabile.");
    positionSizeUnits = 0;
  }

  const notionalPositionValue = positionSizeUnits * entry;
  const feeRt = Math.max(0, user.feeRoundTripPercent) / 100;
  const slipRt = Math.max(0, user.slippagePercent) / 100;
  const estimatedTotalCosts = notionalPositionValue * (feeRt + slipRt);

  const grossLossAtStop =
    positionSizeUnits > 0
      ? Math.abs(grossPnlAtPrice(dir, entry, stop, positionSizeUnits))
      : 0;
  const estimatedLossAtStopWithCosts = grossLossAtStop + estimatedTotalCosts;

  let estimatedGrossProfitAtTp1: number | null = null;
  let estimatedGrossProfitAtTp2: number | null = null;
  if (positionSizeUnits > 0 && tp1 != null) {
    const g = grossPnlAtPrice(dir, entry, tp1, positionSizeUnits);
    if (g > 0) estimatedGrossProfitAtTp1 = g;
    else warnings.push("TP1 non favorevole rispetto all’ingresso per questa direzione.");
  }
  if (positionSizeUnits > 0 && tp2 != null) {
    const g = grossPnlAtPrice(dir, entry, tp2, positionSizeUnits);
    if (g > 0) estimatedGrossProfitAtTp2 = g;
  }

  const estimatedNetProfitAtTp1 =
    estimatedGrossProfitAtTp1 != null
      ? estimatedGrossProfitAtTp1 - estimatedTotalCosts
      : null;
  const estimatedNetProfitAtTp2 =
    estimatedGrossProfitAtTp2 != null
      ? estimatedGrossProfitAtTp2 - estimatedTotalCosts
      : null;

  const rrTp1Money =
    estimatedLossAtStopWithCosts > 0 && estimatedNetProfitAtTp1 != null
      ? estimatedNetProfitAtTp1 / estimatedLossAtStopWithCosts
      : null;
  const rrTp2Money =
    estimatedLossAtStopWithCosts > 0 && estimatedNetProfitAtTp2 != null
      ? estimatedNetProfitAtTp2 / estimatedLossAtStopWithCosts
      : null;

  const accountCapitalPctAllocated =
    user.accountCapital > 0 ? (notionalPositionValue / user.accountCapital) * 100 : 0;
  const impliedLeverage =
    user.accountCapital > 0 ? notionalPositionValue / user.accountCapital : 0;

  if (notionalPositionValue > cap + 1e-6) {
    warnings.push("Notional supera il massimo allocabile per trade (cap % conto).");
  }
  if (positionSizeUnits <= 0 || !Number.isFinite(positionSizeUnits)) {
    warnings.push("Trade non eseguibile con i parametri attuali.");
  }

  const leverageOk =
    user.maxLeverage == null || user.maxLeverage <= 0 || impliedLeverage <= user.maxLeverage + 1e-6;
  const ok =
    positionSizeUnits > 0 &&
    user.accountCapital > 0 &&
    leverageOk &&
    !warnings.some((w) => w.includes("Trade non eseguibile"));

  return {
    ok,
    maxRiskMoney,
    positionSizingCappedByNotional,
    positionSizingCappedByLeverage,
    sizingLimitedBy: positionSizeUnits > 0 ? sizingLimitedBy : "unknown",
    stopDistanceAbs,
    stopDistancePct,
    positionSizeUnits,
    notionalPositionValue,
    estimatedLossAtStop: grossLossAtStop,
    estimatedGrossProfitAtTp1,
    estimatedGrossProfitAtTp2,
    estimatedLossAtStopWithCosts,
    estimatedNetProfitAtTp1,
    estimatedNetProfitAtTp2,
    rrTp1Money,
    rrTp2Money,
    accountCapitalPctAllocated,
    impliedLeverage,
    estimatedTotalCosts,
    warnings,
  };
}

function emptyPreview(warnings: string[]): PositionSizingPreview {
  return {
    ok: false,
    maxRiskMoney: 0,
    positionSizingCappedByNotional: false,
    positionSizingCappedByLeverage: false,
    sizingLimitedBy: "unknown",
    stopDistanceAbs: 0,
    stopDistancePct: 0,
    positionSizeUnits: 0,
    notionalPositionValue: 0,
    estimatedLossAtStop: 0,
    estimatedGrossProfitAtTp1: null,
    estimatedGrossProfitAtTp2: null,
    estimatedLossAtStopWithCosts: 0,
    estimatedNetProfitAtTp1: null,
    estimatedNetProfitAtTp2: null,
    rrTp1Money: null,
    rrTp2Money: null,
    accountCapitalPctAllocated: 0,
    impliedLeverage: 0,
    estimatedTotalCosts: 0,
    warnings,
  };
}

const STORAGE_KEY = "positionSizingUserInputV1";

export function loadPositionSizingInput(): PositionSizingUserInput {
  if (typeof window === "undefined") return DEFAULT_POSITION_SIZING_INPUT;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_POSITION_SIZING_INPUT;
    const p = JSON.parse(raw) as Partial<PositionSizingUserInput>;
    return {
      ...DEFAULT_POSITION_SIZING_INPUT,
      ...p,
      maxLeverage:
        p.maxLeverage === undefined ? DEFAULT_POSITION_SIZING_INPUT.maxLeverage : p.maxLeverage,
    };
  } catch {
    return DEFAULT_POSITION_SIZING_INPUT;
  }
}

export function savePositionSizingInput(input: PositionSizingUserInput): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(input));
  } catch {
    /* ignore */
  }
}

/** Una riga di spiegazione per la card «Risposta diretta» (vincolo attivo sulla size). */
export function sizingLimitShortLineItalian(reason: SizingLimitReason): string | null {
  switch (reason) {
    case "risk_budget":
      return "Puntata determinata dall’obiettivo di rischio e dalla distanza dello stop.";
    case "max_account_allocation":
      return "Puntata limitata dal «Max % conto per trade» (non è obbligatorio usare tutto il conto).";
    case "leverage_cap":
      return "Puntata limitata dal tetto di leva impostato (notional rispetto al capitale).";
    case "min_trade_size":
      return "Possibile vincolo minimo di lotto non modellato in questa anteprima.";
    default:
      return null;
  }
}
