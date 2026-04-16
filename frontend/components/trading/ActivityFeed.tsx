"use client";

import { useMemo } from "react";
import {
  Activity,
  CheckCircle2,
  Radar,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";

import type { ActivityItem, ActivityItemType } from "@/lib/schemas/dashboard";
import { cn } from "@/lib/utils";

// ── Relative time ─────────────────────────────────────────────────────────────

const rtf = new Intl.RelativeTimeFormat("it", { numeric: "auto", style: "short" });

function relativeTime(iso: string): string {
  try {
    const diff = (new Date(iso).getTime() - Date.now()) / 1000;
    const abs = Math.abs(diff);
    if (abs < 60)    return rtf.format(Math.round(diff), "second");
    if (abs < 3600)  return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    return rtf.format(Math.round(diff / 86400), "day");
  } catch { return iso; }
}

// ── Per-type icon + glow class ────────────────────────────────────────────────

const TYPE_CONFIG: Record<string, {
  Icon: React.ElementType;
  iconCls: string;
  glowCls: string;
  dotCls: string;
}> = {
  signal_executed:  { Icon: CheckCircle2, iconCls: "text-bull",    glowCls: "glow-bull",   dotCls: "bg-bull" },
  signal_generated: { Icon: Radar,        iconCls: "text-accent",  glowCls: "glow-accent", dotCls: "bg-accent" },
  pipeline_run:     { Icon: RefreshCw,    iconCls: "text-info",    glowCls: "glow-info",   dotCls: "bg-info" },
  trade_closed:     { Icon: TrendingUp,   iconCls: "text-bull",    glowCls: "glow-bull",   dotCls: "bg-bull" },
  signal_skipped:   { Icon: Activity,     iconCls: "text-fg-3",    glowCls: "",            dotCls: "bg-fg-3" },
  signal_cancelled: { Icon: XCircle,      iconCls: "text-bear",    glowCls: "glow-bear",   dotCls: "bg-bear" },
  ibkr_event:       { Icon: Activity,     iconCls: "text-fg-2",    glowCls: "",            dotCls: "bg-fg-2" },
};

// ── Grouped skipped items ─────────────────────────────────────────────────────

type GroupedItem =
  | ActivityItem
  | { id: string; isGroup: true; count: number; title: string; timestamp: string };

function groupItems(items: ActivityItem[]): GroupedItem[] {
  const result: GroupedItem[] = [];
  let i = 0;

  while (i < items.length) {
    const item = items[i];
    if (!item) { i++; continue; }

    if (item.type === "signal_skipped") {
      let j = i;
      while (j < items.length && items[j]?.type === "signal_skipped") j++;
      const count = j - i;
      if (count > 2) {
        result.push({
          id: `group-skip-${i}`,
          isGroup: true,
          count,
          title: `${count} segnali skippati`,
          timestamp: item.timestamp,
        });
        i = j;
        continue;
      }
    }
    result.push(item);
    i++;
  }

  return result;
}

// ── Components ────────────────────────────────────────────────────────────────

function GroupedSkipItem({ item }: { item: Extract<GroupedItem, { isGroup: true }> }) {
  return (
    <li className="flex items-center gap-3 rounded-lg px-2 py-1.5 opacity-50">
      <Activity className="h-4 w-4 shrink-0 text-fg-3" aria-hidden />
      <div className="flex-1">
        <p className="text-xs text-fg-2">{item.title}</p>
      </div>
      <time className="shrink-0 font-mono text-[10px] text-fg-3 tabular-nums" dateTime={item.timestamp}>
        {relativeTime(item.timestamp)}
      </time>
    </li>
  );
}

function FeedItem({ item }: { item: ActivityItem }) {
  const config = TYPE_CONFIG[item.type] ?? TYPE_CONFIG.ibkr_event;
  const { Icon, iconCls, glowCls, dotCls } = config;

  const isSkipped = item.type === "signal_skipped";

  const inner = (
    <li
      className={cn(
        "group flex items-start gap-3 rounded-lg px-2 py-2 transition-all duration-150",
        "hover:bg-[var(--glass-bg-hover)] hover:border hover:border-[var(--glass-border-hover)]",
        isSkipped && "opacity-45",
        item.href && "cursor-pointer",
      )}
    >
      {/* Icon with dot */}
      <div className="relative mt-0.5 shrink-0">
        <div className={cn(
          "flex h-7 w-7 items-center justify-center rounded-lg transition-all",
          !isSkipped && glowCls && `bg-[var(--color-${item.variant}-dim,hsla(228_15%_10%/0.5))]`,
        )}>
          <Icon className={cn("h-3.5 w-3.5", iconCls)} aria-hidden />
        </div>
        <span className={cn("absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-canvas", dotCls)} aria-hidden />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{item.title}</p>
        {item.description && (
          <p className="truncate text-xs text-fg-2">{item.description}</p>
        )}
      </div>

      {/* Timestamp */}
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
    return (
      <a
        href={item.href}
        className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded-lg"
      >
        {inner}
      </a>
    );
  }
  return inner;
}

function FeedSkeleton({ count = 5 }: { count?: number }) {
  return (
    <ul aria-label="Caricamento attività…">
      {Array.from({ length: count }).map((_, i) => (
        <li key={i} className="flex items-start gap-3 px-2 py-2">
          <div className="skeleton-shimmer mt-0.5 h-7 w-7 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-1.5">
            <div className="skeleton-shimmer h-3.5 w-32 rounded" />
            <div className="skeleton-shimmer h-3 w-48 rounded" />
          </div>
          <div className="skeleton-shimmer h-3 w-12 shrink-0 rounded" />
        </li>
      ))}
    </ul>
  );
}

function EmptyFeed() {
  return (
    <div className="py-8 text-center">
      <Activity className="mx-auto mb-3 h-7 w-7 text-fg-3" aria-hidden />
      <p className="text-sm text-fg-2">Nessuna attività recente</p>
      <p className="mt-1 text-xs text-fg-faint">
        Le esecuzioni e le notifiche sistema appariranno qui.
      </p>
    </div>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

export interface ActivityFeedProps {
  items: ActivityItem[];
  loading?: boolean;
  maxItems?: number;
  className?: string;
}

export function ActivityFeed({ items, loading = false, maxItems = 10, className }: ActivityFeedProps) {
  const grouped = useMemo(
    () => groupItems(items.slice(0, maxItems * 2)).slice(0, maxItems),
    [items, maxItems],
  );

  if (loading) return <FeedSkeleton count={5} />;
  if (grouped.length === 0) return <EmptyFeed />;

  return (
    <ul
      role="log"
      aria-live="polite"
      aria-label="Feed attività recenti"
      className={cn("space-y-0.5", className)}
    >
      {grouped.map((item) => {
        if ("isGroup" in item && item.isGroup) {
          return <GroupedSkipItem key={item.id} item={item} />;
        }
        return <FeedItem key={item.id} item={item as ActivityItem} />;
      })}
    </ul>
  );
}
