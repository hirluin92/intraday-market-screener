"use client";

import { useEffect, useState } from "react";

import {
  DEFAULT_POSITION_SIZING_INPUT,
  loadPositionSizingInput,
  savePositionSizingInput,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";
import {
  loadTraderBroker,
  saveTraderBroker,
  syncLegacyPrefKeys,
  type TraderBrokerId,
} from "@/lib/traderPrefs";

/**
 * Manages position sizing preferences + broker selection.
 * Reads from / writes to localStorage.
 * Replaces the direct localStorage calls scattered in page.tsx load() and handlers.
 */
export function useOpportunityPreferences() {
  const [sizingInput, setSizingInput] = useState<PositionSizingUserInput>(
    DEFAULT_POSITION_SIZING_INPUT,
  );
  const [broker, setBroker] = useState<TraderBrokerId>("ibkr");

  useEffect(() => {
    setSizingInput(loadPositionSizingInput());
    setBroker(loadTraderBroker());
  }, []);

  const persistSizing = (s: PositionSizingUserInput) => {
    setSizingInput(s);
    savePositionSizingInput(s);
    syncLegacyPrefKeys(s, broker);
  };

  const persistBroker = (b: TraderBrokerId) => {
    setBroker(b);
    saveTraderBroker(b);
    syncLegacyPrefKeys(sizingInput, b);
  };

  return { sizingInput, persistSizing, broker, persistBroker };
}
