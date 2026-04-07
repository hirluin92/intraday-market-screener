"use client";

import { useState } from "react";

import type { PositionSizingUserInput } from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";

type Props = {
  sizing: PositionSizingUserInput;
  onSizingChange: (s: PositionSizingUserInput) => void;
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
};

export function OpportunityPreferencesBar({
  sizing,
  onSizingChange,
  broker,
  onBrokerChange,
}: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]/90">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-2 text-left text-sm font-semibold text-[var(--text-secondary)]"
        aria-expanded={open}
      >
        <span>⚙️ Preferenze conto & broker</span>
        <span>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="grid gap-3 border-t border-[var(--border)] px-4 py-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-xs text-[var(--text-secondary)]">
            Capitale (€)
            <input
              type="number"
              min={100}
              step={50}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 font-[family-name:var(--font-trader-mono)] text-sm text-[var(--text-primary)]"
              value={sizing.accountCapital}
              onChange={(e) =>
                onSizingChange({
                  ...sizing,
                  accountCapital: Number(e.target.value) || 0,
                })
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--text-secondary)]">
            Rischio % / trade
            <input
              type="number"
              min={0.1}
              max={5}
              step={0.1}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 font-[family-name:var(--font-trader-mono)] text-sm text-[var(--text-primary)]"
              value={sizing.riskMode === "percent" ? sizing.riskPercent : sizing.riskFixed}
              onChange={(e) =>
                onSizingChange({
                  ...sizing,
                  riskMode: "percent",
                  riskPercent: Number(e.target.value) || 0.5,
                })
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--text-secondary)]">
            Broker istruzioni
            <select
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-sm text-[var(--text-primary)]"
              value={broker}
              onChange={(e) => onBrokerChange(e.target.value as TraderBrokerId)}
            >
              <option value="ibkr">IBKR</option>
              <option value="xtb">XTB</option>
              <option value="other">Altro</option>
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
