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
  return total >= MARKET_OPEN_H * 60 + MARKET_OPEN_M && total < MARKET_CLOSE_H * 60 + MARKET_CLOSE_M;
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
    return <div className={cn("skeleton h-6 w-24 rounded-md", className)} />;
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
      {/* Pulsating dot — animate-ping for visible OPEN state */}
      {open ? (
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
            style={{ backgroundColor: "#00d4a0" }} />
          <span className="relative inline-flex h-2 w-2 rounded-full"
            style={{ backgroundColor: "#00d4a0" }} />
        </span>
      ) : (
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: "hsla(0,0%,100%,0.2)" }} aria-hidden />
      )}

      {/* Time */}
      <span
        className="font-mono text-xs tabular-nums"
        style={{ color: "hsla(0,0%,100%,0.5)" }}
        suppressHydrationWarning
      >
        {timeStr} NY
      </span>

      {/* OPEN badge con glow */}
      <span
        className="rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold"
        style={open ? {
          color: "#00d4a0",
          border: "1px solid hsla(168, 100%, 45%, 0.3)",
          background: "hsla(168, 100%, 45%, 0.08)",
          boxShadow: "0 0 10px hsla(168, 100%, 45%, 0.3)",
        } : {
          color: "hsla(0,0%,100%,0.25)",
          border: "1px solid hsla(0,0%,100%,0.06)",
          background: "hsla(0,0%,100%,0.04)",
        }}
      >
        {open ? "OPEN" : "CLOSED"}
      </span>
    </div>
  );
}
