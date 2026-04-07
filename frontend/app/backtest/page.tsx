"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchBacktestPatterns,
  type BacktestAggregateRow,
} from "@/lib/api";
import { isPatternValidatedForTimeframe } from "@/lib/constants";
import { timeframeFilterLabel } from "@/lib/displayLabels";

const TIMEFRAMES = ["", "1m", "5m", "15m", "1h", "1d"] as const;

const PROVIDERS = ["", "binance", "yahoo_finance"] as const;

const ASSET_TYPES = ["", "crypto", "etf", "stock"] as const;

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(digits)}%`;
}

function fmtWinRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function sampleReliabilityCiClass(
  rel: string | null | undefined,
): string {
  if (rel === "insufficient") return "text-red-400";
  if (rel === "poor") return "text-orange-400";
  if (rel === "fair") return "text-yellow-400";
  return "text-green-400";
}

function sampleReliabilityBadgeClass(rel: string | null | undefined): string {
  if (rel === "insufficient") return "bg-red-900 text-red-300";
  if (rel === "poor") return "bg-orange-900 text-orange-300";
  if (rel === "fair") return "bg-yellow-900 text-yellow-300";
  if (rel === "good") return "bg-blue-900 text-blue-300";
  return "bg-green-900 text-green-300";
}

function significanceTextClass(sig: string | null | undefined): string {
  if (sig === "***")
    return "text-emerald-600 dark:text-emerald-400";
  if (sig === "**") return "text-sky-600 dark:text-sky-400";
  if (sig === "*") return "text-amber-600 dark:text-amber-400";
  return "text-zinc-500 dark:text-zinc-400";
}

export default function BacktestPage() {
  const [aggregates, setAggregates] = useState<BacktestAggregateRow[]>([]);
  const [patternsEvaluated, setPatternsEvaluated] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterTimeframe, setFilterTimeframe] = useState("");
  const [filterPatternName, setFilterPatternName] = useState("");
  const [filterProvider, setFilterProvider] = useState("");
  const [filterAssetType, setFilterAssetType] = useState("");
  const filterSymbolRef = useRef(filterSymbol);
  const filterTimeframeRef = useRef(filterTimeframe);
  const filterPatternNameRef = useRef(filterPatternName);
  const filterProviderRef = useRef(filterProvider);
  const filterAssetTypeRef = useRef(filterAssetType);
  filterSymbolRef.current = filterSymbol;
  filterTimeframeRef.current = filterTimeframe;
  filterPatternNameRef.current = filterPatternName;
  filterProviderRef.current = filterProvider;
  filterAssetTypeRef.current = filterAssetType;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBacktestPatterns({
        symbol: filterSymbolRef.current.trim() || undefined,
        timeframe: filterTimeframeRef.current || undefined,
        pattern_name: filterPatternNameRef.current.trim() || undefined,
        provider: filterProviderRef.current.trim() || undefined,
        asset_type: filterAssetTypeRef.current.trim() || undefined,
        limit: 5000,
      });
      setAggregates(data.aggregates);
      setPatternsEvaluated(data.patterns_evaluated);
    } catch (e) {
      setAggregates([]);
      setPatternsEvaluated(0);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedRows = useMemo(() => {
    const copy = [...aggregates];
    copy.sort((a, b) => {
      const qA = a.pattern_quality_score ?? -1;
      const qB = b.pattern_quality_score ?? -1;
      if (qB !== qA) return qB - qA;
      return `${a.pattern_name}.${a.timeframe}`.localeCompare(
        `${b.pattern_name}.${b.timeframe}`,
      );
    });
    return copy;
  }, [aggregates]);

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-6 p-6">
      <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Backtest pattern
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Rendimenti a termine dopo i pattern rilevati (+1/+3/+5/+10 candele). Lo
            score di qualità è un’euristica MVP semplice da win rate, rendimento
            medio e profondità del campione.
          </p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">
            Nota: il backtest pattern mostra rendimenti lordi (senza costi). I costi vengono inclusi
            solo nei backtest trade plan e varianti.
          </p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">
            Significatività (test one-sided, WR &gt; 50% e media return &gt; 0): *** p&lt;0.01 | ** p&lt;0.05 |
            * p&lt;0.10 | ns = non significativo
          </p>
        </div>
      </header>

      <section className="flex flex-wrap items-end gap-3" aria-label="Filtri">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Simbolo
          </span>
          <input
            className="min-w-[12rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterSymbol}
            onChange={(e) => setFilterSymbol(e.target.value)}
            placeholder="es. BTC/USDT (esatto)"
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
                {timeframeFilterLabel(tf)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Nome pattern
          </span>
          <input
            className="min-w-[14rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterPatternName}
            onChange={(e) => setFilterPatternName(e.target.value)}
            placeholder="es. impulsive_bullish_candle"
          />
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
                {p === "" ? "Tutti" : p === "yahoo_finance" ? "Yahoo Finance" : "Binance"}
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
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
        >
          Applica filtri
        </button>
      </section>

      {patternsEvaluated > 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-500">
          Righe pattern valutate: {patternsEvaluated}
        </p>
      )}

      {loading && (
        <div
          className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-600 dark:border-zinc-600 dark:text-zinc-400"
          role="status"
        >
          Caricamento backtest…
        </div>
      )}

      {!loading && error && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
          role="alert"
        >
          <strong className="font-medium">Impossibile caricare il backtest.</strong>
          <pre className="mt-2 whitespace-pre-wrap font-mono text-xs">{error}</pre>
        </div>
      )}

      {!loading && !error && sortedRows.length === 0 && (
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-8 text-center text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-400">
          Nessun aggregato per i filtri attuali (servono pattern salvati e candele
          future).
        </div>
      )}

      {!loading && !error && sortedRows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full min-w-[64rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                <th className="sticky left-0 z-10 bg-zinc-50 px-3 py-2 font-medium dark:bg-zinc-900/90">
                  Pattern
                </th>
                <th className="px-3 py-2 font-medium">TF</th>
                <th className="px-3 py-2 font-medium">Qualità</th>
                <th className="px-3 py-2 font-medium">IC 95% WR (5→3)</th>
                <th className="px-3 py-2 font-medium">Affidabilità</th>
                <th className="px-3 py-2 font-medium">Signif. WR</th>
                <th className="px-3 py-2 font-medium">Signif. ret</th>
                <th className="px-3 py-2 font-medium">n</th>
                <th className="px-3 py-2 font-medium">Media +1</th>
                <th className="px-3 py-2 font-medium">Media +3</th>
                <th className="px-3 py-2 font-medium">Media +5</th>
                <th className="px-3 py-2 font-medium">Media +10</th>
                <th className="px-3 py-2 font-medium">Vinc. +1</th>
                <th className="px-3 py-2 font-medium">Vinc. +3</th>
                <th className="px-3 py-2 font-medium">Vinc. +5</th>
                <th className="px-3 py-2 font-medium">Vinc. +10</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r) => (
                <tr
                  key={`${r.pattern_name}-${r.timeframe}`}
                  className="border-b border-zinc-100 dark:border-zinc-800/80"
                >
                  <td className="sticky left-0 bg-[var(--background)] px-3 py-2 font-mono text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span>{r.pattern_name}</span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          isPatternValidatedForTimeframe(r.pattern_name, r.timeframe)
                            ? "bg-emerald-900/50 text-emerald-400"
                            : "bg-zinc-800 text-zinc-500"
                        }`}
                      >
                        {isPatternValidatedForTimeframe(r.pattern_name, r.timeframe)
                          ? "Operativo"
                          : "Dev"}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{r.timeframe}</td>
                  <td className="px-3 py-2 tabular-nums">
                    {r.pattern_quality_score != null ? (
                      <span className="font-bold">
                        {r.pattern_quality_score.toFixed(1)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {r.win_rate_ci_lower != null &&
                    r.win_rate_ci_upper != null ? (
                      <span
                        className={`ml-0 ${sampleReliabilityCiClass(r.sample_reliability)}`}
                      >
                        [{r.win_rate_ci_lower.toFixed(0)}%–
                        {r.win_rate_ci_upper.toFixed(0)}%]
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${sampleReliabilityBadgeClass(
                        r.sample_reliability,
                      )}`}
                    >
                      n=
                      {Math.max(r.sample_size_3, r.sample_size_5)} ·{" "}
                      {r.sample_reliability ?? "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <span
                      className={`font-mono font-medium ${significanceTextClass(
                        r.win_rate_significance,
                      )}`}
                    >
                      {r.win_rate_significance ?? "—"}
                    </span>
                    {r.win_rate_pvalue != null ? (
                      <span className="ml-1 text-zinc-500">
                        p={r.win_rate_pvalue.toFixed(3)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <span
                      className={`font-mono font-medium ${significanceTextClass(
                        r.expectancy_r_significance,
                      )}`}
                    >
                      {r.expectancy_r_significance ?? "—"}
                    </span>
                    {r.expectancy_r_pvalue != null ? (
                      <span className="ml-1 text-zinc-500">
                        p={r.expectancy_r_pvalue.toFixed(3)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{r.sample_size}</td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtPct(r.avg_return_1)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtPct(r.avg_return_3)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtPct(r.avg_return_5)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtPct(r.avg_return_10)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtWinRate(r.win_rate_1)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtWinRate(r.win_rate_3)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtWinRate(r.win_rate_5)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {fmtWinRate(r.win_rate_10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
