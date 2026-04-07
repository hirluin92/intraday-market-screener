"use client";

import { useCallback, useMemo, useState } from "react";
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

/**
 * Preset Top Yahoo 1h: pattern validati + universo operativo (6 ticker) da
 * `VALIDATED_SYMBOLS_YAHOO` / simulazione.
 */
const TOP_YAHOO_1H = [
  "compression_to_expansion_transition",
  "rsi_momentum_continuation",
] as const;

const TOP_YAHOO_1H_INCLUDE_SYMBOLS = [
  "GOOGL",
  "TSLA",
  "AMD",
  "META",
  "NVDA",
  "NFLX",
] as const;

const PRESET_KEYS = [
  "Top Yahoo 1h",
  "Top Yahoo 5m",
  "Top Binance 1h",
  "Tutti i pattern",
] as const;

type PresetKey = (typeof PRESET_KEYS)[number];

const PRESETS: Record<PresetKey, string[]> = {
  "Top Yahoo 1h": [
    "compression_to_expansion_transition",
    "rsi_momentum_continuation",
  ],
  "Top Yahoo 5m": ["rsi_momentum_continuation"],
  "Top Binance 1h": [
    "rsi_momentum_continuation",
    "trend_continuation_pullback",
    "compression_to_expansion_transition",
    "engulfing_bearish",
    "inside_bar_breakout_bull",
    "support_bounce",
  ],
  "Tutti i pattern": [],
};

const ALL_PATTERNS: string[] = [
  "bear_flag",
  "bull_flag",
  "compression_to_expansion_transition",
  "engulfing_bearish",
  "engulfing_bullish",
  "ema_pullback_to_resistance",
  "ema_pullback_to_support",
  "fibonacci_bounce",
  "hammer_reversal",
  "impulsive_bearish_candle",
  "impulsive_bullish_candle",
  "inside_bar_breakout_bull",
  "morning_star",
  "evening_star",
  "opening_range_breakout_bull",
  "opening_range_breakout_bear",
  "rsi_momentum_continuation",
  "resistance_rejection",
  "support_bounce",
  "shooting_star_reversal",
  "trend_continuation_pullback",
  "vwap_bounce_bull",
  "vwap_bounce_bear",
  "breakout_with_retest",
];

/** Suggerimento opzionale (pranzo NY / after hours su 1h Yahoo). */
const SUGGESTED_EXCLUDE_HOURS_UTC = [17, 21] as const;
const HOURS_UTC_OPTIONS = Array.from({ length: 24 }, (_, i) => i);

const PERIOD_LABELS: Record<string, string> = {
  "1m": "Ultimo mese",
  "3m": "Ultimi 3 mesi",
  "6m": "Ultimi 6 mesi",
  "1y": "Ultimo anno",
  "2y": "Ultimi 2 anni",
  "3y": "Ultimi 3 anni",
  all: "Tutto lo storico",
};

