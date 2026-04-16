"use client";

import {
  Activity,
  CheckCircle2,
  Radar,
  RefreshCw,
  XCircle,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import type { ActivityItem, ActivityItemType } from "@/lib/schemas/dashboard";
import { cn } from "@/lib/utils";

// ── Relative time ─────────────────────────────────────────────────────────────

const rtf = new Intl.RelativeTimeFormat("it", { numeric: "auto", style: "short" });

function relativeTime(iso: string): string {
  try {
    const diff = (new Date(iso).getTime() - Date.now()) / 1000; // negative = past
    const abs = Math.abs(diff);
    if (abs < 60) return rtf.format(Math.round(diff), "second");
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    return rtf.format(Math.round(diff / 86400), "day");
  } catch {
    return iso;
  }
}

// ── Type → icon ───────────────────────────────────────────────────────────────

const TYPE_ICON: Record<ActivityItemType, React.ElementType> = {
  signal_executed: CheckCircle2,
  signal_skipped:  Activity,
  signal_cancelled: XCircle,
  pipeline_run:    RefreshCw,
  trade_closed:    CheckCircle2,
  ibkr_event:      Radar,
};

const VARIANT_DOT: Record<NonNullable<ActivityItem["variant"]>, string> = {
  bull:    "bg-bull",
  bear:    "bg-bear",
  neutral: "bg-neutral",
  warn:    "bg-warn",
};

const VARIANT_ICON: Record<NonNullable<ActivityItem["variant"]>, string> = {
  bull:    "text-bull",
  bear:    "text-bear",
  neutral: "text-neutral",
  warn:    "text-warn",
};

// ── Components ────────────────────────────────────────────────────────────────

function FeedSkeleton({ count = 5 }: { count?: number }) {
  return (
    <ul className="space-y-3" aria-label="Caricamento attività…">
      {Array.from({ length: count }).map((_, i) => (
        <li key={i} className="flex items-start gap-3">
          <Skeleton className="mt-0.5 h-4 w-4 shrink-0 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
          <Skeleton className="h-3 w-12 shrink-0" />
        </li>
      ))}
    </ul>
  );
}

function EmptyFeed() {
  return (
    <div className="py-8 text-center">
      <Activity className="mx-auto mb-3 h-8 w-8 text-fg-3" aria-hidden />
      <p className="text-sm text-fg-2">Nessuna attività recente</p>
      <p className="mt-1 text-xs text-fg-3">
        Le esecuzioni e le notifiche sistema appariranno qui.
      </p>
    </div>
  );
}

function FeedItem({ item }: { item: ActivityItem }) {
  const Icon = TYPE_ICON[item.type] ?? Activity;
  const iconCls = item.variant ? VARIANT_ICON[item.variant] : "text-fg-2";
  const dotCls = item.variant ? VARIANT_DOT[item.variant] : "bg-fg-3";

  const inner = (
    <li
      className={cn(
        "flex items-start gap-3 rounded-md px-2 py-2 transition-colors",
        item.href && "hover:bg-surface-2 cursor-pointer",
      )}
    >
      {/* Icon + dot */}
      <div className="relative mt-0.5 shrink-0">
        <Icon className={cn("h-4 w-4", iconCls)} aria-hidden />
        <span
          className={cn(
            "absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full",
            dotCls,
          )}
          aria-hidden
        />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{item.title}</p>
        {item.description && (
          <p className="truncate text-xs text-fg-2">{item.description}</p>
        )}
      </div>

      {/* Relative time */}
      <time
        dateTime={item.timestamp}
        className="shrink-0 font-mono text-[10px] text-fg-3 tabular-nums"
        title={new Date(item.timestamp).toLocaleString("it-IT")}
      >
        {relativeTime(item.timestamp)}
      </time>
    </li>
  );

  if (item.href) {
    // Wrap in an anchor-like container using the li as trigger
    return (
      <a
        href={item.href}
        className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50 rounded-md"
      >
        {inner}
      </a>
    );
  }

  return inner;
}

// ── Public component ──────────────────────────────────────────────────────────

export interface ActivityFeedProps {
  items: ActivityItem[];
  loading?: boolean;
  maxItems?: number;
  className?: string;
}

export function ActivityFeed({
  items,
  loading = false,
  maxItems = 10,
  className,
}: ActivityFeedProps) {
  if (loading) return <FeedSkeleton count={5} />;

  const visible = items.slice(0, maxItems);
  if (visible.length === 0) return <EmptyFeed />;

  return (
    <ul
      role="log"
      aria-live="polite"
      aria-label="Feed attività recenti"
      className={cn("space-y-0.5", className)}
    >
      {visible.map((item) => (
        <FeedItem key={item.id} item={item} />
      ))}
    </ul>
  );
}
