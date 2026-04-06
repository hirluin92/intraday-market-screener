"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchTradePlanVariantBest,
  type OperationalVariantStatus,
  type TradePlanVariantBestRow,
  type TradePlanVariantStatusCounts,
  type TradePlanVariantStatusScope,
} from "@/lib/api";
import { displayTechnicalLabel } from "@/lib/displayLabels";

const TIMEFRAMES = ["", "1m", "5m", "15m", "1h", "1d"] as const;

const PROVIDERS = ["", "binance", "yahoo_finance"] as const;

const ASSET_TYPES = ["", "crypto", "etf", "stock", "index"] as const;

/** Soglia sample "alta" per colonna affidabilità (allineata al backend promoted). */
const SAMPLE_HIGH = 50;

const STATUS_SORT: Record<OperationalVariantStatus, number> = {
  promoted: 0,
  watchlist: 1,
  rejected: 2,
};

type SampleReliability = "high" | "medium" | "low";

function operationalStatusBadgeClass(s: OperationalVariantStatus): string {
  if (s === "promoted") {
    return "bg-emerald-600 text-white dark:bg-emerald-700";
  }
  if (s === "watchlist") {
    return "bg-amber-500 text-amber-950 dark:bg-amber-600 dark:text-amber-50";
  }
  return "bg-zinc-400 text-zinc-950 dark:bg-zinc-600 dark:text-zinc-100";
}

function operationalStatusLabel(s: OperationalVariantStatus): string {
  if (s === "promoted") return "Promossa";
  if (s === "watchlist") return "Watchlist";
  return "Respinta";
}

function sampleReliability(
  sampleSize: number,
  minReliable: number,
): SampleReliability {
  if (sampleSize >= SAMPLE_HIGH) return "high";
  if (sampleSize >= minReliable) return "medium";
  return "low";
}

function sampleReliabilityLabel(t: SampleReliability): string {
  if (t === "high") return "Alta";
  if (t === "medium") return "Media";
  return "Bassa";
}

function sampleReliabilityBadgeClass(t: SampleReliability): string {
  if (t === "high") {
    return "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/80 dark:text-emerald-200";
  }
  if (t === "medium") {
    return "bg-amber-100 text-amber-950 dark:bg-amber-950/50 dark:text-amber-200";
  }
  return "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-200";
}

