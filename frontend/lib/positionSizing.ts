/**
 * Position sizing — rischio ancorato al conto, leva riduce il margine richiesto.
 *
 * 1. maxRiskMoney = capitale × risk% (o fisso)
 * 2. size = maxRiskMoney / stopDistanceAbs
 * 3. notional = size × entry
 * 4. marginRequired = notional / leva
 * 5. Tetto: maxNotional = (capitale × maxMargin%) × leva — se notional dal rischio lo supera, si riduce la size
 */

import type { TradePlanV1 } from "./api";

export type PositionSizingRiskMode = "percent" | "fixed";

export type PositionSizingUserInput = {
  accountCapital: number;
  riskMode: PositionSizingRiskMode;
  riskPercent: number;
  riskFixed: number;
  feeRoundTripPercent: number;
  slippagePercent: number;
  maxLeverage: number | null;
  /** Max % del conto utilizzabile come margine (garanzia) per questo trade. */
  maxMarginPercent: number;
};

export const DEFAULT_POSITION_SIZING_INPUT: PositionSizingUserInput = {
  accountCapital: 1_000,
  riskMode: "percent",
  riskPercent: 1,
  riskFixed: 10,
  feeRoundTripPercent: 0.10,
  slippagePercent: 0.05,
  maxLeverage: 1,
  maxMarginPercent: 50,
};

export type SizingLimitReason =
  | "risk_budget"
  | "margin_cap"
  | "no_leverage"
  | "unknown";

export type PositionSizingPreview = {
  ok: boolean;
  maxRiskMoney: number;
  effectiveLeverage: number;
  positionSizeUnits: number;
  notionalPositionValue: number;
  marginUsed: number;
  marginPctOfAccount: number;
  sizingLimitedBy: SizingLimitReason;
  cappedByMargin: boolean;
  actualRiskAtStop: number;
  actualRiskPctOfAccount: number;
  stopDistanceAbs: number;
  stopDistancePct: number;
  estimatedTotalCosts: number;
  estimatedLossAtStopWithCosts: number;
  estimatedGrossProfitAtTp1: number | null;
  estimatedGrossProfitAtTp2: number | null;
  estimatedNetProfitAtTp1: number | null;
  estimatedNetProfitAtTp2: number | null;
  rrNetTp1: number | null;
  rrNetTp2: number | null;
  recommendedRiskPct: number;
  recommendedRiskRationale: string;
  warnings: string[];
};

