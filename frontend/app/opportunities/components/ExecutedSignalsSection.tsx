"use client";

import type { ExecutedSignalRow } from "@/lib/api";

interface ExecutedSignalsSectionProps {
  signals: ExecutedSignalRow[];
  expanded: boolean;
  onToggleExpanded: () => void;
  statusFilter: "all" | "open" | "skipped" | "cancelled";
  onStatusFilterChange: (v: "all" | "open" | "skipped" | "cancelled") => void;
}

export function ExecutedSignalsSection({
  signals,
  expanded,
  onToggleExpanded,
  statusFilter,
  onStatusFilterChange,
}: ExecutedSignalsSectionProps) {
  if (signals.length === 0) return null;

  const openCount = signals.filter((s) => s.tws_status === "Filled").length;
  const skippedCount = signals.filter((s) => s.tws_status === "skipped").length;
  const cancelledCount = signals.filter(
    (s) => s.tws_status === "Cancelled" || !!s.error,
  ).length;

  const filteredSignals = [...signals]
    .sort((a, b) => {
      const rank = (s: ExecutedSignalRow) =>
        s.tws_status === "Filled" ? 0 : s.tws_status === "Cancelled" ? 1 : 2;
      return rank(a) - rank(b);
    })
    .filter((s) => {
      if (statusFilter === "open") return s.tws_status === "Filled";
      if (statusFilter === "skipped") return s.tws_status === "skipped";
      if (statusFilter === "cancelled")
        return s.tws_status === "Cancelled" || !!s.error;
      return true;
    });

  return (
    <section aria-label="Trade eseguite dal sistema" className="mt-2">
      <div className="mb-2 flex items-center gap-3">
        <button
          onClick={onToggleExpanded}
          className="flex items-center gap-2 font-[family-name:var(--font-trader-sans)] text-sm font-bold uppercase tracking-wide text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <span
            className={`transition-transform duration-200 ${expanded ? "rotate-90" : "rotate-0"}`}
          >
            ▶
          </span>
          ⚡ Segnali sistema
          <span className="ml-1 rounded-full bg-[var(--bg-surface-2)] px-2 py-0.5 text-[10px] font-normal text-[var(--text-muted)]">
            {openCount > 0 && (
              <span className="text-emerald-400">{openCount} aperte</span>
            )}
            {openCount > 0 && skippedCount + cancelledCount > 0 && (
              <span className="mx-1 opacity-40">·</span>
            )}
            {skippedCount > 0 && (
              <span className="text-amber-400">{skippedCount} skip</span>
            )}
            {skippedCount > 0 && cancelledCount > 0 && (
              <span className="mx-1 opacity-40">·</span>
            )}
            {cancelledCount > 0 && (
              <span className="text-[var(--accent-bear)]">{cancelledCount} canc.</span>
            )}
          </span>
        </button>

        <select
          value={statusFilter}
          onChange={(e) =>
            onStatusFilterChange(
              e.target.value as "all" | "open" | "skipped" | "cancelled",
            )
          }
          className="ml-auto rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1 text-xs text-[var(--text-secondary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-bull)]/40"
        >
          <option value="open">Aperte ({openCount})</option>
          <option value="all">Tutte ({signals.length})</option>
          <option value="skipped">Skipped ({skippedCount})</option>
          <option value="cancelled">Cancellate ({cancelledCount})</option>
        </select>
      </div>

      {expanded && (
        <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]">
          {filteredSignals.length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-[var(--text-muted)]">
              {statusFilter === "open"
                ? "Nessuna posizione aperta al momento."
                : "Nessun segnale per il filtro selezionato."}
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--text-muted)]">
                  <th className="px-3 py-2 text-left font-medium">Ora</th>
                  <th className="px-3 py-2 text-left font-medium">Simbolo</th>
                  <th className="px-3 py-2 text-left font-medium">Dir.</th>
                  <th className="px-3 py-2 text-left font-medium">Pattern</th>
                  <th className="px-3 py-2 text-right font-medium">Entry</th>
                  <th className="px-3 py-2 text-right font-medium">SL</th>
                  <th className="px-3 py-2 text-right font-medium">TP1</th>
                  <th className="px-3 py-2 text-right font-medium">TP2</th>
                  <th className="px-3 py-2 text-right font-medium">Qty</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredSignals.map((sig) => {
                  const isBull = sig.direction === "bullish";
                  const hasError = !!sig.error;
                  const isOpen = sig.tws_status === "Filled";
                  return (
                    <tr
                      key={sig.id}
                      className={`border-b border-[var(--border)]/50 transition-colors hover:bg-[var(--bg-surface-2)] ${hasError ? "opacity-60" : ""} ${isOpen ? "bg-emerald-500/5" : ""}`}
                    >
                      <td className="px-3 py-2 font-[family-name:var(--font-trader-mono)] text-[var(--text-muted)]">
                        {new Date(sig.executed_at).toLocaleTimeString("it-IT", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        <span className="ml-1 text-[10px] text-[var(--text-muted)]/60">
                          {new Date(sig.executed_at).toLocaleDateString("it-IT", {
                            day: "2-digit",
                            month: "2-digit",
                          })}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-[family-name:var(--font-trader-sans)] font-bold text-[var(--text-primary)]">
                        {sig.symbol}
                        <span className="ml-1 text-[10px] text-[var(--text-muted)]">
                          {sig.timeframe}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            isBull
                              ? "bg-[var(--accent-bull)]/15 text-[var(--accent-bull)]"
                              : "bg-[var(--accent-bear)]/15 text-[var(--accent-bear)]"
                          }`}
                        >
                          {isBull ? "▲ LONG" : "▼ SHORT"}
                        </span>
                      </td>
                      <td className="max-w-[120px] truncate px-3 py-2 text-[var(--text-secondary)]">
                        {sig.pattern_name.replace(/_/g, " ")}
                      </td>
                      <td className="px-3 py-2 text-right font-[family-name:var(--font-trader-mono)] text-[var(--text-primary)]">
                        {sig.entry_price.toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right font-[family-name:var(--font-trader-mono)] text-[var(--accent-bear)]">
                        {sig.stop_price.toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right font-[family-name:var(--font-trader-mono)] text-[var(--accent-bull)]">
                        {sig.take_profit_1?.toFixed(2) ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-[family-name:var(--font-trader-mono)] text-emerald-400">
                        {sig.take_profit_2?.toFixed(2) ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-[family-name:var(--font-trader-mono)] text-[var(--text-secondary)]">
                        {sig.quantity_tp1 ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                            isOpen
                              ? "bg-emerald-500/15 text-emerald-300"
                              : sig.tws_status === "Cancelled" || hasError
                                ? "bg-[var(--accent-bear)]/15 text-[var(--accent-bear)]"
                                : "bg-amber-500/15 text-amber-300"
                          }`}
                        >
                          {hasError ? "Errore" : isOpen ? "Aperta" : sig.tws_status}
                        </span>
                        {sig.error && (
                          <span
                            className="ml-1 text-[10px] text-[var(--accent-bear)]"
                            title={sig.error}
                          >
                            ⚠
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
