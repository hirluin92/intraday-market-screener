"use client";

import Link from "next/link";
import { Minus } from "lucide-react";

import type { OpportunityRow } from "@/lib/api";
import { seriesDetailHref } from "@/lib/api";
import { opportunityCardId } from "@/lib/opportunityCardId";
import { cn } from "@/lib/utils";

type Props = {
  opportunity: OpportunityRow;
};

function dirArrow(row: OpportunityRow): string {
  const d = row.latest_pattern_direction?.toLowerCase();
  if (d === "bearish") return "▼";
  if (d === "bullish") return "▲";
  return "↔";
}

/**
 * Compact read-only row for discarded opportunities.
 * 3B: h-12 fixed, opacity-60, hover restores opacity, click → detail page.
 * Reason for discard shown inline with tooltip for long text.
 */
export function DiscardedCard({ opportunity: opp }: Props) {
  const summary = opp.decision_rationale?.[0] ?? "Non operativo";
  const isBull = opp.latest_pattern_direction?.toLowerCase() === "bullish";
  const href = seriesDetailHref(opp.symbol, opp.timeframe, opp.exchange, {
    provider: opp.provider,
    asset_type: opp.asset_type,
  });

  return (
    <Link
      id={`card-${opportunityCardId(opp)}`}
      href={href}
      className={cn(
        "flex h-12 items-center gap-3 rounded-lg border border-line bg-surface-2/50 px-3",
        "opacity-60 transition-all duration-150",
        "hover:border-line-hi hover:bg-surface-2 hover:opacity-100",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
      )}
      aria-label={`Scartato: ${opp.symbol} ${opp.timeframe} — ${summary}`}
    >
      {/* Discard icon */}
      <Minus className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden />

      {/* Symbol + timeframe + direction */}
      <span className="font-mono text-sm font-semibold text-fg-2">
        {opp.symbol}
      </span>
      <span className="text-xs text-fg-3">{opp.timeframe}</span>
      <span
        className={cn(
          "font-mono text-xs",
          isBull ? "text-bull/60" : "text-bear/60",
        )}
        aria-hidden
      >
        {dirArrow(opp)}
      </span>

      {/* Motivo scarto — truncated, full text on title tooltip */}
      <span
        className="min-w-0 flex-1 truncate text-xs text-fg-3"
        title={summary}
      >
        {summary}
      </span>

      {/* Timestamp */}
      {opp.pattern_timestamp && (
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-fg-3">
          {new Date(opp.pattern_timestamp).toLocaleTimeString("it-IT", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      )}
    </Link>
  );
}
