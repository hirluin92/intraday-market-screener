"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Settings } from "lucide-react";

import { MarketClock } from "@/components/trading/MarketClock";
import { RegimeIndicator } from "@/components/trading/RegimeIndicator";
import { MobileDrawer } from "./MobileDrawer";
import { cn } from "@/lib/utils";

const ROUTE_LABELS: Record<string, string> = {
  "/":               "Dashboard",
  "/opportunities":  "Opportunità",
  "/backtest":       "Backtest",
  "/simulation":     "Simulazione",
  "/trade-plan-lab": "Trade Plan Lab",
  "/diagnostica":    "Diagnostica",
};

function getBreadcrumb(pathname: string): string {
  if (pathname in ROUTE_LABELS) return ROUTE_LABELS[pathname];
  const oppMatch = pathname.match(/^\/opportunities\/([^/]+)\/([^/]+)/);
  if (oppMatch) {
    const sym = decodeURIComponent(oppMatch[1]).toUpperCase();
    const tf  = decodeURIComponent(oppMatch[2]);
    return `${sym} · ${tf}`;
  }
  return "";
}

interface TopbarProps {
  regime?: string | null;
}

export function Topbar({ regime }: TopbarProps) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const breadcrumb = getBreadcrumb(pathname ?? "");

  return (
    <>
      <header
        className={cn(
          "sticky top-0 z-30 flex h-12 shrink-0 items-center",
          "glass border-b-[var(--glass-border)]",
          "px-4 sm:px-6",
        )}
        style={{
          borderRadius: 0,
          borderLeft: "none",
          borderRight: "none",
          borderTop: "none",
        }}
      >
        {/* Left */}
        <div className="flex flex-1 items-center gap-3">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className={cn(
              "rounded-md p-1.5 text-fg-2 hover:text-fg transition-colors",
              "hover:bg-[var(--glass-bg-hover)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
              "lg:hidden",
            )}
            aria-label="Apri menu navigazione"
            aria-expanded={drawerOpen}
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>

          {/* Logo mobile */}
          <Link
            href="/"
            className="font-sans text-sm font-bold text-fg lg:hidden"
            style={{ textShadow: "0 0 20px hsla(265 80% 62% / 0.3)" }}
          >
            IMS
          </Link>

          {/* Breadcrumb desktop */}
          {breadcrumb && (
            <span className="hidden font-mono text-xs text-fg-2 lg:inline">
              {breadcrumb}
            </span>
          )}
        </div>

        {/* Right: regime + clock + settings */}
        <div className="flex items-center gap-3">
          <RegimeIndicator regime={regime} className="hidden sm:flex" />
          <MarketClock className="hidden md:flex" />
          <button
            type="button"
            className={cn(
              "rounded-md p-1.5 text-fg-2 hover:text-fg transition-colors",
              "hover:bg-[var(--glass-bg-hover)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
            )}
            aria-label="Impostazioni"
            title="Impostazioni (coming soon)"
          >
            <Settings className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </header>

      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