function parsePrice(s: string | null | undefined): number | null {
  if (s == null || String(s).trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function grossPnl(dir: "long" | "short", entry: number, exit: number, size: number): number {
  return dir === "long" ? (exit - entry) * size : (entry - exit) * size;
}

function empty(warnings: string[]): PositionSizingPreview {
  return {
    ok: false,
    maxRiskMoney: 0,
    effectiveLeverage: 1,
    positionSizeUnits: 0,
    notionalPositionValue: 0,
    marginUsed: 0,
    marginPctOfAccount: 0,
    sizingLimitedBy: "unknown",
    cappedByMargin: false,
    actualRiskAtStop: 0,
    actualRiskPctOfAccount: 0,
    stopDistanceAbs: 0,
    stopDistancePct: 0,
    estimatedTotalCosts: 0,
    estimatedLossAtStopWithCosts: 0,
    estimatedGrossProfitAtTp1: null,
    estimatedGrossProfitAtTp2: null,
    estimatedNetProfitAtTp1: null,
    estimatedNetProfitAtTp2: null,
    rrNetTp1: null,
    rrNetTp2: null,
    recommendedRiskPct: 1,
    recommendedRiskRationale: "",
    warnings,
  };
}

export function computePositionSizingPreview(
  user: PositionSizingUserInput,
  plan: TradePlanV1,
  opportunityScore?: number,
  variantStatus?: string | null,
): PositionSizingPreview {
  const warnings: string[] = [];
  const dir = plan.trade_direction;
  const entry = parsePrice(plan.entry_price);
  const stop = parsePrice(plan.stop_loss);
  const tp1 = parsePrice(plan.take_profit_1);
  const tp2 = parsePrice(plan.take_profit_2);

  if (dir === "none" || !entry || !stop) {
    return empty(["Direzione assente o prezzi non validi."]);
  }

  const stopDistanceAbs = Math.abs(entry - stop);
  if (stopDistanceAbs <= 0) return empty(["Distanza stop nulla."]);
  if (dir === "long" && stop >= entry) return empty(["Long: stop deve essere sotto l'entry."]);
  if (dir === "short" && stop <= entry) return empty(["Short: stop deve essere sopra l'entry."]);

  const stopDistancePct = (stopDistanceAbs / entry) * 100;

  const capital = Math.max(0, user.accountCapital);
  const maxRiskMoney =
    user.riskMode === "percent"
      ? capital * (Math.max(0, user.riskPercent) / 100)
      : Math.max(0, user.riskFixed);

  if (capital <= 0) warnings.push("Capitale conto non positivo.");

  const effectiveLeverage = Math.max(1, user.maxLeverage ?? 1);

  const sizeFromRisk = maxRiskMoney / stopDistanceAbs;
  const notionalFromRisk = sizeFromRisk * entry;

  const maxMargin = capital * (Math.max(0, Math.min(100, user.maxMarginPercent)) / 100);
  const maxNotionalFromMarginCap = maxMargin * effectiveLeverage;
  const maxSizeFromMarginCap = entry > 0 ? maxNotionalFromMarginCap / entry : 0;

  const cappedByMargin = notionalFromRisk > maxNotionalFromMarginCap + 1e-6;
  const positionSizeUnits = cappedByMargin ? maxSizeFromMarginCap : sizeFromRisk;
  const notionalPositionValue = positionSizeUnits * entry;
  const marginUsed = notionalPositionValue / effectiveLeverage;
  const marginPctOfAccount = capital > 0 ? (marginUsed / capital) * 100 : 0;

  let sizingLimitedBy: SizingLimitReason;
  if (cappedByMargin) {
    sizingLimitedBy = effectiveLeverage <= 1 ? "no_leverage" : "margin_cap";
  } else {
    sizingLimitedBy = "risk_budget";
  }

  if (cappedByMargin) {
    warnings.push(
      `Size ridotta: il margine richiesto supererebbe il ${user.maxMarginPercent}% del conto. ` +
        `Abbassa il rischio % o aumenta «Max margine % conto» per usare la size completa.`,
    );
  }

  const actualRiskAtStop = positionSizeUnits * stopDistanceAbs;
  const actualRiskPctOfAccount = capital > 0 ? (actualRiskAtStop / capital) * 100 : 0;

  const feeRt = Math.max(0, user.feeRoundTripPercent) / 100;
  const slipRt = Math.max(0, user.slippagePercent) / 100;
  const estimatedTotalCosts = notionalPositionValue * (feeRt + slipRt);
  const estimatedLossAtStopWithCosts = actualRiskAtStop + estimatedTotalCosts;

  let estimatedGrossProfitAtTp1: number | null = null;
  let estimatedGrossProfitAtTp2: number | null = null;

  if (tp1 != null) {
    const g = grossPnl(dir, entry, tp1, positionSizeUnits);
    if (g > 0) estimatedGrossProfitAtTp1 = g;
    else warnings.push("TP1 non favorevole per questa direzione.");
  }
  if (tp2 != null) {
    const g = grossPnl(dir, entry, tp2, positionSizeUnits);
    if (g > 0) estimatedGrossProfitAtTp2 = g;
  }

  const estimatedNetProfitAtTp1 =
    estimatedGrossProfitAtTp1 != null ? estimatedGrossProfitAtTp1 - estimatedTotalCosts : null;
  const estimatedNetProfitAtTp2 =
    estimatedGrossProfitAtTp2 != null ? estimatedGrossProfitAtTp2 - estimatedTotalCosts : null;

  const rrNetTp1 =
    estimatedLossAtStopWithCosts > 0 && estimatedNetProfitAtTp1 != null
      ? estimatedNetProfitAtTp1 / estimatedLossAtStopWithCosts
      : null;
  const rrNetTp2 =
    estimatedLossAtStopWithCosts > 0 && estimatedNetProfitAtTp2 != null
      ? estimatedNetProfitAtTp2 / estimatedLossAtStopWithCosts
      : null;

  const { pct: recommendedRiskPct, rationale: recommendedRiskRationale } = computeRecommendedRiskPct({
    opportunityScore,
    variantStatus,
    rrNetTp1,
    cappedByMargin,
    stopDistancePct,
    currentRiskPct: user.riskMode === "percent" ? user.riskPercent : null,
  });

  const ok = positionSizeUnits > 0 && capital > 0;

  return {
    ok,
    maxRiskMoney,
    effectiveLeverage,
    positionSizeUnits,
    notionalPositionValue,
    marginUsed,
    marginPctOfAccount,
    sizingLimitedBy,
    cappedByMargin,
    actualRiskAtStop,
    actualRiskPctOfAccount,
    stopDistanceAbs,
    stopDistancePct,
    estimatedTotalCosts,
    estimatedLossAtStopWithCosts,
    estimatedGrossProfitAtTp1,
    estimatedGrossProfitAtTp2,
    estimatedNetProfitAtTp1,
    estimatedNetProfitAtTp2,
    rrNetTp1,
    rrNetTp2,
    recommendedRiskPct,
    recommendedRiskRationale,
    warnings,
  };
}

type RiskRecommendInput = {
  opportunityScore?: number;
  variantStatus?: string | null;
  rrNetTp1: number | null;
  cappedByMargin: boolean;
  stopDistancePct: number;
  currentRiskPct: number | null;
};

function computeRecommendedRiskPct(inp: RiskRecommendInput): { pct: number; rationale: string } {
  const { opportunityScore, variantStatus, rrNetTp1, cappedByMargin, stopDistancePct } = inp;

  let basePct = 1.0;
  const reasons: string[] = [];

  if (variantStatus === "promoted") {
    basePct = 1.5;
    reasons.push("variante promossa dal backtest");
  } else if (variantStatus === "watchlist") {
    basePct = 1.0;
    reasons.push("variante in watchlist (affidabilità media)");
  } else {
    basePct = 0.5;
    reasons.push("nessuna variante validata (fallback)");
  }

  if (opportunityScore != null) {
    if (opportunityScore >= 70) {
      basePct = Math.min(basePct + 0.5, 2.0);
      reasons.push("score opportunità alto (≥70)");
    } else if (opportunityScore < 45) {
      basePct = Math.max(basePct - 0.5, 0.5);
      reasons.push("score opportunità basso (<45)");
    }
  }

  if (stopDistancePct > 3) {
    basePct = Math.max(basePct - 0.5, 0.25);
    reasons.push("stop lontano (>3% da entry)");
  }

  if (rrNetTp1 != null && rrNetTp1 < 0.8) {
    basePct = Math.max(basePct - 0.25, 0.25);
    reasons.push("R:R netto debole (<0.8:1)");
  }

  if (cappedByMargin) {
    reasons.push("cap margine attivo — aumenta «Max margine %» per usare il rischio target");
  }

  const rounded = Math.round(basePct * 4) / 4;
  const final = Math.max(0.25, Math.min(3.0, rounded));

  return {
    pct: final,
    rationale: reasons.join(" · "),
  };
}

export type RiskPresetRow = {
  riskPct: number;
  preview: PositionSizingPreview;
  isRecommended: boolean;
};

export function computeRiskPresets(
  user: PositionSizingUserInput,
  plan: TradePlanV1,
  opportunityScore?: number,
  variantStatus?: string | null,
  presets: number[] = [0.5, 1, 1.5, 2, 3],
): RiskPresetRow[] {
  const recommended = computePositionSizingPreview(
    user,
    plan,
    opportunityScore,
    variantStatus,
  ).recommendedRiskPct;

  return presets.map((rp) => {
    const p = computePositionSizingPreview(
      { ...user, riskMode: "percent", riskPercent: rp },
      plan,
      opportunityScore,
      variantStatus,
    );
    return {
      riskPct: rp,
      preview: p,
      isRecommended: Math.abs(rp - recommended) < 0.125,
    };
  });
}

const STORAGE_KEY = "positionSizingUserInputV2";

export function loadPositionSizingInput(): PositionSizingUserInput {
  if (typeof window === "undefined") return DEFAULT_POSITION_SIZING_INPUT;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_POSITION_SIZING_INPUT;
    const p = JSON.parse(raw) as Partial<PositionSizingUserInput>;
    return { ...DEFAULT_POSITION_SIZING_INPUT, ...p };
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
