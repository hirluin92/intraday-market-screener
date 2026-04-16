"use client";

import { cn } from "@/lib/utils";

interface RegimeIndicatorProps {
  regime?: string | null;
  className?: string;
}

const REGIME_CONFIG: Record<
  string,
  { dot: string; text: string; border: string; label: string }
> = {
  bullish: {
    dot: "bg-bull animate-pulse-live",
    text: "text-bull",
    border: "border-bull/30",
    label: "SPY Bull",
  },
  bearish: {
    dot: "bg-bear",
    text: "text-bear",
    border: "border-bear/30",
    label: "SPY Bear",
  },
  neutral: {
    dot: "bg-neutral",
    text: "text-neutral",
    border: "border-neutral/30",
    label: "SPY Neutral",
  },
};

/**
 * Compact SPY regime badge.
 * Stub: will gain a tooltip with details (trend strength, date) in Step 3.
 */
export function RegimeIndicator({ regime, className }: RegimeIndicatorProps) {
  if (!regime || regime === "n/a" || regime === "unknown") {
    return null;
  }

  const key = regime.toLowerCase();
  const cfg = REGIME_CONFIG[key] ?? {
    dot: "bg-fg-3",
    text: "text-fg-2",
    border: "border-line",
    label: `SPY ${regime}`,
  };

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1",
        cfg.border,
        "bg-surface-2",
        className,
      )}
      title={`Regime SPY: ${regime}`}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", cfg.dot)} aria-hidden />
      <span className={cn("font-mono text-xs font-medium", cfg.text)}>{cfg.label}</span>
    </div>
  );
}
