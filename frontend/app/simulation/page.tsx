"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchBacktestSimulation,
  fetchOutOfSample,
  fetchWalkForward,
  type BacktestSimulationResponse,
  type OOSResult,
  type SimulationEquityPoint,
  type SimulationTradeRow,
  type WalkForwardResult,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { KPICard } from "@/components/trading/KPICard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

// ── Constants (UNCHANGED from original) ───────────────────────────────────────

const TOP_YAHOO_1H = [
  "compression_to_expansion_transition",
  "rsi_momentum_continuation",
] as const;

const TOP_YAHOO_1H_INCLUDE_SYMBOLS = [
  "GOOGL", "TSLA", "AMD", "META", "NVDA", "NFLX",
] as const;

const PRESET_KEYS = [
  "Top Yahoo 1h", "Top Yahoo 5m", "Top Binance 1h", "Tutti i pattern",
] as const;
type PresetKey = (typeof PRESET_KEYS)[number];

const PRESETS: Record<PresetKey, string[]> = {
  "Top Yahoo 1h": ["compression_to_expansion_transition", "rsi_momentum_continuation"],
  "Top Yahoo 5m": ["rsi_momentum_continuation"],
  "Top Binance 1h": ["rsi_momentum_continuation", "trend_continuation_pullback", "compression_to_expansion_transition", "engulfing_bearish", "inside_bar_breakout_bull", "support_bounce"],
  "Tutti i pattern": [],
};

const ALL_PATTERNS: string[] = [
  "bear_flag", "bull_flag", "compression_to_expansion_transition", "engulfing_bearish",
  "engulfing_bullish", "ema_pullback_to_resistance", "ema_pullback_to_support",
  "fibonacci_bounce", "hammer_reversal", "impulsive_bearish_candle", "impulsive_bullish_candle",
  "inside_bar_breakout_bull", "morning_star", "evening_star", "opening_range_breakout_bull",
  "opening_range_breakout_bear", "rsi_momentum_continuation", "resistance_rejection",
  "support_bounce", "shooting_star_reversal", "trend_continuation_pullback",
  "vwap_bounce_bull", "vwap_bounce_bear", "breakout_with_retest",
];

const SUGGESTED_EXCLUDE_HOURS_UTC = [17, 21] as const;
const HOURS_UTC_OPTIONS = Array.from({ length: 24 }, (_, i) => i);

const PERIOD_LABELS: Record<string, string> = {
  "1m": "Ultimo mese", "3m": "Ultimi 3 mesi", "6m": "Ultimi 6 mesi",
  "1y": "Ultimo anno", "2y": "Ultimi 2 anni", "3y": "Ultimi 3 anni", "all": "Tutto lo storico",
};

// ── Business logic helpers (UNCHANGED from original) ──────────────────────────

function enrichEquityForChart(points: SimulationEquityPoint[], initialCapital: number) {
  let peak = initialCapital;
  return points.map((p) => {
    peak = Math.max(peak, p.equity);
    const drawdown_pct = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
    let dateLabel = p.timestamp;
    try { dateLabel = new Date(p.timestamp).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); }
    catch { /* ignore */ }
    return { timestamp: p.timestamp, equity: p.equity, capitale: Math.round(p.equity), drawdown_pct, dateLabel };
  });
}

function tradeDerivedStats(trades: SimulationTradeRow[] | undefined) {
  if (!trades?.length) return { winning_trades: 0, losing_trades: 0, flat_trades: 0, avg_win_r: null as number | null, avg_loss_r: null as number | null, profit_factor: null as number | null };
  const wins = trades.filter((t) => t.outcome === "win");
  const losses = trades.filter((t) => t.outcome === "loss");
  const flats = trades.filter((t) => t.outcome === "flat");
  const sumPos = wins.reduce((s, t) => s + Math.max(0, t.pnl_r), 0);
  const sumNeg = losses.reduce((s, t) => s + Math.abs(Math.min(0, t.pnl_r)), 0);
  return {
    winning_trades: wins.length, losing_trades: losses.length, flat_trades: flats.length,
    avg_win_r: wins.length > 0 ? wins.reduce((s, t) => s + t.pnl_r, 0) / wins.length : null,
    avg_loss_r: losses.length > 0 ? losses.reduce((s, t) => s + t.pnl_r, 0) / losses.length : null,
    profit_factor: sumNeg > 1e-12 ? sumPos / sumNeg : null,
  };
}

