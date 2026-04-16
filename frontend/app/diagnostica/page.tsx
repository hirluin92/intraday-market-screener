"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Activity, BarChart2, CheckCircle2, Target } from "lucide-react";

import { Badge } from "@/components/ui/badge";
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
import { KPICard } from "@/components/trading/KPICard";
import { SignalCardCompact } from "@/components/trading/SignalCardCompact";
import { useDiagnosticPatterns, useDiagnosticOpportunities } from "@/hooks/useDiagnosticData";
import {
  computeSignalAlignment,
  displayFinalOpportunityLabel,
  displayTechnicalLabel,
} from "@/lib/displayLabels";
import type { BacktestAggregateRow, OpportunityRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Business logic (unchanged from original) ──────────────────────────────────

const TOP_N_PER_TF = 4;
const TOP_OPPS = 6;

function groupBestByTimeframe(rows: BacktestAggregateRow[]) {
  const withScore = rows.filter((r) => r.pattern_quality_score != null);
  const byTf = new Map<string, BacktestAggregateRow[]>();
  for (const r of withScore) {
    const list = byTf.get(r.timeframe) ?? [];
    list.push(r);
    byTf.set(r.timeframe, list);
  }
  const timeframes = [...byTf.keys()].sort();
  return timeframes.map((tf) => {
    const list = byTf.get(tf)!;
    const sortedDesc = [...list].sort((a, b) => (b.pattern_quality_score ?? 0) - (a.pattern_quality_score ?? 0));
    return { tf, rows: sortedDesc.slice(0, TOP_N_PER_TF) };
  });
}

function countAlignment(opps: OpportunityRow[]) {
  let aligned = 0, mixed = 0, conflicting = 0;
  for (const r of opps) {
    const a = computeSignalAlignment(r.score_direction, r.latest_pattern_direction);
    if (a === "aligned") aligned++;
    else if (a === "mixed") mixed++;
    else conflicting++;
  }
  return { aligned, mixed, conflicting, total: opps.length };
}

// ── Section skeleton ──────────────────────────────────────────────────────────

function RowSkeleton({ cols = 4 }: { cols?: number }) {
  return (
    <TableRow>
      {Array.from({ length: cols }).map((_, i) => (
        <TableCell key={i}><Skeleton className="h-4 w-full" /></TableCell>
      ))}
    </TableRow>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DiagnosticaPage() {
  const patterns = useDiagnosticPatterns();
  const opps = useDiagnosticOpportunities();

  // ── Derived KPIs ─────────────────────────────────────────────────────────
  const kpis = useMemo(() => {
    const patRows = patterns.data?.aggregates ?? [];
    const oppRows = opps.data?.opportunities ?? [];
    const alignment = oppRows.length ? countAlignment(oppRows) : null;
    const executeCount = oppRows.filter((r) => r.operational_decision === "execute").length;
    const validatedPatterns = patRows.filter((r) => (r.pattern_quality_score ?? 0) >= 50).length;
    return {
      totalPatterns: patRows.length,
      validatedPatterns,
      executeSignals: executeCount,
      alignmentPct: alignment
        ? Math.round((alignment.aligned / Math.max(alignment.total, 1)) * 100)
        : null,
      alignment,
    };
  }, [patterns.data, opps.data]);

  // ── Top patterns per TF ────────────────────────────────────────────────────
  const bestByTf = useMemo(
    () => groupBestByTimeframe(patterns.data?.aggregates ?? []),
    [patterns.data],
  );

  // ── Top opportunities ──────────────────────────────────────────────────────
  const topOpps = useMemo(
    () =>
      (opps.data?.opportunities ?? [])
        .filter((r) => r.operational_decision === "execute")
        .slice(0, TOP_OPPS),
    [opps.data],
  );

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-6">
      <h1 className="font-sans text-xl font-bold text-fg">Diagnostica Sistema</h1>

      {/* ── KPI row ───────────────────────────────────────────────────── */}
      <ErrorBoundary label="KPI diagnostica">
        <section aria-label="Metriche sistema">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KPICard
              label="Pattern totali"
              value={patterns.isLoading ? undefined : kpis.totalPatterns}
              icon={BarChart2}
              loading={patterns.isLoading}
              variant="neutral"
            />
            <KPICard
              label="Pattern validati (score ≥50)"
              value={patterns.isLoading ? undefined : kpis.validatedPatterns}
              icon={CheckCircle2}
              loading={patterns.isLoading}
              variant="bull"
            />
            <KPICard
              label="Segnali Execute live"
              value={opps.isLoading ? undefined : kpis.executeSignals}
              icon={Target}
              loading={opps.isLoading}
              variant={kpis.executeSignals > 0 ? "bull" : "neutral"}
              href="/opportunities"
            />
            <KPICard
              label="Allineamento segnali"
              value={opps.isLoading || kpis.alignmentPct == null ? undefined : `${kpis.alignmentPct}%`}
              icon={Activity}
              loading={opps.isLoading}
              variant={
                kpis.alignmentPct == null ? "neutral"
                : kpis.alignmentPct >= 60 ? "bull"
                : kpis.alignmentPct >= 40 ? "neutral"
                : "bear"
              }
              tooltip="% segnali live con pattern allineato allo score screener"
            />
          </div>
        </section>
      </ErrorBoundary>

      {/* ── Best pattern per TF ───────────────────────────────────────── */}
      <ErrorBoundary label="Tabella pattern per TF">
        <section aria-label="Migliori pattern per timeframe">
          <h2 className="mb-3 font-sans text-sm font-semibold uppercase tracking-widest text-fg-2">
            Top pattern per timeframe
          </h2>
          {patterns.isLoading ? (
            <div className="rounded-xl border border-line bg-surface overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-line hover:bg-transparent">
                    <TableHead className="text-fg-3 font-medium">TF</TableHead>
                    <TableHead className="text-fg-3 font-medium">Pattern</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">Score</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">WR% 1</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium">N</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from({ length: 8 }).map((_, i) => <RowSkeleton key={i} cols={5} />)}
                </TableBody>
              </Table>
            </div>
          ) : patterns.error ? (
            <div className="rounded-xl border border-warn/30 bg-warn/5 p-4" role="alert">
              <p className="text-sm text-fg-2">Dati pattern non disponibili.</p>
            </div>
          ) : bestByTf.length === 0 ? (
            <p className="text-sm text-fg-2">Nessun dato disponibile.</p>
          ) : (
            <div className="rounded-xl border border-line bg-surface overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-line hover:bg-transparent">
                    <TableHead className="text-fg-3 font-medium" scope="col">TF</TableHead>
                    <TableHead className="text-fg-3 font-medium" scope="col">Pattern</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">Score</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">WR% 1</TableHead>
                    <TableHead className="text-right text-fg-3 font-medium" scope="col">N</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bestByTf.flatMap(({ tf, rows }) =>
                    rows.map((r, i) => {
                      const score = r.pattern_quality_score ?? 0;
                      const scoreCls = score >= 70 ? "text-bull" : score >= 50 ? "text-neutral" : "text-bear";
                      return (
                        <TableRow key={`${tf}-${r.pattern_name}`} className="border-line/50 hover:bg-surface-2">
                          {i === 0 && (
                            <TableCell rowSpan={rows.length} className="align-top pt-3">
                              <Badge variant="outline" className="font-mono text-[10px] border-line">{tf}</Badge>
                            </TableCell>
                          )}
                          <TableCell className="font-mono text-xs text-fg">
                            {displayTechnicalLabel(r.pattern_name)}
                          </TableCell>
                          <TableCell className={cn("text-right font-mono tabular-nums text-xs font-semibold", scoreCls)}>
                            {score.toFixed(1)}
                          </TableCell>
                          <TableCell className={cn(
                            "text-right font-mono tabular-nums text-xs",
                            (r.win_rate_1 ?? 0) >= 0.55 ? "text-bull" : (r.win_rate_1 ?? 0) < 0.5 ? "text-bear" : "text-neutral",
                          )}>
                            {r.win_rate_1 != null ? `${(r.win_rate_1 * 100).toFixed(1)}%` : "—"}
                          </TableCell>
                          <TableCell className="text-right font-mono tabular-nums text-xs text-fg-2">
                            {r.sample_size}
                          </TableCell>
                        </TableRow>
                      );
                    }),
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </ErrorBoundary>

      {/* ── Top opportunities ─────────────────────────────────────────── */}
      <ErrorBoundary label="Top opportunità">
        <section aria-label="Top opportunità execute">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-sans text-sm font-semibold uppercase tracking-widest text-fg-2">
              Top segnali execute live
            </h2>
            <Link
              href="/opportunities"
              className="text-xs text-neutral hover:text-fg transition-colors"
            >
              Vedi tutti →
            </Link>
          </div>

          {opps.isLoading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-40 rounded-xl" />
              ))}
            </div>
          ) : opps.error ? (
            <div className="rounded-xl border border-warn/30 bg-warn/5 p-4" role="alert">
              <p className="text-sm text-fg-2">Opportunità non disponibili.</p>
            </div>
          ) : topOpps.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-line py-8 text-center">
              <Target className="h-7 w-7 text-fg-3" aria-hidden />
              <p className="text-sm text-fg-2">Nessun segnale execute al momento.</p>
              <Link href="/opportunities" className="text-xs text-neutral underline underline-offset-2">
                Vai alle opportunità
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {topOpps.map((opp) => (
                <SignalCardCompact
                  key={`${opp.symbol}-${opp.timeframe}-${opp.exchange}`}
                  opportunity={opp}
                />
              ))}
            </div>
          )}
        </section>
      </ErrorBoundary>
    </div>
  );
}
