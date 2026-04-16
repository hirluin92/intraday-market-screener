"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CrosshairMode,
  CandlestickSeries as CandlestickSeriesDef,
  HistogramSeries as HistogramSeriesDef,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import type { CandleRow, PatternRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Design tokens (match globals.css) ────────────────────────────────────────

const T = {
  bg:        "transparent",
  text:      "hsl(240, 15%, 48%)",
  gridLine:  "hsl(240, 24%, 14%)",
  crosshair: "hsl(240, 20%, 20%)",
  bull:      "hsl(168, 100%, 42%)",
  bear:      "hsl(349, 100%, 63%)",
  volBull:   "rgba(0, 212, 170, 0.45)",
  volBear:   "rgba(255, 68, 102, 0.45)",
} as const;

// ── Converters ────────────────────────────────────────────────────────────────

function isoToUnixSec(iso: string): Time {
  return Math.floor(new Date(iso).getTime() / 1000) as unknown as Time;
}

function toCandleData(candles: CandleRow[]) {
  return candles
    .map((c) => ({
      time:  isoToUnixSec(c.timestamp),
      open:  Number(c.open),
      high:  Number(c.high),
      low:   Number(c.low),
      close: Number(c.close),
    }))
    .sort((a, b) => (a.time as number) - (b.time as number));
}

function toVolumeData(candles: CandleRow[]) {
  return candles
    .map((c) => ({
      time:  isoToUnixSec(c.timestamp),
      value: Number(c.volume),
      color: Number(c.close) >= Number(c.open) ? T.volBull : T.volBear,
    }))
    .sort((a, b) => (a.time as number) - (b.time as number));
}

function toMarkers(patterns: PatternRow[]): SeriesMarker<Time>[] {
  return patterns.map((p) => {
    const isBull = p.direction.toLowerCase() === "bullish";
    const strength = Number(p.pattern_strength);
    return {
      time:     isoToUnixSec(p.timestamp),
      position: (isBull ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
      color:    isBull ? T.bull : T.bear,
      shape:    (isBull ? "arrowUp" : "arrowDown") as "arrowUp" | "arrowDown",
      text:     `${p.pattern_name.replace(/_/g, " ")} ${(strength * 100).toFixed(0)}%`,
      size:     1,
    };
  });
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface CandleChartProps {
  candles: CandleRow[];
  patterns?: PatternRow[];
  height?: number;
  className?: string;
}

export function CandleChartImpl({
  candles,
  patterns = [],
  height = 500,
  className,
}: CandleChartProps) {
  const containerRef  = useRef<HTMLDivElement>(null);
  const chartRef      = useRef<IChartApi | null>(null);
  const candleRef     = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef     = useRef<ISeriesApi<"Histogram"> | null>(null);

  // ── Create chart once ────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width:  el.clientWidth,
      height,
      layout: {
        background:  { color: T.bg },
        textColor:   T.text,
        fontFamily:  "var(--font-trader-mono, 'JetBrains Mono', ui-monospace, monospace)",
        fontSize:    11,
      },
      grid: {
        vertLines: { color: T.gridLine, style: 2 },
        horzLines: { color: T.gridLine, style: 2 },
      },
      crosshair: {
        mode:     CrosshairMode.Normal,
        vertLine: { color: T.crosshair, labelBackgroundColor: T.crosshair },
        horzLine: { color: T.crosshair, labelBackgroundColor: T.crosshair },
      },
      rightPriceScale: {
        borderColor:  T.gridLine,
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor:    T.gridLine,
        timeVisible:    true,
        secondsVisible: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale:  { mouseWheel: true, pinch: true },
    });
    chartRef.current = chart;

    // ── Candlestick series ───────────────────────────────────────────────
    const cSeries = chart.addSeries(CandlestickSeriesDef, {
      upColor:         T.bull,
      downColor:       T.bear,
      borderUpColor:   T.bull,
      borderDownColor: T.bear,
      wickUpColor:     T.bull,
      wickDownColor:   T.bear,
    });
    candleRef.current = cSeries;

    // ── Volume histogram ─────────────────────────────────────────────────
    const vSeries = chart.addSeries(HistogramSeriesDef, {
      priceScaleId: "volume",
      priceFormat:  { type: "volume" },
    });
    volumeRef.current = vSeries;
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    // ── Resize observer ──────────────────────────────────────────────────
    const ro = new ResizeObserver((entries) => {
      const e = entries[0];
      if (e) chart.applyOptions({ width: e.contentRect.width });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // ── Update data when props change ─────────────────────────────────────────
  useEffect(() => {
    const cSeries = candleRef.current;
    const vSeries = volumeRef.current;
    if (!cSeries || !vSeries || candles.length === 0) return;

    cSeries.setData(toCandleData(candles));
    vSeries.setData(toVolumeData(candles));

    if (patterns.length > 0) {
      createSeriesMarkers(cSeries, toMarkers(patterns));
    } else {
      createSeriesMarkers(cSeries, []);
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles, patterns]);

  return (
    <div
      ref={containerRef}
      className={cn("w-full overflow-hidden rounded-xl border border-line", className)}
      style={{ height }}
      role="img"
      aria-label={`Grafico candele ${candles[0]?.symbol ?? ""} ${candles[0]?.timeframe ?? ""} — ${candles.length} periodi`}
    />
  );
}