// ── Chart tooltip (shared) ────────────────────────────────────────────────────

// Recharts Tooltip props use complex generics — typed via unknown to avoid mismatch
type ChartTooltipProps = {
  active?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: any[];
};

function EquityTooltip({ active, payload }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as { dateLabel?: string; capitale?: number; drawdown_pct?: number } | undefined;
  if (!d) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-md">
      <p className="text-fg-2">{d.dateLabel}</p>
      <p className="font-mono font-semibold text-bull">€{(d.capitale ?? 0).toLocaleString("it-IT", { maximumFractionDigits: 0 })}</p>
      <p className="font-mono text-bear">DD: {(d.drawdown_pct ?? 0).toFixed(1)}%</p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SimulationPage() {
  // ── Form state (UNCHANGED) ────────────────────────────────────────────────
  const [capital, setCapital] = useState(10_000);
  const [riskPct, setRiskPct] = useState(1);
  const [costRate, setCostRate] = useState(0.0015);
  const [provider, setProvider] = useState("yahoo_finance");
  const [timeframe, setTimeframe] = useState("1h");
  const [period, setPeriod] = useState("1y");
  const [selectedPatterns, setSelectedPatterns] = useState<string[]>([...TOP_YAHOO_1H]);
  const [activePreset, setActivePreset] = useState<PresetKey | "custom">("Top Yahoo 1h");
  const [maxSimultaneous, setMaxSimultaneous] = useState(3);
  const [cooldownBars, setCooldownBars] = useState(0);
  const [includeTrades, setIncludeTrades] = useState(true);
  const [useRegimeFilter, setUseRegimeFilter] = useState(true);
  const [excludedHours, setExcludedHours] = useState<number[]>([]);
  const [includedSymbols, setIncludedSymbols] = useState<string[]>([...TOP_YAHOO_1H_INCLUDE_SYMBOLS]);

  // ── Run state (UNCHANGED) ─────────────────────────────────────────────────
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [oosCutoff, setOosCutoff] = useState("2025-01-01");
  const [oosLoading, setOosLoading] = useState(false);
  const [oosResult, setOosResult] = useState<OOSResult | null>(null);
  const [oosError, setOosError] = useState<string | null>(null);

  const [nFolds, setNFolds] = useState(3);
  const [wfLoading, setWfLoading] = useState(false);
  const [wfResult, setWfResult] = useState<WalkForwardResult | null>(null);
  const [wfError, setWfError] = useState<string | null>(null);
  const wfAbortRef = useRef<AbortController | null>(null);

  // ── WF progress bar (NEW) ─────────────────────────────────────────────────
  const [wfProgress, setWfProgress] = useState(0);
  const [wfElapsed, setWfElapsed] = useState(0);

  useEffect(() => {
    if (!wfLoading) { setWfProgress(0); setWfElapsed(0); return; }
    setWfProgress(3);
    const progress = setInterval(() => setWfProgress((p) => Math.min(p + 0.6, 90)), 1000);
    const elapsed = setInterval(() => setWfElapsed((s) => s + 1), 1000);
    return () => { clearInterval(progress); clearInterval(elapsed); };
  }, [wfLoading]);

  // ── Active results tab state ───────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState("equity");

  // ── Callbacks (UNCHANGED logic) ───────────────────────────────────────────
  const applyPreset = useCallback((key: PresetKey) => {
    setSelectedPatterns([...PRESETS[key]]);
    setActivePreset(key);
    if (key === "Top Yahoo 5m") { setTimeframe("5m"); setProvider("yahoo_finance"); setIncludedSymbols([]); }
    else if (key === "Top Yahoo 1h") { setTimeframe("1h"); setProvider("yahoo_finance"); setIncludedSymbols([...TOP_YAHOO_1H_INCLUDE_SYMBOLS]); }
    else if (key === "Top Binance 1h") { setTimeframe("1h"); setProvider("binance"); setIncludedSymbols([]); }
    else { setIncludedSymbols([]); }
  }, []);

  const handlePatternCheckboxChange = useCallback((pattern: string, checked: boolean) => {
    setActivePreset("custom");
    setSelectedPatterns((prev) => checked ? (prev.includes(pattern) ? prev : [...prev, pattern]) : prev.filter((p) => p !== pattern));
  }, []);

  const run = useCallback(async () => {
    setLoading(true); setError(null);
    const names = selectedPatterns.length > 0 ? selectedPatterns.map((p) => p.trim()).filter(Boolean) : undefined;
    try {
      const res = await fetchBacktestSimulation({
        provider, timeframe, pattern_names: names, initial_capital: capital, risk_per_trade_pct: riskPct,
        cost_rate: costRate, max_simultaneous: maxSimultaneous, include_trades: includeTrades,
        pattern_row_limit: 50_000, period, use_regime_filter: useRegimeFilter, cooldown_bars: cooldownBars,
        ...(provider === "yahoo_finance" && excludedHours.length > 0 ? { exclude_hours: excludedHours } : {}),
        ...(provider === "yahoo_finance" && includedSymbols.length > 0 ? { include_symbols: includedSymbols } : {}),
      });
      setResult(res);
      setActiveTab("equity");
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }, [provider, timeframe, selectedPatterns, capital, riskPct, costRate, maxSimultaneous, includeTrades, useRegimeFilter, period, excludedHours, includedSymbols, cooldownBars]);

  const handleRunOOS = useCallback(async () => {
    setOosLoading(true); setOosError(null);
    const names = selectedPatterns.length > 0 ? selectedPatterns.map((p) => p.trim()).filter(Boolean) : undefined;
    try {
      const res = await fetchOutOfSample({ provider, timeframe, pattern_names: names, cutoff_date: oosCutoff, initial_capital: capital, risk_per_trade_pct: riskPct, cost_rate: costRate, max_simultaneous: maxSimultaneous, include_trades: false, use_regime_filter: useRegimeFilter });
      setOosResult(res);
      setActiveTab("oos");
    } catch (e) { setOosResult(null); setOosError(e instanceof Error ? e.message : String(e)); }
    finally { setOosLoading(false); }
  }, [provider, timeframe, selectedPatterns, oosCutoff, capital, riskPct, costRate, maxSimultaneous, useRegimeFilter]);

  const handleRunWF = useCallback(async () => {
    setWfLoading(true); setWfError(null);
    const names = selectedPatterns.length > 0 ? selectedPatterns.map((p) => p.trim()).filter(Boolean) : undefined;
    const controller = new AbortController();
    wfAbortRef.current = controller;
    const timer = setTimeout(() => controller.abort("timeout"), 125_000);
    try {
      const res = await fetchWalkForward({ provider, timeframe, pattern_names: names, n_folds: nFolds, initial_capital: capital, risk_per_trade_pct: riskPct, cost_rate: costRate, max_simultaneous: maxSimultaneous, use_regime_filter: useRegimeFilter, ...(provider === "yahoo_finance" && excludedHours.length > 0 ? { exclude_hours: excludedHours } : {}), ...(provider === "yahoo_finance" && includedSymbols.length > 0 ? { include_symbols: includedSymbols } : {}), timeoutMs: 120_000 });
      setWfResult(res);
      setActiveTab("walkforward");
    } catch (e) { setWfResult(null); setWfError(e instanceof Error ? e.message : String(e)); }
    finally { clearTimeout(timer); wfAbortRef.current = null; setWfLoading(false); }
  }, [provider, timeframe, selectedPatterns, nFolds, capital, riskPct, costRate, maxSimultaneous, useRegimeFilter, excludedHours, includedSymbols]);

  const cancelWF = () => { wfAbortRef.current?.abort("user_cancel"); };

  // ── Derived data (UNCHANGED logic) ────────────────────────────────────────
  const derived = useMemo(() => tradeDerivedStats(result?.trades), [result?.trades]);
  const chartData = useMemo(() => result?.equity_curve?.length ? enrichEquityForChart(result.equity_curve, result.initial_capital) : [], [result]);
  const oosChartData = useMemo(() => oosResult?.test_set.equity_curve?.length ? enrichEquityForChart(oosResult.test_set.equity_curve, capital) : [], [oosResult, capital]);

  const periodLabel = PERIOD_LABELS[period] ?? period;

  // ── Metric KPIs from result ────────────────────────────────────────────────
  const equityKpis = useMemo(() => {
    if (!result) return [];
    const pf = derived.profit_factor != null && Number.isFinite(derived.profit_factor) ? derived.profit_factor : null;
    return [
      { label: "Capitale finale", value: `€${result.final_capital.toLocaleString("it-IT", { maximumFractionDigits: 0 })}`, variant: (result.total_return_pct >= 0 ? "bull" : "bear") as "bull" | "bear", delta: { value: result.total_return_pct } },
      { label: "Max drawdown", value: `${result.max_drawdown_pct.toFixed(1)}%`, variant: (result.max_drawdown_pct > 30 ? "bear" : "warn") as "bear" | "warn" },
      { label: "Win rate", value: `${result.win_rate.toFixed(1)}%`, variant: (result.win_rate >= 55 ? "bull" : result.win_rate >= 50 ? "neutral" : "bear") as "bull" | "neutral" | "bear" },
      { label: "Sharpe", value: result.sharpe_ratio != null ? result.sharpe_ratio.toFixed(3) : "—", variant: (result.sharpe_ratio != null && result.sharpe_ratio > 1 ? "bull" : "neutral") as "bull" | "neutral" },
      { label: "Trade totali", value: result.total_trades.toLocaleString("it-IT"), variant: "neutral" as const },
      { label: "Profit factor R", value: pf != null ? pf.toFixed(2) : "—", variant: (pf != null && pf > 1 ? "bull" : pf != null && pf < 1 ? "bear" : "neutral") as "bull" | "bear" | "neutral" },
    ];
  }, [result, derived]);

  // ── Form input classes ────────────────────────────────────────────────────
  const inputCls = "rounded-lg border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-neutral/40";

  return (
    <div className="flex min-h-full flex-col">
      {/* ── Header ────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur-md px-4 py-2 sm:px-6">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-3">
          <h1 className="font-sans text-sm font-semibold text-fg">Simulation Engine</h1>
          <Button
            size="sm"
            className="h-8 gap-1.5 bg-bull text-canvas hover:bg-bull/90 font-mono text-xs"
            onClick={() => void run()}
            disabled={loading}
          >
            {loading ? "⏳" : "▶"} {loading ? "Simulazione…" : "Esegui"}
          </Button>
        </div>
      </header>

      {/* ── Sidebar + main ────────────────────────────────────────────── */}
      <div className="mx-auto flex w-full max-w-[1440px] flex-1 items-start gap-6 px-4 pb-12 pt-4 sm:px-6">
        {/* ── Form sidebar ──────────────────────────────────────────── */}
        <aside className="hidden w-72 shrink-0 lg:block">
          <div className="sticky top-[calc(theme(spacing.12)+1px)] max-h-[calc(100vh-4rem)] overflow-y-auto rounded-xl border border-line bg-surface p-4 space-y-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-fg-2">Parametri</p>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Capitale iniziale (€)
              <input type="number" min={1} className={inputCls} value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Rischio % / barra
              <input type="number" min={0.01} step="any" className={inputCls} value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))} />
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Provider
              <select className={inputCls} value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="yahoo_finance">yahoo_finance</option>
                <option value="binance">binance</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Timeframe
              <select className={inputCls} value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {["5m", "15m", "1h", "1d"].map((tf) => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Periodo
              <select className={inputCls} value={period} onChange={(e) => setPeriod(e.target.value)}>
                {Object.entries(PERIOD_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Max simultanei
              <input type="number" min={1} max={10} className={inputCls} value={maxSimultaneous} onChange={(e) => setMaxSimultaneous(Math.min(10, Math.max(1, Number(e.target.value) || 1)))} />
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Cooldown barre
              <select className={inputCls} value={cooldownBars} onChange={(e) => setCooldownBars(Number(e.target.value))}>
                <option value={0}>Nessuno</option>
                <option value={2}>2 barre</option>
                <option value={3}>3 barre (cons.)</option>
                <option value={5}>5 barre</option>
                <option value={10}>10 barre</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Costo round-trip
              <input type="number" min={0} step="any" className={inputCls} value={costRate} onChange={(e) => setCostRate(Number(e.target.value))} />
            </label>

            <label className="flex items-center gap-2 text-xs text-fg-2 cursor-pointer">
              <input type="checkbox" checked={useRegimeFilter} onChange={(e) => setUseRegimeFilter(e.target.checked)} className="accent-bull" />
              Filtro regime SPY
            </label>

            {provider === "yahoo_finance" && (
              <label className="flex flex-col gap-1 text-xs text-fg-2">
                Ore escluse (UTC)
                <select multiple size={6} className={cn(inputCls, "font-mono text-xs")} value={excludedHours.map(String)} onChange={(e) => setExcludedHours(Array.from(e.target.selectedOptions).map((o) => Number(o.value)).sort((a, b) => a - b))}>
                  {HOURS_UTC_OPTIONS.map((h) => <option key={h} value={h}>{h}:00 UTC</option>)}
                </select>
                <span className="text-[10px] text-fg-3">Suggeriti: {SUGGESTED_EXCLUDE_HOURS_UTC.join(", ")} UTC</span>
              </label>
            )}

            <label className="flex items-center gap-2 text-xs text-fg-2 cursor-pointer">
              <input type="checkbox" checked={includeTrades} onChange={(e) => setIncludeTrades(e.target.checked)} />
              Includi elenco trade
            </label>

            {/* Presets */}
            <div className="space-y-2">
              <p className="text-[10px] font-medium uppercase tracking-widest text-fg-3">Preset</p>
              <div className="flex flex-wrap gap-1.5">
                {PRESET_KEYS.map((k) => (
                  <button key={k} type="button" onClick={() => applyPreset(k)} className={cn("rounded-md border px-2 py-1 text-[10px] font-medium transition-colors", activePreset === k ? "border-bull/40 bg-bull/10 text-bull" : "border-line bg-surface-2 text-fg-2 hover:border-line-hi hover:text-fg")}>
                    {k}
                  </button>
                ))}
              </div>
            </div>

            {/* Pattern checkboxes */}
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium uppercase tracking-widest text-fg-3">Pattern ({selectedPatterns.length || "tutti"})</p>
              <div className="max-h-40 overflow-y-auto rounded-lg border border-line bg-surface-2 p-2 space-y-0.5">
                {ALL_PATTERNS.map((name) => (
                  <label key={name} className="flex cursor-pointer items-center gap-2 py-0.5 text-[10px]">
                    <input type="checkbox" checked={selectedPatterns.includes(name)} onChange={(e) => handlePatternCheckboxChange(name, e.target.checked)} className="accent-bull" />
                    <span className="font-mono text-fg-2">{name}</span>
                  </label>
                ))}
              </div>
            </div>

            <Button size="sm" className="w-full bg-bull text-canvas hover:bg-bull/90 font-mono text-xs" onClick={() => void run()} disabled={loading}>
              {loading ? "⏳ Simulazione…" : "▶ Esegui simulazione"}
            </Button>
          </div>
        </aside>

        {/* ── Results ─────────────────────────────────────────────────── */}
        <main className="min-w-0 flex-1">
          {/* Error */}
          {error && (
            <div className="mb-4 rounded-xl border border-bear/30 bg-bear/5 p-3 text-sm text-bear" role="alert">
              {error}
            </div>
          )}

          {/* Empty state */}
          {!result && !loading && !error && (
            <div className="flex items-center justify-center rounded-xl border border-dashed border-line bg-surface p-12 text-center">
              <p className="text-sm text-fg-2">
                Configura i parametri e clicca <strong className="text-fg">Esegui simulazione</strong>.
              </p>
            </div>
          )}

          {/* Loading state */}
          {loading && !result && (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-line bg-surface py-16">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-bull border-t-transparent" aria-hidden />
              <p className="text-sm text-fg-2">Simulazione in corso…</p>
            </div>
          )}

          {/* Results tabs */}
          {result && (
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="bg-surface border border-line">
                <TabsTrigger value="equity" className="text-xs data-[state=active]:bg-surface-3">
                  Equity Curve
                </TabsTrigger>
                <TabsTrigger value="oos" className="text-xs data-[state=active]:bg-surface-3">
                  OOS {oosResult && <span className="ml-1 h-1.5 w-1.5 rounded-full bg-bull inline-block" />}
                </TabsTrigger>
                <TabsTrigger value="walkforward" className="text-xs data-[state=active]:bg-surface-3">
                  Walk-Forward {wfResult && <span className="ml-1 h-1.5 w-1.5 rounded-full bg-bull inline-block" />}
                </TabsTrigger>
              </TabsList>

              {/* ── Equity tab ─────────────────────────────────────────── */}
              <TabsContent value="equity" className="mt-4 space-y-4">
                {/* KPI row */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {equityKpis.map((k) => (
                    <KPICard key={k.label} label={k.label} value={k.value} variant={k.variant} delta={k.delta} />
                  ))}
                </div>

                {/* Chart */}
                {chartData.length >= 2 && (
                  <div className="rounded-xl border border-line bg-surface p-4">
                    <p className="mb-3 text-xs text-fg-2">{periodLabel} · {result.total_trades.toLocaleString("it-IT")} trade</p>
                    <div className="h-[360px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="capitalGradient" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="hsl(168,100%,42%)" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="hsl(168,100%,42%)" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(240,24%,14%)" />
                          <XAxis dataKey="timestamp" tick={{ fontSize: 10, fill: "hsl(240,15%,48%)" }} interval="preserveStartEnd" minTickGap={32} tickFormatter={(ts) => { try { return new Date(ts).toLocaleDateString("it-IT", { month: "short", day: "numeric" }); } catch { return String(ts); } }} />
                          <YAxis tickFormatter={(v) => v >= 1000 ? `€${(v / 1000).toFixed(1)}k` : `€${Math.round(v)}`} tick={{ fontSize: 11, fill: "hsl(240,15%,48%)" }} width={56} />
                          <Tooltip content={({ active, payload }) => <EquityTooltip active={active} payload={payload as ChartTooltipProps["payload"]} />} />
                          <ReferenceLine y={result.initial_capital} stroke="hsl(240,24%,14%)" strokeDasharray="4 4" />
                          <Area type="monotone" dataKey="capitale" stroke="hsl(168,100%,42%)" strokeWidth={2} fill="url(#capitalGradient)" dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Notes */}
                {result.note && (
                  <p className="rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-warn">{result.note}</p>
                )}
              </TabsContent>

              {/* ── OOS tab ────────────────────────────────────────────── */}
              <TabsContent value="oos" className="mt-4 space-y-4">
                <div className="flex flex-wrap items-end gap-4">
                  <label className="flex flex-col gap-1 text-xs text-fg-2">
                    Data cutoff (IS/OOS)
                    <input type="date" className="rounded-lg border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg" value={oosCutoff} onChange={(e) => setOosCutoff(e.target.value)} />
                  </label>
                  <Button size="sm" className="bg-fg text-canvas hover:bg-fg/90 font-mono text-xs" onClick={() => void handleRunOOS()} disabled={oosLoading}>
                    {oosLoading ? "⏳ Validazione…" : "▶ Valida OOS"}
                  </Button>
                </div>

                {oosError && <p className="rounded-xl border border-bear/30 bg-bear/5 p-3 text-sm text-bear" role="alert">{oosError}</p>}

                {oosResult && (
                  <>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      {[
                        { label: "OOS Win rate", value: `${(oosResult.test_set.win_rate * 100).toFixed(1)}%`, variant: ((oosResult.test_set.win_rate * 100) >= 55 ? "bull" : "bear") as "bull" | "bear" },
                        { label: "OOS Return", value: `${oosResult.test_set.total_return_pct.toFixed(1)}%`, variant: (oosResult.test_set.total_return_pct >= 0 ? "bull" : "bear") as "bull" | "bear" },
                        { label: "Degradazione", value: `${oosResult.performance_degradation_pct.toFixed(1)}%`, variant: (oosResult.performance_degradation_pct < 10 ? "neutral" : "warn") as "neutral" | "warn" },
                      ].map((k) => <KPICard key={k.label} label={k.label} value={k.value} variant={k.variant} />)}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-fg-2">Verdetto:</span>
                      <Badge variant="outline" className={cn("font-mono text-xs", oosResult.oos_verdict === "robusto" ? "border-bull/40 text-bull" : oosResult.oos_verdict === "degradazione_moderata" ? "border-warn/40 text-warn" : "border-bear/40 text-bear")}>
                        {oosResult.oos_verdict.replace(/_/g, " ")}
                      </Badge>
                    </div>
                    {oosChartData.length >= 2 && (
                      <div className="rounded-xl border border-line bg-surface p-4">
                        <p className="mb-3 text-xs text-fg-2">OOS equity ({oosResult.test_set.total_trades} trade)</p>
                        <div className="h-[280px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={oosChartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                              <defs>
                                <linearGradient id="oosGradient" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="5%" stopColor="hsl(229,57%,63%)" stopOpacity={0.3} />
                                  <stop offset="95%" stopColor="hsl(229,57%,63%)" stopOpacity={0} />
                                </linearGradient>
                              </defs>
                              <CartesianGrid strokeDasharray="3 3" stroke="hsl(240,24%,14%)" />
                              <XAxis dataKey="timestamp" tick={{ fontSize: 10, fill: "hsl(240,15%,48%)" }} interval="preserveStartEnd" minTickGap={40} tickFormatter={(ts) => { try { return new Date(ts).toLocaleDateString("it-IT", { month: "short", day: "numeric" }); } catch { return String(ts); } }} />
                              <YAxis tickFormatter={(v) => `€${Math.round(v)}`} tick={{ fontSize: 11, fill: "hsl(240,15%,48%)" }} width={56} />
                              <Tooltip content={({ active, payload }) => <EquityTooltip active={active} payload={payload as ChartTooltipProps["payload"]} />} />
                              <Area type="monotone" dataKey="capitale" stroke="hsl(229,57%,63%)" strokeWidth={2} fill="url(#oosGradient)" dot={false} />
                            </AreaChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </TabsContent>

              {/* ── Walk-Forward tab ───────────────────────────────────── */}
              <TabsContent value="walkforward" className="mt-4 space-y-4">
                <div className="flex flex-wrap items-end gap-4">
                  <label className="flex flex-col gap-1 text-xs text-fg-2">
                    Numero fold
                    <input type="number" min={2} max={10} className="w-20 rounded-lg border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg" value={nFolds} onChange={(e) => setNFolds(Math.min(10, Math.max(2, Number(e.target.value) || 3)))} />
                  </label>
                  <Button size="sm" className="bg-fg text-canvas hover:bg-fg/90 font-mono text-xs" onClick={() => void handleRunWF()} disabled={wfLoading}>
                    {wfLoading ? "⏳" : "▶"} {wfLoading ? "Walk-Forward…" : "Esegui Walk-Forward"}
                  </Button>
                  {wfLoading && (
                    <Button size="sm" variant="ghost" className="text-xs text-bear" onClick={cancelWF}>
                      Annulla
                    </Button>
                  )}
                </div>

                {/* WF progress bar */}
                {wfLoading && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs text-fg-2">
                      <span>Walk-Forward in corso… può richiedere fino a 2 minuti</span>
                      <span className="font-mono tabular-nums text-fg-3" suppressHydrationWarning>{wfElapsed}s</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                      <div
                        className="h-full rounded-full bg-neutral transition-all duration-1000"
                        style={{ width: `${wfProgress}%` }}
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={Math.round(wfProgress)}
                      />
                    </div>
                  </div>
                )}

                {wfError && <p className="rounded-xl border border-bear/30 bg-bear/5 p-3 text-sm text-bear" role="alert">{wfError}</p>}

                {wfResult && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      {[
                        { label: "Fold valutati", value: wfResult.n_folds, variant: "neutral" as const },
                        { label: "Win rate medio OOS", value: `${(wfResult.avg_test_win_rate * 100).toFixed(1)}%`, variant: (wfResult.avg_test_win_rate >= 0.55 ? "bull" : "neutral") as "bull" | "neutral" },
                        { label: "Return medio OOS", value: `${wfResult.avg_test_return_pct.toFixed(1)}%`, variant: (wfResult.avg_test_return_pct >= 0 ? "bull" : "bear") as "bull" | "bear" },
                      ].map((k) => <KPICard key={k.label} label={k.label} value={k.value} variant={k.variant} />)}
                    </div>

                    {wfResult.folds && (
                      <div className="rounded-xl border border-line bg-surface overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-line">
                              {["Fold", "IS Return", "OOS Return", "IS WR%", "OOS WR%", "Trade OOS"].map((h) => (
                                <th key={h} scope="col" className="px-3 py-2 text-left font-medium text-fg-3">{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                          {wfResult.folds.map((f, i) => (
                            <tr key={i} className="border-b border-line/50 hover:bg-surface-2">
                              <td className="px-3 py-2 font-mono text-fg-2">#{f.fold_number}</td>
                              <td className={cn("px-3 py-2 font-mono tabular-nums", f.train_return_pct >= 0 ? "text-bull" : "text-bear")}>{f.train_return_pct.toFixed(1)}%</td>
                              <td className={cn("px-3 py-2 font-mono tabular-nums", f.test_return_pct >= 0 ? "text-bull" : "text-bear")}>{f.test_return_pct.toFixed(1)}%</td>
                              <td className="px-3 py-2 font-mono tabular-nums text-fg">{(f.train_win_rate * 100).toFixed(1)}%</td>
                              <td className={cn("px-3 py-2 font-mono tabular-nums", f.test_win_rate >= 0.55 ? "text-bull" : "text-fg")}>{(f.test_win_rate * 100).toFixed(1)}%</td>
                              <td className="px-3 py-2 font-mono tabular-nums text-fg-2">{f.test_trades}</td>
                            </tr>
                          ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          )}
        </main>
      </div>
    </div>
  );
}

