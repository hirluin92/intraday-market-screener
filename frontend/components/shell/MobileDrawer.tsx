"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart2,
  FlaskConical,
  LayoutDashboard,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";

import { IBKRStatusPill } from "@/components/trading/IBKRStatusPill";
import { cn } from "@/lib/utils";

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

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MobileDrawer({ open, onClose }: MobileDrawerProps) {
  const pathname = usePathname();

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-canvas/80 backdrop-blur-sm lg:hidden"
        onClick={onClose}
        aria-hidden
      />

      {/* Drawer panel */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-72 flex-col",
          "bg-surface border-r border-line",
          "animate-slide-in lg:hidden",
        )}
        role="dialog"
        aria-modal
        aria-label="Menu navigazione"
      >
        {/* Header */}
        <div className="flex h-12 items-center justify-between border-b border-line px-4">
          <span className="font-sans text-sm font-bold text-fg">
            IMS <span className="font-mono text-[10px] font-normal text-fg-2">screener</span>
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-fg-2 hover:bg-surface-3 hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50"
            aria-label="Chiudi menu"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Sezioni applicazione">
          <ul className="space-y-0.5" role="list">
            {NAV_ITEMS.map(({ href, label, Icon }) => {
              const active = isActive(href, pathname);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onClose}
                    className={cn(
                      "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
                      active
                        ? "bg-surface-3 border-l-2 border-bull text-fg font-medium"
                        : "text-fg-2 hover:bg-surface-3 hover:text-fg border-l-2 border-transparent",
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        active ? "text-bull" : "text-fg-2",
                      )}
                      aria-hidden
                    />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="shrink-0 border-t border-line p-4">
          <IBKRStatusPill variant="pill" className="w-full justify-start" />
        </div>
      </div>
    </>
  );
}
