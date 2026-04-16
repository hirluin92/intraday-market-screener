"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { seriesDetailHref } from "@/lib/api";
import type { OpportunityRow } from "@/lib/api";
import { formatPrice } from "@/lib/formatPrice";
import { cn } from "@/lib/utils";

interface SignalCardCompactProps {
  opportunity: OpportunityRow;
  currencySymbol?: string;
  className?: string;
}

export function SignalCardCompact({
  opportunity: row,
  className,
}: SignalCardCompactProps) {
  const isBull = (row.latest_pattern_direction ?? "").toLowerCase() === "bullish";
  const plan = row.trade_plan;
  const score = Math.round((row.final_opportunity_score ?? 0) * 100);
  const href = seriesDetailHref(row.symbol, row.timeframe, row.exchange, {
    provider: row.provider,
    asset_type: row.asset_type,
  });

  return (
    <Link
      href={href}
      className={cn(
        "group block rounded-lg border p-4 transition-colors",
        "bg-surface hover:bg-surface-2",
        isBull ? "border-bull/30 hover:border-bull/50" : "border-bear/30 hover:border-bear/50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
        className,
      )}
      aria-label={`${row.symbol} ${row.timeframe} ${isBull ? "Long" : "Short"} — score ${score}%`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="font-sans text-sm font-bold text-fg">{row.symbol}</span>
          <span className="ml-1.5 font-mono text-xs text-fg-2">{row.timeframe}</span>
        </div>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 font-mono text-[10px] font-bold",
            isBull
              ? "bg-bull/15 text-bull"
              : "bg-bear/15 text-bear",
          )}
        >
          {isBull ? "▲ LONG" : "▼ SHORT"}
        </span>
      </div>

      {/* Pattern + strength */}
      {row.latest_pattern_name && (
        <p className="mt-1.5 truncate text-xs text-fg-2">
          {row.latest_pattern_name.replace(/_/g, " ")}
          {row.latest_pattern_strength != null && (
            <span className="ml-1 text-fg-3">
              · {Math.round(
                typeof row.latest_pattern_strength === "number"
                  ? row.latest_pattern_strength <= 1
                    ? row.latest_pattern_strength * 100
                    : row.latest_pattern_strength
                  : Number(row.latest_pattern_strength) * 100,
              )}%
            </span>
          )}
        </p>
      )}

      {/* Prices */}
      {plan && (
        <div className="mt-3 grid grid-cols-3 gap-x-2 font-mono text-xs tabular-nums">
          <div>
            <p className="text-[10px] text-fg-3">Entry</p>
            <p className="text-fg">{formatPrice(plan.entry_price)}</p>
          </div>
          <div>
            <p className="text-[10px] text-fg-3">SL</p>
            <p className="text-bear">{formatPrice(plan.stop_loss)}</p>
          </div>
          <div>
            <p className="text-[10px] text-fg-3">TP1</p>
            <p className="text-bull">{formatPrice(plan.take_profit_1)}</p>
          </div>
        </div>
      )}

      {/* Score bar */}
      <div className="mt-3 flex items-center gap-2">
        <div className="h-1 flex-1 rounded-full bg-surface-3">
          <div
            className={cn(
              "h-1 rounded-full transition-all",
              isBull ? "bg-bull" : "bg-bear",
            )}
            style={{ width: `${Math.min(100, score)}%` }}
            aria-hidden
          />
        </div>
        <span className={cn("font-mono text-[10px] font-bold", isBull ? "text-bull" : "text-bear")}>
          {score}%
        </span>
      </div>

      {/* CTA */}
      <div className="mt-3 flex items-center justify-end gap-1 text-xs text-fg-2 group-hover:text-fg transition-colors">
        <span>Vai al dettaglio</span>
        <ArrowRight className="h-3 w-3" aria-hidden />
      </div>
    </Link>
  );
}
