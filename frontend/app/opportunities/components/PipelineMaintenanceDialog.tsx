"use client";

import type { usePipelineControl } from "@/hooks/usePipelineControl";

type PipelineControl = ReturnType<typeof usePipelineControl>;

interface PipelineMaintenanceDialogProps {
  pipeline: PipelineControl;
}

/**
 * Pipeline maintenance form.
 * 3A: keeps the same <details> element visual (no visual change).
 * 3B: will become a proper shadcn Dialog triggered from the header "Strumenti" button.
 */
export function PipelineMaintenanceDialog({
  pipeline,
}: PipelineMaintenanceDialogProps) {
  return (
    <details className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]/60 p-4 text-sm text-[var(--text-secondary)]">
      <summary className="cursor-pointer font-medium text-[var(--text-primary)]">
        Manutenzione pipeline
      </summary>
      <p className="mt-2 text-xs">
        Esegue ingest → features → context → patterns (POST /pipeline/refresh). Uso avanzato.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          Provider
          <select
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
            value={pipeline.provider}
            onChange={(e) =>
              pipeline.setProvider(e.target.value as "binance" | "yahoo_finance")
            }
          >
            <option value="binance">Binance</option>
            <option value="yahoo_finance">Yahoo Finance</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Venue (opz.)
          <input
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
            value={pipeline.exchangeOverride}
            onChange={(e) => pipeline.setExchangeOverride(e.target.value)}
            placeholder="default"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Simbolo
          <input
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
            value={pipeline.symbol}
            onChange={(e) => pipeline.setSymbol(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Timeframe
          <select
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
            value={pipeline.timeframe}
            onChange={(e) => pipeline.setTimeframe(e.target.value)}
          >
            {pipeline.timeframeOptions.map((tf) => (
              <option key={tf || "all"} value={tf}>
                {tf === "" ? "—" : tf}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Limite ingest
          <input
            type="number"
            min={1}
            className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
            value={pipeline.ingestLimit}
            onChange={(e) => pipeline.setIngestLimit(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Limite extract
          <input
            type="number"
            min={1}
            className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
            value={pipeline.extractLimit}
            onChange={(e) => pipeline.setExtractLimit(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Lookback
          <input
            type="number"
            min={3}
            className="w-20 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
            value={pipeline.lookback}
            onChange={(e) => pipeline.setLookback(Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          disabled={pipeline.isRefreshing}
          onClick={() => void pipeline.refresh()}
          className="rounded-lg bg-[var(--text-primary)] px-4 py-2 text-xs font-semibold text-[var(--bg-base)] disabled:opacity-50"
        >
          {pipeline.isRefreshing ? "…" : "Esegui pipeline"}
        </button>
      </div>
      {pipeline.message && (
        <p className="mt-2 text-xs text-[var(--accent-bull)]">{pipeline.message}</p>
      )}
      {pipeline.error && (
        <p className="mt-2 text-xs text-[var(--accent-bear)]">{pipeline.error}</p>
      )}
    </details>
  );
}
