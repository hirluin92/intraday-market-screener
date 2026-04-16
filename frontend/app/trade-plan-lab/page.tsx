"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useTradePlanLab } from "@/hooks/useBacktestData";
import type { OperationalVariantStatus, TradePlanVariantBestRow } from "@/lib/api";
import { displayTechnicalLabel } from "@/lib/displayLabels";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(s: OperationalVariantStatus) {
  const cls =
    s === "promoted"  ? "border-bull/40 bg-bull/10 text-bull" :
    s === "watchlist" ? "border-warn/40 bg-warn/10 text-warn" :
                        "border-line bg-surface-2 text-fg-3";
  const label =
    s === "promoted" ? "✓ Promossa" : s === "watchlist" ? "👁 Watchlist" : "✗ Respinta";
  return (
    <Badge variant="outline" className={cn("font-mono text-[10px]", cls)}>
      {label}
    </Badge>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtR(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(3)}R`;
}

// ── Row component ─────────────────────────────────────────────────────────────

function VariantRow({ row }: { row: TradePlanVariantBestRow }) {
  return (
    <TableRow className="border-line/50 hover:bg-surface-2">
      <TableCell className="font-mono text-xs text-fg">
        {displayTechnicalLabel(row.pattern_name)}
      </TableCell>
      <TableCell>
        <Badge variant="outline" className="font-mono text-[10px] border-line">{row.timeframe}</Badge>
      </TableCell>
      <TableCell className="text-xs text-fg-2">{row.provider}</TableCell>
      <TableCell className="text-xs text-fg-2">{row.best_variant_label}</TableCell>
      <TableCell>{statusBadge(row.operational_status)}</TableCell>
      <TableCell className="text-right font-mono tabular-nums text-xs text-fg-2">{row.sample_size}</TableCell>
      <TableCell className={cn(
        "text-right font-mono tabular-nums text-xs",
        (row.tp1_or_tp2_rate_given_entry ?? 0) >= 0.55 ? "text-bull" : "text-fg-2",
      )}>
        {fmtPct(row.tp1_or_tp2_rate_given_entry)}
      </TableCell>
      <TableCell className={cn(
        "text-right font-mono tabular-nums text-xs",
        (row.expectancy_r ?? 0) > 0 ? "text-bull" : (row.expectancy_r ?? 0) < 0 ? "text-bear" : "text-fg-2",
      )}>
        {fmtR(row.expectancy_r)}
      </TableCell>
    </TableRow>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const TIMEFRAMES = ["", "1m", "5m", "15m", "1h", "1d"] as const;
const PROVIDERS  = ["", "binance", "yahoo_finance"] as const;
const ASSET_TYPES = ["", "crypto", "etf", "stock", "index"] as const;
const STATUS_OPTIONS = ["", "promoted_watchlist", "promoted", "watchlist", "rejected"] as const;

export default function TradePlanLabPage() {
  const [filterTimeframe,  setFilterTimeframe]  = useState("");
  const [filterProvider,   setFilterProvider]   = useState("");
  const [filterAssetType,  setFilterAssetType]  = useState("");
  const [filterStatus,     setFilterStatus]     = useState("");

  const { data, isLoading, error, refetch } = useTradePlanLab({
    timeframe:    filterTimeframe  || undefined,
    provider:     filterProvider   || undefined,
    asset_type:   filterAssetType  || undefined,
    status_scope: (filterStatus as typeof STATUS_OPTIONS[number]) || undefined,
  });

  const rows = useMemo(
    () => data?.rows ?? [],
    [data],
  );

  return (
    <div className="flex min-h-full flex-col">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-2 px-4 py-2 sm:px-6">
          <h1 className="font-sans text-sm font-semibold text-fg">Trade Plan Lab</h1>

          <div className="flex flex-wrap items-center gap-2 ml-4">
            <Select value={filterTimeframe} onValueChange={setFilterTimeframe}>
              <SelectTrigger className="h-8 w-24 bg-surface-2 border-line text-fg text-xs">
                <SelectValue placeholder="TF" />
              </SelectTrigger>
              <SelectContent className="bg-surface border-line text-fg">
                {TIMEFRAMES.map((tf) => (
                  <SelectItem key={tf || "all"} value={tf} className="text-xs">{tf || "Tutti TF"}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={filterProvider} onValueChange={setFilterProvider}>
              <SelectTrigger className="h-8 w-32 bg-surface-2 border-line text-fg text-xs">
                <SelectValue placeholder="Provider" />
              </SelectTrigger>
              <SelectContent className="bg-surface border-line text-fg">
                {PROVIDERS.map((p) => (
                  <SelectItem key={p || "all"} value={p} className="text-xs">{p || "Tutti"}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={filterAssetType} onValueChange={setFilterAssetType}>
              <SelectTrigger className="h-8 w-28 bg-surface-2 border-line text-fg text-xs">
                <SelectValue placeholder="Asset" />
              </SelectTrigger>
              <SelectContent className="bg-surface border-line text-fg">
                {ASSET_TYPES.map((a) => (
                  <SelectItem key={a || "all"} value={a} className="text-xs">{a || "Tutti"}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={filterStatus} onValueChange={setFilterStatus}>
              <SelectTrigger className="h-8 w-36 bg-surface-2 border-line text-fg text-xs">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent className="bg-surface border-line text-fg">
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s || "all"} value={s} className="text-xs">
                    {s === "" ? "Tutti" : s.replace(/_/g, " ")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="ml-auto flex items-center gap-3">
            {data && (
              <div className="flex items-center gap-2 font-mono text-[10px] text-fg-3">
                {data.counts_by_status.promoted > 0 && (
                  <span className="text-bull">✓ {data.counts_by_status.promoted}</span>
                )}
                {data.counts_by_status.watchlist > 0 && (
                  <span className="text-warn">👁 {data.counts_by_status.watchlist}</span>
                )}
                {data.counts_by_status.rejected > 0 && (
                  <span className="text-fg-3">✗ {data.counts_by_status.rejected}</span>
                )}
              </div>
            )}
            <span className="font-mono text-xs tabular-nums text-fg-3">
              {rows.length} varianti
            </span>
          </div>
        </div>
      </header>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <div className="mx-auto w-full max-w-[1440px] flex-1 px-4 pb-8 sm:px-6">
        <ErrorBoundary label="Trade Plan Lab">
          {isLoading ? (
            <div className="mt-4 rounded-xl border border-line bg-surface overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-line hover:bg-transparent">
                    {["Pattern", "TF", "Provider", "Variante", "Status", "N", "TP rate", "E[R]"].map((h) => (
                      <TableHead key={h} className="text-fg-3 font-medium">{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from({ length: 10 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 8 }).map((_, j) => (
                        <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : error ? (
            <div className="mt-8 flex flex-col items-center gap-3 rounded-xl border border-warn/30 bg-warn/5 py-8 text-center" role="alert">
              <p className="text-sm text-fg-2">Errore caricamento varianti.</p>
              <Button variant="ghost" size="sm" className="text-xs text-neutral" onClick={() => void refetch()}>
                Riprova
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="mt-8 py-10 text-center">
              <p className="text-sm text-fg-2">Nessuna variante trovata con i filtri applicati.</p>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-line bg-surface overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-line hover:bg-transparent">
                    <TableHead className="text-fg-3 font-medium" scope="col">Pattern</TableHead>
                    <TableHead className="text-fg-3 font-medium" scope="col">TF</TableHead>
                    <TableHead className="text-fg-3 font-medium" scope="col">Provider</TableHead>
                    <TableHead className="text-fg-3 font-medium" scope="col">Variante</TableHead>
                    <TableHead className="text-fg-3 font-medium" scope="col">Status</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">N</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">TP rate</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">E[R]</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row, i) => (
                    <VariantRow key={`${row.pattern_name}-${row.timeframe}-${row.provider}-${i}`} row={row} />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </ErrorBoundary>
      </div>
    </div>
  );
}
