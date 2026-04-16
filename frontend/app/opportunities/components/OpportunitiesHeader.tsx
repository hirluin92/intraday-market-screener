"use client";

import type { UseIBKRStatusResult } from "@/hooks/useIBKRStatus";
import { RegimeBadge } from "./RegimeBadge";

const CURRENCY = "€";

interface OpportunitiesHeaderProps {
  ibkr: UseIBKRStatusResult;
  regime?: string;
  isLoading: boolean;
  isFetching?: boolean;
  autoRefresh: boolean;
  onAutoRefreshChange: (v: boolean) => void;
  secondsToRefresh: number;
  lastUpdate: Date | null;
  onRefresh: () => void;
  totalExecute: number;
  timeLabelReady: boolean;
  onPipelineOpen: () => void;
}

export function OpportunitiesHeader({
  ibkr,
  regime,
  isLoading,
  autoRefresh,
  onAutoRefreshChange,
  secondsToRefresh,
  lastUpdate,
  onRefresh,
  totalExecute,
  timeLabelReady,
}: OpportunitiesHeaderProps) {
  const ibkrStatus = ibkr.data;
  const ibkrFetchFailed = !!ibkr.error && !ibkr.isLoading;

  return (
    <header className="sticky top-0 z-30 -mx-4 border-b border-[var(--border)] bg-[var(--bg-base)]/95 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="inline-flex items-center gap-2 font-[family-name:var(--font-trader-sans)] font-semibold text-[var(--text-primary)]">
            <span
              className="relative flex h-2.5 w-2.5 items-center justify-center"
              aria-hidden
            >
              <span className="absolute h-2.5 w-2.5 animate-pulse-live rounded-full bg-[var(--accent-bull)]" />
            </span>
            LIVE
          </span>
          <span className="text-[var(--text-muted)]">•</span>
          <span className="text-[var(--text-secondary)]" suppressHydrationWarning>
            Ultimo refresh:{" "}
            {timeLabelReady && lastUpdate != null
              ? lastUpdate.toLocaleTimeString("it-IT")
              : "—"}
          </span>
          <span className="text-[var(--text-muted)]">•</span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1 text-xs font-semibold text-[var(--text-primary)] hover:border-[var(--border-active)] disabled:opacity-50"
          >
            ↻ Aggiorna
          </button>
          <label className="ml-1 flex cursor-pointer items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => onAutoRefreshChange(e.target.checked)}
              className="rounded border-[var(--border)] bg-[var(--bg-surface-2)]"
            />
            Auto 60s
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {ibkrFetchFailed && (
            <div
              className="flex items-center gap-1.5 rounded-full border border-amber-700/60 bg-amber-950/40 px-3 py-1 text-xs text-amber-300"
              title="Il servizio IBKR non ha risposto. Dati di connessione e auto-exec non disponibili."
            >
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              ⚠ IBKR non risponde
            </div>
          )}
          {ibkrStatus?.enabled === true && (
            <>
              <div
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                  ibkrStatus.authenticated
                    ? "border-emerald-700/80 bg-emerald-950/40 text-emerald-200"
                    : "border-red-800/80 bg-red-950/40 text-red-200"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    ibkrStatus.authenticated
                      ? "animate-pulse bg-emerald-400"
                      : "bg-red-400"
                  }`}
                />
                IBKR {ibkrStatus.paper_trading ? "PAPER" : "LIVE"} ·{" "}
                {ibkrStatus.authenticated ? "connesso" : "disconnesso"}
              </div>
              {ibkrStatus.authenticated && (
                <span className="text-xs text-[var(--text-muted)]">
                  Auto-exec:{" "}
                  <span
                    className={
                      ibkrStatus.auto_execute
                        ? "font-semibold text-emerald-300"
                        : "text-[var(--text-secondary)]"
                    }
                  >
                    {ibkrStatus.auto_execute ? "ON" : "OFF"}
                  </span>
                </span>
              )}
            </>
          )}
          <RegimeBadge regime={regime} />
          <span
            className={`inline-flex items-center rounded-lg border px-3 py-1.5 font-[family-name:var(--font-trader-mono)] text-xs font-bold ${
              totalExecute > 0
                ? "border-[var(--accent-bull)] bg-[var(--accent-bull)]/10 text-[var(--accent-bull)] shadow-[var(--glow-bull)]"
                : "border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]"
            }`}
            aria-label={`Segnali esegui: ${totalExecute}`}
          >
            {totalExecute} segnali ESEGUI
          </span>
        </div>
      </div>
      <p
        className="mt-2 font-[family-name:var(--font-trader-mono)] text-xs text-[var(--text-muted)]"
        aria-live="polite"
        aria-atomic="true"
      >
        Prossimo refresh tra{" "}
        <span suppressHydrationWarning>
          {autoRefresh ? `${secondsToRefresh}s` : "—"}
        </span>
      </p>
    </header>
  );
}
