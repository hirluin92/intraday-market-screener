"use client";

import type { OpportunityRow } from "@/lib/api";
import { opportunityCardId } from "@/lib/opportunityCardId";
import type { PositionSizingUserInput } from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";
import { SignalCard } from "./SignalCard";

const CURRENCY = "€";

interface SignalListProps {
  executeRows: OpportunityRow[];
  monitorRows: OpportunityRow[];
  showExecuteBlock: boolean;
  showMonitorBlock: boolean;
  sizingInput: PositionSizingUserInput;
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
  expandedCardId: string | null;
  onExpandedChange: (id: string | null) => void;
}

export function SignalList({
  executeRows,
  monitorRows,
  showExecuteBlock,
  showMonitorBlock,
  sizingInput,
  broker,
  onBrokerChange,
  expandedCardId,
  onExpandedChange,
}: SignalListProps) {
  return (
    <>
      {showExecuteBlock && executeRows.length > 0 && (
        <section aria-label="Segnali esegui">
          <h2 className="mb-3 font-[family-name:var(--font-trader-sans)] text-sm font-bold uppercase tracking-wide text-[var(--text-secondary)]">
            Esegui ora
          </h2>
          <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
            {executeRows.map((row) => (
              <SignalCard
                key={opportunityCardId(row)}
                opportunity={row}
                sizingInput={sizingInput}
                broker={broker}
                onBrokerChange={onBrokerChange}
                currencySymbol={CURRENCY}
                variant="execute"
                cardId={opportunityCardId(row)}
                expanded={expandedCardId === opportunityCardId(row)}
                onExpandedChange={onExpandedChange}
              />
            ))}
          </div>
        </section>
      )}

      {showMonitorBlock && monitorRows.length > 0 && (
        <section aria-label="In monitoraggio">
          <h2 className="mb-3 font-[family-name:var(--font-trader-sans)] text-sm font-bold uppercase tracking-wide text-[var(--text-secondary)]">
            Monitora
          </h2>
          <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
            {monitorRows.map((row) => (
              <SignalCard
                key={opportunityCardId(row)}
                opportunity={row}
                sizingInput={sizingInput}
                broker={broker}
                onBrokerChange={onBrokerChange}
                currencySymbol={CURRENCY}
                variant="monitor"
                cardId={opportunityCardId(row)}
                expanded={expandedCardId === opportunityCardId(row)}
                onExpandedChange={onExpandedChange}
              />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
