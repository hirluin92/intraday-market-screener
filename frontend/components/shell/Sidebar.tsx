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
  { href: "/",                  label: "Dashboard",      Icon: LayoutDashboard },
  { href: "/opportunities",     label: "Opportunità",    Icon: Zap            },
  { href: "/backtest",          label: "Backtest",       Icon: BarChart2      },
  { href: "/simulation",        label: "Simulazione",    Icon: TrendingUp     },
  { href: "/trade-plan-lab",    label: "Trade Plan Lab", Icon: FlaskConical   },
  { href: "/diagnostica",       label: "Diagnostica",    Icon: Activity       },
] as const;

function isActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Read persisted state after hydration to avoid SSR mismatch
  useEffect(() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved !== null) setCollapsed(saved === "true");
    } catch {
      // localStorage unavailable (SSR guard)
    }
    setMounted(true);
  }, []);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(LS_KEY, String(next));
    } catch {
      // noop
    }
  }

  return (
    <aside
      className={cn(
        "hidden lg:flex flex-col shrink-0",
        "bg-surface border-r border-line",
        "sticky top-0 h-screen overflow-y-auto",
        "transition-[width] duration-200 ease-in-out",
        collapsed ? "w-16" : "w-60",
      )}
      aria-label="Navigazione principale"
    >
      {/* Logo */}
      <div
        className={cn(
          "flex h-12 shrink-0 items-center border-b border-line px-4",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        {!collapsed && (
          <span className="font-sans text-sm font-bold tracking-tight text-fg">
            IMS
            <span className="ml-1 font-mono text-[10px] font-normal text-fg-2">
              screener
            </span>
          </span>
        )}
        {collapsed && (
          <span className="font-mono text-xs font-bold text-bull">IMS</span>
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
                    "group flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
                    active
                      ? "bg-surface-3 border-l-2 border-bull text-fg font-medium"
                      : "text-fg-2 hover:bg-surface-3 hover:text-fg border-l-2 border-transparent",
                    collapsed && "justify-center",
                  )}
                  title={collapsed ? label : undefined}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      active ? "text-bull" : "text-fg-2 group-hover:text-fg",
                    )}
                    aria-hidden
                  />
                  {!collapsed && (
                    <span className="truncate">{label}</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer: status + collapse toggle */}
      <div className={cn("shrink-0 border-t border-line p-3 space-y-2")}>
        {!collapsed && <IBKRStatusPill variant="pill" className="w-full justify-start" />}
        {collapsed && <IBKRStatusPill variant="inline" className="justify-center" />}

        <button
          type="button"
          onClick={toggleCollapsed}
          className={cn(
            "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg-2",
            "hover:bg-surface-3 hover:text-fg transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
            collapsed ? "justify-center" : "justify-end",
          )}
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
