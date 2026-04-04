"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchMarketDataCandles,
  fetchMarketDataContext,
  fetchMarketDataFeatures,
  fetchMarketDataPatterns,
  fetchOpportunities,
  type CandleRow,
  type ContextRow,
  type FeatureRow,
  type OpportunityRow,
  type PatternRow,
  type TradePlanV1,
} from "@/lib/api";
import {
  alertLevelBadgeClass,
  computeSignalAlignment,
  displayAlertLevelLabel,
  displayEnumLabel,
  displayFinalOpportunityLabel,
  displayPatternTimeframeGateLabel,
  displayPatternQualityLabel,
  displaySignalAlignmentLabel,
  displayTechnicalLabel,
  signalAlignmentBadgeClass,
  tradePlanFallbackReasonIt,
  displayOperationalDecisionBadgeShort,
  operationalDecisionBadgeClass,
} from "@/lib/displayLabels";
import { SeriesCandleChart } from "@/components/SeriesCandleChart";

const ROW_LIMIT = 50;

function fmtTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString("it-IT", {
      dateStyle: "short",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

function shortNum(s: string | null | undefined, digits = 6): string {
  if (s == null || s === "") return "—";
  const n = Number(s);
  if (Number.isNaN(n)) return s;
  return n.toFixed(digits);
}

function tradeDirectionLabel(d: TradePlanV1["trade_direction"]): string {
  if (d === "long") return "Long";
  if (d === "short") return "Short";
  return "Nessuna direzione";
}

function entryStrategyLabel(s: TradePlanV1["entry_strategy"]): string {
  if (s === "breakout") return "Breakout";
  if (s === "retest") return "Retest";
  return "Conferma su chiusura";
}

function displayOperationalConfidence(s: string | undefined): string {
  if (s === "high") return "Alta";
  if (s === "medium") return "Media";
  if (s === "low") return "Bassa";
  return "Sconosciuta";
}

type VariantOpStatus = "promoted" | "watchlist" | "rejected";

function bucketVariantStatusBadgeClass(s: VariantOpStatus): string {
  if (s === "promoted") {
    return "bg-emerald-600 text-white dark:bg-emerald-700";
  }
  if (s === "watchlist") {
    return "bg-amber-500 text-amber-950 dark:bg-amber-600 dark:text-amber-50";
  }
  return "bg-zinc-400 text-zinc-950 dark:bg-zinc-600 dark:text-zinc-100";
}

function bucketVariantStatusLabel(s: VariantOpStatus): string {
  if (s === "promoted") return "Promossa";
  if (s === "watchlist") return "Watchlist";
  return "Respinta";
}

function fmtBucketExp(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(3);
}

function parseVariantStatus(s: string | null | undefined): VariantOpStatus | null {
  if (s === "promoted" || s === "watchlist" || s === "rejected") return s;
  return null;
}

function SeriesDetailInner() {
  const routeParams = useParams();
  const searchParams = useSearchParams();

  const symbol = useMemo(() => {
    const s = routeParams.symbol;
    return typeof s === "string" ? decodeURIComponent(s) : "";
  }, [routeParams.symbol]);

  const timeframe = useMemo(() => {
    const t = routeParams.timeframe;
    return typeof t === "string" ? decodeURIComponent(t) : "";
  }, [routeParams.timeframe]);

  const exchangeParam = searchParams.get("exchange")?.trim() ?? "";
  const providerParam = searchParams.get("provider")?.trim() ?? "";
  const assetTypeParam = searchParams.get("asset_type")?.trim() ?? "";

  /** Venue effettivo: query esplicita, oppure dedotta da provider (Yahoo → YAHOO_US). Senza hint → binance (link legacy). */
  const effectiveExchange =
    exchangeParam ||
    (providerParam === "yahoo_finance"
      ? "YAHOO_US"
      : providerParam === "binance"
        ? "binance"
        : "binance");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<OpportunityRow | null>(null);
  const [candles, setCandles] = useState<CandleRow[]>([]);
  const [features, setFeatures] = useState<FeatureRow[]>([]);
  const [contexts, setContexts] = useState<ContextRow[]>([]);
  const [patterns, setPatterns] = useState<PatternRow[]>([]);

  const load = useCallback(async () => {
    if (!symbol || !timeframe) return;
    setLoading(true);
    setError(null);
    try {
      const [opp, c, f, ctx, pat] = await Promise.all([
        fetchOpportunities({
          symbol,
          timeframe,
          exchange: effectiveExchange,
          provider: providerParam || undefined,
          asset_type: assetTypeParam || undefined,
          limit: 5,
        }),
        fetchMarketDataCandles({
          symbol,
          exchange: effectiveExchange,
          timeframe,
          provider: providerParam || undefined,
          asset_type: assetTypeParam || undefined,
          limit: ROW_LIMIT,
        }),
        fetchMarketDataFeatures({
          symbol,
          exchange: effectiveExchange,
          timeframe,
          provider: providerParam || undefined,
          asset_type: assetTypeParam || undefined,
          limit: ROW_LIMIT,
        }),
        fetchMarketDataContext({
          symbol,
          exchange: effectiveExchange,
          timeframe,
          provider: providerParam || undefined,
          asset_type: assetTypeParam || undefined,
          limit: ROW_LIMIT,
        }),
        fetchMarketDataPatterns({
          symbol,
          exchange: effectiveExchange,
          timeframe,
          provider: providerParam || undefined,
          asset_type: assetTypeParam || undefined,
          limit: ROW_LIMIT,
        }),
      ]);
      setSnapshot(opp.opportunities[0] ?? null);
      setCandles(c.candles);
      setFeatures(f.features);
      setContexts(ctx.contexts);
      setPatterns(pat.patterns);
    } catch (e) {
      setSnapshot(null);
      setCandles([]);
      setFeatures([]);
      setContexts([]);
      setPatterns([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, effectiveExchange, providerParam, assetTypeParam]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!symbol || !timeframe) {
    return (
      <div className="mx-auto max-w-[120rem] p-6">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Parametri serie non validi.
        </p>
        <Link href="/opportunities" className="mt-4 inline-block text-sm underline">
          Torna alle opportunità
        </Link>
      </div>
    );
  }

  const align =
    snapshot != null
      ? computeSignalAlignment(
          snapshot.score_direction,
          snapshot.latest_pattern_direction,
        )
      : null;

  const candleById = useMemo(() => {
    const m = new Map<number, CandleRow>();
    for (const c of candles) {
      m.set(c.id, c);
    }
    return m;
  }, [candles]);

  /** Una riga per candela con feature: OHLC dalla candela collegata. */
  const featureCandleRows = useMemo(
    () =>
      features.map((f) => ({
        feature: f,
        candle: candleById.get(f.candle_id) ?? null,
      })),
    [features, candleById],
  );

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-8 p-6">
      <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Dettaglio serie
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">
              <span className="font-mono">{symbol}</span>
              <span className="mx-2 text-zinc-400">·</span>
              <span className="font-mono">{timeframe}</span>
            </h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Exchange: <span className="font-mono">{effectiveExchange}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <Link
              href="/opportunities"
              className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              ← Opportunità
            </Link>
            <Link
              href="/trade-plan-lab"
              className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              Trade plan lab
            </Link>
          </div>
        </div>
      </header>

      {loading && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status">
          Caricamento dati serie…
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
          <section aria-labelledby="snap-h">
            <h2 id="snap-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Ultimo snapshot opportunità
            </h2>
            {snapshot ? (
              <div className="mt-2 grid gap-2 rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 text-sm dark:border-zinc-800 dark:bg-zinc-950/40">
                <div className="flex flex-wrap items-center gap-3 border-b border-zinc-200 pb-3 dark:border-zinc-800">
                  <span
                    className={`rounded-md px-4 py-2 text-sm font-bold uppercase tracking-wider ${operationalDecisionBadgeClass(snapshot.operational_decision)}`}
                  >
                    {displayOperationalDecisionBadgeShort(snapshot.operational_decision)}
                  </span>
                  <span>
                    Score finale:{" "}
                    <strong className="tabular-nums">
                      {snapshot.final_opportunity_score.toFixed(1)}
                    </strong>{" "}
                    <span className="text-zinc-600 dark:text-zinc-400">
                      ({displayFinalOpportunityLabel(snapshot.final_opportunity_label)})
                    </span>
                  </span>
                  <span>
                    Alert:{" "}
                    <strong>{snapshot.alert_candidate ? "sì" : "no"}</strong>
                    {" — "}
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${alertLevelBadgeClass(snapshot.alert_level)}`}
                    >
                      {displayAlertLevelLabel(snapshot.alert_level)}
                    </span>
                  </span>
                </div>
                {snapshot.decision_rationale && snapshot.decision_rationale.length > 0 ? (
                  <div
                    className="rounded-lg border border-zinc-200 bg-white/90 p-3 dark:border-zinc-700 dark:bg-zinc-900/60"
                    role="region"
                    aria-label="Motivazione decisione"
                  >
                    <p className="text-xs font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
                      Perché
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-snug text-zinc-800 dark:text-zinc-200">
                      {snapshot.decision_rationale.map((line, idx) => (
                        <li key={idx}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                  <span>
                    Score screener:{" "}
                    <strong className="tabular-nums">{snapshot.screener_score}</strong>{" "}
                    <span className="text-zinc-600 dark:text-zinc-400">
                      ({displayTechnicalLabel(snapshot.score_label)})
                    </span>
                  </span>
                  {snapshot.final_opportunity_score_before_trade_plan_backtest != null &&
                    Math.abs(
                      snapshot.final_opportunity_score_before_trade_plan_backtest -
                        snapshot.final_opportunity_score,
                    ) > 0.05 && (
                      <span className="text-zinc-600 dark:text-zinc-400" title="Prima dell'aggiustamento soft trade-plan backtest">
                        Base pre-TPB:{" "}
                        <strong className="tabular-nums text-zinc-800 dark:text-zinc-200">
                          {snapshot.final_opportunity_score_before_trade_plan_backtest.toFixed(1)}
                        </strong>
                        {snapshot.trade_plan_backtest_score_delta != null &&
                        snapshot.trade_plan_backtest_score_delta !== 0 ? (
                          <span className="ml-1">
                            (Δ {snapshot.trade_plan_backtest_score_delta > 0 ? "+" : ""}
                            {snapshot.trade_plan_backtest_score_delta.toFixed(1)})
                          </span>
                        ) : null}
                      </span>
                    )}
                  <span title="Indicatore di cautela dal backtest simulato; non filtra da solo le opportunità">
                    Confidenza operativa (TPB):{" "}
                    <strong>{displayOperationalConfidence(snapshot.operational_confidence)}</strong>
                  </span>
                  <span>
                    Dir. score:{" "}
                    <strong>{displayEnumLabel(snapshot.score_direction)}</strong>
                  </span>
                  <span>
                    Pattern:{" "}
                    <strong className="text-xs">
                      {displayTechnicalLabel(snapshot.latest_pattern_name)}
                    </strong>
                  </span>
                  <span>
                    Dir. pattern:{" "}
                    <strong>
                      {displayEnumLabel(snapshot.latest_pattern_direction)}
                    </strong>
                  </span>
                  {align != null && (
                    <span>
                      Allineamento:{" "}
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${signalAlignmentBadgeClass(align)}`}
                      >
                        {displaySignalAlignmentLabel(align)}
                      </span>
                    </span>
                  )}
                  <span>
                    Qualità pattern:{" "}
                    {snapshot.pattern_quality_score != null
                      ? snapshot.pattern_quality_score.toFixed(1)
                      : "—"}{" "}
                    ({displayPatternQualityLabel(snapshot.pattern_quality_label)})
                  </span>
                  <span>
                    Storico sul TF:{" "}
                    <strong className="text-xs">
                      {displayPatternTimeframeGateLabel(
                        snapshot.pattern_timeframe_gate_label,
                      )}
                    </strong>
                    {snapshot.pattern_timeframe_filtered_candidate ? (
                      <span className="ml-1 text-amber-700 dark:text-amber-400">
                        (filtrato)
                      </span>
                    ) : null}
                    {snapshot.pattern_timeframe_quality_ok != null && (
                      <span className="text-zinc-600 dark:text-zinc-400">
                        {" "}
                        — OK:{" "}
                        {snapshot.pattern_timeframe_quality_ok ? "sì" : "no"}
                      </span>
                    )}
                  </span>
                </div>
                {snapshot.trade_plan ? (
                  <div
                    className="mt-4 rounded-md border border-emerald-200/90 bg-emerald-50/60 p-3 dark:border-emerald-900/60 dark:bg-emerald-950/30"
                    role="region"
                    aria-label="Piano di trade versione 1"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-emerald-900 dark:text-emerald-200">
                        Piano di trade (v1)
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {(snapshot.trade_plan_source ?? "default_fallback") ===
                        "variant_backtest" ? (
                          <span className="rounded bg-emerald-700 px-2 py-0.5 text-[11px] font-medium text-white dark:bg-emerald-600">
                            Variant backtest (livelli)
                          </span>
                        ) : (
                          <span className="rounded bg-zinc-300 px-2 py-0.5 text-[11px] font-medium text-zinc-900 dark:bg-zinc-600 dark:text-zinc-100">
                            Fallback standard
                          </span>
                        )}
                      </div>
                    </div>
                    {(snapshot.trade_plan_source ?? "default_fallback") ===
                      "default_fallback" && (
                      <p className="mt-2 text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">
                        Questo setup non è supportato da una variante validata; il piano mostrato
                        è il fallback del motore base.
                      </p>
                    )}
                    <div className="mt-2 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
                      <span>
                        Direzione:{" "}
                        <strong>{tradeDirectionLabel(snapshot.trade_plan.trade_direction)}</strong>
                      </span>
                      <span>
                        Ingresso:{" "}
                        <strong>{entryStrategyLabel(snapshot.trade_plan.entry_strategy)}</strong>
                      </span>
                      <span>
                        Prezzo ingresso:{" "}
                        <strong className="tabular-nums">
                          {shortNum(snapshot.trade_plan.entry_price, 4)}
                        </strong>
                      </span>
                      <span>
                        Stop loss:{" "}
                        <strong className="tabular-nums">
                          {shortNum(snapshot.trade_plan.stop_loss, 4)}
                        </strong>
                      </span>
                      <span>
                        Take profit 1:{" "}
                        <strong className="tabular-nums">
                          {shortNum(snapshot.trade_plan.take_profit_1, 4)}
                        </strong>
                      </span>
                      <span>
                        Take profit 2:{" "}
                        <strong className="tabular-nums">
                          {shortNum(snapshot.trade_plan.take_profit_2, 4)}
                        </strong>
                      </span>
                      <span className="sm:col-span-2 lg:col-span-3">
                        Risk/reward (verso TP1):{" "}
                        <strong className="tabular-nums">
                          {snapshot.trade_plan.risk_reward_ratio != null
                            ? shortNum(snapshot.trade_plan.risk_reward_ratio, 2)
                            : "—"}
                        </strong>
                      </span>
                    </div>
                    {(snapshot.trade_plan_source ?? "default_fallback") === "default_fallback" &&
                      snapshot.trade_plan_fallback_reason && (
                        <p className="mt-3 rounded-md border border-amber-200/90 bg-amber-50/90 px-2 py-1.5 text-[11px] leading-snug text-amber-950 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-100">
                          <strong>Motivo fallback:</strong>{" "}
                          {tradePlanFallbackReasonIt(snapshot.trade_plan_fallback_reason)}
                        </p>
                      )}
                    {snapshot.latest_pattern_name ? (
                      <div className="mt-3 border-t border-emerald-200/80 pt-3 text-xs dark:border-emerald-900/50">
                        <p className="font-semibold text-emerald-900 dark:text-emerald-200">
                          Variante selezionata (bucket storico)
                        </p>
                        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                          <span>
                            Variante:{" "}
                            <strong className="font-mono text-[11px]">
                              {snapshot.selected_trade_plan_variant ?? "—"}
                            </strong>
                          </span>
                          <span>
                            Fonte piano:{" "}
                            <strong>
                              {(snapshot.trade_plan_source ?? "default_fallback") ===
                              "variant_backtest"
                                ? "variant_backtest"
                                : "default_fallback"}
                            </strong>
                          </span>
                          <span>
                            Sample variante:{" "}
                            <strong className="tabular-nums">
                              {snapshot.selected_trade_plan_variant_sample_size ?? "—"}
                            </strong>
                          </span>
                          <span>
                            Expectancy R:{" "}
                            <strong className="tabular-nums">
                              {fmtBucketExp(snapshot.selected_trade_plan_variant_expectancy_r)}
                            </strong>
                          </span>
                          <span className="sm:col-span-2">
                            Stato operativo:{" "}
                            {(() => {
                              const st = parseVariantStatus(
                                snapshot.selected_trade_plan_variant_status,
                              );
                              return st ? (
                                <span
                                  className={`inline-block rounded px-2 py-0.5 text-[11px] font-medium ${bucketVariantStatusBadgeClass(st)}`}
                                >
                                  {bucketVariantStatusLabel(st)}
                                </span>
                              ) : (
                                "—"
                              );
                            })()}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    {snapshot.trade_plan.invalidation_note ? (
                      <p className="mt-3 whitespace-pre-wrap border-t border-emerald-200/80 pt-2 text-xs leading-relaxed text-emerald-950/90 dark:border-emerald-900/50 dark:text-emerald-100/90">
                        {snapshot.trade_plan.invalidation_note}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                <p className="text-xs text-zinc-500">
                  Contesto: mercato {displayEnumLabel(snapshot.market_regime)}, vol.{" "}
                  {displayEnumLabel(snapshot.volatility_regime)}, esp.{" "}
                  {displayEnumLabel(snapshot.candle_expansion)}, bias{" "}
                  {displayEnumLabel(snapshot.direction_bias)}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                Nessuno snapshot per questa serie con i filtri attuali (pipeline non eseguita o
                dati assenti).
              </p>
            )}
          </section>

          <section aria-labelledby="chart-h">
            <h2
              id="chart-h"
              className="text-sm font-medium text-zinc-800 dark:text-zinc-200"
            >
              Grafico candele recenti
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Ultime fino a 50 candele: pattern segnati in alto, fascia ambra sulla candela di
              contesto dell&apos;opportunità (se disponibile).
            </p>
            <div className="mt-2">
              <SeriesCandleChart
                candles={candles}
                patterns={patterns}
                opportunityContextTimestamp={snapshot?.context_timestamp}
              />
            </div>
          </section>

          <section aria-labelledby="ctx-h">
            <h2 id="ctx-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Storico contesto recente
            </h2>
            <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[48rem] border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <th className="px-2 py-2 font-medium">Orario</th>
                    <th className="px-2 py-2 font-medium">Mercato</th>
                    <th className="px-2 py-2 font-medium">Volatilità</th>
                    <th className="px-2 py-2 font-medium">Espansione</th>
                    <th className="px-2 py-2 font-medium">Bias</th>
                  </tr>
                </thead>
                <tbody>
                  {contexts.map((r: ContextRow) => (
                    <tr
                      key={r.id}
                      className="border-b border-zinc-100 dark:border-zinc-800/80"
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 text-zinc-600 dark:text-zinc-400">
                        {fmtTs(r.timestamp)}
                      </td>
                      <td className="px-2 py-1.5">{displayEnumLabel(r.market_regime)}</td>
                      <td className="px-2 py-1.5">
                        {displayEnumLabel(r.volatility_regime)}
                      </td>
                      <td className="px-2 py-1.5">
                        {displayEnumLabel(r.candle_expansion)}
                      </td>
                      <td className="px-2 py-1.5">{displayEnumLabel(r.direction_bias)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {contexts.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">Nessuna riga contesto.</p>
              )}
            </div>
          </section>

          <section aria-labelledby="pat-h">
            <h2 id="pat-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Storico pattern recente
            </h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">
              Pattern rilevati sulla serie (più recenti in alto).
            </p>
            <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[42rem] border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <th className="px-2 py-2 font-medium" title="timestamp">
                      Orario
                    </th>
                    <th className="px-2 py-2 font-medium" title="pattern_name">
                      Nome pattern
                    </th>
                    <th className="px-2 py-2 font-medium" title="direction">
                      Direzione pattern
                    </th>
                    <th className="px-2 py-2 font-medium" title="pattern_strength">
                      Forza pattern
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {patterns.map((r: PatternRow) => (
                    <tr
                      key={r.id}
                      className="border-b border-zinc-100 dark:border-zinc-800/80"
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 text-zinc-600 dark:text-zinc-400">
                        {fmtTs(r.timestamp)}
                      </td>
                      <td
                        className="max-w-[18rem] truncate px-2 py-1.5"
                        title={r.pattern_name}
                      >
                        {displayTechnicalLabel(r.pattern_name)}
                      </td>
                      <td className="px-2 py-1.5">{displayEnumLabel(r.direction)}</td>
                      <td className="px-2 py-1.5 tabular-nums">{r.pattern_strength}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {patterns.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">Nessun pattern rilevato.</p>
              )}
            </div>
          </section>

          <section aria-labelledby="fc-h">
            <h2 id="fc-h" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Ultime feature/candele
            </h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">
              Una riga per candela con feature: open/high/low/close dalla candela; body_size,
              range_size, close_position_in_range, pct_return_1 e volume_ratio_vs_prev dalla
              feature.
            </p>
            <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[76rem] border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <th className="px-2 py-2 font-medium">Orario</th>
                    <th className="px-2 py-2 font-medium" title="open">
                      Apertura
                    </th>
                    <th className="px-2 py-2 font-medium" title="high">
                      Massimo
                    </th>
                    <th className="px-2 py-2 font-medium" title="low">
                      Minimo
                    </th>
                    <th className="px-2 py-2 font-medium" title="close">
                      Chiusura
                    </th>
                    <th className="px-2 py-2 font-medium" title="body_size">
                      Corpo (body)
                    </th>
                    <th className="px-2 py-2 font-medium" title="range_size">
                      Range
                    </th>
                    <th className="px-2 py-2 font-medium" title="close_position_in_range">
                      Chiusura nel range
                    </th>
                    <th className="px-2 py-2 font-medium" title="pct_return_1">
                      % rend. 1
                    </th>
                    <th className="px-2 py-2 font-medium" title="volume_ratio_vs_prev">
                      Vol. / prec.
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {featureCandleRows.map(({ feature: r, candle: c }) => (
                    <tr
                      key={r.id}
                      className="border-b border-zinc-100 dark:border-zinc-800/80"
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 text-zinc-600 dark:text-zinc-400">
                        {fmtTs(r.timestamp)}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {c ? shortNum(c.open, 2) : "—"}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {c ? shortNum(c.high, 2) : "—"}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {c ? shortNum(c.low, 2) : "—"}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {c ? shortNum(c.close, 2) : "—"}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">{shortNum(r.body_size)}</td>
                      <td className="px-2 py-1.5 tabular-nums">{shortNum(r.range_size)}</td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {shortNum(r.close_position_in_range, 4)}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {shortNum(r.pct_return_1)}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {shortNum(r.volume_ratio_vs_prev)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {features.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">
                  Nessuna feature per questa serie (eseguire la pipeline di estrazione feature).
                </p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default function SeriesDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[120rem] p-6 text-sm text-zinc-600 dark:text-zinc-400">
          Caricamento…
        </div>
      }
    >
      <SeriesDetailInner />
    </Suspense>
  );
}
