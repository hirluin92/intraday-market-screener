"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

// ── Market hours: NYSE/NASDAQ regular session ────────────────────────────────
// 09:30–16:00 ET  (Mon–Fri)

const NY_TZ = "America/New_York";

function getNYParts(): { h: number; m: number; dow: number; timeStr: string } {
  // Use Intl.DateTimeFormat to extract parts WITHOUT double-conversion bug.
  // The old approach `new Date(new Date().toLocaleString(...))` creates a
  // "fake-local" Date causing a double timezone shift.
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: NY_TZ,
    weekday: "short",
    hour:    "2-digit",
    minute:  "2-digit",
    hour12:  false,
  });
  const parts = fmt.formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "0";

  const rawH = parseInt(get("hour"), 10);
  // 24:xx → 0:xx (midnight edge case in some locales)
  const h = rawH === 24 ? 0 : rawH;
  const m = parseInt(get("minute"), 10);
  const dowStr = get("weekday"); // "Mon", "Tue", ...
  const dowMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const dow = dowMap[dowStr] ?? new Date().getDay();

  // Format time string "HH:MM"
  const timeStr = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;

  return { h, m, dow, timeStr };
}

function isMarketOpen(h: number, m: number, dow: number): boolean {
  if (dow < 1 || dow > 5) return false;
  const total = h * 60 + m;
  return total >= 9 * 60 + 30 && total < 16 * 60;
}

interface MarketClockProps { className?: string; }

export function MarketClock({ className }: MarketClockProps) {
  const [state, setState] = useState<{ timeStr: string; open: boolean } | null>(null);

  useEffect(() => {
    function tick() {
      const { h, m, dow, timeStr } = getNYParts();
      setState({ timeStr, open: isMarketOpen(h, m, dow) });
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  if (!state) {
    return <div className={cn("skeleton h-6 w-24 rounded-md", className)} />;
  }

  const { timeStr, open } = state;

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      title={`Ora New York: ${timeStr} · Mercato ${open ? "aperto" : "chiuso"}`}
    >
      {open ? (
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60"
            style={{ backgroundColor: "#00d4a0" }} />
          <span className="relative inline-flex h-2 w-2 rounded-full"
            style={{ backgroundColor: "#00d4a0" }} />
        </span>
      ) : (
        <span className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: "rgba(255,255,255,0.2)" }} aria-hidden />
      )}

      <span
        className="font-mono text-xs tabular-nums"
        style={{ color: "rgba(255,255,255,0.5)" }}
        suppressHydrationWarning
      >
        {timeStr} NY
      </span>

      <span
        className="rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold"
        style={open ? {
          color: "#00d4a0",
          border: "1px solid rgba(0,212,160,0.30)",
          background: "rgba(0,212,160,0.08)",
          boxShadow: "0 0 10px rgba(0,212,160,0.25)",
        } : {
          color: "rgba(255,255,255,0.25)",
          border: "1px solid rgba(255,255,255,0.06)",
          background: "rgba(255,255,255,0.03)",
        }}
      >
        {open ? "OPEN" : "CLOSED"}
      </span>
    </div>
  );
}
