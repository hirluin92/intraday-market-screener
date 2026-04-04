"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchOpportunities,
  postPipelineRefresh,
  seriesDetailHref,
  type OpportunityRow,
  type PipelineRefreshRequest,
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
  FONTE_PIANO_LEGENDA,
  fontePianoListLabel,
  fontePianoListTitle,
  displayOperationalDecisionListLabel,
  operationalDecisionListCellClass,
  signalAlignmentBadgeClass,
  timeframeFilterLabel,
  TOOLTIP_ALLINEAMENTO_SEGNALE_IT,
  TOOLTIP_DIR_PATTERN_IT,
  TOOLTIP_DIR_SCORE_IT,
} from "@/lib/displayLabels";

/** Filtri lista opportunità (multi-mercato: include 1d / 5m Yahoo). */
const TIMEFRAME_FILTER_OPTIONS = ["", "1m", "5m", "15m", "1h", "1d"] as const;

const PROVIDER_FILTER_OPTIONS = ["", "binance", "yahoo_finance"] as const;

const ASSET_TYPE_FILTER_OPTIONS = ["", "crypto", "etf", "stock", "index"] as const;

/** Filtro semaforo (valori API). */
const DECISION_FILTER_OPTIONS = ["", "operable", "monitor", "discard"] as const;

function formatTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

function formatStrength(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return String(v);
  return v;
}

/** Righe fallback meno enfatiche delle varianti promosse (UI). */
function opportunityRowClass(r: OpportunityRow): string {
  const base =
    "cursor-pointer border-b border-zinc-100 dark:border-zinc-800/80";
  const src = r.trade_plan_source ?? "default_fallback";
  if (src === "default_fallback") {
    return `${base} bg-zinc-50/60 text-zinc-600 hover:bg-zinc-100/80 dark:bg-zinc-950/40 dark:text-zinc-400 dark:hover:bg-zinc-900/50`;
  }
  if (r.selected_trade_plan_variant_status === "promoted") {
    return `${base} hover:bg-zinc-50 dark:hover:bg-zinc-900/50`;
  }
  return `${base} bg-sky-50/25 hover:bg-sky-50/40 dark:bg-sky-950/20 dark:hover:bg-sky-950/35`;
}

