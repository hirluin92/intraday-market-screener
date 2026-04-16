"use client";

import { useIBKRStatus } from "@/hooks/useIBKRStatus";
import { cn } from "@/lib/utils";

interface IBKRStatusPillProps {
  /** "pill" = compact rounded badge (sidebar/topbar); "banner" = text only */
  variant?: "pill" | "inline";
  className?: string;
}

export function IBKRStatusPill({ variant = "pill", className }: IBKRStatusPillProps) {
  const { connectionStatus, data, isLoading } = useIBKRStatus();

  if (isLoading) {
    return (
      <div className={cn("skeleton h-6 w-28 rounded-full", className)} />
    );
  }

  if (connectionStatus === "disabled") return null;

  const config = {
    connected: {
      dot: "bg-bull animate-pulse-live",
      text: "text-bull",
      border: "border-bull/30",
      label: data?.paper_trading ? "IBKR PAPER" : "IBKR LIVE",
    },
    disconnected: {
      dot: "bg-warn",
      text: "text-warn",
      border: "border-warn/30",
      label: "IBKR disconnesso",
    },
    error: {
      dot: "bg-bear",
      text: "text-bear",
      border: "border-bear/30",
      label: "IBKR errore",
    },
    unknown: {
      dot: "bg-fg-3",
      text: "text-fg-2",
      border: "border-line",
      label: "IBKR —",
    },
  }[connectionStatus] ?? {
    dot: "bg-fg-3",
    text: "text-fg-2",
    border: "border-line",
    label: "IBKR —",
  };

  if (variant === "inline") {
    return (
      <span className={cn("flex items-center gap-1.5", config.text, className)}>
        <span className={cn("h-2 w-2 shrink-0 rounded-full", config.dot)} aria-hidden />
        <span className="font-mono text-xs">{config.label}</span>
        {connectionStatus === "connected" && data?.auto_execute && (
          <span className="text-xs text-fg-2">· auto-exec ON</span>
        )}
      </span>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1",
        config.border,
        "bg-surface-2",
        className,
      )}
      title={
        connectionStatus === "error"
          ? "IBKR non raggiungibile"
          : connectionStatus === "connected"
            ? `Account: ${data?.account_id ?? "—"}`
            : undefined
      }
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", config.dot)} aria-hidden />
      <span className={cn("font-mono text-xs font-medium", config.text)}>{config.label}</span>
      {connectionStatus === "connected" && data?.auto_execute && (
        <span className="text-[10px] text-bull/70">AUTO</span>
      )}
    </div>
  );
}
