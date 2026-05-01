"use client";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { ExecutedSignalRow } from "@/lib/api";

interface ExecutedSignalsSectionProps {
  signals: ExecutedSignalRow[];
  expanded: boolean;
  onToggleExpanded: () => void;
  statusFilter: "all" | "open" | "closed" | "skipped" | "cancelled";
  onStatusFilterChange: (
    v: "all" | "open" | "closed" | "skipped" | "cancelled",
  ) => void;
}

function OutcomeBadge({ outcome }: { outcome: ExecutedSignalRow["close_outcome"] }) {
  if (!outcome) return null;
  const map: Record<string, { label: string; cls: string }> = {
    tp1:     { label: "TP1 ✓",  cls: "border-bull/40 bg-bull/15 text-bull" },
    tp2:     { label: "TP2 ✓",  cls: "border-bull/40 bg-bull/15 text-bull" },
    stop:    { label: "SL ✗",   cls: "border-bear/40 bg-bear/15 text-bear" },
    timeout: { label: "Timeout", cls: "border-warn/40 bg-warn/15 text-warn" },
  };
  const cfg = map[outcome] ?? { label: outcome, cls: "border-line bg-surface-2 text-fg-2" };
  return (
    <Badge variant="outline" className={cn("font-mono text-[10px] tabular-nums", cfg.cls)}>
      {cfg.label}
    </Badge>
  );
}

function RBadge({ r }: { r: number | null }) {
  if (r == null) return <span className="text-fg-3">—</span>;
  const isPos = r > 0;
  return (
    <span
      className={cn(
        "font-mono text-xs tabular-nums font-semibold",
        isPos ? "text-bull" : "text-bear",
      )}
    >
      {isPos ? "+" : ""}
      {r.toFixed(2)}R
    </span>
  );
}

function StatusBadge({ sig }: { sig: ExecutedSignalRow }) {
  if (sig.close_outcome) return <OutcomeBadge outcome={sig.close_outcome} />;

  const isOpen = sig.tws_status === "Filled" || sig.tws_status === "PreSubmitted" || sig.tws_status === "Submitted";
  const hasError = !!sig.error;
  const isCancelled = sig.tws_status === "Cancelled" || hasError;
  const isSkipped = sig.tws_status === "skipped";

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[10px] tabular-nums",
        isOpen && "border-bull/30 bg-bull/10 text-bull",
        isCancelled && "border-bear/30 bg-bear/10 text-bear",
        isSkipped && "border-warn/30 bg-warn/10 text-warn",
        !isOpen && !isCancelled && !isSkipped && "border-line bg-surface-2 text-fg-2",
      )}
      title={sig.error ?? undefined}
    >
      {hasError ? "Errore" : isOpen ? "Aperta" : sig.tws_status}
    </Badge>
  );
}