function AllineamentoSegnaleBadge({ row }: { row: OpportunityRow }) {
  const a = computeSignalAlignment(
    row.score_direction,
    row.latest_pattern_direction,
  );
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${signalAlignmentBadgeClass(a)}`}
      title={`Valori: score ${displayEnumLabel(row.score_direction)}, pattern ${displayEnumLabel(row.latest_pattern_direction)}. ${TOOLTIP_ALLINEAMENTO_SEGNALE_IT}`}
    >
      {displaySignalAlignmentLabel(a)}
    </span>
  );
}

export default function OpportunitiesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<OpportunityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterTimeframe, setFilterTimeframe] = useState<string>("");
  const [filterProvider, setFilterProvider] = useState<string>("");
  const [filterAssetType, setFilterAssetType] = useState<string>("");
  const [filterDecision, setFilterDecision] = useState<string>("");
  const filterSymbolRef = useRef(filterSymbol);
  const filterTimeframeRef = useRef(filterTimeframe);
  const filterProviderRef = useRef(filterProvider);
  const filterAssetTypeRef = useRef(filterAssetType);
  const filterDecisionRef = useRef(filterDecision);
  filterSymbolRef.current = filterSymbol;
  filterTimeframeRef.current = filterTimeframe;
  filterProviderRef.current = filterProvider;
  filterAssetTypeRef.current = filterAssetType;
  filterDecisionRef.current = filterDecision;

  /** Provider esplicito per la pipeline (nessun default nascosto sul venue). */
  const [pipeProvider, setPipeProvider] = useState<"binance" | "yahoo_finance">(
    "binance",
  );
  /** Override opzionale del venue (es. YAHOO_US); se vuoto il backend usa il default per provider. */
  const [pipeExchangeOverride, setPipeExchangeOverride] = useState("");
  const [pipeSymbol, setPipeSymbol] = useState("");
  const [pipeTimeframe, setPipeTimeframe] = useState("");
  const [pipeIngestLimit, setPipeIngestLimit] = useState(100);
  const [pipeExtractLimit, setPipeExtractLimit] = useState(500);
  const [pipeLookback, setPipeLookback] = useState(20);
  const [pipeLoading, setPipeLoading] = useState(false);
  const [pipeMessage, setPipeMessage] = useState<string | null>(null);
  const [pipeError, setPipeError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOpportunities({
        symbol: filterSymbolRef.current.trim() || undefined,
        timeframe: filterTimeframeRef.current || undefined,
        provider: filterProviderRef.current.trim() || undefined,
        asset_type: filterAssetTypeRef.current.trim() || undefined,
        decision: filterDecisionRef.current.trim() || undefined,
      });
      setRows(data.opportunities);
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function runPipelineRefresh() {
    setPipeLoading(true);
    setPipeMessage(null);
    setPipeError(null);
    const body: PipelineRefreshRequest = {
      provider: pipeProvider,
      ingest_limit: pipeIngestLimit,
      extract_limit: pipeExtractLimit,
      lookback: pipeLookback,
    };
    if (pipeExchangeOverride.trim()) body.exchange = pipeExchangeOverride.trim();
    if (pipeSymbol.trim()) body.symbol = pipeSymbol.trim();
    if (pipeTimeframe.trim()) body.timeframe = pipeTimeframe.trim();
    try {
      await postPipelineRefresh(body);
      setPipeMessage("Aggiornamento pipeline completato.");
      await load();
    } catch (e) {
      setPipeError(e instanceof Error ? e.message : String(e));
    } finally {
      setPipeLoading(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-6 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-4 border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Opportunità
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Ultimi snapshot dello screener con eventuali suggerimenti sui pattern (dall’API).
            La colonna Alert indica i candidati alert MVP (regole lato server). Clicca una riga per
            aprire il dettaglio della serie.
          </p>
        </div>
        <div className="flex gap-4 text-sm">
          <Link
            href="/"
            className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Home
          </Link>
          <Link
            href="/backtest"
            className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Backtest
          </Link>
          <Link
            href="/trade-plan-lab"
            className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Trade plan lab
          </Link>
          <Link
            href="/diagnostica"
            className="text-zinc-600 underline underline-offset-4 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Diagnostica
          </Link>
        </div>
      </header>

      <section
        className="rounded-lg border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-800 dark:bg-zinc-950/50"
        aria-label="Aggiornamento pipeline"
      >
        <h2 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          Aggiornamento pipeline
        </h2>
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
          Esegue ingest → features → context → patterns (come POST /pipeline/refresh).
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Provider</span>
            <select
              className="min-w-[10rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeProvider}
              onChange={(e) =>
                setPipeProvider(e.target.value as "binance" | "yahoo_finance")
              }
            >
              <option value="binance">Binance (crypto)</option>
              <option value="yahoo_finance">Yahoo Finance (US)</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span
              className="text-zinc-600 dark:text-zinc-400"
              title="Opzionale: sovrascrive il venue (es. YAHOO_US). Vuoto = default per provider."
            >
              Venue (opz.)
            </span>
            <input
              className="min-w-[8rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeExchangeOverride}
              onChange={(e) => setPipeExchangeOverride(e.target.value)}
              placeholder="default automatico"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Simbolo</span>
            <input
              className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeSymbol}
              onChange={(e) => setPipeSymbol(e.target.value)}
              placeholder="opzionale, es. BTC/USDT"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Timeframe</span>
            <select
              className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeTimeframe}
              onChange={(e) => setPipeTimeframe(e.target.value)}
            >
              {TIMEFRAME_FILTER_OPTIONS.map((tf) => (
                <option key={tf || "all"} value={tf}>
                  {timeframeFilterLabel(tf)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Limite ingest</span>
            <input
              type="number"
              min={1}
              max={1500}
              className="w-24 rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeIngestLimit}
              onChange={(e) => setPipeIngestLimit(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Limite extract</span>
            <input
              type="number"
              min={1}
              max={10000}
              className="w-24 rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeExtractLimit}
              onChange={(e) => setPipeExtractLimit(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-zinc-600 dark:text-zinc-400">Lookback</span>
            <input
              type="number"
              min={3}
              max={200}
              className="w-20 rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              value={pipeLookback}
              onChange={(e) => setPipeLookback(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            disabled={pipeLoading}
            onClick={() => void runPipelineRefresh()}
            className="rounded bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {pipeLoading ? "Esecuzione…" : "Esegui aggiornamento pipeline"}
          </button>
        </div>
        {pipeMessage && (
          <p className="mt-2 text-sm text-emerald-700 dark:text-emerald-400">
            {pipeMessage}
          </p>
        )}
        {pipeError && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{pipeError}</p>
        )}
      </section>

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
            {TIMEFRAME_FILTER_OPTIONS.map((tf) => (
              <option key={tf || "all"} value={tf}>
                {timeframeFilterLabel(tf)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Provider
          </span>
          <select
            className="min-w-[9rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterProvider}
            onChange={(e) => setFilterProvider(e.target.value)}
          >
            {PROVIDER_FILTER_OPTIONS.map((p) => (
              <option key={p || "all"} value={p}>
                {p === ""
                  ? "Tutti"
                  : p === "yahoo_finance"
                    ? "Yahoo Finance"
                    : "Binance"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Asset
          </span>
          <select
            className="min-w-[7rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterAssetType}
            onChange={(e) => setFilterAssetType(e.target.value)}
          >
            {ASSET_TYPE_FILTER_OPTIONS.map((a) => (
              <option key={a || "all"} value={a}>
                {a === "" ? "Tutti" : a}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">
            Decisione
          </span>
          <select
            className="min-w-[11rem] rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            value={filterDecision}
            onChange={(e) => setFilterDecision(e.target.value)}
          >
            {DECISION_FILTER_OPTIONS.map((d) => (
              <option key={d || "all"} value={d}>
                {d === ""
                  ? "Tutte"
                  : d === "operable"
                    ? "Operabili"
                    : d === "monitor"
                      ? "Da monitorare"
                      : "Scartare"}
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

      {loading && (
        <div
          className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-600 dark:border-zinc-600 dark:text-zinc-400"
          role="status"
        >
          Caricamento opportunità…
        </div>
      )}

      {!loading && error && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
          role="alert"
        >
          <strong className="font-medium">Impossibile caricare i dati.</strong>
          <pre className="mt-2 whitespace-pre-wrap font-mono text-xs">{error}</pre>
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-8 text-center text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-400">
          Nessuna opportunità corrisponde ai filtri attuali.
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <p
            className="border-b border-zinc-200 bg-zinc-50/90 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-400"
            role="note"
          >
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              Direzioni:
            </span>{" "}
            «Dir. score» = interpretazione direzionale del contesto live dello screener; «Dir.
            pattern» = direzione dell’ultimo pattern rilevato. «Allineamento segnale» le confronta.
            Passa il mouse sulle intestazioni di colonna per il testo di aiuto.
          </p>
          <p
            className="border-b border-zinc-200 bg-zinc-50/95 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-400"
            role="note"
          >
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              Fonte piano:
            </span>{" "}
            <span title={FONTE_PIANO_LEGENDA.promossa}>Promossa</span> = best variant
            validata;{" "}
            <span title={FONTE_PIANO_LEGENDA.watchlist}>Watchlist</span> = variante con
            affidabilità media;{" "}
            <span title={FONTE_PIANO_LEGENDA.fallback}>Fallback standard</span> = motore base
            senza variante affidabile per le regole live.
          </p>
          <table className="w-full min-w-[144rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60">
                <th className="sticky left-0 z-20 min-w-[8rem] border-r border-zinc-200 bg-zinc-50 px-3 py-2 font-medium shadow-[4px_0_12px_-6px_rgba(0,0,0,0.12)] dark:border-zinc-700 dark:bg-zinc-950">
                  Simbolo
                </th>
                <th className="min-w-[10rem] whitespace-nowrap px-3 py-2 font-medium">
                  Provider
                </th>
                <th className="px-3 py-2 font-medium">Asset</th>
                <th
                  className="min-w-[8rem] whitespace-nowrap px-3 py-2 font-medium"
                  title={`${FONTE_PIANO_LEGENDA.promossa} | ${FONTE_PIANO_LEGENDA.watchlist} | ${FONTE_PIANO_LEGENDA.fallback}`}
                >
                  Fonte piano
                </th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title="Candidato alert: regole MVP (allineamento, OK TF, banda qualità, score). Priorità da score finale."
                >
                  Alert
                </th>
                <th className="px-3 py-2 font-medium">Priorità</th>
                <th className="px-3 py-2 font-medium">TF</th>
                <th className="px-3 py-2 font-medium">Mercato</th>
                <th className="px-3 py-2 font-medium">Volatilità</th>
                <th className="px-3 py-2 font-medium">Espansione</th>
                <th className="px-3 py-2 font-medium">Bias dir.</th>
                <th className="px-3 py-2 font-medium">Score screener</th>
                <th className="px-3 py-2 font-medium">Score finale</th>
                <th className="px-3 py-2 font-medium">Livello finale</th>
                <th className="px-3 py-2 font-medium">Etichetta</th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title={TOOLTIP_DIR_SCORE_IT}
                >
                  Dir. score
                </th>
                <th className="px-3 py-2 font-medium">Pattern</th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title={TOOLTIP_DIR_PATTERN_IT}
                >
                  Dir. pattern
                </th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title={TOOLTIP_ALLINEAMENTO_SEGNALE_IT}
                >
                  Allineamento segnale
                </th>
                <th className="px-3 py-2 font-medium">Qualità pat.</th>
                <th className="px-3 py-2 font-medium">Band qualità</th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title="Backtest sul timeframe: il pattern è storicamente adeguato su questo TF?"
                >
                  OK sul TF
                </th>
                <th
                  className="cursor-help px-3 py-2 font-medium"
                  title="Esito policy qualità pattern+timeframe (backtest)"
                >
                  Evid. storico TF
                </th>
                <th className="px-3 py-2 font-medium">Forza pattern</th>
                <th className="px-3 py-2 font-medium">Orario ctx</th>
                <th className="px-3 py-2 font-medium">Orario pattern</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.exchange}-${r.symbol}-${r.timeframe}-${r.context_timestamp}`}
                  className="cursor-pointer border-b border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800/80 dark:hover:bg-zinc-900/50"
                  onClick={() =>
                    router.push(
                      seriesDetailHref(r.symbol, r.timeframe, r.exchange, {
                        provider: r.provider,
                        asset_type: r.asset_type,
                      }),
                    )
                  }
                >
                  <td className="sticky left-0 z-20 min-w-[8rem] border-r border-zinc-200 bg-[var(--background)] px-3 py-2 font-mono text-xs shadow-[4px_0_12px_-6px_rgba(0,0,0,0.1)] dark:border-zinc-700 dark:bg-zinc-950">
                    {r.symbol}
                  </td>
                  <td className="min-w-[10rem] whitespace-nowrap px-3 py-2 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                    {r.provider ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-xs capitalize text-zinc-600 dark:text-zinc-400">
                    {r.asset_type ?? "—"}
                  </td>
                  <td
                    className="min-w-[8rem] whitespace-nowrap px-3 py-2 text-xs"
                    title={fontePianoListTitle(r)}
                  >
                    <span
                      className={
                        (r.trade_plan_source ?? "default_fallback") === "variant_backtest"
                          ? r.selected_trade_plan_variant_status === "promoted"
                            ? "font-medium text-emerald-800 dark:text-emerald-300"
                            : "font-medium text-sky-800 dark:text-sky-300"
                          : "text-zinc-600 dark:text-zinc-400"
                      }
                    >
                      {fontePianoListLabel(r)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs tabular-nums">
                    {r.alert_candidate ? (
                      <span className="font-medium text-emerald-700 dark:text-emerald-400">
                        Sì
                      </span>
                    ) : (
                      <span className="text-zinc-500">No</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${alertLevelBadgeClass(r.alert_level)}`}
                    >
                      {displayAlertLevelLabel(r.alert_level)}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{r.timeframe}</td>
                  <td className="px-3 py-2">{displayEnumLabel(r.market_regime)}</td>
                  <td className="px-3 py-2">{displayEnumLabel(r.volatility_regime)}</td>
                  <td className="px-3 py-2">{displayEnumLabel(r.candle_expansion)}</td>
                  <td className="px-3 py-2">{displayEnumLabel(r.direction_bias)}</td>
                  <td className="px-3 py-2 tabular-nums">{r.screener_score}</td>
                  <td
                    className={`px-3 py-2 tabular-nums ${
                      (r.trade_plan_source ?? "default_fallback") === "default_fallback"
                        ? "font-normal text-zinc-600 dark:text-zinc-400"
                        : "font-medium"
                    }`}
                  >
                    {r.final_opportunity_score.toFixed(1)}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {displayFinalOpportunityLabel(r.final_opportunity_label)}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {displayTechnicalLabel(r.score_label)}
                  </td>
                  <td className="px-3 py-2">
                    {displayEnumLabel(r.score_direction)}
                  </td>
                  <td
                    className="max-w-[10rem] truncate px-3 py-2 text-xs"
                    title={r.latest_pattern_name ?? undefined}
                  >
                    {displayTechnicalLabel(r.latest_pattern_name)}
                  </td>
                  <td className="px-3 py-2">
                    {displayEnumLabel(r.latest_pattern_direction)}
                  </td>
                  <td className="px-3 py-2">
                    <AllineamentoSegnaleBadge row={r} />
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {r.pattern_quality_score != null
                      ? r.pattern_quality_score.toFixed(1)
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {displayPatternQualityLabel(r.pattern_quality_label)}
                  </td>
                  <td className="px-3 py-2 text-xs tabular-nums">
                    {r.pattern_timeframe_quality_ok == null
                      ? "—"
                      : r.pattern_timeframe_quality_ok
                        ? "Sì"
                        : "No"}
                  </td>
                  <td className="max-w-[14rem] px-3 py-2 text-xs">
                    <span>{displayPatternTimeframeGateLabel(r.pattern_timeframe_gate_label)}</span>
                    {r.pattern_timeframe_filtered_candidate ? (
                      <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
                        (filtrato)
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs">
                    {formatStrength(r.latest_pattern_strength)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400">
                    {formatTs(r.context_timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400">
                    {formatTs(r.pattern_timestamp ?? undefined)}
                  </td>
                  <td
                    className={`sticky right-0 z-10 min-w-[9rem] border-l border-zinc-200 bg-[var(--background)] px-3 py-2 text-xs shadow-[-8px_0_12px_-6px_rgba(0,0,0,0.06)] dark:border-zinc-700 dark:bg-zinc-950`}
                  >
                    <span className={operationalDecisionListCellClass(r.operational_decision)}>
                      {displayOperationalDecisionListLabel(r.operational_decision)}
                    </span>
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
