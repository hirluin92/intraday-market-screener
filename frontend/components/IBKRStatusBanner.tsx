"use client";

import { useIBKRStatus } from "@/hooks/useIBKRStatus";

/**
 * Sticky top banner shown only when IBKR is disconnected or in error.
 * Uses the unified useIBKRStatus hook (TanStack Query, 30s poll).
 * TanStack Query deduplicates: IBKRStatusPill in Sidebar hits the same
 * cache — no double network requests.
 */
export function IBKRStatusBanner() {
  const { connectionStatus, data, lastUpdated } = useIBKRStatus();

  // Silent states: connected, disabled (IBKR not configured), or loading
  if (
    connectionStatus === "connected" ||
    connectionStatus === "disabled" ||
    connectionStatus === "unknown"
  ) {
    return null;
  }

  const isError = connectionStatus === "error";
  const bgClass = isError ? "bg-bear" : "bg-warn";
  const icon = isError ? "⚠" : "⚡";
  const title = isError ? "Errore connessione IBKR" : "IBKR disconnesso";
  const message =
    data?.message ??
    "Il sistema non riesce a comunicare con TWS. Verificare che TWS sia attivo e autenticato.";

  return (
    <div
      className={`${bgClass} text-canvas sticky top-0 z-50 flex items-center justify-between px-4 py-2 shadow-md`}
      role="alert"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <span className="text-xl" aria-hidden="true">
          {icon}
        </span>
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <div className="text-xs opacity-90">{message}</div>
        </div>
      </div>
      {lastUpdated && (
        <div className="ml-4 shrink-0 text-xs opacity-75">
          Ultimo contatto:{" "}
          {lastUpdated.toLocaleTimeString("it-IT")}
        </div>
      )}
    </div>
  );
}
