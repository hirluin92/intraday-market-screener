/**
 * Preferenze trader (broker) + allineamento a PositionSizingUserInput.
 */

import type { PositionSizingUserInput } from "./positionSizing";
import { loadPositionSizingInput, savePositionSizingInput } from "./positionSizing";

export type TraderBrokerId = "ibkr" | "xtb" | "other";

const BROKER_KEY = "trader_prefs_broker_v1";

export function loadTraderBroker(): TraderBrokerId {
  if (typeof window === "undefined") return "ibkr";
  try {
    const raw = localStorage.getItem(BROKER_KEY);
    if (raw === "ibkr" || raw === "xtb" || raw === "other") return raw;
  } catch {
    /* ignore */
  }
  return "ibkr";
}

export function saveTraderBroker(b: TraderBrokerId): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(BROKER_KEY, b);
  } catch {
    /* ignore */
  }
}

/** Legge sizing salvato e restituisce input per i calcoli card. */
export function loadSizingForTraderCards(): PositionSizingUserInput {
  return loadPositionSizingInput();
}

export function saveSizingForTraderCards(input: PositionSizingUserInput): void {
  savePositionSizingInput(input);
}

/** Chiavi legacy `pref_*` per strumenti esterni / prompt; allineate a sizing + broker. */
export function syncLegacyPrefKeys(
  sizing: PositionSizingUserInput,
  broker: TraderBrokerId,
): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("pref_capital", String(sizing.accountCapital));
    localStorage.setItem(
      "pref_risk",
      String(sizing.riskMode === "percent" ? sizing.riskPercent : sizing.riskFixed),
    );
    localStorage.setItem("pref_broker", broker);
  } catch {
    /* ignore */
  }
}
