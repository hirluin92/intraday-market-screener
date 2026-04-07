"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  fetchIbkrStatus,
  fetchOpportunities,
  postPipelineRefresh,
  type IbkrStatus,
  type OpportunityRow,
  type PipelineRefreshRequest,
} from "@/lib/api";
import { isDiscardedOutOfUniverse } from "@/lib/opportunityDiscardFilter";
import { opportunityCardId } from "@/lib/opportunityCardId";
import {
  sortOpportunityGroup,
  type OpportunitySortBy,
} from "@/lib/opportunitySort";
import {
  DEFAULT_POSITION_SIZING_INPUT,
  loadPositionSizingInput,
  savePositionSizingInput,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";
import { recordExecuteListMax, getTodayMaxExecute, getWeekSumLast7Days } from "@/lib/traderExecuteStats";
import {
  loadTraderBroker,
  saveTraderBroker,
  syncLegacyPrefKeys,
  type TraderBrokerId,
} from "@/lib/traderPrefs";

import { DiscardedCard } from "./components/DiscardedCard";
import { OpportunityPreferencesBar } from "./components/OpportunityPreferencesBar";
import { RegimeBadge } from "./components/RegimeBadge";
import { SignalCard } from "./components/SignalCard";

const FETCH_LIMIT = 500;
const REFRESH_SEC = 60;
const CURRENCY = "€";

const TIMEFRAME_PIPELINE = ["", "1m", "5m", "15m", "1h", "1d"] as const;

type DecisionFilter = "all" | "execute" | "monitor" | "discard";
type TfFilter = "all" | "1h" | "5m";
type DirFilter = "all" | "bullish" | "bearish";

function pickRegimeSpy(rows: OpportunityRow[]): string | undefined {
  const withRegime = rows.filter((r) => r.regime_spy && r.regime_spy !== "n/a");
  if (withRegime.length === 0) return undefined;
  const spy = withRegime.find((r) => String(r.symbol).toUpperCase().includes("SPY"));
  return (spy ?? withRegime[0]).regime_spy;
}

function pillClass(active: boolean, accent?: "execute" | "monitor" | "warn"): string {
  const base =
    "rounded-full border px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-neutral)]";
  if (!active) {
    return `${base} border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)] hover:border-[var(--border-active)]`;
  }
  if (accent === "execute") {
    return `${base} border-[var(--accent-bull)] bg-[var(--accent-bull)]/15 text-[var(--accent-bull)] shadow-[var(--glow-bull)]`;
  }
  if (accent === "monitor") {
    return `${base} border-amber-400/80 bg-amber-500/15 text-amber-200`;
  }
  if (accent === "warn") {
    return `${base} border-[var(--accent-bear)]/60 bg-[var(--accent-bear)]/10 text-[var(--accent-bear)]`;
  }
  return `${base} border-[var(--accent-neutral)] bg-[var(--accent-neutral)]/15 text-[var(--text-primary)]`;
}

function applyClientFilters(
  rows: OpportunityRow[],
  decision: DecisionFilter,
  tf: TfFilter,
  dir: DirFilter,
): OpportunityRow[] {
  return rows.filter((r) => {
    const d = (r.operational_decision ?? "monitor") as DecisionFilter;
    if (decision !== "all" && d !== decision) return false;
    if (tf !== "all" && r.timeframe !== tf) return false;
    if (dir !== "all") {
      const pat = (r.latest_pattern_direction ?? "").toLowerCase();
      if (dir === "bullish" && pat !== "bullish") return false;
      if (dir === "bearish" && pat !== "bearish") return false;
    }
    return true;
  });
}

function OpportunitiesPageInner() {
  const searchParams = useSearchParams();
  const [rows, setRows] = useState<OpportunityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>("all");
  const [tfFilter, setTfFilter] = useState<TfFilter>("all");
  const [dirFilter, setDirFilter] = useState<DirFilter>("all");
  const [sortBy, setSortBy] = useState<OpportunitySortBy>("default");

  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [showDiscarded, setShowDiscarded] = useState(false);
  const skipFilterClearRef = useRef(false);
  const [deepLinkHandled, setDeepLinkHandled] = useState(false);

  const [sizingInput, setSizingInput] = useState<PositionSizingUserInput>(DEFAULT_POSITION_SIZING_INPUT);
  const [broker, setBroker] = useState<TraderBrokerId>("ibkr");

  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [ibkrStatus, setIbkrStatus] = useState<IbkrStatus | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [timeLabelReady, setTimeLabelReady] = useState(false);
  const [secondsToRefresh, setSecondsToRefresh] = useState(REFRESH_SEC);

  const [pipeProvider, setPipeProvider] = useState<"binance" | "yahoo_finance">("binance");
  const [pipeExchangeOverride, setPipeExchangeOverride] = useState("");
  const [pipeSymbol, setPipeSymbol] = useState("");
  const [pipeTimeframe, setPipeTimeframe] = useState("");
  const [pipeIngestLimit, setPipeIngestLimit] = useState(2500);
  const [pipeExtractLimit, setPipeExtractLimit] = useState(5000);
  const [pipeLookback, setPipeLookback] = useState(50);
  const [pipeLoading, setPipeLoading] = useState(false);
  const [pipeMessage, setPipeMessage] = useState<string | null>(null);
  const [pipeError, setPipeError] = useState<string | null>(null);

  useEffect(() => {
    setSizingInput(loadPositionSizingInput());
    setBroker(loadTraderBroker());
    setTimeLabelReady(true);
  }, []);

  useEffect(() => {
    if (skipFilterClearRef.current) {
      skipFilterClearRef.current = false;
      return;
    }
    setExpandedCardId(null);
  }, [decisionFilter, tfFilter, dirFilter]);

  const focusSymbol = searchParams.get("symbol");
  const focusTimeframe = searchParams.get("timeframe");
  const focusProvider = searchParams.get("provider");
  const focusExchange = searchParams.get("exchange");
  const shouldExpandFromUrl = searchParams.get("expand") === "true";

  useEffect(() => {
    if (!shouldExpandFromUrl || !focusSymbol?.trim() || loading || deepLinkHandled) {
      return;
    }
    if (rows.length === 0) {
      return;
    }

    const sym = focusSymbol.trim().toUpperCase();
    const target = rows.find((o) => {
      const os = String(o.symbol).toUpperCase();
      if (os !== sym) return false;
      if (focusTimeframe && o.timeframe !== focusTimeframe) return false;
      if (focusProvider && (o.provider ?? "") !== focusProvider) return false;
      if (focusExchange != null && focusExchange !== "" && (o.exchange ?? "") !== focusExchange) {
        return false;
      }
      return true;
    });

    if (!target) {
      setDeepLinkHandled(true);
      return;
    }

    skipFilterClearRef.current = true;
    setDecisionFilter("all");
    if (focusTimeframe === "1h" || focusTimeframe === "5m") {
      setTfFilter(focusTimeframe);
    } else {
      setTfFilter("all");
    }
    setDirFilter("all");

    const cid = opportunityCardId(target);
    if (target.operational_decision === "discard") {
      setShowDiscarded(true);
    }

    let t1: number | undefined;
    let t2: number | undefined;
    let t3: number | undefined;

    t1 = window.setTimeout(() => {
      if (target.operational_decision !== "discard") {
        setExpandedCardId(cid);
      }
      setDeepLinkHandled(true);
      t2 = window.setTimeout(() => {
        const el = document.getElementById(`card-${cid}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add(
            "ring-2",
            "ring-yellow-400",
            "ring-offset-2",
            "ring-offset-[var(--bg-base)]",
          );
          t3 = window.setTimeout(() => {
            el.classList.remove(
              "ring-2",
              "ring-yellow-400",
              "ring-offset-2",
              "ring-offset-[var(--bg-base)]",
            );
          }, 3000);
        }
      }, 400);
    }, 0);

    return () => {
      if (t1) window.clearTimeout(t1);
      if (t2) window.clearTimeout(t2);
      if (t3) window.clearTimeout(t3);
    };
  }, [
    shouldExpandFromUrl,
    focusSymbol,
    focusTimeframe,
    focusProvider,
    focusExchange,
    loading,
    rows,
    deepLinkHandled,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, ibkr] = await Promise.all([
        fetchOpportunities({ limit: FETCH_LIMIT }),
        fetchIbkrStatus(),
      ]);
      setRows(data.opportunities);
      setIbkrStatus(ibkr);
      setSizingInput(loadPositionSizingInput());
      const execN = data.opportunities.filter((r) => r.operational_decision === "execute").length;
      recordExecuteListMax(execN);
      setLastUpdate(new Date());
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

  useEffect(() => {
    if (!autoRefresh) return;
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void load();
    };
    const interval = setInterval(tick, REFRESH_SEC * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, load]);

  useEffect(() => {
    if (!lastUpdate) return;
    const t = () => {
      const elapsed = (Date.now() - lastUpdate.getTime()) / 1000;
      setSecondsToRefresh(Math.max(0, REFRESH_SEC - Math.floor(elapsed)));
    };
    t();
    const id = setInterval(t, 1000);
    return () => clearInterval(id);
  }, [lastUpdate]);

  const regimeSpy = useMemo(() => pickRegimeSpy(rows), [rows]);

  const filtered = useMemo(
    () => applyClientFilters(rows, decisionFilter, tfFilter, dirFilter),
    [rows, decisionFilter, tfFilter, dirFilter],
  );

  const executeRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "execute"),
    [filtered],
  );
  const monitorRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "monitor"),
    [filtered],
  );
  const discardRows = useMemo(
    () => filtered.filter((r) => r.operational_decision === "discard"),
    [filtered],
  );

  /** Scarti fuori universo (DB/scheduler): non mostrati in lista. */
  const discardRowsInUniverse = useMemo(
    () => discardRows.filter((r) => !isDiscardedOutOfUniverse(r)),
    [discardRows],
  );

  const executeRowsSorted = useMemo(
    () => sortOpportunityGroup(executeRows, sortBy),
    [executeRows, sortBy],
  );
  const monitorRowsSorted = useMemo(
    () => sortOpportunityGroup(monitorRows, sortBy),
    [monitorRows, sortBy],
  );
  const discardRowsSorted = useMemo(
    () => sortOpportunityGroup(discardRowsInUniverse, sortBy),
    [discardRowsInUniverse, sortBy],
  );

  const totalExecute = useMemo(
    () => rows.filter((r) => r.operational_decision === "execute").length,
    [rows],
  );

  const persistSizing = (s: PositionSizingUserInput) => {
    setSizingInput(s);
    savePositionSizingInput(s);
    syncLegacyPrefKeys(s, broker);
  };

  const persistBroker = (b: TraderBrokerId) => {
    setBroker(b);
    saveTraderBroker(b);
    syncLegacyPrefKeys(sizingInput, b);
  };

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

  const showExecuteBlock = decisionFilter === "all" || decisionFilter === "execute";
  const showMonitorBlock = decisionFilter === "all" || decisionFilter === "monitor";
  const showDiscardBlock = decisionFilter === "all" || decisionFilter === "discard";

  const emptyExecute =
    showExecuteBlock &&
    executeRows.length === 0 &&
    !loading &&
    !error &&
    rows.length > 0;

  return (
    <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-4 px-4 pb-10 pt-4 sm:px-6">
      <header className="sticky top-0 z-30 -mx-4 border-b border-[var(--border)] bg-[var(--bg-base)]/95 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-2 font-[family-name:var(--font-trader-sans)] font-semibold text-[var(--text-primary)]">
              <span
                className="relative flex h-2.5 w-2.5 items-center justify-center"
                aria-hidden
              >
                <span className="absolute h-2.5 w-2.5 animate-pulse-live rounded-full bg-[var(--accent-bull)]" />
              </span>
              LIVE
            </span>
            <span className="text-[var(--text-muted)]">•</span>
            <span className="text-[var(--text-secondary)]" suppressHydrationWarning>
              Ultimo refresh:{" "}
              {timeLabelReady && lastUpdate != null
                ? lastUpdate.toLocaleTimeString("it-IT")
                : "—"}
            </span>
            <span className="text-[var(--text-muted)]">•</span>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1 text-xs font-semibold text-[var(--text-primary)] hover:border-[var(--border-active)]"
            >
              ↻ Aggiorna
            </button>
            <label className="ml-1 flex cursor-pointer items-center gap-1.5 text-xs text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-[var(--border)] bg-[var(--bg-surface-2)]"
              />
              Auto 60s
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {ibkrStatus?.enabled === true && (
              <>
                <div
                  className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                    ibkrStatus.authenticated
                      ? "border-emerald-700/80 bg-emerald-950/40 text-emerald-200"
                      : "border-red-800/80 bg-red-950/40 text-red-200"
                  }`}
                >
                  <span
                    className={`h-2 w-2 rounded-full ${
                      ibkrStatus.authenticated ? "animate-pulse bg-emerald-400" : "bg-red-400"
                    }`}
                  />
                  IBKR {ibkrStatus.paper_trading ? "PAPER" : "LIVE"} ·{" "}
                  {ibkrStatus.authenticated ? "connesso" : "disconnesso"}
                </div>
                {ibkrStatus.authenticated && (
                  <span className="text-xs text-[var(--text-muted)]">
                    Auto-exec:{" "}
                    <span
                      className={
                        ibkrStatus.auto_execute ? "font-semibold text-emerald-300" : "text-[var(--text-secondary)]"
                      }
                    >
                      {ibkrStatus.auto_execute ? "ON" : "OFF"}
                    </span>
                  </span>
                )}
              </>
            )}
            <RegimeBadge regime={regimeSpy} />
            <span
              className={`inline-flex items-center rounded-lg border px-3 py-1.5 font-[family-name:var(--font-trader-mono)] text-xs font-bold ${
                totalExecute > 0
                  ? "border-[var(--accent-bull)] bg-[var(--accent-bull)]/10 text-[var(--accent-bull)] shadow-[var(--glow-bull)]"
                  : "border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]"
              }`}
              aria-label={`Segnali esegui: ${totalExecute}`}
            >
              {totalExecute} segnali ESEGUI
            </span>
          </div>
        </div>
        <p className="mt-2 font-[family-name:var(--font-trader-mono)] text-xs text-[var(--text-muted)]">
          Prossimo refresh tra{" "}
          <span suppressHydrationWarning>
            {autoRefresh ? `${secondsToRefresh}s` : "—"}
          </span>
        </p>
      </header>

      <OpportunityPreferencesBar
        sizing={sizingInput}
        onSizingChange={persistSizing}
        broker={broker}
        onBrokerChange={persistBroker}
      />

      <section aria-label="Filtri rapidi" className="flex flex-wrap gap-2">
        <span className="w-full text-xs font-medium text-[var(--text-muted)]">Decisione</span>
        {(
          [
            ["all", "Tutti"],
            ["execute", "✅ Esegui"],
            ["monitor", "👁 Monitora"],
            ["discard", "Scarta"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={pillClass(decisionFilter === id, id === "execute" ? "execute" : id === "monitor" ? "monitor" : id === "discard" ? "warn" : undefined)}
            onClick={() => setDecisionFilter(id)}
          >
            {label}
          </button>
        ))}
        <span className="mx-1 w-full sm:w-auto sm:pl-2" />
        <span className="w-full text-xs font-medium text-[var(--text-muted)] sm:w-auto">Timeframe</span>
        {(
          [
            ["all", "Tutti"],
            ["1h", "1h"],
            ["5m", "5m"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={pillClass(tfFilter === id)}
            onClick={() => setTfFilter(id)}
          >
            {label}
          </button>
        ))}
        <span className="mx-1 w-full sm:w-auto sm:pl-2" />
        <span className="w-full text-xs font-medium text-[var(--text-muted)] sm:w-auto">Direzione</span>
        {(
          [
            ["all", "Tutti"],
            ["bearish", "Bearish"],
            ["bullish", "Bullish"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={pillClass(dirFilter === id)}
            onClick={() => setDirFilter(id)}
          >
            {label}
          </button>
        ))}
      </section>

      {loading && (
        <div
          className="rounded-xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]"
          role="status"
        >
          Caricamento opportunità…
        </div>
      )}

      {!loading && error && (
        <div
          className="rounded-xl border border-[var(--accent-bear)]/40 bg-[var(--accent-bear)]/10 p-4 text-sm text-[var(--accent-bear)]"
          role="alert"
        >
          <strong className="font-medium">Errore caricamento.</strong>
          <pre className="mt-2 whitespace-pre-wrap font-[family-name:var(--font-trader-mono)] text-xs opacity-90">
            {error}
          </pre>
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-8 text-center text-[var(--text-secondary)]">
          Nessuna opportunità dal server. Verifica la pipeline o riprova tra poco.
        </div>
      )}

      {emptyExecute && (
        <div className="animate-[slide-in_0.4s_ease-out] rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)]/90 p-8 text-center backdrop-blur-sm">
          <p className="font-[family-name:var(--font-trader-sans)] text-lg font-bold text-[var(--text-primary)]">
            📡 In ascolto…
          </p>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Nessun segnale operativo con i filtri attuali. Il refresh automatico è ogni {REFRESH_SEC}{" "}
            secondi.
          </p>
          <p className="mt-4 font-[family-name:var(--font-trader-mono)] text-sm text-[var(--accent-neutral)]">
            Prossimo refresh:{" "}
            <span suppressHydrationWarning>
              {autoRefresh ? `${secondsToRefresh}s` : "—"}
            </span>
          </p>
          <p className="mt-4 text-xs text-[var(--text-muted)]">
            Oggi (max execute in lista): {getTodayMaxExecute()} · Ultimi 7 giorni (somma max
            giornalieri): {getWeekSumLast7Days()}
          </p>
        </div>
      )}

      {showExecuteBlock && executeRows.length > 0 && (
        <section aria-label="Segnali esegui">
          <h2 className="mb-3 font-[family-name:var(--font-trader-sans)] text-sm font-bold uppercase tracking-wide text-[var(--text-secondary)]">
            Esegui ora
          </h2>
          <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
            {executeRowsSorted.map((row) => (
              <SignalCard
                key={opportunityCardId(row)}
                opportunity={row}
                sizingInput={sizingInput}
                broker={broker}
                onBrokerChange={persistBroker}
                currencySymbol={CURRENCY}
                variant="execute"
                cardId={opportunityCardId(row)}
                expanded={expandedCardId === opportunityCardId(row)}
                onExpandedChange={setExpandedCardId}
              />
            ))}
          </div>
        </section>
      )}

      {showMonitorBlock && monitorRows.length > 0 && (
        <section aria-label="In monitoraggio">
          <h2 className="mb-3 font-[family-name:var(--font-trader-sans)] text-sm font-bold uppercase tracking-wide text-[var(--text-secondary)]">
            Monitora
          </h2>
          <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
            {monitorRowsSorted.map((row) => (
              <SignalCard
                key={opportunityCardId(row)}
                opportunity={row}
                sizingInput={sizingInput}
                broker={broker}
                onBrokerChange={persistBroker}
                currencySymbol={CURRENCY}
                variant="monitor"
                cardId={opportunityCardId(row)}
                expanded={expandedCardId === opportunityCardId(row)}
                onExpandedChange={setExpandedCardId}
              />
            ))}
          </div>
        </section>
      )}

      {showDiscardBlock && discardRowsInUniverse.length > 0 && (
        <section aria-label="Scartati nell'universo" className="mt-2">
          <button
            type="button"
            onClick={() => setShowDiscarded((v) => !v)}
            className="flex w-full items-center justify-between gap-2 border-t border-[var(--border)] py-3 text-left text-sm text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            aria-expanded={showDiscarded}
          >
            <span>
              {showDiscarded ? "▲" : "▼"} Nell&apos;universo ma pattern non operativo (
              {discardRowsInUniverse.length})
            </span>
          </button>
          {showDiscarded && (
            <div className="space-y-2 pb-2" role="list">
              {discardRowsSorted.map((row) => (
                <DiscardedCard key={opportunityCardId(row)} opportunity={row} />
              ))}
            </div>
          )}
        </section>
      )}

      <details className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]/60 p-4 text-sm text-[var(--text-secondary)]">
        <summary className="cursor-pointer font-medium text-[var(--text-primary)]">
          Manutenzione pipeline
        </summary>
        <p className="mt-2 text-xs">
          Esegue ingest → features → context → patterns (POST /pipeline/refresh). Uso avanzato.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs">
            Provider
            <select
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
              value={pipeProvider}
              onChange={(e) => setPipeProvider(e.target.value as "binance" | "yahoo_finance")}
            >
              <option value="binance">Binance</option>
              <option value="yahoo_finance">Yahoo Finance</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Venue (opz.)
            <input
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
              value={pipeExchangeOverride}
              onChange={(e) => setPipeExchangeOverride(e.target.value)}
              placeholder="default"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Simbolo
            <input
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
              value={pipeSymbol}
              onChange={(e) => setPipeSymbol(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Timeframe
            <select
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5 text-[var(--text-primary)]"
              value={pipeTimeframe}
              onChange={(e) => setPipeTimeframe(e.target.value)}
            >
              {TIMEFRAME_PIPELINE.map((tf) => (
                <option key={tf || "all"} value={tf}>
                  {tf === "" ? "—" : tf}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Limite ingest
            <input
              type="number"
              min={1}
              className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
              value={pipeIngestLimit}
              onChange={(e) => setPipeIngestLimit(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Limite extract
            <input
              type="number"
              min={1}
              className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
              value={pipeExtractLimit}
              onChange={(e) => setPipeExtractLimit(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            Lookback
            <input
              type="number"
              min={3}
              className="w-20 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-1.5"
              value={pipeLookback}
              onChange={(e) => setPipeLookback(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            disabled={pipeLoading}
            onClick={() => void runPipelineRefresh()}
            className="rounded-lg bg-[var(--text-primary)] px-4 py-2 text-xs font-semibold text-[var(--bg-base)] disabled:opacity-50"
          >
            {pipeLoading ? "…" : "Esegui pipeline"}
          </button>
        </div>
        {pipeMessage && <p className="mt-2 text-xs text-[var(--accent-bull)]">{pipeMessage}</p>}
        {pipeError && <p className="mt-2 text-xs text-[var(--accent-bear)]">{pipeError}</p>}
      </details>
    </div>
  );
}

export default function OpportunitiesPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-4 px-4 pb-10 pt-4 sm:px-6">
          <div
            className="rounded-xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]"
            role="status"
          >
            Caricamento opportunità…
          </div>
        </div>
      }
    >
      <OpportunitiesPageInner />
    </Suspense>
  );
}
