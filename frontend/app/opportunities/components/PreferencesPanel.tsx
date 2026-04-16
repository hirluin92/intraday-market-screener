"use client";

import type { PositionSizingUserInput } from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";
import { OpportunityPreferencesBar } from "./OpportunityPreferencesBar";

interface PreferencesPanelProps {
  sizing: PositionSizingUserInput;
  onSizingChange: (s: PositionSizingUserInput) => void;
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
}

/**
 * Thin wrapper around the existing OpportunityPreferencesBar.
 * In 3B this will be refactored to a sticky sidebar (≥1280px) / Sheet drawer (<1280px).
 */
export function PreferencesPanel(props: PreferencesPanelProps) {
  return <OpportunityPreferencesBar {...props} />;
}