function fmtRate(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtExp(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(3);
}

export default function TradePlanLabPage() {
  const [rows, setRows] = useState<TradePlanVariantBestRow[]>([]);
  const [totalBuckets, setTotalBuckets] = useState(0);
  const [countsByStatus, setCountsByStatus] = useState<TradePlanVariantStatusCounts>({
    promoted: 0,
    watchlist: 0,
    rejected: 0,
  });
  const [insights, setInsights] = useState<string[]>([]);
  const [patternsEvaluated, setPatternsEvaluated] = useState(0);
  const [minSampleReliable, setMinSampleReliable] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterTimeframe, setFilterTimeframe] = useState("");
  const [filterProvider, setFilterProvider] = useState("");
  const [filterAssetType, setFilterAssetType] = useState("");
  const [filterScope, setFilterScope] = useState<TradePlanVariantStatusScope>(
    "promoted_watchlist",
  );

  const filterSymbolRef = useRef(filterSymbol);
  const filterTimeframeRef = useRef(filterTimeframe);
  const filterProviderRef = useRef(filterProvider);
  const filterAssetTypeRef = useRef(filterAssetType);
  const filterScopeRef = useRef(filterScope);
  filterSymbolRef.current = filterSymbol;
  filterTimeframeRef.current = filterTimeframe;
  filterProviderRef.current = filterProvider;
  filterAssetTypeRef.current = filterAssetType;
  filterScopeRef.current = filterScope;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTradePlanVariantBest({
        symbol: filterSymbolRef.current.trim() || undefined,
        timeframe: filterTimeframeRef.current || undefined,
        provider: filterProviderRef.current.trim() || undefined,
        asset_type: filterAssetTypeRef.current.trim() || undefined,
        status_scope: filterScopeRef.current,
        limit: 300,
      });
      setRows(data.rows);
      setTotalBuckets(data.total_buckets_evaluated);
      setCountsByStatus(data.counts_by_status);
      setInsights(data.insights);
      setPatternsEvaluated(data.patterns_evaluated);
      setMinSampleReliable(data.min_sample_for_reliable_rank);
    } catch (e) {
      setRows([]);
      setTotalBuckets(0);
      setCountsByStatus({ promoted: 0, watchlist: 0, rejected: 0 });
      setInsights([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedRows = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const sa = STATUS_SORT[a.operational_status];
      const sb = STATUS_SORT[b.operational_status];
      if (sa !== sb) return sa - sb;
      if (b.sample_size !== a.sample_size) return b.sample_size - a.sample_size;
      const eA = a.expectancy_r ?? -1e9;
      const eB = b.expectancy_r ?? -1e9;
      return eB - eA;
    });
    return copy;
  }, [rows]);

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-6 p-6">
      <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Backtest
          </p>
          <h1 className="text-xl font-semibold tracking-tight">
            Trade plan — varianti migliori
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
            Una riga per bucket (pattern × timeframe × provider × asset). Ordine tabella: stato
            operativo (promossa → watchlist → respinta), poi sample decrescente, poi expectancy R.
            Di default sono nascoste le righe respinte; usa il filtro stato per includerle.
          </p>
          <p className="mt-1 max-w-3xl text-xs text-amber-800 dark:text-amber-300 bg-amber-50/60 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 rounded px-3 py-2">
            Simulazione con costi stimati round-trip inclusi: fee 0.10% + slippage 0.05% = 0.15% del
            notional per trade. L&apos;expectancy R e il ranking delle varianti riflettono i costi reali
            stimati. Parametro configurabile via API (<code className="font-mono">cost_rate</code>).
          </p>
        </div>
      </header>

      <section className="flex flex-wrap items-end gap-3" aria-label="Filtri">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Simbolo (opz.)
          </span>
          <input
            className="min-w-[11rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterSymbol}
            onChange={(e) => setFilterSymbol(e.target.value)}
            placeholder="es. BTC/USDT"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Timeframe
          </span>
          <select
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterTimeframe}
            onChange={(e) => setFilterTimeframe(e.target.value)}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf || "all"} value={tf}>
                {tf || "Tutti"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Provider
          </span>
          <select
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterProvider}
            onChange={(e) => setFilterProvider(e.target.value)}
          >
            {PROVIDERS.map((p) => (
              <option key={p || "all"} value={p}>
                {p || "Tutti"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Asset
          </span>
          <select
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterAssetType}
            onChange={(e) => setFilterAssetType(e.target.value)}
          >
            {ASSET_TYPES.map((a) => (
              <option key={a || "all"} value={a}>
                {a || "Tutti"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Vista per stato
          </span>
          <select
            className="min-w-[14rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterScope}
            onChange={(e) =>
              setFilterScope(e.target.value as TradePlanVariantStatusScope)
            }
          >
            <option value="promoted_watchlist">
              Promosse + watchlist (default, senza respinte)
            </option>
            <option value="promoted">Solo promosse</option>
            <option value="watchlist">Solo watchlist</option>
            <option value="rejected">Solo respinte</option>
            <option value="all">Tutti gli stati</option>
          </select>
        </label>
        <button
          type="button"
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-900 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
          onClick={() => void load()}
        >
          Applica filtri
        </button>
      </section>

      {loading && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status">
          Caricamento…
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
        <section aria-labelledby="tbl-h" className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/90 p-4 dark:border-emerald-900/60 dark:bg-emerald-950/40">
              <p className="text-xs font-medium uppercase tracking-wide text-emerald-800 dark:text-emerald-300">
                Promosse
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-emerald-950 dark:text-emerald-100">
                {countsByStatus.promoted}
              </p>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50/90 p-4 dark:border-amber-900/60 dark:bg-amber-950/40">
              <p className="text-xs font-medium uppercase tracking-wide text-amber-900 dark:text-amber-300">
                Watchlist
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-amber-950 dark:text-amber-100">
                {countsByStatus.watchlist}
              </p>
            </div>
            <div className="rounded-lg border border-zinc-300 bg-zinc-100/80 p-4 dark:border-zinc-600 dark:bg-zinc-900/60">
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
                Respinte
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                {countsByStatus.rejected}
              </p>
            </div>
            <div className="rounded-lg border border-sky-200 bg-sky-50/90 p-4 dark:border-sky-900/50 dark:bg-sky-950/40">
              <p className="text-xs font-medium uppercase tracking-wide text-sky-800 dark:text-sky-300">
                Totale bucket valutati
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-sky-950 dark:text-sky-100">
                {totalBuckets}
              </p>
              <p className="mt-1 text-[11px] text-sky-800/80 dark:text-sky-300/90">
                Pattern storici letti: {patternsEvaluated}
              </p>
            </div>
          </div>

          {insights.length > 0 && (
            <div
              className="rounded-lg border border-indigo-200 bg-indigo-50/80 p-4 dark:border-indigo-900/50 dark:bg-indigo-950/30"
              aria-label="Insight automatici"
            >
              <h2 className="text-xs font-semibold uppercase tracking-wide text-indigo-900 dark:text-indigo-200">
                Insight sintetici
              </h2>
              <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-indigo-950/90 dark:text-indigo-100/90">
                {insights.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h2
              id="tbl-h"
              className="text-sm font-medium text-zinc-800 dark:text-zinc-200"
            >
              Sintesi varianti
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Righe mostrate: {sortedRows.length} (filtro vista:{" "}
              {filterScope === "promoted_watchlist"
                ? "promosse + watchlist"
                : filterScope}
              ). Soglia sample affidabile ranking: ≥{minSampleReliable}.
            </p>
            <div className="mt-3 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[72rem] border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <th className="px-2 py-2 font-medium">Pattern</th>
                    <th className="px-2 py-2 font-medium">TF</th>
                    <th className="px-2 py-2 font-medium">Provider</th>
                    <th className="px-2 py-2 font-medium">Asset</th>
                    <th className="px-2 py-2 font-medium">Best variant</th>
                    <th className="px-2 py-2 font-medium">Affidabilità campione</th>
                    <th className="px-2 py-2 font-medium">Sample</th>
                    <th className="px-2 py-2 font-medium">Expectancy R</th>
                    <th className="px-2 py-2 font-medium">Stop rate</th>
                    <th className="px-2 py-2 font-medium">TP hit rate</th>
                    <th className="px-2 py-2 font-medium">Stato</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((r) => {
                    const rel = sampleReliability(r.sample_size, minSampleReliable);
                    const lowSample = r.sample_size < minSampleReliable;
                    return (
                      <tr
                        key={`${r.pattern_name}-${r.timeframe}-${r.provider}-${r.asset_type}-${r.best_variant_label}`}
                        className="border-b border-zinc-100 dark:border-zinc-800/80"
                      >
                        <td
                          className="max-w-[14rem] truncate px-2 py-1.5"
                          title={r.pattern_name}
                        >
                          {displayTechnicalLabel(r.pattern_name)}
                        </td>
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono">
                          {r.timeframe}
                        </td>
                        <td className="px-2 py-1.5 font-mono">{r.provider}</td>
                        <td className="px-2 py-1.5 font-mono">{r.asset_type}</td>
                        <td
                          className="max-w-[16rem] truncate px-2 py-1.5 font-mono text-[11px]"
                          title={r.best_variant_label}
                        >
                          {r.best_variant_label}
                        </td>
                        <td className="px-2 py-1.5">
                          <span
                            className={`inline-block rounded px-2 py-0.5 text-[11px] font-medium ${sampleReliabilityBadgeClass(rel)}`}
                            title={
                              rel === "low"
                                ? "Campione sotto la soglia minima per ranking affidabile tra varianti"
                                : undefined
                            }
                          >
                            {sampleReliabilityLabel(rel)}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 tabular-nums">{r.sample_size}</td>
                        <td
                          className={`px-2 py-1.5 tabular-nums ${lowSample ? "text-zinc-400 dark:text-zinc-500" : ""}`}
                          title={
                            lowSample
                              ? `Campione insufficiente (min. ${minSampleReliable} per confronto affidabile tra varianti)`
                              : undefined
                          }
                        >
                          {fmtExp(r.expectancy_r)}
                          {lowSample ? (
                            <span className="ml-1 text-[10px] text-zinc-400 dark:text-zinc-500">
                              (campione insufficiente)
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-1.5 tabular-nums">
                          {fmtRate(r.stop_rate_given_entry)}
                        </td>
                        <td className="px-2 py-1.5 tabular-nums">
                          {fmtRate(r.tp1_or_tp2_rate_given_entry)}
                        </td>
                        <td className="px-2 py-1.5">
                          <span
                            className={`inline-block rounded px-2 py-0.5 text-[11px] font-medium ${operationalStatusBadgeClass(r.operational_status)}`}
                          >
                            {operationalStatusLabel(r.operational_status)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {sortedRows.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">
                  Nessun bucket con la vista selezionata (prova &quot;Tutti gli stati&quot; o
                  allenta i filtri).
                </p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
