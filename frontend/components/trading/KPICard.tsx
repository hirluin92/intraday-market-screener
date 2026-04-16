"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export interface KPICardProps {
  label: string;
  value?: string | number | null;
  delta?: { value: number; label?: string };
  variant?: "bull" | "bear" | "neutral" | "warn" | "auto";
  icon?: LucideIcon;
  loading?: boolean;
  href?: string;
  tooltip?: string;
  placeholder?: boolean;
  placeholderNote?: string;
  className?: string;
}

// ── Glass inline styles (inline = guaranteed, no CSS cascade override) ─────────

const GLASS_BASE: React.CSSProperties = {
  background: "hsla(0, 0%, 100%, 0.04)",
  backdropFilter: "blur(24px) saturate(160%)",
  WebkitBackdropFilter: "blur(24px) saturate(160%)",
  border: "1px solid hsla(0, 0%, 100%, 0.08)",
  borderRadius: "12px",
  transition: "background 200ms, border-color 200ms, box-shadow 200ms",
};

const GLOW_STYLES: Record<string, React.CSSProperties> = {
  bull:    { borderColor: "hsla(168, 100%, 45%, 0.3)", boxShadow: "0 0 30px -5px hsla(168, 100%, 45%, 0.25)" },
  bear:    { borderColor: "hsla(349, 100%, 65%, 0.3)", boxShadow: "0 0 30px -5px hsla(349, 100%, 65%, 0.25)" },
  neutral: { borderColor: "hsla(265, 80%, 62%, 0.25)", boxShadow: "0 0 30px -5px hsla(265, 80%, 62%, 0.2)" },
  warn:    { borderColor: "hsla(38, 92%, 60%, 0.25)", boxShadow: "none" },
  default: {},
};

const VALUE_COLORS: Record<string, string> = {
  bull:    "#00d4a0",   // --color-bull
  bear:    "#ff4d7a",   // --color-bear
  neutral: "#8b7fd4",   // --color-neutral
  warn:    "#f5a224",   // --color-warn
  default: "#f2f2f2",
};

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
  const hasData = !placeholder && value !== null && value !== undefined;
  const glowStyle = hasData ? (GLOW_STYLES[resolved] ?? {}) : {};
  const valueColor = hasData ? VALUE_COLORS[resolved] : "hsla(0,0%,100%,0.2)";

  const ariaLabel = [label, formatValue(value), delta ? `${delta.value > 0 ? "+" : ""}${delta.value.toFixed(1)}%` : ""]
    .filter(Boolean).join(", ");

  if (loading) {
    return (
      <div
        style={{ ...GLASS_BASE, padding: "20px" }}
        className={cn("animate-slide-up", className)}
      >
        <div className="skeleton mb-3 h-3 w-20 rounded" />
        <div className="skeleton h-8 w-28 rounded" />
        <div className="skeleton mt-2 h-3 w-16 rounded" />
      </div>
    );
  }

  const content = (
    <div
      style={{ ...GLASS_BASE, ...glowStyle, padding: "20px" }}
      className={cn("animate-slide-up", className)}
      role="article"
      aria-label={ariaLabel}
    >
      {/* Label row */}
      <div className="mb-3 flex items-center justify-between">
        <span className="kpi-label">{label}</span>
        <div className="flex items-center gap-1">
          {tooltip && (
            <span title={tooltip} style={{ color: "hsla(0,0%,100%,0.3)" }}>
              <Info className="h-3 w-3" aria-hidden />
            </span>
          )}
          {Icon && <Icon className="h-4 w-4" style={{ color: valueColor, opacity: hasData ? 1 : 0.3 }} aria-hidden />}
        </div>
      </div>

      {/* Value */}
      {placeholder ? (
        <div>
          <p className="kpi-value" style={{ color: "hsla(0,0%,100%,0.2)" }}>—</p>
          {placeholderNote && (
            <p className="mt-2 text-[10px] italic leading-tight" style={{ color: "hsla(0,0%,100%,0.25)" }}>
              {placeholderNote}
            </p>
          )}
        </div>
      ) : (
        <div>
          <p className="kpi-value" style={{ color: valueColor }}>
            {formatValue(value)}
          </p>
          {delta && (
            <p className="mt-1 font-mono text-xs tabular-nums" style={{
              color: delta.value > 0 ? "#00d4a0" : delta.value < 0 ? "#ff4d7a" : "hsla(0,0%,100%,0.4)",
            }}>
              {delta.value > 0 ? "↑" : "↓"} {Math.abs(delta.value).toFixed(1)}%
              {delta.label && <span style={{ color: "hsla(0,0%,100%,0.25)", marginLeft: "4px" }}>{delta.label}</span>}
            </p>
          )}
        </div>
      )}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded-xl" tabIndex={0}>
        {content}
      </Link>
    );
  }
  return content;
}
