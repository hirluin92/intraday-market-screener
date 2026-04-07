"use client";

import { useState } from "react";

import type { OpportunityRow } from "@/lib/api";
import { formatPrice } from "@/lib/formatPrice";
import { opportunityCardId } from "@/lib/opportunityCardId";

type Props = {
  opportunity: OpportunityRow;
};

function strengthPctDisplay(row: OpportunityRow): string {
  const s = row.latest_pattern_strength;
  if (s == null) return "—";
  const n = typeof s === "number" ? s : Number(s);
  if (!Number.isFinite(n)) return "—";
  const pct = n <= 1 ? n * 100 : n;
  return `${Math.round(pct)}%`;
}

function dirArrow(row: OpportunityRow): string {
  const d = row.latest_pattern_direction?.toLowerCase();
  if (d === "bearish") return "↓";
  if (d === "bullish") return "↑";
  return "↔";
}

export function DiscardedCard({ opportunity: opp }: Props) {
  const [expanded, setExpanded] = useState(false);
  const summary = opp.decision_rationale?.[0] ?? "Non operativo";

  return (
    <div
      id={`card-${opportunityCardId(opp)}`}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      className="cursor-pointer rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/80 opacity-60 transition-opacity hover:opacity-85 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-neutral)]"
      onClick={() => setExpanded((v) => !v)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setExpanded((v) => !v);
        }
      }}
    >
      <div className="flex flex-col gap-1 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <span className="text-xs text-[var(--text-muted)]" aria-hidden>
            ✗
          </span>
          <span className="font-[family-name:var(--font-trader-mono)] text-sm font-bold text-[var(--text-secondary)]">
            {opp.symbol}
          </span>
          <span className="text-xs text-[var(--text-muted)]">{opp.timeframe}</span>
          <span className="text-xs text-[var(--text-muted)]" aria-hidden>
            {dirArrow(opp)}
          </span>
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <span
            className="min-w-0 truncate text-xs text-[var(--text-muted)] sm:max-w-md"
            title={summary}
          >
            {summary}
          </span>
          <span className="shrink-0 text-xs text-[var(--text-muted)]" aria-hidden>
            {expanded ? "▲" : "▼"}
          </span>
        </div>
      </div>

      {expanded && (
        <div
          className="space-y-3 border-t border-[var(--border)] px-3 pb-3 pt-2"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          {opp.trade_plan && (
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <div>
                <p className="text-[var(--text-muted)]">Entry</p>
                <p className="font-[family-name:var(--font-trader-mono)] text-[var(--text-primary)]">
                  {formatPrice(opp.trade_plan.entry_price)}
                </p>
              </div>
              <div>
                <p className="text-[var(--text-muted)]">Stop</p>
                <p className="font-[family-name:var(--font-trader-mono)] text-[var(--text-primary)]">
                  {formatPrice(opp.trade_plan.stop_loss)}
                </p>
              </div>
              <div>
                <p className="text-[var(--text-muted)]">TP1</p>
                <p className="font-[family-name:var(--font-trader-mono)] text-[var(--text-primary)]">
                  {formatPrice(opp.trade_plan.take_profit_1)}
                </p>
              </div>
              <div>
                <p className="text-[var(--text-muted)]">R/R</p>
                <p className="font-[family-name:var(--font-trader-mono)] text-[var(--text-primary)]">
                  {opp.trade_plan.risk_reward_ratio ?? "—"}
                </p>
              </div>
            </div>
          )}

          <div>
            <p className="mb-1 text-xs text-[var(--text-muted)]">Motivi</p>
            <ul className="list-none space-y-1">
              {(opp.decision_rationale ?? []).map((r, i) => (
                <li key={i} className="text-xs text-[var(--text-secondary)]">
                  • {r}
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap gap-4 text-xs text-[var(--text-secondary)]">
            <div>
              <span className="text-[var(--text-muted)]">Pattern: </span>
              <span>{opp.latest_pattern_name?.replace(/_/g, " ") ?? "—"}</span>
            </div>
            <div>
              <span className="text-[var(--text-muted)]">Forza: </span>
              <span className="font-[family-name:var(--font-trader-mono)]">{strengthPctDisplay(opp)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
