"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const MARKET_OPEN_H = 9, MARKET_OPEN_M = 30;
const MARKET_CLOSE_H = 16, MARKET_CLOSE_M = 0;

function getNYTime(): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
}

function isWeekday(d: Date): boolean {
  const day = d.getDay();
  return day >= 1 && day <= 5;
}

function isMarketOpen(d: Date): boolean {
  if (!isWeekday(d)) return false;
  const h = d.getHours(), m = d.getMinutes();
  const total = h * 60 + m;
  const open = MARKET_OPEN_H * 60 + MARKET_OPEN_M;
  const close = MARKET_CLOSE_H * 60 + MARKET_CLOSE_M;
  return total >= open && total < close;
}

interface MarketClockProps { className?: string; }

export function MarketClock({ className }: MarketClockProps) {
  const [nyTime, setNyTime] = useState<Date | null>(null);

  useEffect(() => {
    setNyTime(getNYTime());
    const id = setInterval(() => setNyTime(getNYTime()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!nyTime) {
    return <div className={cn("skeleton-shimmer h-6 w-24 rounded-md", className)} />;
  }

  const open = isMarketOpen(nyTime);
  const timeStr = nyTime.toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York",
  });

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      title={`Ora New York: ${timeStr} · Mercato ${open ? "aperto" : "chiuso"}`}
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          open ? "bg-bull animate-glow-pulse" : "bg-fg-3",
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
          "rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold",
          open
            ? "text-bull border border-bull/30 bg-bull/10"
            : "bg-surface-2 text-fg-3",
        )}
        style={open ? { boxShadow: "0 0 10px hsla(168 100% 45% / 0.25)" } : undefined}
      >
        {open ? "OPEN" : "CLOSED"}
      </span>
    </div>
  );
}
