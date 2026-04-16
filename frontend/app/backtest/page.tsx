"use client";

import { useMemo, useRef, useState } from "react";
import { Download, Filter, X } from "lucide-react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useBacktestPatterns } from "@/hooks/useBacktestData";
import type { BacktestAggregateRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtWr(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(1);
}

function wrVariant(v: number | null | undefined): "bull" | "neutral" | "bear" {
  if (v == null) return "neutral";
  const pct = v * 100;
  if (pct >= 55) return "bull";
  if (pct >= 50) return "neutral";
  return "bear";
}

function wrClass(v: number | null | undefined): string {
  const variant = wrVariant(v);
  if (variant === "bull") return "text-bull";
  if (variant === "bear") return "text-bear";
  return "text-neutral";
}

function reliabilityBadge(rel: string | null | undefined) {
  if (!rel) return null;
  const cls =
    rel === "excellent" ? "border-bull/30 bg-bull/10 text-bull" :
    rel === "good"      ? "border-neutral/30 bg-neutral/10 text-neutral" :
    rel === "fair"      ? "border-warn/30 bg-warn/10 text-warn" :
                          "border-bear/30 bg-bear/10 text-bear";
  return <Badge variant="outline" className={cn("font-mono text-[10px]", cls)}>{rel}</Badge>;
}

// ── Column definitions ────────────────────────────────────────────────────────

const COLUMNS: ColumnDef<BacktestAggregateRow>[] = [
  {
    accessorKey: "pattern_name",
    header: "Pattern",
    cell: ({ getValue }) => (
      <span className="font-mono text-xs text-fg">{String(getValue()).replace(/_/g, " ")}</span>
    ),
    size: 220,
  },
  {
    accessorKey: "timeframe",
    header: "TF",
    cell: ({ getValue }) => (
      <Badge variant="outline" className="font-mono text-[10px] border-line">{String(getValue())}</Badge>
    ),
    size: 60,
  },
  {
    accessorKey: "sample_size",
    header: "N",
    cell: ({ getValue }) => (
      <span className="font-mono tabular-nums text-xs text-fg-2">{Number(getValue())}</span>
    ),
    size: 70,
  },
  {
    accessorKey: "win_rate_1",
    header: "WR% 1",
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      return <span className={cn("font-mono tabular-nums text-xs", wrClass(v))}>{fmtWr(v)}</span>;
    },
    size: 75,
  },
  {
    accessorKey: "win_rate_5",
    header: "WR% 5",
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      return <span className={cn("font-mono tabular-nums text-xs", wrClass(v))}>{fmtWr(v)}</span>;
    },
    size: 75,
  },
  {
    accessorKey: "win_rate_10",
    header: "WR% 10",
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      return <span className={cn("font-mono tabular-nums text-xs", wrClass(v))}>{fmtWr(v)}</span>;
    },
    size: 75,
  },
  {
    accessorKey: "avg_return_1",
    header: "Avg R 1",
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      if (v == null) return <span className="text-fg-3">—</span>;
      return (
        <span className={cn("font-mono tabular-nums text-xs", v >= 0 ? "text-bull" : "text-bear")}>
          {v >= 0 ? "+" : ""}{v.toFixed(3)}
        </span>
      );
    },
    size: 80,
  },
  {
    accessorKey: "pattern_quality_score",
    header: "Score",
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      if (v == null) return <span className="text-fg-3">—</span>;
      const cls = v >= 70 ? "text-bull" : v >= 50 ? "text-neutral" : "text-bear";
      return <span className={cn("font-mono tabular-nums text-xs font-semibold", cls)}>{fmtScore(v)}</span>;
    },
    size: 70,
  },
  {
    accessorKey: "sample_reliability",
    header: "Affidabilità",
    cell: ({ getValue }) => reliabilityBadge(getValue() as string | null),
    size: 100,
  },
  {
    accessorKey: "win_rate_significance",
    header: "Sig.",
    cell: ({ getValue }) => {
      const v = getValue() as string | null;
      if (!v || v === "ns") return <span className="text-fg-3 text-xs">ns</span>;
      const cls = v === "***" ? "text-bull font-bold" : v === "**" ? "text-neutral font-semibold" : "text-warn";
      return <span className={cn("font-mono text-xs", cls)}>{v}</span>;
    },
    size: 60,
  },
];

// ── CSV export ────────────────────────────────────────────────────────────────

