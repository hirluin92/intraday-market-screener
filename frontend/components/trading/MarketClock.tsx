"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/** NYSE/NASDAQ regular session: 09:30–16:00 ET */
const MARKET_OPEN_H = 9;
const MARKET_OPEN_M = 30;
const MARKET_CLOSE_H = 16;
const MARKET_CLOSE_M = 0;

function getNYTime(): Date {
  return new Date(
    new Date().toLocaleString("en-US", { timeZone: "America/New_York" }),
  );
}

function isWeekday(d: Date): boolean {
  const day = d.getDay();
  return day >= 1 && day <= 5;
}

function isMarketOpen(d: Date): boolean {
  if (!isWeekday(d)) return false;
  const h = d.getHours();
  const m = d.getMinutes();
  const total = h * 60 + m;
  const open = MARKET_OPEN_H * 60 + MARKET_OPEN_M;
  const close = MARKET_CLOSE_H * 60 + MARKET_CLOSE_M;
  return total >= open && total < close;
}

interface MarketClockProps {
  className?: string;
}

/**
 * Real-time NYSE market clock.
 * Shows current NY time + open/closed status.
 * Stub: future versions will show pre/post-market sessions and countdown to open.
 */
export function MarketClock({ className }: MarketClockProps) {
  const [nyTime, setNyTime] = useState<Date | null>(null);

  useEffect(() => {
    setNyTime(getNYTime());
    const id = setInterval(() => setNyTime(getNYTime()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!nyTime) {
    return <div className={cn("skeleton h-6 w-24 rounded-md", className)} />;
  }

  const open = isMarketOpen(nyTime);
  const timeStr = nyTime.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  });

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      title={`Ora New York: ${timeStr} · Mercato ${open ? "aperto" : "chiuso"}`}
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          open ? "bg-bull animate-pulse-live" : "bg-fg-3",
        )}
        aria-hidden
      />
      <span
        className="font-mono text-xs tabular-nums text-fg-2"
        suppressHydrationWarning
      >
        {timeStr} NY
      </span>
      <span
        className={cn(
          "rounded-xs px-1.5 py-0.5 font-mono text-[10px] font-bold",
          open
            ? "bg-bull/10 text-bull"
            : "bg-surface-2 text-fg-3",
        )}
      >
        {open ? "OPEN" : "CLOSED"}
      </span>
    </div>
  );
}
