"use client";

import { useIBKRStatus } from "@/hooks/useIBKRStatus";
import { cn } from "@/lib/utils";

interface IBKRStatusPillProps {
  variant?: "pill" | "inline";
  className?: string;
}

export function IBKRStatusPill({ variant = "pill", className }: IBKRStatusPillProps) {
  const { connectionStatus, data, isLoading } = useIBKRStatus();

  if (isLoading) {
    return <div className={cn("skeleton-shimmer h-6 w-28 rounded-full", className)} />;
  }

  if (connectionStatus === "disabled") return null;

  const config = {
    connected:    { dot: "bg-bull animate-pulse-live", text: "text-bull",  label: data?.paper_trading ? "IBKR PAPER" : "IBKR LIVE" },
    disconnected: { dot: "bg-warn",    text: "text-warn",  label: "IBKR disconnesso" },
    error:        { dot: "bg-bear",    text: "text-bear",  label: "IBKR errore" },
    unknown:      { dot: "bg-fg-3",    text: "text-fg-2",  label: "IBKR —" },
  }[connectionStatus] ?? { dot: "bg-fg-3", text: "text-fg-2", label: "IBKR —" };

  if (variant === "inline") {
    return (
      <span className={cn("flex items-center gap-1.5", config.text, className)}>
        <span className={cn("h-2 w-2 shrink-0 rounded-full", config.dot)} aria-hidden />
        <span className="font-mono text-xs">{config.label}</span>
        {connectionStatus === "connected" && data?.auto_execute && (
          <span className="text-xs text-fg-2">· auto ON</span>
        )}
      </span>
    );
  }

  const isConnected = connectionStatus === "connected";
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full px-3 py-1",
        "border",
        isConnected
          ? "border-bull/25 bg-bull/8 text-bull"
          : connectionStatus === "error"
            ? "border-bear/25 bg-bear/8 text-bear"
            : connectionStatus === "disconnected"
              ? "border-warn/25 bg-warn/8 text-warn"
              : "border-line bg-elevated text-fg-2",
        className,
      )}
      style={isConnected ? { boxShadow: "0 0 12px hsla(168 100% 45% / 0.2)" } : undefined}
      title={connectionStatus === "error" ? "IBKR non raggiungibile" : undefined}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", config.dot)} aria-hidden />
      <span className="font-mono text-xs font-medium">{config.label}</span>
      {isConnected && data?.auto_execute && (
        <span className="text-[10px] text-bull/70">AUTO</span>
      )}
    </div>
  );
}
