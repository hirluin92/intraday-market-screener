"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Info } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface KPICardProps {
  label: string;
  value?: string | number | null;
  delta?: { value: number; label?: string };
  /** 'auto' derives bull/bear from delta.value sign */
  variant?: "bull" | "bear" | "neutral" | "warn" | "auto";
  icon?: LucideIcon;
  loading?: boolean;
  href?: string;
  tooltip?: string;
  /** If true, shows a "TODO backend" placeholder instead of value */
  placeholder?: boolean;
  placeholderNote?: string;
  className?: string;
}

const VARIANT_STYLES = {
  bull:    { border: "border-bull/25",    text: "text-bull",    bg: "bg-bull/5"    },
  bear:    { border: "border-bear/25",    text: "text-bear",    bg: "bg-bear/5"    },
  neutral: { border: "border-neutral/25", text: "text-neutral", bg: "bg-neutral/5" },
  warn:    { border: "border-warn/25",    text: "text-warn",    bg: "bg-warn/5"    },
  default: { border: "border-line",       text: "text-fg",      bg: ""             },
};

function resolveVariant(
  variant: KPICardProps["variant"],
  delta?: { value: number },
): keyof typeof VARIANT_STYLES {
  if (!variant || variant === "auto") {
    if (!delta) return "default";
    return delta.value > 0 ? "bull" : delta.value < 0 ? "bear" : "default";
  }
  return variant as keyof typeof VARIANT_STYLES;
}

function formatValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

function formatDelta(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

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
  const resolvedVariant = resolveVariant(variant, delta);
  const styles = VARIANT_STYLES[resolvedVariant] ?? VARIANT_STYLES.default;

  const ariaLabel = [
    label,
    value != null ? formatValue(value) : "",
    delta ? `${formatDelta(delta.value)}${delta.label ? ` ${delta.label}` : ""}` : "",
  ]
    .filter(Boolean)
    .join(", ");

  if (loading) {
    return (
      <div
        className={cn(
          "rounded-lg border border-line bg-surface p-4",
          className,
        )}
        aria-busy="true"
        aria-label={`${label} — caricamento`}
      >
        <Skeleton className="mb-3 h-3 w-20" />
        <Skeleton className="h-8 w-24" />
        <Skeleton className="mt-2 h-3 w-16" />
      </div>
    );
  }

  const content = (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        styles.border,
        styles.bg,
        "bg-surface",
        href && "cursor-pointer hover:border-line-hi hover:bg-surface-2",
        placeholder && "opacity-60",
        className,
      )}
      role="article"
      aria-label={ariaLabel}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-fg-2">{label}</span>
        <div className="flex items-center gap-1">
          {tooltip && (
            <span
              className="text-fg-3"
              title={tooltip}
              aria-label={`Info: ${tooltip}`}
            >
              <Info className="h-3 w-3" aria-hidden />
            </span>
          )}
          {Icon && (
            <Icon className={cn("h-4 w-4", styles.text)} aria-hidden />
          )}
        </div>
      </div>

      {/* Value */}
      {placeholder ? (
        <div className="mt-2">
          <p className="font-mono text-2xl font-bold tabular-nums text-fg-3">—</p>
          {placeholderNote && (
            <p className="mt-1 text-[10px] text-fg-3 leading-tight">{placeholderNote}</p>
          )}
        </div>
      ) : (
        <div className="mt-2">
          <p
            className={cn(
              "font-mono text-2xl font-bold tabular-nums",
              resolvedVariant !== "default" ? styles.text : "text-fg",
            )}
          >
            {formatValue(value)}
          </p>
          {delta && (
            <p
              className={cn(
                "mt-1 font-mono text-xs tabular-nums",
                delta.value > 0 ? "text-bull" : delta.value < 0 ? "text-bear" : "text-fg-2",
              )}
            >
              {formatDelta(delta.value)}
              {delta.label && (
                <span className="ml-1 text-fg-3">{delta.label}</span>
              )}
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
        className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50 rounded-lg"
        tabIndex={0}
      >
        {content}
      </Link>
    );
  }

  return content;
}