export function ExecutedSignalsSection({
  signals,
  expanded,
  onToggleExpanded,
  statusFilter,
  onStatusFilterChange,
}: ExecutedSignalsSectionProps) {
  if (signals.length === 0) return null;

  const openCount = signals.filter(
    (s) =>
      !s.close_outcome &&
      (s.tws_status === "Filled" || s.tws_status === "PreSubmitted" || s.tws_status === "Submitted"),
  ).length;
  const closedCount = signals.filter((s) => !!s.close_outcome).length;
  const skippedCount = signals.filter((s) => s.tws_status === "skipped").length;
  const cancelledCount = signals.filter(
    (s) => !s.close_outcome && (s.tws_status === "Cancelled" || !!s.error),
  ).length;

  // Calcola P&L totale realizzato dalle posizioni chiuse (in R)
  const totalRealizedR = signals
    .filter((s) => s.realized_r != null)
    .reduce((acc, s) => acc + (s.realized_r ?? 0), 0);

  const filteredSignals = [...signals]
    .sort((a, b) => {
      const rank = (s: ExecutedSignalRow) => {
        if (!s.close_outcome && (s.tws_status === "Filled" || s.tws_status === "PreSubmitted" || s.tws_status === "Submitted")) return 0;
        if (s.close_outcome) return 1;
        if (s.tws_status === "Cancelled" || !!s.error) return 2;
        return 3;
      };
      return rank(a) - rank(b);
    })
    .filter((s) => {
      if (statusFilter === "open")
        return !s.close_outcome && (s.tws_status === "Filled" || s.tws_status === "PreSubmitted" || s.tws_status === "Submitted");
      if (statusFilter === "closed") return !!s.close_outcome;
      if (statusFilter === "skipped") return s.tws_status === "skipped";
      if (statusFilter === "cancelled")
        return !s.close_outcome && (s.tws_status === "Cancelled" || !!s.error);
      return true;
    });

  const tabs: { id: typeof statusFilter; label: string; count: number }[] = [
    { id: "open",      label: "Aperte",  count: openCount },
    { id: "closed",    label: "Chiuse",  count: closedCount },
    { id: "all",       label: "Tutte",   count: signals.length },
    { id: "skipped",   label: "Skip",    count: skippedCount },
    { id: "cancelled", label: "Canc.",   count: cancelledCount },
  ];

  return (
    <section aria-label="Trade eseguite dal sistema">
      {/* Section header */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onToggleExpanded}
          className="flex items-center gap-2 font-sans text-sm font-semibold text-fg-2 transition-colors hover:text-fg"
          aria-expanded={expanded}
        >
          <span
            className={cn(
              "font-mono text-xs transition-transform duration-150",
              expanded ? "rotate-90" : "rotate-0",
            )}
            aria-hidden
          >
            ▶
          </span>
          ⚡ Segnali sistema
        </button>

        {/* P&L sommario */}
        {closedCount > 0 && (
          <span
            className={cn(
              "font-mono text-xs font-semibold tabular-nums",
              totalRealizedR > 0 ? "text-bull" : totalRealizedR < 0 ? "text-bear" : "text-fg-3",
            )}
            title={`P&L totale su ${closedCount} trade chiuse`}
          >
            {totalRealizedR > 0 ? "+" : ""}
            {totalRealizedR.toFixed(2)}R
          </span>
        )}

        {/* Status filter tabs */}
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-line bg-canvas p-0.5">
          {tabs.map(({ id, label, count }) => (
            <button
              key={id}
              type="button"
              onClick={() => onStatusFilterChange(id)}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50",
                statusFilter === id
                  ? "bg-surface-3 text-fg"
                  : "text-fg-3 hover:text-fg",
              )}
            >
              {label}
              {count > 0 && (
                <Badge
                  variant="outline"
                  className={cn(
                    "h-4 min-w-4 px-1 font-mono text-[10px] tabular-nums",
                    id === "open"   && count > 0 && "border-bull/30 text-bull",
                    id === "closed" && count > 0 && "border-neutral/30 text-fg-2",
                    id === "cancelled" && count > 0 && "border-bear/30 text-bear",
                    id === "skipped"   && count > 0 && "border-warn/30 text-warn",
                  )}
                >
                  {count}
                </Badge>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {expanded && (
        <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface">
          {filteredSignals.length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-fg-3">
              {statusFilter === "open"
                ? "Nessuna posizione aperta al momento."
                : statusFilter === "closed"
                  ? "Nessuna trade chiusa nel periodo."
                  : "Nessun segnale per il filtro selezionato."}
            </p>
          ) : (
            <ScrollArea
              className={cn(filteredSignals.length > 20 && "h-96")}
            >
              <Table>
                <TableHeader>
                  <TableRow className="border-line hover:bg-transparent">
                    <TableHead className="text-fg-3 font-medium">Ora</TableHead>
                    <TableHead className="text-fg-3 font-medium">Simbolo</TableHead>
                    <TableHead className="text-fg-3 font-medium">Dir.</TableHead>
                    <TableHead className="text-fg-3 font-medium">Pattern</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">Entry</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">SL</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">TP1</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">Qty</TableHead>
                    <TableHead className="text-fg-3 font-medium">Status</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">P&amp;L (R)</TableHead>
                    <TableHead className="text-fg-3 font-medium">Chiuso</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredSignals.map((sig) => {
                    const isBull = sig.direction === "bullish";
                    const isOpen =
                      !sig.close_outcome &&
                      (sig.tws_status === "Filled" ||
                        sig.tws_status === "PreSubmitted" ||
                        sig.tws_status === "Submitted");
                    const isClosed = !!sig.close_outcome;
                    const isLoss =
                      isClosed && sig.realized_r != null && sig.realized_r < 0;
                    return (
                      <TableRow
                        key={sig.id}
                        className={cn(
                          "border-line/50 transition-colors hover:bg-surface-2",
                          isOpen && "bg-bull/5",
                          isLoss && "bg-bear/5",
                          !!sig.error && "opacity-60",
                        )}
                      >
                        <TableCell className="font-mono text-xs tabular-nums text-fg-3">
                          <span>
                            {new Date(sig.executed_at).toLocaleTimeString("it-IT", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                          <span className="ml-1 text-[10px] text-fg-3/60">
                            {new Date(sig.executed_at).toLocaleDateString("it-IT", {
                              day: "2-digit",
                              month: "2-digit",
                            })}
                          </span>
                        </TableCell>
                        <TableCell className="font-sans font-bold text-fg">
                          {sig.symbol}
                          <span className="ml-1 font-mono text-[10px] text-fg-3">
                            {sig.timeframe}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={cn(
                              "font-mono text-[10px]",
                              isBull
                                ? "border-bull/30 bg-bull/10 text-bull"
                                : "border-bear/30 bg-bear/10 text-bear",
                            )}
                          >
                            {isBull ? "▲" : "▼"}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[120px] truncate text-xs text-fg-2">
                          {sig.pattern_name.replace(/_/g, " ")}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums text-fg">
                          {sig.entry_price.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums text-bear">
                          {sig.stop_price.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums text-bull">
                          {sig.take_profit_1?.toFixed(2) ?? "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums text-fg-2">
                          {sig.filled_qty != null
                            ? sig.filled_qty
                            : sig.quantity_tp1 ?? "—"}
                          {sig.partial_fill && (
                            <span className="ml-1 text-[9px] text-warn">P</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <StatusBadge sig={sig} />
                        </TableCell>
                        <TableCell className="text-right">
                          <RBadge r={sig.realized_r} />
                        </TableCell>
                        <TableCell className="font-mono text-[10px] tabular-nums text-fg-3">
                          {sig.closed_at ? (
                            <>
                              <span>
                                {new Date(sig.closed_at).toLocaleTimeString("it-IT", {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </span>
                              <span className="ml-1 text-fg-3/60">
                                {new Date(sig.closed_at).toLocaleDateString("it-IT", {
                                  day: "2-digit",
                                  month: "2-digit",
                                })}
                              </span>
                              {sig.close_cause === "overnight_gap" && (
                                <span className="ml-1 text-[9px] text-warn" title="Gap notturno">
                                  gap
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-fg-3/40">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </div>
      )}
    </section>
  );
}
