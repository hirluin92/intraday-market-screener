"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/opportunities", label: "Opportunità" },
  { href: "/backtest", label: "Backtest" },
  { href: "/simulation", label: "Simulazione" },
  { href: "/trade-plan-lab", label: "Trade plan lab" },
  { href: "/diagnostica", label: "Diagnostica" },
] as const;

const LINK_BASE =
  "text-sm text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100";
const LINK_ACTIVE =
  " font-semibold text-zinc-900 dark:text-zinc-100";

function navLinkClass(href: string, pathname: string | null): string {
  if (!pathname) return LINK_BASE;
  const active =
    href === "/"
      ? pathname === "/"
      : pathname === href || pathname.startsWith(`${href}/`);
  return `${LINK_BASE}${active ? LINK_ACTIVE : ""}`;
}

export function AppNav() {
  const pathname = usePathname();
  return (
    <nav className="w-full" aria-label="Navigazione principale">
      <div className="mx-auto flex max-w-[120rem] flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
        {NAV_ITEMS.map(({ href, label }) => (
          <Link key={href} href={href} className={navLinkClass(href, pathname)}>
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
