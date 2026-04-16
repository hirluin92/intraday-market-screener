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

// ── Inline style (guaranteed glass, no CSS override) ─────────────────────────

const TOPBAR_STYLE: React.CSSProperties = {
  background: "hsla(228, 15%, 8%, 0.60)",
  backdropFilter: "blur(20px) saturate(160%)",
  WebkitBackdropFilter: "blur(20px) saturate(160%)",
  borderBottom: "1px solid hsla(0, 0%, 100%, 0.06)",
};

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
        className="sticky top-0 z-30 flex h-12 shrink-0 items-center px-4 sm:px-6"
        style={TOPBAR_STYLE}
      >
        {/* Left */}
        <div className="flex flex-1 items-center gap-3">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className={cn(
              "rounded-md p-1.5 transition-colors lg:hidden",
              "hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
            )}
            style={{ color: "hsla(0,0%,100%,0.5)" }}
            aria-label="Apri menu navigazione"
            aria-expanded={drawerOpen}
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>

          {/* Logo mobile */}
          <Link
            href="/"
            className="font-sans text-sm font-bold lg:hidden"
            style={{
              color: "#f2f2f2",
              textShadow: "0 0 20px hsla(265, 80%, 62%, 0.3)",
            }}
          >
            IMS
          </Link>

          {/* Breadcrumb desktop */}
          {breadcrumb && (
            <span className="hidden font-mono text-xs lg:inline" style={{ color: "hsla(0,0%,100%,0.4)" }}>
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
              "rounded-md p-1.5 transition-colors",
              "hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
            )}
            style={{ color: "hsla(0,0%,100%,0.5)" }}
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
