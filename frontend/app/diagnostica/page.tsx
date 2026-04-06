"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchBacktestPatterns,
  fetchOpportunities,
  seriesDetailHref,
  type BacktestAggregateRow,
  type OpportunityRow,
} from "@/lib/api";
import {
  computeSignalAlignment,
  displayFinalOpportunityLabel,
  displayTechnicalLabel,
} from "@/lib/displayLabels";

const FETCH_LIMIT = 500;
const TOP_N_PER_TF = 4;
const TOP_OPPS = 12;

function groupBestWorstByTimeframe(rows: BacktestAggregateRow[]) {
  const withScore = rows.filter((r) => r.pattern_quality_score != null);
  const byTf = new Map<string, BacktestAggregateRow[]>();
  for (const r of withScore) {
    const list = byTf.get(r.timeframe) ?? [];
    list.push(r);
    byTf.set(r.timeframe, list);
  }
  const timeframes = [...byTf.keys()].sort();
  const best: { tf: string; rows: BacktestAggregateRow[] }[] = [];
  const worst: { tf: string; rows: BacktestAggregateRow[] }[] = [];
  for (const tf of timeframes) {
    const list = byTf.get(tf)!;
    const sortedDesc = [...list].sort(
      (a, b) =>
        (b.pattern_quality_score ?? 0) - (a.pattern_quality_score ?? 0),
    );
    const sortedAsc = [...list].sort(
      (a, b) =>
        (a.pattern_quality_score ?? 0) - (b.pattern_quality_score ?? 0),
    );
    best.push({ tf, rows: sortedDesc.slice(0, TOP_N_PER_TF) });
    worst.push({ tf, rows: sortedAsc.slice(0, TOP_N_PER_TF) });
  }
  return { best, worst, timeframes };
}

function countAlignment(opps: OpportunityRow[]) {
  let allineato = 0;
  let misto = 0;
  let conflittuale = 0;
  for (const r of opps) {
    const a = computeSignalAlignment(
      r.score_direction,
      r.latest_pattern_direction,
    );
    if (a === "aligned") allineato++;
    else if (a === "mixed") misto++;
    else conflittuale++;
  }
  return { allineato, misto, conflittuale };
}

function countTfOk(opps: OpportunityRow[]) {
  let ok = 0;
  let nonOk = 0;
  let na = 0;
  for (const r of opps) {
    if (r.pattern_timeframe_quality_ok === null) na++;
    else if (r.pattern_timeframe_quality_ok === true) ok++;
    else nonOk++;
  }
  return { ok, nonOk, na };
}

