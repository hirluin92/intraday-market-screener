"use client";

import { getTodayMaxExecute, getWeekSumLast7Days } from "@/lib/traderExecuteStats";

const REFRESH_SEC = 60;

interface Props {
  isLoading: boolean;
  error: string | null;
  hasRows: boolean;
  emptyExecute: boolean;
  autoRefresh: boolean;
  secondsToRefresh: number;
}

export function OpportunitiesStateBlocks({
  isLoading,
  error,
  hasRows,
  emptyExecute,
  autoRefresh,
  secondsToRefresh,
}: Props) {
  return (
    <>
      {isLoading && (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]" role="status">
          Caricamento opportunità…
        </div>
      )}

      {!isLoading && error && (
        <div className="rounded-xl border border-[var(--accent-bear)]/40 bg-[var(--accent-bear)]/10 p-4 text-sm text-[var(--accent-bear)]" role="alert">
          <strong className="font-medium">Errore caricamento.</strong>
          <pre className="mt-2 whitespace-pre-wrap font-[family-name:var(--font-trader-mono)] text-xs opacity-90">{error}</pre>
        </div>
      )}

      {!isLoading && !error && !hasRows && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-8 text-center text-[var(--text-secondary)]">
          Nessuna opportunità dal server. Verifica la pipeline o riprova tra poco.
        </div>
      )}

      {emptyExecute && (
        <div className="animate-[slide-in_0.4s_ease-out] rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)]/90 p-8 text-center backdrop-blur-sm">
          <p className="font-[family-name:var(--font-trader-sans)] text-lg font-bold text-[var(--text-primary)]">📡 In ascolto…</p>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Nessun segnale operativo con i filtri attuali. Il refresh automatico è ogni {REFRESH_SEC} secondi.
          </p>
          <p className="mt-4 font-[family-name:var(--font-trader-mono)] text-sm text-[var(--accent-neutral)]">
            Prossimo refresh:{" "}
            <span suppressHydrationWarning>{autoRefresh ? `${secondsToRefresh}s` : "—"}</span>
          </p>
          <p className="mt-4 text-xs text-[var(--text-muted)]">
            Oggi (max execute in lista): {getTodayMaxExecute()} · Ultimi 7 giorni: {getWeekSumLast7Days()}
          </p>
        </div>
      )}
    </>
  );
}
