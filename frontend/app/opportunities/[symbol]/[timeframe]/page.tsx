"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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
  computeSignalAlignment,
  displayAlertLevelLabel,
  displayEnumLabel,
  displayFinalOpportunityLabel,
  displayPatternTimeframeGateLabel,
  displayPatternQualityLabel,
  displaySignalAlignmentLabel,
  displayTechnicalLabel,
  operationalDecisionBadgeClass,
  displayOperationalDecisionBadgeShort,
  tradePlanFallbackReasonIt,
  alertLevelBadgeClass,
  signalAlignmentBadgeClass,
} from "@/lib/displayLabels";
import { SeriesCandleChart } from "@/components/SeriesCandleChart";
import { TradePlanPositionSizingCard } from "@/components/TradePlanPositionSizingCard";

const ROW_LIMIT = 50;

function fmtTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtPrice(s: string | null | undefined): string {
  if (s == null || s === "") return "—";
  const n = Number(s);
  if (Number.isNaN(n)) return s;
  return n.toPrecision(6).replace(/\.?0+$/, "");
}

function fmtRR(s: string | null | undefined): string {
  if (s == null || s === "") return "—";
  const n = Number(s);
  return Number.isNaN(n) ? "—" : `${n.toFixed(2)}:1`;
}

function dirLabel(d: TradePlanV1["trade_direction"]) {
  if (d === "long") return { text: "LONG ↑", cls: "bg-emerald-500 text-white" };
  if (d === "short") return { text: "SHORT ↓", cls: "bg-rose-500 text-white" };
  return { text: "NESSUNA DIREZIONE", cls: "bg-zinc-400 text-zinc-900" };
}

function entryLabel(s: TradePlanV1["entry_strategy"]) {
  return s === "breakout" ? "Breakout" : s === "retest" ? "Retest" : "Chiusura barra";
}