export default function DiagnosticaPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aggregates, setAggregates] = useState<BacktestAggregateRow[]>([]);
  const [patternsEvaluated, setPatternsEvaluated] = useState(0);
  const [opportunities, setOpportunities] = useState<OpportunityRow[]>([]);
  const [oppCount, setOppCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [bt, op] = await Promise.all([
        fetchBacktestPatterns({ limit: FETCH_LIMIT }),
        fetchOpportunities({ limit: FETCH_LIMIT }),
      ]);
      setAggregates(bt.aggregates);
      setPatternsEvaluated(bt.patterns_evaluated);
      setOpportunities(op.opportunities);
      setOppCount(op.count);
    } catch (e) {
      setAggregates([]);
      setOpportunities([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const { best, worst } = useMemo(
    () => groupBestWorstByTimeframe(aggregates),
    [aggregates],
  );

  const alignmentCounts = useMemo(
    () => countAlignment(opportunities),
    [opportunities],
  );

  const tfCounts = useMemo(() => countTfOk(opportunities), [opportunities]);

  const topOpps = useMemo(() => {
    const copy = [...opportunities];
    copy.sort((a, b) => b.final_opportunity_score - a.final_opportunity_score);
    return copy.slice(0, TOP_OPPS);
  }, [opportunities]);

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-8 p-6">
      <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Report MVP
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">Diagnostica screener</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Sintesi da backtest aggregati e lista opportunità corrente (nessun filtro applicato
          oltre al limite richiesto all&apos;API).
        </p>
      </header>

      {loading && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status">
          Caricamento dati…
        </p>
      )}

      {!loading && error && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
          role="alert"
        >
          <strong className="font-medium">Errore caricamento.</strong>
          <pre className="mt-2 whitespace-pre-wrap font-mono text-xs">{error}</pre>
        </div>
      )}

      {!loading && !error && (
        <>
          <section aria-labelledby="kpi-h">
            <h2 id="kpi-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Indicatori rapidi (opportunità caricate: {oppCount})
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-800 dark:bg-zinc-950/40">
                <p className="text-xs font-medium text-zinc-500">Allineamento segnale</p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {alignmentCounts.allineato}
                </p>
                <p className="text-xs text-zinc-600 dark:text-zinc-400">allineati</p>
              </div>
              <div className="rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-800 dark:bg-zinc-950/40">
                <p className="text-xs font-medium text-zinc-500">Allineamento segnale</p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {alignmentCounts.misto}
                </p>
                <p className="text-xs text-zinc-600 dark:text-zinc-400">misti</p>
              </div>
              <div className="rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-800 dark:bg-zinc-950/40">
                <p className="text-xs font-medium text-zinc-500">Allineamento segnale</p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {alignmentCounts.conflittuale}
                </p>
                <p className="text-xs text-zinc-600 dark:text-zinc-400">conflittuali</p>
              </div>
              <div className="rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-800 dark:bg-zinc-950/40">
                <p className="text-xs font-medium text-zinc-500">Pattern righe backtest</p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {patternsEvaluated}
                </p>
                <p className="text-xs text-zinc-600 dark:text-zinc-400">valutate (estrazione)</p>
              </div>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/30">
                <p className="text-xs font-medium text-emerald-800 dark:text-emerald-300">
                  OK storico sul TF
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{tfCounts.ok}</p>
              </div>
              <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/30">
                <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
                  Non OK sul TF
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{tfCounts.nonOk}</p>
                <p className="text-xs text-zinc-500">marginali / insufficienti / sconosciuti</p>
              </div>
              <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/30">
                <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Senza pattern (N/A)
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{tfCounts.na}</p>
              </div>
            </div>
          </section>

          <section aria-labelledby="best-h">
            <h2 id="best-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Migliori pattern per timeframe (qualità backtest)
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Fino a {TOP_N_PER_TF} pattern per TF con score qualità più alto (solo righe con
              score numerico).
            </p>
            <div className="mt-2 space-y-4">
              {best.length === 0 ? (
                <p className="text-sm text-zinc-500">Nessun aggregato con qualità numerica.</p>
              ) : (
                best.map(({ tf, rows }) => (
                  <div key={tf} className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
                    <p className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-xs font-medium dark:border-zinc-800 dark:bg-zinc-900/60">
                      Timeframe <span className="font-mono">{tf}</span>
                    </p>
                    <table className="w-full min-w-[32rem] border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-zinc-200 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-900/40">
                          <th className="px-3 py-2 font-medium">Pattern</th>
                          <th className="px-3 py-2 font-medium">Qualità</th>
                          <th className="px-3 py-2 font-medium">n</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr
                            key={`${r.pattern_name}-${r.timeframe}-${r.pattern_quality_score}`}
                            className="border-b border-zinc-100 dark:border-zinc-800/80"
                          >
                            <td className="px-3 py-1.5 font-mono">
                              {displayTechnicalLabel(r.pattern_name)}
                            </td>
                            <td className="px-3 py-1.5 tabular-nums">
                              {r.pattern_quality_score != null
                                ? r.pattern_quality_score.toFixed(1)
                                : "—"}
                            </td>
                            <td className="px-3 py-1.5 tabular-nums">{r.sample_size}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              )}
            </div>
          </section>

          <section aria-labelledby="worst-h">
            <h2 id="worst-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Pattern più deboli per timeframe
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Fino a {TOP_N_PER_TF} pattern per TF con score qualità più basso.
            </p>
            <div className="mt-2 space-y-4">
              {worst.length === 0 ? (
                <p className="text-sm text-zinc-500">Nessun dato.</p>
              ) : (
                worst.map(({ tf, rows }) => (
                  <div key={`w-${tf}`} className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
                    <p className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-xs font-medium dark:border-zinc-800 dark:bg-zinc-900/60">
                      Timeframe <span className="font-mono">{tf}</span>
                    </p>
                    <table className="w-full min-w-[32rem] border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-zinc-200 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-900/40">
                          <th className="px-3 py-2 font-medium">Pattern</th>
                          <th className="px-3 py-2 font-medium">Qualità</th>
                          <th className="px-3 py-2 font-medium">n</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr
                            key={`w-${r.pattern_name}-${r.timeframe}-${r.pattern_quality_score}`}
                            className="border-b border-zinc-100 dark:border-zinc-800/80"
                          >
                            <td className="px-3 py-1.5 font-mono">
                              {displayTechnicalLabel(r.pattern_name)}
                            </td>
                            <td className="px-3 py-1.5 tabular-nums">
                              {r.pattern_quality_score != null
                                ? r.pattern_quality_score.toFixed(1)
                                : "—"}
                            </td>
                            <td className="px-3 py-1.5 tabular-nums">{r.sample_size}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              )}
            </div>
          </section>

          <section aria-labelledby="top-h">
            <h2 id="top-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Top opportunità correnti (score finale)
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Prime {TOP_OPPS} righe per score finale tra quelle restituite dall&apos;API.
            </p>
            <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[48rem] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <th className="px-3 py-2 font-medium">Simbolo</th>
                    <th className="px-3 py-2 font-medium">TF</th>
                    <th className="px-3 py-2 font-medium">Score finale</th>
                    <th className="px-3 py-2 font-medium">Livello</th>
                    <th className="px-3 py-2 font-medium">Pattern</th>
                  </tr>
                </thead>
                <tbody>
                  {topOpps.map((r) => (
                    <tr
                      key={`${r.exchange}-${r.symbol}-${r.timeframe}-${r.context_timestamp}`}
                      className="border-b border-zinc-100 dark:border-zinc-800/80"
                    >
                      <td className="px-3 py-2 font-mono text-xs">
                        <Link
                          href={seriesDetailHref(r.symbol, r.timeframe, r.exchange)}
                          className="text-zinc-900 underline underline-offset-2 hover:text-zinc-600 dark:text-zinc-100 dark:hover:text-zinc-300"
                        >
                          {r.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{r.timeframe}</td>
                      <td className="px-3 py-2 tabular-nums font-medium">
                        {r.final_opportunity_score.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {displayFinalOpportunityLabel(r.final_opportunity_label)}
                      </td>
                      <td className="max-w-[14rem] truncate px-3 py-2 text-xs">
                        {displayTechnicalLabel(r.latest_pattern_name)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {topOpps.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">Nessuna opportunità.</p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