function exportCsv(rows: BacktestAggregateRow[]) {
  const headers = ["Pattern", "TF", "N", "WR%1", "WR%5", "WR%10", "AvgR1", "Score", "Affidabilità", "Sig."];
  const body = rows.map((r) =>
    [
      r.pattern_name,
      r.timeframe,
      r.sample_size,
      r.win_rate_1 != null ? (r.win_rate_1 * 100).toFixed(2) : "",
      r.win_rate_5 != null ? (r.win_rate_5 * 100).toFixed(2) : "",
      r.win_rate_10 != null ? (r.win_rate_10 * 100).toFixed(2) : "",
      r.avg_return_1?.toFixed(4) ?? "",
      r.pattern_quality_score?.toFixed(1) ?? "",
      r.sample_reliability ?? "",
      r.win_rate_significance ?? "",
    ]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`)
      .join(","),
  );
  const csv = [headers.join(","), ...body].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `backtest_patterns_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Table skeleton ────────────────────────────────────────────────────────────

function TableSkeleton() {
  return (
    <div className="space-y-1">
      <div className="flex gap-3 border-b border-line px-4 py-2">
        {[220, 60, 70, 75, 75, 75, 80, 70, 100, 60].map((w, i) => (
          <Skeleton key={i} className="h-4" style={{ width: w }} />
        ))}
      </div>
      {Array.from({ length: 12 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-4 py-2">
          {[220, 60, 70, 75, 75, 75, 80, 70, 100, 60].map((w, j) => (
            <Skeleton key={j} className="h-4" style={{ width: w }} />
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const TIMEFRAMES = ["", "1m", "5m", "15m", "1h", "1d"] as const;
const PROVIDERS  = ["", "binance", "yahoo_finance"] as const;
const ASSET_TYPES = ["", "crypto", "etf", "stock"] as const;

export default function BacktestPage() {
  // ── Filter state ────────────────────────────────────────────────────────────
  const [filterTimeframe, setFilterTimeframe] = useState("");
  const [filterProvider,  setFilterProvider]  = useState("");
  const [filterAssetType, setFilterAssetType] = useState("");
  const [globalFilter,    setGlobalFilter]    = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "pattern_quality_score", desc: true },
  ]);

  const queryParams = useMemo(
    () => ({
      timeframe:  filterTimeframe  || undefined,
      provider:   filterProvider   || undefined,
      asset_type: filterAssetType  || undefined,
    }),
    [filterTimeframe, filterProvider, filterAssetType],
  );

  const { data, isLoading, error, refetch } = useBacktestPatterns(queryParams);

  const table = useReactTable({
    data: data?.aggregates ?? [],
    columns: COLUMNS,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel:    getCoreRowModel(),
    getSortedRowModel:  getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const rows = table.getRowModel().rows;
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count:            rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize:     () => 40,
    overscan:         12,
  });

  const hasFilters = !!(filterTimeframe || filterProvider || filterAssetType || globalFilter);

  const resetFilters = () => {
    setFilterTimeframe("");
    setFilterProvider("");
    setFilterAssetType("");
    setGlobalFilter("");
  };

  return (
    <div className="flex min-h-full flex-col">
      {/* ── Sticky header ─────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-3 px-4 py-2 sm:px-6">
          <div className="flex flex-1 items-center gap-3">
            <h1 className="font-sans text-sm font-semibold text-fg">Analisi Pattern</h1>

            {/* Global search */}
            <div className="relative max-w-xs flex-1">
              <Input
                placeholder="Cerca pattern…"
                value={globalFilter}
                onChange={(e) => setGlobalFilter(e.target.value)}
                className="h-8 bg-surface-2 border-line text-fg text-xs pl-3"
              />
            </div>

            {/* Filter popover */}
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-8 gap-1.5 border-line bg-surface-2 text-xs text-fg-2",
                    hasFilters && "border-neutral/40 text-neutral",
                  )}
                >
                  <Filter className="h-3.5 w-3.5" aria-hidden />
                  Filtri
                  {hasFilters && <span className="h-1.5 w-1.5 rounded-full bg-neutral" />}
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-72 bg-surface border-line text-fg p-4 space-y-3"
              >
                <p className="text-xs font-semibold uppercase tracking-widest text-fg-2">Filtri avanzati</p>
                <div className="space-y-1.5">
                  <label className="text-xs text-fg-2">Timeframe</label>
                  <Select value={filterTimeframe} onValueChange={setFilterTimeframe}>
                    <SelectTrigger className="bg-surface-2 border-line text-fg text-xs h-8">
                      <SelectValue placeholder="Tutti" />
                    </SelectTrigger>
                    <SelectContent className="bg-surface border-line text-fg">
                      {TIMEFRAMES.map((tf) => (
                        <SelectItem key={tf || "all"} value={tf} className="text-xs">{tf || "Tutti"}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-fg-2">Provider</label>
                  <Select value={filterProvider} onValueChange={setFilterProvider}>
                    <SelectTrigger className="bg-surface-2 border-line text-fg text-xs h-8">
                      <SelectValue placeholder="Tutti" />
                    </SelectTrigger>
                    <SelectContent className="bg-surface border-line text-fg">
                      {PROVIDERS.map((p) => (
                        <SelectItem key={p || "all"} value={p} className="text-xs">{p || "Tutti"}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-fg-2">Asset type</label>
                  <Select value={filterAssetType} onValueChange={setFilterAssetType}>
                    <SelectTrigger className="bg-surface-2 border-line text-fg text-xs h-8">
                      <SelectValue placeholder="Tutti" />
                    </SelectTrigger>
                    <SelectContent className="bg-surface border-line text-fg">
                      {ASSET_TYPES.map((a) => (
                        <SelectItem key={a || "all"} value={a} className="text-xs">{a || "Tutti"}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {hasFilters && (
                  <Button variant="ghost" size="sm" className="w-full text-xs text-fg-3" onClick={resetFilters}>
                    <X className="mr-1 h-3 w-3" /> Reset filtri
                  </Button>
                )}
              </PopoverContent>
            </Popover>
          </div>

          <div className="flex items-center gap-2">
            {/* Row count */}
            {data && (
              <span className="font-mono text-xs tabular-nums text-fg-3">
                {rows.length.toLocaleString("it-IT")} / {data.aggregates.length.toLocaleString("it-IT")} pattern
              </span>
            )}
            {/* Export */}
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 border-line bg-surface-2 text-xs text-fg-2"
              onClick={() => data && exportCsv(rows.map((r) => r.original))}
              disabled={!data || rows.length === 0}
              aria-label="Esporta CSV"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              <span className="hidden sm:inline">Export CSV</span>
            </Button>
          </div>
        </div>
      </header>

      {/* ── Table area ────────────────────────────────────────────────── */}
      <div className="mx-auto w-full max-w-[1440px] flex-1 px-4 sm:px-6">
        <ErrorBoundary label="Tabella backtest">
          {isLoading ? (
            <TableSkeleton />
          ) : error ? (
            <div className="mt-8 flex flex-col items-center gap-3 rounded-xl border border-warn/30 bg-warn/5 py-10 text-center" role="alert">
              <p className="text-sm text-fg-2">Errore caricamento pattern backtest.</p>
              <Button variant="ghost" size="sm" className="text-xs text-neutral" onClick={() => void refetch()}>
                Riprova
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="mt-8 flex flex-col items-center gap-3 py-10 text-center">
              <p className="text-sm text-fg-2">Nessun pattern trovato con i filtri applicati.</p>
              {hasFilters && (
                <Button variant="ghost" size="sm" className="text-xs text-neutral" onClick={resetFilters}>
                  Reset filtri
                </Button>
              )}
            </div>
          ) : (
            <div
              ref={parentRef}
              className="overflow-auto"
              style={{ height: "calc(100vh - 8rem)" }}
              role="region"
              aria-label={`Tabella pattern backtest, ${rows.length} righe, ordinata per score`}
            >
              <table className="w-full border-separate border-spacing-0 text-xs">
                <thead className="sticky top-0 z-10 bg-canvas">
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id}>
                      {hg.headers.map((header) => {
                        const sorted = header.column.getIsSorted();
                        return (
                          <th
                            key={header.id}
                            scope="col"
                            aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                            className={cn(
                              "border-b border-line px-3 py-2 text-left font-medium text-fg-2 whitespace-nowrap",
                              header.column.getCanSort() && "cursor-pointer select-none hover:text-fg",
                            )}
                            style={{ width: header.column.columnDef.size }}
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody
                  style={{
                    height:   `${virtualizer.getTotalSize()}px`,
                    position: "relative",
                  }}
                >
                  {virtualizer.getVirtualItems().map((vRow) => {
                    const row = rows[vRow.index];
                    if (!row) return null;
                    return (
                      <tr
                        key={row.id}
                        style={{
                          position:  "absolute",
                          top:       0,
                          left:      0,
                          width:     "100%",
                          height:    `${vRow.size}px`,
                          transform: `translateY(${vRow.start}px)`,
                        }}
                        className="border-b border-line/40 hover:bg-surface-2"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td
                            key={cell.id}
                            className="px-3 py-2 align-middle"
                            style={{ width: cell.column.columnDef.size }}
                          >
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </ErrorBoundary>
      </div>

      {/* ── Footer ────────────────────────────────────────────────────── */}
      {data && rows.length > 0 && (
        <div className="sticky bottom-0 border-t border-line bg-canvas/95 px-4 py-2 sm:px-6">
          <p className="mx-auto max-w-[1440px] font-mono text-xs tabular-nums text-fg-3">
            Mostrando {rows.length.toLocaleString("it-IT")} di {data.aggregates.length.toLocaleString("it-IT")} pattern
            {data.patterns_evaluated > 0 && ` · ${data.patterns_evaluated.toLocaleString("it-IT")} valutati`}
          </p>
        </div>
      )}
    </div>
  );
}