function enrichEquityForChart(
  points: SimulationEquityPoint[],
  initialCapital: number,
): Array<{
  timestamp: string;
  equity: number;
  capitale: number;
  drawdown_pct: number;
  dateLabel: string;
}> {
  let peak = initialCapital;
  return points.map((p) => {
    peak = Math.max(peak, p.equity);
    const drawdown_pct = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
    let dateLabel = p.timestamp;
    try {
      dateLabel = new Date(p.timestamp).toLocaleString("it-IT", {
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch {
      /* ignore */
    }
    return {
      timestamp: p.timestamp,
      equity: p.equity,
      capitale: Math.round(p.equity),
      drawdown_pct,
      dateLabel,
    };
  });
}

function tradeDerivedStats(trades: SimulationTradeRow[] | undefined) {
  if (!trades?.length) {
    return {
      winning_trades: 0,
      losing_trades: 0,
      flat_trades: 0,
      avg_win_r: null as number | null,
      avg_loss_r: null as number | null,
      profit_factor: null as number | null,
    };
  }
  const wins = trades.filter((t) => t.outcome === "win");
  const losses = trades.filter((t) => t.outcome === "loss");
  const flats = trades.filter((t) => t.outcome === "flat");
  const sumPos = wins.reduce((s, t) => s + Math.max(0, t.pnl_r), 0);
  const sumNeg = losses.reduce((s, t) => s + Math.abs(Math.min(0, t.pnl_r)), 0);
  const profitFactor = sumNeg > 1e-12 ? sumPos / sumNeg : null;
  return {
    winning_trades: wins.length,
    losing_trades: losses.length,
    flat_trades: flats.length,
    avg_win_r:
      wins.length > 0 ? wins.reduce((s, t) => s + t.pnl_r, 0) / wins.length : null,
    avg_loss_r:
      losses.length > 0
        ? losses.reduce((s, t) => s + t.pnl_r, 0) / losses.length
        : null,
    profit_factor: profitFactor,
  };
}

function metricColorClass(
  kind: "return" | "dd" | "sharpe" | "pf",
  value: number,
): string {
  if (kind === "return") {
    return value >= 0
      ? "text-emerald-700 dark:text-emerald-300"
      : "text-red-700 dark:text-red-300";
  }
  if (kind === "dd") {
    return value > 30
      ? "text-red-700 dark:text-red-300"
      : "text-amber-700 dark:text-amber-300";
  }
  if (kind === "sharpe") {
    return value > 1
      ? "text-emerald-700 dark:text-emerald-300"
      : "text-amber-700 dark:text-amber-300";
  }
  if (kind === "pf") {
    return value > 1
      ? "text-emerald-700 dark:text-emerald-300"
      : "text-red-700 dark:text-red-300";
  }
  return "";
}

export default function SimulationPage() {
  const [capital, setCapital] = useState(10_000);
  const [riskPct, setRiskPct] = useState(1);
  const [costRate, setCostRate] = useState(0.0015);
  const [provider, setProvider] = useState("yahoo_finance");
  const [timeframe, setTimeframe] = useState("1h");
  const [period, setPeriod] = useState("1y");
  const [selectedPatterns, setSelectedPatterns] = useState<string[]>(() => [
    ...TOP_YAHOO_1H,
  ]);
  /** Preset UI attivo; "custom" = checkbox modificati a mano. */
  const [activePreset, setActivePreset] = useState<PresetKey | "custom">(
    "Top Yahoo 1h",
  );
  const [maxSimultaneous, setMaxSimultaneous] = useState(3);
  const [cooldownBars, setCooldownBars] = useState(0);
  const [includeTrades, setIncludeTrades] = useState(true);
  const [useRegimeFilter, setUseRegimeFilter] = useState(true);
  /** Solo Yahoo Finance — vuoto = nessun filtro (allineato all’API). */
  const [excludedHours, setExcludedHours] = useState<number[]>(() => []);
  /** Preset Top Yahoo 1h: solo questi ticker; vuoto = tutti i simboli nel DB. */
  const [includedSymbols, setIncludedSymbols] = useState<string[]>(() => [
    ...TOP_YAHOO_1H_INCLUDE_SYMBOLS,
  ]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [showOOS, setShowOOS] = useState(false);
  const [oosCutoff, setOosCutoff] = useState("2025-01-01");
  const [oosLoading, setOosLoading] = useState(false);
  const [oosResult, setOosResult] = useState<OOSResult | null>(null);
  const [oosError, setOosError] = useState<string | null>(null);

  const [showWF, setShowWF] = useState(false);
  const [nFolds, setNFolds] = useState(3);
  const [wfLoading, setWfLoading] = useState(false);
  const [wfResult, setWfResult] = useState<WalkForwardResult | null>(null);
  const [wfError, setWfError] = useState<string | null>(null);

  const applyPreset = useCallback((key: PresetKey) => {
    const next = PRESETS[key];
    setSelectedPatterns([...next]);
    setActivePreset(key);
    if (key === "Top Yahoo 5m") {
      setTimeframe("5m");
      setProvider("yahoo_finance");
      setIncludedSymbols([]);
    } else if (key === "Top Yahoo 1h") {
      setTimeframe("1h");
      setProvider("yahoo_finance");
      setIncludedSymbols([...TOP_YAHOO_1H_INCLUDE_SYMBOLS]);
    } else if (key === "Top Binance 1h") {
      setTimeframe("1h");
      setProvider("binance");
      setIncludedSymbols([]);
    } else {
      setIncludedSymbols([]);
    }
  }, []);

  /** Allineamento esplicito allo stato del checkbox (evita doppio toggle con <label>). */
  const handlePatternCheckboxChange = useCallback(
    (pattern: string, checked: boolean) => {
      setActivePreset("custom");
      setSelectedPatterns((prev) => {
        if (checked) {
          return prev.includes(pattern) ? prev : [...prev, pattern];
        }
        return prev.filter((p) => p !== pattern);
      });
    },
    [],
  );

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    const trimmed =
      selectedPatterns.length > 0
        ? selectedPatterns.map((p) => p.trim()).filter(Boolean)
        : [];
    const names =
      trimmed.length > 0 ? trimmed : undefined;
    try {
      const res = await fetchBacktestSimulation({
        provider,
        timeframe,
        pattern_names: names,
        initial_capital: capital,
        risk_per_trade_pct: riskPct,
        cost_rate: costRate,
        max_simultaneous: maxSimultaneous,
        include_trades: includeTrades,
        pattern_row_limit: 50_000,
        period,
        use_regime_filter: useRegimeFilter,
        cooldown_bars: cooldownBars,
        ...(provider === "yahoo_finance" && excludedHours.length > 0
          ? { exclude_hours: excludedHours }
          : {}),
        ...(provider === "yahoo_finance" && includedSymbols.length > 0
          ? { include_symbols: includedSymbols }
          : {}),
      });
      setResult(res);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [
    provider,
    timeframe,
    selectedPatterns,
    capital,
    riskPct,
    costRate,
    maxSimultaneous,
    includeTrades,
    useRegimeFilter,
    period,
    excludedHours,
    includedSymbols,
    cooldownBars,
  ]);

  const handleRunOOS = useCallback(async () => {
    setOosLoading(true);
    setOosError(null);
    const trimmed =
      selectedPatterns.length > 0
        ? selectedPatterns.map((p) => p.trim()).filter(Boolean)
        : [];
    const names = trimmed.length > 0 ? trimmed : undefined;
    try {
      const res = await fetchOutOfSample({
        provider,
        timeframe,
        pattern_names: names,
        cutoff_date: oosCutoff,
        initial_capital: capital,
        risk_per_trade_pct: riskPct,
        cost_rate: costRate,
        max_simultaneous: maxSimultaneous,
        include_trades: false,
        use_regime_filter: useRegimeFilter,
      });
      setOosResult(res);
    } catch (e) {
      setOosResult(null);
      setOosError(e instanceof Error ? e.message : String(e));
    } finally {
      setOosLoading(false);
    }
  }, [
    provider,
    timeframe,
    selectedPatterns,
    oosCutoff,
    capital,
    riskPct,
    costRate,
    maxSimultaneous,
    useRegimeFilter,
  ]);

  const handleRunWF = useCallback(async () => {
    setWfLoading(true);
    setWfError(null);
    const trimmed =
      selectedPatterns.length > 0
        ? selectedPatterns.map((p) => p.trim()).filter(Boolean)
        : [];
    const names = trimmed.length > 0 ? trimmed : undefined;
    try {
      const res = await fetchWalkForward({
        provider,
        timeframe,
        pattern_names: names,
        n_folds: nFolds,
        initial_capital: capital,
        risk_per_trade_pct: riskPct,
        cost_rate: costRate,
        max_simultaneous: maxSimultaneous,
        use_regime_filter: useRegimeFilter,
        ...(provider === "yahoo_finance" && excludedHours.length > 0
          ? { exclude_hours: excludedHours }
          : {}),
        ...(provider === "yahoo_finance" && includedSymbols.length > 0
          ? { include_symbols: includedSymbols }
          : {}),
        timeoutMs: 120_000,
      });
      setWfResult(res);
    } catch (e) {
      setWfResult(null);
      setWfError(e instanceof Error ? e.message : String(e));
    } finally {
      setWfLoading(false);
    }
  }, [
    provider,
    timeframe,
    selectedPatterns,
    nFolds,
    capital,
    riskPct,
    costRate,
    maxSimultaneous,
    useRegimeFilter,
    excludedHours,
    includedSymbols,
  ]);

  const derived = useMemo(
    () => tradeDerivedStats(result?.trades),
    [result?.trades],
  );

  const chartData = useMemo(() => {
    if (!result?.equity_curve?.length) return [];
    return enrichEquityForChart(result.equity_curve, result.initial_capital);
  }, [result]);

  const oosChartData = useMemo(() => {
    if (!oosResult?.test_set.equity_curve?.length) return [];
    return enrichEquityForChart(oosResult.test_set.equity_curve, capital);
  }, [oosResult, capital]);

  const recentTrades = useMemo(() => {
    const t = result?.trades;
    if (!t?.length) return [];
    return [...t].slice(-100).reverse();
  }, [result?.trades]);

  const metrics = useMemo(() => {
    if (!result) return [];
    const pf =
      derived.profit_factor != null && Number.isFinite(derived.profit_factor)
        ? derived.profit_factor
        : null;
    return [
      {
        label: "Capitale finale",
        value: `€${result.final_capital.toLocaleString("it-IT", {
          maximumFractionDigits: 0,
        })}`,
        sub: `${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct.toFixed(1)}%`,
        colorClass: metricColorClass("return", result.total_return_pct),
      },
      {
        label: "Max drawdown",
        value: `${result.max_drawdown_pct.toFixed(1)}%`,
        sub: undefined,
        colorClass: metricColorClass("dd", result.max_drawdown_pct),
      },
      {
        label: "Sharpe (euristico)",
        value:
          result.sharpe_ratio != null ? result.sharpe_ratio.toFixed(3) : "—",
        sub: undefined,
        colorClass:
          result.sharpe_ratio != null
            ? metricColorClass("sharpe", result.sharpe_ratio)
            : "text-zinc-600 dark:text-zinc-400",
      },
      {
        label: "Win rate",
        value: `${result.win_rate.toFixed(1)}%`,
        sub:
          includeTrades && result.trades?.length
            ? `${derived.winning_trades}W / ${derived.losing_trades}L`
            : `${result.total_trades} trade`,
        colorClass: "text-zinc-900 dark:text-zinc-100",
      },
      {
        label: "Trade totali",
        value: result.total_trades.toLocaleString("it-IT"),
        sub: `${result.bars_with_trades ?? "—"} barre`,
        colorClass: "text-zinc-900 dark:text-zinc-100",
      },
      {
        label: "Profit factor (R)",
        value: pf != null ? pf.toFixed(2) : "—",
        sub:
          result.avg_simultaneous_trades != null
            ? `Ø simultanei ${result.avg_simultaneous_trades.toFixed(2)} (max ${result.max_simultaneous_observed ?? "—"})`
            : undefined,
        colorClass:
          pf != null ? metricColorClass("pf", pf) : "text-zinc-600 dark:text-zinc-400",
      },
      {
        label: "Regime SPY (1d)",
        value: result.regime_filter_active
          ? `${result.trades_skipped_by_regime ?? 0} esclusi`
          : useRegimeFilter
            ? "Non attivo (no dati)"
            : "Off",
        sub: result.regime_filter_active
          ? "Solo direzioni allineate a EMA50 (±2%)"
          : undefined,
        colorClass: "text-zinc-900 dark:text-zinc-100",
      },
    ];
  }, [result, derived, includeTrades, useRegimeFilter]);

  const periodLabel = PERIOD_LABELS[period] ?? period;

  const rowClass = (outcome: string) => {
    if (outcome === "win")
      return "bg-emerald-950/20 hover:bg-emerald-950/35 dark:bg-emerald-950/25";
    if (outcome === "loss")
      return "bg-red-950/20 hover:bg-red-950/35 dark:bg-red-950/25";
    return "bg-zinc-900/20 hover:bg-zinc-900/35";
  };

  return (
    <div className="mx-auto flex min-h-full max-w-[120rem] flex-col gap-6 p-4 sm:p-6">
      <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Simulazione equity curve
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Trade plan in-sample (stesso motore del backtest); rischio ripartito per
            barra tra i fill simultanei.
          </p>
        </div>
      </header>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <aside className="lg:sticky lg:top-6 lg:w-80 lg:shrink-0">
          <div className="flex flex-col gap-4 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-700 dark:bg-zinc-900/60">
            <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
              Parametri
            </h2>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">
                Capitale iniziale (€)
              </span>
              <input
                type="number"
                min={1}
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={capital}
                onChange={(e) => setCapital(Number(e.target.value))}
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">
                Rischio % / barra (totale)
              </span>
              <input
                type="number"
                min={0.01}
                step="any"
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={riskPct}
                onChange={(e) => setRiskPct(Number(e.target.value))}
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">Provider</span>
              <select
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="yahoo_finance">yahoo_finance</option>
                <option value="binance">binance</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">Timeframe</span>
              <select
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
              >
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="1d">1d</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">Periodo</span>
              <select
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              >
                <option value="1m">Ultimo mese</option>
                <option value="3m">Ultimi 3 mesi</option>
                <option value="6m">Ultimi 6 mesi</option>
                <option value="1y">Ultimo anno</option>
                <option value="2y">Ultimi 2 anni</option>
                <option value="3y">Ultimi 3 anni</option>
                <option value="all">Tutto lo storico</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">
                Max simultanei / barra
              </span>
              <input
                type="number"
                min={1}
                max={10}
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={maxSimultaneous}
                onChange={(e) =>
                  setMaxSimultaneous(
                    Math.min(10, Math.max(1, Number(e.target.value) || 1)),
                  )
                }
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">
                Cooldown barre (anti-overlap per serie)
              </span>
              <select
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={cooldownBars}
                onChange={(e) => setCooldownBars(Number(e.target.value))}
              >
                <option value={0}>Nessuno (come prima)</option>
                <option value={2}>2 barre</option>
                <option value={3}>3 barre (consigliato)</option>
                <option value={5}>5 barre</option>
                <option value={10}>10 barre</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-600 dark:text-zinc-400">
                Costo round-trip
              </span>
              <input
                type="number"
                min={0}
                step="any"
                className="rounded border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-600 dark:bg-zinc-950"
                value={costRate}
                onChange={(e) => setCostRate(Number(e.target.value))}
              />
            </label>

            <div className="mt-3 flex items-center gap-2 text-sm">
              <input
                id="regimeFilter"
                type="checkbox"
                checked={useRegimeFilter}
                onChange={(e) => setUseRegimeFilter(e.target.checked)}
                className="h-4 w-4 rounded accent-emerald-600"
              />
              <label
                htmlFor="regimeFilter"
                className="cursor-pointer text-zinc-700 dark:text-zinc-300"
              >
                Filtro regime SPY (solo direzione allineata al trend)
              </label>
            </div>

            {provider === "yahoo_finance" ? (
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-zinc-600 dark:text-zinc-400">
                  Ore escluse (UTC)
                </span>
                <select
                  multiple
                  size={8}
                  className="min-h-[10rem] min-w-[12rem] rounded border border-zinc-300 bg-white px-2 py-1 font-mono text-xs dark:border-zinc-600 dark:bg-zinc-950"
                  value={excludedHours.map(String)}
                  onChange={(e) => {
                    const opts = Array.from(e.target.selectedOptions).map((o) =>
                      Number(o.value),
                    );
                    if (opts.length === 0) {
                      setExcludedHours([]);
                      return;
                    }
                    setExcludedHours(opts.sort((a, b) => a - b));
                  }}
                  title="Barre la cui chiusura cade in queste ore UTC non entrano in simulazione (default 17, 21)."
                >
                  {HOURS_UTC_OPTIONS.map((h) => (
                    <option key={h} value={h}>
                      {h}:00 UTC
                    </option>
                  ))}
                </select>
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  Suggerimento spesso usato: {SUGGESTED_EXCLUDE_HOURS_UTC.join(" e ")} UTC.
                  Crypto 24/7: nessun filtro orario.
                </span>
              </label>
            ) : (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Filtro orario non applicato a Binance (mercato 24/7).
              </p>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeTrades}
                onChange={(e) => setIncludeTrades(e.target.checked)}
                className="rounded border-zinc-400"
              />
              <span className="text-zinc-700 dark:text-zinc-300">
                Scarica elenco trade (più lento)
              </span>
            </label>

            <div>
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                Preset pattern
              </span>
              <div className="mt-2 flex flex-wrap gap-2">
                {PRESET_KEYS.map((k) => {
                  const isActive = activePreset === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        isActive
                          ? "border-emerald-500 bg-emerald-600 text-white shadow-sm dark:border-emerald-400"
                          : "border-zinc-300 bg-white text-zinc-700 hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      }`}
                      onClick={() => applyPreset(k)}
                    >
                      {k}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                Pattern (checkbox)
              </span>
              <div className="mt-2 max-h-48 overflow-y-auto rounded border border-zinc-200 p-2 dark:border-zinc-700">
                {ALL_PATTERNS.map((name) => (
                  <label
                    key={name}
                    className="flex cursor-pointer items-center gap-2 py-0.5 text-xs"
                  >
                    <input
                      type="checkbox"
                      className="rounded border-zinc-400"
                      checked={selectedPatterns.includes(name)}
                      onChange={(e) =>
                        handlePatternCheckboxChange(name, e.target.checked)
                      }
                    />
                    <span className="font-mono text-zinc-700 dark:text-zinc-300">
                      {name}
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {selectedPatterns.length === 0
                  ? "Nessun pattern selezionato: la richiesta userà tutti i pattern disponibili per provider×timeframe (API)."
                  : `${selectedPatterns.length} pattern selezionati${
                      activePreset === "custom" ? " (selezione manuale)" : ""
                    }`}
              </p>
            </div>

            <button
              type="button"
              className="rounded-lg bg-emerald-600 px-4 py-3 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
              onClick={() => void run()}
              disabled={loading}
            >
              {loading ? "Simulazione in corso…" : "Esegui simulazione"}
            </button>
            {loading ? (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Può richiedere 10–30 secondi con molti pattern.
              </p>
            ) : null}
          </div>
        </aside>

        <main className="min-w-0 flex-1 flex flex-col gap-6">
          {error ? (
            <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
              {error}
            </p>
          ) : null}

          {!result && !loading && !error ? (
            <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50/80 p-8 text-center dark:border-zinc-600 dark:bg-zinc-900/40">
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Configura i parametri a sinistra e clicca{" "}
                <strong>Esegui simulazione</strong> per caricare la curva e le
                metriche.
              </p>
            </div>
          ) : null}

          {loading && !result ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-zinc-200 bg-white py-16 dark:border-zinc-700 dark:bg-zinc-900/60">
              <div
                className="h-10 w-10 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent"
                aria-hidden
              />
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Simulazione in corso…
              </p>
            </div>
          ) : null}

          {result ? (
            <>
              {result.note ? (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100">
                  {result.note}
                </p>
              ) : null}

              {result.regime_filter_active ? (
                <p className="mt-1 text-xs text-sky-600 dark:text-sky-400">
                  Filtro regime attivo —{" "}
                  {result.trades_skipped_by_regime ?? 0} segnali esclusi per
                  direzione non allineata al trend SPY (EMA50 giornaliera).
                </p>
              ) : null}

              {(result.trades_skipped_by_cooldown ?? 0) > 0 ? (
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                  {result.trades_skipped_by_cooldown} trade saltati per cooldown
                  ({result.cooldown_bars_used ?? cooldownBars} barre anti-overlap
                  per simbolo+timeframe+provider)
                </p>
              ) : null}

              <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {metrics.map((m) => (
                  <div
                    key={m.label}
                    className="rounded-lg border border-zinc-200 bg-zinc-50/80 px-3 py-3 dark:border-zinc-700 dark:bg-zinc-900/40"
                  >
                    <div className="text-xs text-zinc-500 dark:text-zinc-400">
                      {m.label}
                    </div>
                    <div
                      className={`mt-1 font-mono text-lg font-semibold tabular-nums ${m.colorClass}`}
                    >
                      {m.value}
                    </div>
                    {m.sub ? (
                      <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-500">
                        {m.sub}
                      </div>
                    ) : null}
                  </div>
                ))}
              </section>

              {result.total_trades > 0 ? (
                <p className="text-xs text-zinc-600 dark:text-zinc-400">
                  Significatività statistica (one-sided): win rate{" "}
                  <span
                    className={`font-mono font-medium ${
                      result.win_rate_significance === "***"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : result.win_rate_significance === "**"
                          ? "text-sky-600 dark:text-sky-400"
                          : result.win_rate_significance === "*"
                            ? "text-amber-600 dark:text-amber-400"
                            : "text-zinc-500 dark:text-zinc-500"
                    }`}
                  >
                    {result.win_rate_significance ?? "ns"}
                  </span>
                  {result.win_rate_pvalue != null ? (
                    <span className="text-zinc-500">
                      {" "}
                      (p={result.win_rate_pvalue.toFixed(3)})
                    </span>
                  ) : null}
                  {" · "}edge R (expectancy){" "}
                  <span
                    className={`font-mono font-medium ${
                      result.expectancy_significance === "***"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : result.expectancy_significance === "**"
                          ? "text-sky-600 dark:text-sky-400"
                          : result.expectancy_significance === "*"
                            ? "text-amber-600 dark:text-amber-400"
                            : "text-zinc-500 dark:text-zinc-500"
                    }`}
                  >
                    {result.expectancy_significance ?? "ns"}
                  </span>
                  {result.expectancy_pvalue != null ? (
                    <span className="text-zinc-500">
                      {" "}
                      (p={result.expectancy_pvalue.toFixed(3)})
                    </span>
                  ) : null}
                </p>
              ) : null}

              <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900/60">
                <h2 className="mb-1 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                  Equity curve
                </h2>
                <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
                  {period === "all"
                    ? "Tutto lo storico disponibile"
                    : `Periodo: ${periodLabel}`}
                  {" · "}
                  {result.total_trades.toLocaleString("it-IT")} trade
                </p>
                {chartData.length >= 2 ? (
                  <div className="h-[400px] w-full min-h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={chartData}
                        margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient
                            id="capitalGradient"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="5%"
                              stopColor="#10b981"
                              stopOpacity={0.35}
                            />
                            <stop
                              offset="95%"
                              stopColor="#10b981"
                              stopOpacity={0}
                            />
                          </linearGradient>
                        </defs>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          className="opacity-30"
                          stroke="currentColor"
                        />
                        <XAxis
                          dataKey="timestamp"
                          tick={{ fontSize: 10 }}
                          interval="preserveStartEnd"
                          minTickGap={32}
                          tickFormatter={(ts) => {
                            try {
                              return new Date(ts).toLocaleDateString("it-IT", {
                                month: "short",
                                day: "numeric",
                              });
                            } catch {
                              return String(ts);
                            }
                          }}
                        />
                        <YAxis
                          tickFormatter={(v) =>
                            v >= 1000
                              ? `€${(v / 1000).toFixed(1)}k`
                              : `€${Math.round(v)}`
                          }
                          tick={{ fontSize: 11 }}
                          width={56}
                        />
                        <Tooltip
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null;
                            const d = payload[0]?.payload as (typeof chartData)[0];
                            return (
                              <div className="rounded-lg border border-zinc-600 bg-zinc-900 px-3 py-2 text-xs text-zinc-100 shadow-lg">
                                <p className="text-zinc-400">{d.dateLabel}</p>
                                <p className="font-mono font-semibold text-emerald-400">
                                  €
                                  {d.capitale.toLocaleString("it-IT", {
                                    maximumFractionDigits: 0,
                                  })}
                                </p>
                                {d.drawdown_pct > 0.05 ? (
                                  <p className="text-red-400">
                                    DD: −{d.drawdown_pct.toFixed(2)}%
                                  </p>
                                ) : null}
                              </div>
                            );
                          }}
                        />
                        <ReferenceLine
                          y={result.initial_capital}
                          stroke="#71717a"
                          strokeDasharray="4 4"
                          label={{
                            value: "Capitale iniziale",
                            position: "insideTopRight",
                            fill: "#71717a",
                            fontSize: 11,
                          }}
                        />
                        <Area
                          type="monotone"
                          dataKey="capitale"
                          stroke="#059669"
                          strokeWidth={2}
                          fill="url(#capitalGradient)"
                          dot={false}
                          activeDot={{ r: 4 }}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500">
                    Punti insufficienti per il grafico.
                  </p>
                )}
              </section>

              {includeTrades && result.trades && result.trades.length > 0 ? (
                <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900/60">
                  <h2 className="mb-3 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                    Ultimi 100 trade
                  </h2>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[640px] border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-zinc-200 dark:border-zinc-700">
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            Data/ora
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            Simbolo
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            Pattern
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            Dir
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            Esito
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            R
                          </th>
                          <th className="py-2 pr-2 font-medium text-zinc-500">
                            R net
                          </th>
                          <th className="py-2 font-medium text-zinc-500">
                            Capitale dopo barra
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentTrades.map((t, i) => (
                          <tr
                            key={`${t.timestamp}-${t.symbol}-${t.pattern_name}-${i}`}
                            className={`border-b border-zinc-100 dark:border-zinc-800 ${rowClass(t.outcome)}`}
                          >
                            <td className="py-1.5 pr-2 font-mono text-zinc-700 dark:text-zinc-300">
                              {new Date(t.timestamp).toLocaleString("it-IT")}
                            </td>
                            <td className="py-1.5 pr-2">{t.symbol}</td>
                            <td className="py-1.5 pr-2 font-mono">{t.pattern_name}</td>
                            <td className="py-1.5 pr-2">{t.direction}</td>
                            <td className="py-1.5 pr-2">{t.outcome}</td>
                            <td className="py-1.5 pr-2 font-mono tabular-nums">
                              {t.pnl_r.toFixed(3)}
                            </td>
                            <td className="py-1.5 pr-2 font-mono tabular-nums">
                              {t.pnl_r_net.toFixed(3)}
                            </td>
                            <td className="py-1.5 font-mono tabular-nums">
                              €
                              {t.capital_after.toLocaleString("it-IT", {
                                maximumFractionDigits: 2,
                              })}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
            </>
          ) : null}

          <div className="mt-6 rounded-lg border border-zinc-200 dark:border-zinc-700">
            <button
              type="button"
              onClick={() => setShowOOS(!showOOS)}
              className="flex w-full items-center justify-between p-4 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
            >
              <div>
                <span className="font-medium text-zinc-900 dark:text-zinc-100">
                  Validazione Out-of-Sample
                </span>
                <span className="ml-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Verifica che l&apos;edge non sia overfitting (stessi parametri del
                  form)
                </span>
              </div>
              <span className="text-zinc-400" aria-hidden>
                {showOOS ? "▲" : "▼"}
              </span>
            </button>

            {showOOS ? (
              <div className="border-t border-zinc-200 p-4 dark:border-zinc-700">
                <div className="mb-4 flex flex-wrap items-end gap-4">
                  <div>
                    <label className="mb-1 block text-sm text-zinc-600 dark:text-zinc-400">
                      Data di cutoff (train/test split)
                    </label>
                    <select
                      value={oosCutoff}
                      onChange={(e) => setOosCutoff(e.target.value)}
                      className="rounded border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-950"
                    >
                      <option value="2024-01-01">
                        Train: fino al 2023 · Test: 2024→oggi
                      </option>
                      <option value="2025-01-01">
                        Train: fino al 2024 · Test: 2025→oggi
                      </option>
                      <option value="2025-07-01">
                        Train: fino a giu 2025 · Test: lug 2025→oggi
                      </option>
                      <option value="2026-01-01">
                        Train: fino al 2025 · Test: 2026→oggi
                      </option>
                    </select>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRunOOS()}
                    disabled={oosLoading}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {oosLoading ? "Analisi…" : "Esegui validazione"}
                  </button>
                </div>

                {oosError ? (
                  <p className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
                    {oosError}
                  </p>
                ) : null}

                {oosResult ? (
                  <div>
                    <div
                      className={`mb-4 rounded p-3 text-sm font-medium ${
                        oosResult.oos_verdict === "robusto"
                          ? "border border-emerald-600/50 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200"
                          : oosResult.oos_verdict === "degradazione_moderata"
                            ? "border border-amber-600/50 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                            : "border border-red-600/50 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
                      }`}
                    >
                      {oosResult.oos_verdict === "robusto" &&
                        "Sistema robusto — performance simile su dati non visti"}
                      {oosResult.oos_verdict === "degradazione_moderata" &&
                        "Degradazione moderata — edge presente ma ridotto out-of-sample"}
                      {oosResult.oos_verdict === "possibile_overfitting" &&
                        "Possibile overfitting — performance molto peggiore su dati non visti"}
                      <span className="ml-2 font-normal">
                        (degradazione expectancy R:{" "}
                        {oosResult.performance_degradation_pct.toFixed(1)}%)
                      </span>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div className="rounded border border-zinc-200 bg-zinc-50/80 p-3 dark:border-zinc-700 dark:bg-zinc-900/40">
                        <h4 className="mb-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                          Train set ({oosResult.train_set.period})
                        </h4>
                        <div className="space-y-1 text-sm">
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Rendimento</span>
                            <span
                              className={
                                oosResult.train_set.total_return_pct >= 0
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : "text-red-600 dark:text-red-400"
                              }
                            >
                              {oosResult.train_set.total_return_pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Win rate</span>
                            <span className="tabular-nums">
                              {oosResult.train_set.win_rate.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Expectancy R</span>
                            <span className="font-mono tabular-nums">
                              {oosResult.train_set.expectancy_r != null
                                ? oosResult.train_set.expectancy_r.toFixed(3)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Sharpe</span>
                            <span className="tabular-nums">
                              {oosResult.train_set.sharpe_ratio != null
                                ? oosResult.train_set.sharpe_ratio.toFixed(3)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Profit factor</span>
                            <span className="tabular-nums">
                              {oosResult.train_set.profit_factor != null
                                ? oosResult.train_set.profit_factor.toFixed(2)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Max DD</span>
                            <span className="text-red-600 dark:text-red-400">
                              {oosResult.train_set.max_drawdown_pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Trade</span>
                            <span>
                              {oosResult.train_set.total_trades.toLocaleString(
                                "it-IT",
                              )}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="rounded border border-zinc-200 bg-zinc-50/80 p-3 dark:border-zinc-700 dark:bg-zinc-900/40">
                        <h4 className="mb-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                          Test set — dati non visti (
                          {oosResult.test_set.period})
                        </h4>
                        <div className="space-y-1 text-sm">
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Rendimento</span>
                            <span
                              className={
                                oosResult.test_set.total_return_pct >= 0
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : "text-red-600 dark:text-red-400"
                              }
                            >
                              {oosResult.test_set.total_return_pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Win rate</span>
                            <span className="tabular-nums">
                              {oosResult.test_set.win_rate.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Expectancy R</span>
                            <span className="font-mono tabular-nums">
                              {oosResult.test_set.expectancy_r != null
                                ? oosResult.test_set.expectancy_r.toFixed(3)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Sharpe</span>
                            <span className="tabular-nums">
                              {oosResult.test_set.sharpe_ratio != null
                                ? oosResult.test_set.sharpe_ratio.toFixed(3)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Profit factor</span>
                            <span className="tabular-nums">
                              {oosResult.test_set.profit_factor != null
                                ? oosResult.test_set.profit_factor.toFixed(2)
                                : "—"}
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Max DD</span>
                            <span className="text-red-600 dark:text-red-400">
                              {oosResult.test_set.max_drawdown_pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between gap-2">
                            <span className="text-zinc-500">Trade</span>
                            <span>
                              {oosResult.test_set.total_trades.toLocaleString(
                                "it-IT",
                              )}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {oosChartData.length >= 2 ? (
                      <div className="mt-4">
                        <p className="mb-2 text-sm text-zinc-500 dark:text-zinc-400">
                          Equity curve — Test set (dati non visti)
                        </p>
                        <div className="h-[280px] w-full min-h-[200px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <AreaChart
                              data={oosChartData}
                              margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
                            >
                              <defs>
                                <linearGradient
                                  id="oosCapitalGradient"
                                  x1="0"
                                  y1="0"
                                  x2="0"
                                  y2="1"
                                >
                                  <stop
                                    offset="5%"
                                    stopColor="#10b981"
                                    stopOpacity={0.35}
                                  />
                                  <stop
                                    offset="95%"
                                    stopColor="#10b981"
                                    stopOpacity={0}
                                  />
                                </linearGradient>
                              </defs>
                              <CartesianGrid
                                strokeDasharray="3 3"
                                className="opacity-30"
                                stroke="currentColor"
                              />
                              <XAxis
                                dataKey="timestamp"
                                tick={{ fontSize: 10 }}
                                interval="preserveStartEnd"
                                minTickGap={32}
                                tickFormatter={(ts) => {
                                  try {
                                    return new Date(ts).toLocaleDateString(
                                      "it-IT",
                                      {
                                        month: "short",
                                        day: "numeric",
                                      },
                                    );
                                  } catch {
                                    return String(ts);
                                  }
                                }}
                              />
                              <YAxis
                                tickFormatter={(v) =>
                                  v >= 1000
                                    ? `€${(v / 1000).toFixed(1)}k`
                                    : `€${Math.round(v)}`
                                }
                                tick={{ fontSize: 11 }}
                                width={56}
                              />
                              <Tooltip
                                content={({ active, payload }) => {
                                  if (!active || !payload?.length) return null;
                                  const d = payload[0]?.payload as (typeof oosChartData)[0];
                                  return (
                                    <div className="rounded-lg border border-zinc-600 bg-zinc-900 px-3 py-2 text-xs text-zinc-100 shadow-lg">
                                      <p className="text-zinc-400">{d.dateLabel}</p>
                                      <p className="font-mono font-semibold text-emerald-400">
                                        €
                                        {d.capitale.toLocaleString("it-IT", {
                                          maximumFractionDigits: 0,
                                        })}
                                      </p>
                                      {d.drawdown_pct > 0.05 ? (
                                        <p className="text-red-400">
                                          DD: −{d.drawdown_pct.toFixed(2)}%
                                        </p>
                                      ) : null}
                                    </div>
                                  );
                                }}
                              />
                              <ReferenceLine
                                y={capital}
                                stroke="#71717a"
                                strokeDasharray="4 4"
                                label={{
                                  value: "Capitale iniziale",
                                  position: "insideTopRight",
                                  fill: "#71717a",
                                  fontSize: 11,
                                }}
                              />
                              <Area
                                type="monotone"
                                dataKey="capitale"
                                stroke="#059669"
                                strokeWidth={2}
                                fill="url(#oosCapitalGradient)"
                                dot={false}
                                activeDot={{ r: 4 }}
                              />
                            </AreaChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="mt-6 rounded-lg border border-zinc-200 dark:border-zinc-700">
            <button
              type="button"
              onClick={() => setShowWF(!showWF)}
              className="flex w-full items-center justify-between p-4 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
            >
              <div>
                <span className="font-medium text-zinc-900 dark:text-zinc-100">
                  Walk-Forward Validation
                </span>
                <span className="ml-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Test su {nFolds} periodi indipendenti (quality lookup solo sul train,
                  no leakage)
                </span>
              </div>
              <span className="text-zinc-400" aria-hidden>
                {showWF ? "▲" : "▼"}
              </span>
            </button>

            {showWF ? (
              <div className="border-t border-zinc-200 p-4 dark:border-zinc-700">
                <div className="mb-4 flex flex-wrap items-end gap-4">
                  <div>
                    <label className="mb-1 block text-sm text-zinc-600 dark:text-zinc-400">
                      Numero di fold
                    </label>
                    <select
                      value={nFolds}
                      onChange={(e) => setNFolds(Number(e.target.value))}
                      className="rounded border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-950"
                    >
                      <option value={2}>2 fold</option>
                      <option value={3}>3 fold</option>
                      <option value={4}>4 fold</option>
                      <option value={5}>5 fold</option>
                      <option value={6}>6 fold</option>
                    </select>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRunWF()}
                    disabled={wfLoading}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {wfLoading ? "Analisi…" : "Esegui Walk-Forward"}
                  </button>
                </div>

                {wfError ? (
                  <p className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
                    {wfError}
                  </p>
                ) : null}

                {wfResult ? (
                  <>
                    <div
                      className={`mb-4 rounded p-3 text-sm font-medium ${
                        wfResult.overall_verdict === "robusto"
                          ? "border border-emerald-600/50 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200"
                          : wfResult.overall_verdict === "prevalentemente_robusto"
                            ? "border border-sky-600/50 bg-sky-50 text-sky-900 dark:border-sky-700 dark:bg-sky-950/40 dark:text-sky-200"
                            : wfResult.overall_verdict === "degradazione_moderata"
                              ? "border border-amber-600/50 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                              : "border border-red-600/50 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
                      }`}
                    >
                      Verdict: {wfResult.overall_verdict} | Fold positivi:{" "}
                      {wfResult.pct_folds_positive.toFixed(1)}% | Avg test return:{" "}
                      {wfResult.avg_test_return_pct.toFixed(1)}% | Avg degradazione:{" "}
                      {wfResult.avg_degradation_pct.toFixed(1)}%
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-zinc-200 text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
                            <th className="py-2 pr-2 text-left font-medium">Fold</th>
                            <th className="py-2 pr-2 text-left font-medium">
                              Periodo test
                            </th>
                            <th className="py-2 pr-2 text-right font-medium">
                              Train ret
                            </th>
                            <th className="py-2 pr-2 text-right font-medium">
                              Test ret
                            </th>
                            <th className="py-2 pr-2 text-right font-medium">
                              Test WR
                            </th>
                            <th className="py-2 pr-2 text-right font-medium">
                              Test DD
                            </th>
                            <th className="py-2 pr-2 text-right font-medium">
                              Degradazione
                            </th>
                            <th className="py-2 text-left font-medium">Verdict</th>
                          </tr>
                        </thead>
                        <tbody>
                          {wfResult.folds.map((fold) => (
                            <tr
                              key={fold.fold_number}
                              className="border-b border-zinc-100 dark:border-zinc-800"
                            >
                              <td className="py-2 pr-2">{fold.fold_number}</td>
                              <td className="py-2 pr-2 font-mono text-xs text-zinc-500 dark:text-zinc-400">
                                {fold.test_start.substring(0, 10)} →{" "}
                                {fold.test_end.substring(0, 10)}
                              </td>
                              <td
                                className={`py-2 pr-2 text-right tabular-nums ${
                                  fold.train_return_pct >= 0
                                    ? "text-emerald-600 dark:text-emerald-400"
                                    : "text-red-600 dark:text-red-400"
                                }`}
                              >
                                {fold.train_return_pct >= 0 ? "+" : ""}
                                {fold.train_return_pct.toFixed(0)}%
                              </td>
                              <td
                                className={`py-2 pr-2 text-right tabular-nums ${
                                  fold.test_return_pct > 0
                                    ? "text-emerald-600 dark:text-emerald-400"
                                    : "text-red-600 dark:text-red-400"
                                }`}
                              >
                                {fold.test_return_pct > 0 ? "+" : ""}
                                {fold.test_return_pct.toFixed(0)}%
                              </td>
                              <td className="py-2 pr-2 text-right tabular-nums">
                                {fold.test_win_rate.toFixed(1)}%
                              </td>
                              <td className="py-2 pr-2 text-right tabular-nums text-red-600 dark:text-red-400">
                                {fold.test_max_dd.toFixed(1)}%
                              </td>
                              <td
                                className={`py-2 pr-2 text-right tabular-nums ${
                                  fold.degradation_pct < 20
                                    ? "text-emerald-600 dark:text-emerald-400"
                                    : fold.degradation_pct < 50
                                      ? "text-amber-600 dark:text-amber-400"
                                      : "text-red-600 dark:text-red-400"
                                }`}
                              >
                                {fold.degradation_pct.toFixed(1)}%
                              </td>
                              <td
                                className={`py-2 text-xs ${
                                  fold.verdict === "robusto"
                                    ? "text-emerald-600 dark:text-emerald-400"
                                    : fold.verdict === "degradazione_moderata"
                                      ? "text-amber-600 dark:text-amber-400"
                                      : "text-red-600 dark:text-red-400"
                                }`}
                              >
                                {fold.verdict}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
