"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart2,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  LayoutDashboard,
  TrendingUp,
  Zap,
} from "lucide-react";

import { IBKRStatusPill } from "@/components/trading/IBKRStatusPill";
import { cn } from "@/lib/utils";

const LS_KEY = "ims-sidebar-collapsed";

const NAV_ITEMS = [
  { href: "/",               label: "Dashboard",      Icon: LayoutDashboard },
  { href: "/opportunities",  label: "Opportunità",    Icon: Zap            },
  { href: "/backtest",       label: "Backtest",       Icon: BarChart2      },
  { href: "/simulation",     label: "Simulazione",    Icon: TrendingUp     },
  { href: "/trade-plan-lab", label: "Trade Plan Lab", Icon: FlaskConical   },
  { href: "/diagnostica",    label: "Diagnostica",    Icon: Activity       },
] as const;

function isActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

// ── Inline styles (guaranteed, no CSS cascade issues) ─────────────────────────

const SIDEBAR_STYLE: React.CSSProperties = {
  background: "hsla(228, 15%, 8%, 0.72)",
  backdropFilter: "blur(40px) saturate(180%)",
  WebkitBackdropFilter: "blur(40px) saturate(180%)",
  borderRight: "1px solid hsla(0, 0%, 100%, 0.06)",
};

const DIVIDER_STYLE: React.CSSProperties = {
  borderColor: "hsla(0, 0%, 100%, 0.06)",
};

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved !== null) setCollapsed(saved === "true");
    } catch { /* noop */ }
    setMounted(true);
  }, []);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem(LS_KEY, String(next)); } catch { /* noop */ }
  }

  return (
    <aside
      className={cn(
        "hidden lg:flex flex-col shrink-0",
        "sticky top-0 h-screen overflow-y-auto",
        "transition-[width] duration-200 ease-in-out",
        collapsed ? "w-16" : "w-60",
      )}
      style={SIDEBAR_STYLE}
      aria-label="Navigazione principale"
    >
      {/* Logo */}
      <div
        className={cn(
          "flex h-12 shrink-0 items-center border-b px-4",
          collapsed ? "justify-center" : "justify-between",
        )}
        style={DIVIDER_STYLE}
      >
        {!collapsed && (
          <span
            className="font-sans text-sm font-bold tracking-tight"
            style={{
              color: "#f2f2f2",
              textShadow: "0 0 30px hsla(265, 80%, 62%, 0.4)",
            }}
          >
            IMS
            <span className="ml-1 font-mono text-[10px] font-normal" style={{ color: "hsla(0,0%,100%,0.4)" }}>
              screener
            </span>
          </span>
        )}
        {collapsed && (
          <span
            className="font-mono text-xs font-bold"
            style={{
              color: "#00d4a0",
              textShadow: "0 0 20px hsla(168, 100%, 45%, 0.5)",
            }}
          >
            IMS
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-2 py-3" aria-label="Sezioni applicazione">
        <ul className="space-y-0.5" role="list">
          {NAV_ITEMS.map(({ href, label, Icon }) => {
            const active = isActive(href, pathname);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn(
                    "group flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-all duration-150",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
                    collapsed && "justify-center",
                  )}
                  style={active ? {
                    background: "hsla(265, 80%, 60%, 0.12)",
                    borderLeft: "2px solid hsl(265, 80%, 60%)",
                    boxShadow: "inset 0 0 30px hsla(265, 80%, 60%, 0.08)",
                    color: "#f2f2f2",
                    paddingLeft: collapsed ? undefined : "calc(0.5rem - 2px)",
                  } : {
                    color: "hsla(0,0%,100%,0.45)",
                    borderLeft: "2px solid transparent",
                  }}
                  title={collapsed ? label : undefined}
                  aria-current={active ? "page" : undefined}
                  onMouseEnter={(e) => {
                    if (!active) (e.currentTarget as HTMLElement).style.color = "#f2f2f2";
                  }}
                  onMouseLeave={(e) => {
                    if (!active) (e.currentTarget as HTMLElement).style.color = "hsla(0,0%,100%,0.45)";
                  }}
                >
                  <Icon
                    className="h-4 w-4 shrink-0"
                    style={{ color: active ? "hsl(265, 80%, 70%)" : undefined }}
                    aria-hidden
                  />
                  {!collapsed && <span className="truncate">{label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="shrink-0 border-t p-3 space-y-2" style={DIVIDER_STYLE}>
        {!collapsed && <IBKRStatusPill variant="pill" className="w-full justify-start" />}
        {collapsed && <IBKRStatusPill variant="inline" className="justify-center" />}

        <button
          type="button"
          onClick={toggleCollapsed}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors",
            "hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
            collapsed ? "justify-center" : "justify-end",
          )}
          style={{ color: "hsla(0,0%,100%,0.35)" }}
          aria-label={collapsed ? "Espandi sidebar" : "Comprimi sidebar"}
          suppressHydrationWarning
        >
          {mounted && (collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <>
              <span>Comprimi</span>
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            </>
          ))}
        </button>
      </div>
    </aside>
  );
}
