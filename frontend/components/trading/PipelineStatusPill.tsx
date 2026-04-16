"use client";

import { RefreshCw } from "lucide-react";

import { cn } from "@/lib/utils";

interface PipelineStatusPillProps {
  /** ISO timestamp of last run (passed down from opportunities query cache). */
  lastRunAt?: string | null;
  className?: string;
}

/**
 * Stub component — displays last pipeline run timestamp.
 * Will be enriched in Step 3 (Home dashboard) with live status from
 * the scheduler health endpoint when available.
 */
export function PipelineStatusPill({ lastRunAt, className }: PipelineStatusPillProps) {
  const label = lastRunAt
    ? new Date(lastRunAt).toLocaleTimeString("it-IT", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full border border-line bg-surface-2 px-3 py-1",
        className,
      )}
    >
      <RefreshCw className="h-3 w-3 shrink-0 text-fg-2" aria-hidden />
      <span className="font-mono text-xs text-fg-2">
        Pipeline <span className="text-fg">{label}</span>
      </span>
    </div>
  );
}