function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${className}`}
    >
      {children}
    </span>
  );
}

function ContextRow2({ ctx }: { ctx: ContextRow }) {
  return (
    <tr className="border-b border-zinc-100 dark:border-zinc-800/60 text-xs">
      <td className="px-3 py-1.5 text-zinc-500 whitespace-nowrap">{fmtTs(ctx.timestamp)}</td>
      <td className="px-3 py-1.5">{displayEnumLabel(ctx.market_regime)}</td>
      <td className="px-3 py-1.5">{displayEnumLabel(ctx.volatility_regime)}</td>
      <td className="px-3 py-1.5">{displayEnumLabel(ctx.candle_expansion)}</td>
      <td className="px-3 py-1.5 font-medium">{displayEnumLabel(ctx.direction_bias)}</td>
    </tr>
  );
}

function PatternRowUI({ p }: { p: PatternRow }) {
  return (
    <tr className="border-b border-zinc-100 dark:border-zinc-800/60 text-xs">
      <td className="px-3 py-1.5 text-zinc-500 whitespace-nowrap">{fmtTs(p.timestamp)}</td>
      <td className="px-3 py-1.5 font-medium">{displayTechnicalLabel(p.pattern_name)}</td>
      <td className="px-3 py-1.5">{displayEnumLabel(p.direction)}</td>
      <td className="px-3 py-1.5 tabular-nums text-zinc-600 dark:text-zinc-400">
        {Number(p.pattern_strength).toFixed(3)}
      </td>
    </tr>
  );
}

function DecisionCard({ snap }: { snap: OpportunityRow }) {
  const align = computeSignalAlignment(snap.score_direction, snap.latest_pattern_direction);
  const dir = dirLabel(snap.trade_plan?.trade_direction ?? "none");

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 overflow-hidden shadow-sm">
      <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
        <span
          className={`rounded-lg px-4 py-2 text-sm font-bold tracking-wide ${operationalDecisionBadgeClass(snap.operational_decision)}`}
        >
          {displayOperationalDecisionBadgeShort(snap.operational_decision)}
        </span>
        {snap.trade_plan && snap.trade_plan.trade_direction !== "none" && (
          <span className={`rounded-lg px-3 py-1.5 text-sm font-bold tracking-wide ${dir.cls}`}>
            {dir.text}
          </span>
        )}
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${alertLevelBadgeClass(snap.alert_level)}`}
        >
          {displayAlertLevelLabel(snap.alert_level)}
        </span>
        <div className="ml-auto flex items-baseline gap-1.5">
          <span className="text-2xl font-bold tabular-nums">{snap.final_opportunity_score.toFixed(1)}</span>
          <span className="text-sm text-zinc-500">{displayFinalOpportunityLabel(snap.final_opportunity_label)}</span>
        </div>
      </div>

      {snap.decision_rationale && snap.decision_rationale.length > 0 && (
        <div className="px-5 py-3 bg-zinc-50/60 dark:bg-zinc-950/40 border-b border-zinc-100 dark:border-zinc-800">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1.5">Perché</p>
          <ul className="space-y-0.5">
            {snap.decision_rationale.map((line, i) => (
              <li key={i} className="text-sm text-zinc-700 dark:text-zinc-300 flex gap-2">
                <span className="text-zinc-400 shrink-0">·</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-zinc-100 dark:divide-zinc-800">
        <Metric label="Score screener" value={`${snap.screener_score}/12`} />
        <Metric
          label="Allineamento"
          value={
            <Pill className={signalAlignmentBadgeClass(align)}>
              {displaySignalAlignmentLabel(align)}
            </Pill>
          }
        />
        <Metric
          label="Qualità pattern"
          value={`${snap.pattern_quality_score != null ? snap.pattern_quality_score.toFixed(1) : "—"} · ${displayPatternQualityLabel(snap.pattern_quality_label)}`}
        />
        <Metric
          label="Storico TF"
          value={displayPatternTimeframeGateLabel(snap.pattern_timeframe_gate_label)}
          highlight={snap.pattern_timeframe_filtered_candidate ? "warn" : undefined}
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-zinc-100 dark:divide-zinc-800 border-t border-zinc-100 dark:border-zinc-800">
        <Metric label="Mercato" value={displayEnumLabel(snap.market_regime)} />
        <Metric label="Volatilità" value={displayEnumLabel(snap.volatility_regime)} />
        <Metric label="Espansione" value={displayEnumLabel(snap.candle_expansion)} />
        <Metric label="Bias dir." value={displayEnumLabel(snap.direction_bias)} />
      </div>

      {snap.latest_pattern_name && (
        <div className="px-5 py-3 border-t border-zinc-100 dark:border-zinc-800 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span className="text-zinc-500">Pattern:</span>
          <span className="font-medium">{displayTechnicalLabel(snap.latest_pattern_name)}</span>
          <span className="text-zinc-500">dir.:</span>
          <span>{displayEnumLabel(snap.latest_pattern_direction)}</span>
          {snap.pattern_age_bars != null && (
            <>
              <span className="text-zinc-500">età:</span>
              <span
                className={snap.pattern_stale ? "font-medium text-amber-600 dark:text-amber-400" : ""}
              >
                {snap.pattern_age_bars} barre
                {snap.pattern_stale ? " ⚠ datato" : ""}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  highlight,
}: {
  label: string;
  value: ReactNode;
  highlight?: "warn" | "ok";
}) {
  return (
    <div className="px-4 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">{label}</p>
      <p
        className={`text-sm font-medium ${highlight === "warn" ? "text-amber-600 dark:text-amber-400" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}

function TradePlanCard({ snap }: { snap: OpportunityRow }) {
  const plan = snap.trade_plan;
  if (!plan || plan.trade_direction === "none") return null;

  const isVariant = snap.trade_plan_source === "variant_backtest";
  const dir = dirLabel(plan.trade_direction);

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 overflow-hidden shadow-sm">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
        <h2 className="font-semibold text-sm">Piano di trade</h2>
        {isVariant ? (
          <Pill className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200">
            ✓ Variant backtest
          </Pill>
        ) : (
          <Pill className="bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            Fallback standard
          </Pill>
        )}
        <span className={`rounded-lg px-3 py-1 text-xs font-bold ${dir.cls}`}>{dir.text}</span>
      </div>

      {!isVariant && snap.trade_plan_fallback_reason && (
        <div className="px-5 py-2.5 bg-amber-50/80 dark:bg-amber-950/20 border-b border-amber-200/80 dark:border-amber-900/40 text-xs text-amber-800 dark:text-amber-200">
          {tradePlanFallbackReasonIt(snap.trade_plan_fallback_reason)}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-zinc-100 dark:divide-zinc-800">
        <Metric label="Ingresso" value={fmtPrice(plan.entry_price)} />
        <Metric label="Stop loss" value={fmtPrice(plan.stop_loss)} />
        <Metric label="TP1" value={fmtPrice(plan.take_profit_1)} />
        <Metric label="TP2" value={fmtPrice(plan.take_profit_2)} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 divide-x divide-zinc-100 dark:divide-zinc-800 border-t border-zinc-100 dark:border-zinc-800">
        <Metric label="R:R verso TP1" value={fmtRR(plan.risk_reward_ratio)} />
        <Metric label="Strategia ingresso" value={entryLabel(plan.entry_strategy)} />
        {isVariant && snap.selected_trade_plan_variant && (
          <Metric
            label="Variante usata"
            value={<span className="font-mono text-[11px]">{snap.selected_trade_plan_variant}</span>}
          />
        )}
      </div>

      {isVariant && snap.selected_trade_plan_variant_status && (
        <div className="px-5 py-3 border-t border-zinc-100 dark:border-zinc-800 flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
          <span>
            Stato:{" "}
            <strong
              className={
                snap.selected_trade_plan_variant_status === "promoted"
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-amber-700 dark:text-amber-300"
              }
            >
              {snap.selected_trade_plan_variant_status === "promoted" ? "Promossa" : "Watchlist"}
            </strong>
          </span>
          {snap.selected_trade_plan_variant_sample_size != null && (
            <span>
              Campione: <strong>{snap.selected_trade_plan_variant_sample_size}</strong>
            </span>
          )}
          {snap.selected_trade_plan_variant_expectancy_r != null && (
            <span>
              Expectancy R: <strong>{snap.selected_trade_plan_variant_expectancy_r.toFixed(3)}</strong>
            </span>
          )}
        </div>
      )}

      {plan.invalidation_note && (
        <details className="border-t border-zinc-100 dark:border-zinc-800">
          <summary className="px-5 py-3 text-xs text-zinc-500 cursor-pointer hover:text-zinc-700 dark:hover:text-zinc-300 select-none">
            Note invalidazione ▾
          </summary>
          <p className="px-5 pb-4 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap">
            {plan.invalidation_note}
          </p>
        </details>
      )}

      <div className="border-t-2 border-zinc-100 dark:border-zinc-800 mt-1">
        <TradePlanPositionSizingCard
          tradePlan={plan}
          opportunityScore={snap.final_opportunity_score}
          variantStatus={snap.selected_trade_plan_variant_status}
        />
      </div>
    </div>
  );
}

function Section({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="group">
      <summary className="flex items-center gap-2 cursor-pointer select-none list-none mb-3 [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{title}</span>
        <span className="text-xs text-zinc-400 group-open:rotate-90 transition-transform">▶</span>
      </summary>
      {children}
    </details>
  );
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

  const effectiveExchange =
    exchangeParam ||
    (providerParam === "yahoo_finance" ? "YAHOO_US" : providerParam === "binance" ? "binance" : "binance");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<OpportunityRow | null>(null);
  const [candles, setCandles] = useState<CandleRow[]>([]);
  const [features, setFeatures] = useState<FeatureRow[]>([]);
  const [contexts, setContexts] = useState<ContextRow[]>([]);
  const [patterns, setPatterns] = useState<PatternRow[]>([]);
  const [failedSections, setFailedSections] = useState<string[]>([]);

  const load = useCallback(async () => {
    if (!symbol || !timeframe) return;
    setLoading(true);
    setError(null);
    try {
      // allSettled: candele/features/context/pattern possono fallire indipendentemente
      // senza bloccare lo snapshot dell'opportunità principale
      const [oppResult, cResult, fResult, ctxResult, patResult] =
        await Promise.allSettled([
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

      if (oppResult.status === "rejected") throw oppResult.reason;
      setSnapshot(oppResult.value.opportunities[0] ?? null);
      setCandles(cResult.status === "fulfilled" ? cResult.value.candles : []);
      setFeatures(fResult.status === "fulfilled" ? fResult.value.features : []);
      setContexts(ctxResult.status === "fulfilled" ? ctxResult.value.contexts : []);
      setPatterns(patResult.status === "fulfilled" ? patResult.value.patterns : []);

      const failed: string[] = [];
      if (cResult.status === "rejected") failed.push("Grafico candele");
      if (fResult.status === "rejected") failed.push("Indicatori");
      if (ctxResult.status === "rejected") failed.push("Contesto");
      if (patResult.status === "rejected") failed.push("Pattern recenti");
      setFailedSections(failed);
    } catch (e) {
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
      <div className="max-w-2xl mx-auto p-6">
        <p className="text-sm text-zinc-500">Parametri serie non validi.</p>
        <Link href="/opportunities" className="mt-3 inline-block text-sm underline">
          ← Torna
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl flex flex-col gap-6 p-4 sm:p-6">
      {failedSections.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-700/50 bg-amber-950/30 px-4 py-2.5 text-sm text-amber-300">
          <span className="shrink-0">⚠</span>
          <span>
            Dati parziali — sezioni non disponibili:{" "}
            <span className="font-semibold">{failedSections.join(", ")}</span>.
            Il backend potrebbe essere temporaneamente irraggiungibile.
          </span>
        </div>
      )}
      <div className="flex items-center gap-2 text-sm text-zinc-500 flex-wrap">
        <Link href="/opportunities" className="hover:text-zinc-800 dark:hover:text-zinc-200">
          Opportunità
        </Link>
        <span>/</span>
        <span className="font-mono font-medium text-zinc-800 dark:text-zinc-200">{symbol}</span>
        <span>/</span>
        <span className="font-mono text-zinc-600 dark:text-zinc-400">{timeframe}</span>
        <span className="text-zinc-400">· {effectiveExchange}</span>
        <div className="ml-auto flex items-center gap-2">
          <Link
            href="/trade-plan-lab"
            className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 underline"
          >
            Trade plan lab
          </Link>
          <button
            type="button"
            onClick={() => void load()}
            className="text-xs border border-zinc-200 dark:border-zinc-700 rounded px-2 py-1 hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            ↻ Aggiorna
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-3 py-12 justify-center text-sm text-zinc-400">
          <span className="inline-block w-4 h-4 border-2 border-zinc-300 border-t-zinc-600 rounded-full animate-spin" />
          Caricamento…
        </div>
      )}

      {!loading && error && (
        <div className="rounded-xl border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-4 text-sm text-red-800 dark:text-red-200">
          <strong>Errore:</strong> {error}
        </div>
      )}

      {!loading && !error && !snapshot && (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-8 text-center text-sm text-zinc-500">
          Nessuno snapshot per questa serie. Esegui prima la pipeline.
        </div>
      )}

      {!loading && !error && snapshot && (
        <>
          <DecisionCard snap={snapshot} />

          <Section title="Grafico candele recenti" defaultOpen>
            <SeriesCandleChart
              candles={candles}
              patterns={patterns}
              timeframe={timeframe}
              opportunityContextTimestamp={snapshot.context_timestamp}
            />
          </Section>

          {snapshot.trade_plan && snapshot.trade_plan.trade_direction !== "none" ? (
            <TradePlanCard snap={snapshot} />
          ) : (
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 px-5 py-4 text-sm text-zinc-500 bg-zinc-50 dark:bg-zinc-900/40">
              Nessun piano operativo (direzione non sufficiente o dati OHLC assenti).
            </div>
          )}

          <Section title={`Storico contesto (${contexts.length} righe)`}>
            <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[32rem] border-collapse text-left">
                <thead>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60 text-xs text-zinc-500">
                    <th className="px-3 py-2 font-medium">Orario</th>
                    <th className="px-3 py-2 font-medium">Mercato</th>
                    <th className="px-3 py-2 font-medium">Volatilità</th>
                    <th className="px-3 py-2 font-medium">Espansione</th>
                    <th className="px-3 py-2 font-medium">Bias</th>
                  </tr>
                </thead>
                <tbody>
                  {contexts.map((r) => (
                    <ContextRow2 key={r.id} ctx={r} />
                  ))}
                </tbody>
              </table>
              {contexts.length === 0 && <p className="p-4 text-sm text-zinc-500">Nessuna riga.</p>}
            </div>
          </Section>

          <Section title={`Pattern rilevati (${patterns.length})`}>
            <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[28rem] border-collapse text-left">
                <thead>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60 text-xs text-zinc-500">
                    <th className="px-3 py-2 font-medium">Orario</th>
                    <th className="px-3 py-2 font-medium">Pattern</th>
                    <th className="px-3 py-2 font-medium">Dir.</th>
                    <th className="px-3 py-2 font-medium">Forza</th>
                  </tr>
                </thead>
                <tbody>
                  {patterns.map((p) => (
                    <PatternRowUI key={p.id} p={p} />
                  ))}
                </tbody>
              </table>
              {patterns.length === 0 && <p className="p-4 text-sm text-zinc-500">Nessun pattern.</p>}
            </div>
          </Section>

          <details className="group">
            <summary className="flex items-center gap-2 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
              <span className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300">
                Mostra dati tecnici avanzati (feature candele, TPB, score intermedi) ▶
              </span>
            </summary>
            <div className="mt-4 space-y-4">
              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-100 dark:divide-zinc-800">
                <div className="px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-widest text-zinc-400 mb-2">
                    Score dettaglio
                  </p>
                  <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
                    <AdvRow
                      k="Score pre-TPB"
                      v={
                        snapshot.final_opportunity_score_before_trade_plan_backtest?.toFixed(1) ?? "—"
                      }
                    />
                    <AdvRow k="Score finale" v={snapshot.final_opportunity_score.toFixed(1)} />
                    <AdvRow
                      k="Delta TPB"
                      v={
                        snapshot.trade_plan_backtest_score_delta
                          ? `${snapshot.trade_plan_backtest_score_delta > 0 ? "+" : ""}${snapshot.trade_plan_backtest_score_delta.toFixed(2)}`
                          : "0"
                      }
                    />
                    <AdvRow k="Confidenza TPB" v={snapshot.operational_confidence ?? "—"} />
                    <AdvRow
                      k="Expectancy R (TPB)"
                      v={snapshot.trade_plan_backtest_expectancy_r?.toFixed(3) ?? "—"}
                    />
                    <AdvRow k="Campione TPB" v={snapshot.trade_plan_backtest_sample_size?.toString() ?? "—"} />
                  </dl>
                </div>
              </div>
              <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                <p className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 px-3 py-2 text-xs font-semibold text-zinc-500">
                  Feature candele (ultime {features.length})
                </p>
                <table className="w-full min-w-[60rem] border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-500">
                      {["Orario", "O", "H", "L", "C", "Corpo", "Range", "Cl/range", "Rend.1", "Vol./prec"].map(
                        (h) => (
                          <th key={h} className="px-2 py-2 font-medium">
                            {h}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {features.map((f) => {
                      const c = candles.find((x) => x.id === f.candle_id);
                      return (
                        <tr key={f.id} className="border-b border-zinc-100 dark:border-zinc-800/60">
                          <td className="px-2 py-1.5 text-zinc-500 whitespace-nowrap">{fmtTs(f.timestamp)}</td>
                          <td className="px-2 py-1.5 tabular-nums">{c ? fmtPrice(c.open) : "—"}</td>
                          <td className="px-2 py-1.5 tabular-nums">{c ? fmtPrice(c.high) : "—"}</td>
                          <td className="px-2 py-1.5 tabular-nums">{c ? fmtPrice(c.low) : "—"}</td>
                          <td className="px-2 py-1.5 tabular-nums">{c ? fmtPrice(c.close) : "—"}</td>
                          <td className="px-2 py-1.5 tabular-nums">{fmtPrice(f.body_size)}</td>
                          <td className="px-2 py-1.5 tabular-nums">{fmtPrice(f.range_size)}</td>
                          <td className="px-2 py-1.5 tabular-nums">
                            {Number(f.close_position_in_range).toFixed(3)}
                          </td>
                          <td className="px-2 py-1.5 tabular-nums">
                            {f.pct_return_1 ? Number(f.pct_return_1).toFixed(4) : "—"}
                          </td>
                          <td className="px-2 py-1.5 tabular-nums">
                            {f.volume_ratio_vs_prev ? Number(f.volume_ratio_vs_prev).toFixed(3) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {features.length === 0 && <p className="p-4 text-sm text-zinc-500">Nessuna feature.</p>}
              </div>
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function AdvRow({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-zinc-400 mb-0.5">{k}</dt>
      <dd className="font-mono font-medium">{v}</dd>
    </div>
  );
}

export default function SeriesDetailPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">Caricamento…</div>}>
      <SeriesDetailInner />
    </Suspense>
  );
}
