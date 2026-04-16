"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

export interface KPICardProps {
  label: string;
  value?: string | number | null;
  delta?: { value: number; label?: string };
  /** 'auto' derives from delta sign */
  variant?: "bull" | "bear" | "neutral" | "warn" | "auto";
  icon?: LucideIcon;
  loading?: boolean;
  href?: string;
  tooltip?: string;
  placeholder?: boolean;
  placeholderNote?: string;
  className?: string;
}

function resolveVariant(
  variant: KPICardProps["variant"],
  delta?: { value: number },
): "bull" | "bear" | "neutral" | "warn" | "default" {
  if (!variant || variant === "auto") {
    if (!delta) return "default";
    return delta.value > 0 ? "bull" : delta.value < 0 ? "bear" : "default";
  }
  return variant;
}

function formatValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

function formatDelta(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

const VARIANT_CLASSES = {
  bull:    { glow: "glow-bull",    text: "text-bull",    icon: "text-bull" },
  bear:    { glow: "glow-bear",    text: "text-bear",    icon: "text-bear" },
  neutral: { glow: "glow-accent",  text: "text-neutral", icon: "text-neutral" },
  warn:    { glow: "",             text: "text-warn",    icon: "text-warn" },
  default: { glow: "",             text: "text-fg",      icon: "text-fg-2" },
};

export function KPICard({
  label,
  value,
  delta,
  variant = "auto",
  icon: Icon,
  loading = false,
  href,
  tooltip,
  placeholder = false,
  placeholderNote,
  className,
}: KPICardProps) {
  const resolved = resolveVariant(variant, delta);
  const { glow, text, icon: iconCls } = VARIANT_CLASSES[resolved];
  const hasData = !placeholder && value !== null && value !== undefined;

  const ariaLabel = [label, formatValue(value), delta ? formatDelta(delta.value) : ""]
    .filter(Boolean).join(", ");

  if (loading) {
    return (
      <div className={cn("glass rounded-xl p-5 animate-slide-up", className)}>
        <div className="skeleton-shimmer mb-3 h-3 w-20 rounded" />
        <div className="skeleton-shimmer h-8 w-28 rounded" />
        <div className="skeleton-shimmer mt-2 h-3 w-16 rounded" />
      </div>
    );
  }

  const content = (
    <div
      className={cn(
        "glass glass-hover rounded-xl p-5 transition-all duration-200 animate-slide-up",
        hasData && glow,
        href && "cursor-pointer",
        className,
      )}
      role="article"
      aria-label={ariaLabel}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="kpi-label">{label}</span>
        <div className="flex items-center gap-1">
          {tooltip && (
            <span className="text-fg-faint" title={tooltip} aria-label={`Info: ${tooltip}`}>
              <Info className="h-3 w-3" aria-hidden />
            </span>
          )}
          {Icon && (
            <Icon className={cn("h-4 w-4", hasData ? iconCls : "text-fg-faint")} aria-hidden />
          )}
        </div>
      </div>

      {/* Value */}
      {placeholder ? (
        <div>
          <p className={cn("kpi-value text-fg-faint")}>—</p>
          {placeholderNote && (
            <p className="mt-2 text-[10px] text-fg-faint italic leading-tight">{placeholderNote}</p>
          )}
        </div>
      ) : (
        <div>
          <p className={cn("kpi-value", hasData ? text : "text-fg-faint")}>
            {formatValue(value)}
          </p>
          {delta && (
            <p className={cn(
              "mt-1 font-mono text-xs tabular-nums",
              delta.value > 0 ? "text-bull" : delta.value < 0 ? "text-bear" : "text-fg-2",
            )}>
              {delta.value > 0 ? "↑" : "↓"} {Math.abs(delta.value).toFixed(1)}%
              {delta.label && <span className="ml-1 text-fg-faint">{delta.label}</span>}
            </p>
          )}
        </div>
      )}
    </div>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded-xl"
        tabIndex={0}
      >
        {content}
      </Link>
    );
  }
  return content;
}
