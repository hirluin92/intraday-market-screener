"use client";

import { useState } from "react";

import {
  BROKER_INSTRUCTIONS,
  fillInstructionTemplate,
} from "./brokerInstructions";
import type { TraderBrokerId } from "@/lib/traderPrefs";

type Props = {
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
  direction: "long" | "short";
  symbol: string;
  entry: string;
  stop: string;
  tp: string;
  qty: string;
};

export function TradeInstructions({
  broker,
  onBrokerChange,
  direction,
  symbol,
  entry,
  stop,
  tp,
  qty,
}: Props) {
  const [open, setOpen] = useState(true);

  const vars: Record<string, string> = {
    symbol,
    entry,
    stop,
    tp,
    qty,
  };

  const tpl =
    broker === "other"
      ? null
      : BROKER_INSTRUCTIONS[broker as "ibkr" | "xtb"];

  const lines =
    tpl != null
      ? fillInstructionTemplate(
          direction === "short" ? tpl.short : tpl.long,
          vars,
        )
      : [
          `Verifica su broker: ${symbol}`,
          `Direzione: ${direction === "short" ? "Short / vendita" : "Long / acquisto"}`,
          `Entry: ${entry} · Stop: ${stop} · TP: ${tp} · Qty: ${qty}`,
        ];

  const warn =
    tpl != null
      ? direction === "short"
        ? tpl.warning.short
        : tpl.warning.long ?? tpl.warning.short
      : null;

  return (
    <div
      className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/80 p-3 text-sm text-[var(--text-primary)] backdrop-blur-sm"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left font-[family-name:var(--font-trader-sans)] font-semibold"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span>📖 Come aprire il trade</span>
        <span className="text-[var(--text-secondary)]">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Broker">
            {(["ibkr", "xtb", "other"] as const).map((b) => (
              <button
                key={b}
                type="button"
                role="tab"
                aria-selected={broker === b}
                onClick={() => onBrokerChange(b)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  broker === b
                    ? "border-[var(--accent-neutral)] bg-[var(--accent-neutral)]/20 text-[var(--text-primary)]"
                    : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-active)]"
                }`}
              >
                {b === "ibkr" ? "IBKR" : b === "xtb" ? "XTB" : "Altro"}
              </button>
            ))}
          </div>
          <ol className="list-decimal space-y-1.5 pl-5 font-[family-name:var(--font-trader-sans)] text-[0.85rem] leading-relaxed text-[var(--text-secondary)]">
            {lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>
          {warn && (
            <p className="border-t border-[var(--border)] pt-2 text-xs text-[var(--text-secondary)]">
              {warn}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
