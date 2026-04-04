"use client";

import { useMemo } from "react";
import type { CandleRow, PatternRow } from "@/lib/api";
import { displayTechnicalLabel } from "@/lib/displayLabels";

const VIEW_W = 800;
const VIEW_H = 300;
const PAD_L = 52;
const PAD_R = 12;
const PAD_T = 16;
const PAD_B = 36;

function tsMillis(iso: string): number {
  return new Date(iso).getTime();
}

function num(s: string): number {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

/** Indice candela nel grafico più vicino al timestamp. */
function findNearestCandleIndex(
  chartCandles: CandleRow[],
  targetIso: string | null | undefined,
  maxDiffMs: number = Infinity,
): number {
  if (!targetIso || chartCandles.length === 0) return -1;
  const t = tsMillis(targetIso);
  let best = -1;
  let bestDiff = Infinity;
  for (let i = 0; i < chartCandles.length; i++) {
    const d = Math.abs(tsMillis(chartCandles[i].timestamp) - t);
    if (d < bestDiff) {
      bestDiff = d;
      best = i;
    }
  }
  return bestDiff <= maxDiffMs ? best : -1;
}

type Props = {
  candles: CandleRow[];
  patterns: PatternRow[];
  /** Orario barra contesto opportunità (es. context_timestamp). */
  opportunityContextTimestamp: string | null | undefined;
  maxCandles?: number;
};

/**
 * Grafico a candele SVG (MVP): ultime N barre, pattern segnati, evidenziazione opportunità.
 */
export function SeriesCandleChart({
  candles,
  patterns,
  opportunityContextTimestamp,
  maxCandles = 50,
}: Props) {
  const chartCandles = useMemo(() => {
    if (candles.length === 0) return [];
    const asc = [...candles].sort(
      (a, b) => tsMillis(a.timestamp) - tsMillis(b.timestamp),
    );
    const cap = Math.min(maxCandles, 50);
    return asc.slice(-Math.min(cap, asc.length));
  }, [candles, maxCandles]);

  const { minP, maxP, plotW, plotH } = useMemo(() => {
    if (chartCandles.length === 0) {
      return { minP: 0, maxP: 1, plotW: VIEW_W - PAD_L - PAD_R, plotH: VIEW_H - PAD_T - PAD_B };
    }
    let lo = Infinity;
    let hi = -Infinity;
    for (const c of chartCandles) {
      lo = Math.min(lo, num(c.low), num(c.high));
      hi = Math.max(hi, num(c.low), num(c.high));
    }
    if (lo === hi) {
      lo *= 0.999;
      hi *= 1.001;
    }
    const pad = (hi - lo) * 0.04;
    return {
      minP: lo - pad,
      maxP: hi + pad,
      plotW: VIEW_W - PAD_L - PAD_R,
      plotH: VIEW_H - PAD_T - PAD_B,
    };
  }, [chartCandles]);

  const yAt = (price: number) =>
    PAD_T + plotH - ((price - minP) / (maxP - minP)) * plotH;

  const patternByIndex = useMemo(() => {
    const m = new Map<number, PatternRow[]>();
    for (const p of patterns) {
      const idx = findNearestCandleIndex(chartCandles, p.timestamp, Infinity);
      if (idx < 0) continue;
      const list = m.get(idx) ?? [];
      list.push(p);
      m.set(idx, list);
    }
    return m;
  }, [patterns, chartCandles]);

  const oppIndex = useMemo(
    () =>
      findNearestCandleIndex(
        chartCandles,
        opportunityContextTimestamp ?? null,
        2 * 60 * 1000,
      ),
    [chartCandles, opportunityContextTimestamp],
  );

  const n = chartCandles.length;
  if (n === 0) {
    return (
      <p className="rounded-lg border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-600">
        Nessuna candela disponibile per il grafico.
      </p>
    );
  }

  const slotW = plotW / n;
  const barW = Math.max(2, slotW * 0.62);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950/30">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="w-full h-auto max-h-[360px]"
        role="img"
        aria-label="Grafico a candele"
      >
        {/* Griglia orizzontale leggera */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = PAD_T + t * plotH;
          const price = maxP - t * (maxP - minP);
          return (
            <g key={t}>
              <line
                x1={PAD_L}
                y1={y}
                x2={VIEW_W - PAD_R}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.08}
                className="text-zinc-900 dark:text-zinc-100"
              />
              <text
                x={PAD_L - 6}
                y={y + 4}
                textAnchor="end"
                className="fill-zinc-500 text-[10px] font-mono"
              >
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {chartCandles.map((c, i) => {
          const xCenter = PAD_L + (i + 0.5) * slotW;
          const o = num(c.open);
          const h = num(c.high);
          const l = num(c.low);
          const cl = num(c.close);
          const bull = cl >= o;
          const yH = yAt(h);
          const yL = yAt(l);
          const yO = yAt(o);
          const yC = yAt(cl);
          const top = Math.min(yO, yC);
          const bot = Math.max(yO, yC);
          const fill = bull ? "#22c55e" : "#ef4444";
          const stroke = bull ? "#15803d" : "#b91c1c";

          return (
            <g key={c.id}>
              <line
                x1={xCenter}
                y1={yH}
                x2={xCenter}
                y2={yL}
                stroke={stroke}
                strokeWidth={1.2}
              />
              <rect
                x={xCenter - barW / 2}
                y={top}
                width={barW}
                height={Math.max(1, bot - top)}
                fill={fill}
                stroke={stroke}
                strokeWidth={0.6}
              />
            </g>
          );
        })}

        {/* Evidenziazione candela opportunità (contesto) */}
        {oppIndex >= 0 && (
          <rect
            x={PAD_L + oppIndex * slotW}
            y={PAD_T}
            width={slotW}
            height={plotH}
            fill="#f59e0b"
            fillOpacity={0.12}
            stroke="#d97706"
            strokeWidth={1}
            strokeOpacity={0.5}
          />
        )}

        {/* Marker pattern */}
        {Array.from(patternByIndex.entries()).map(([idx, plist]) => {
          const xCenter = PAD_L + (idx + 0.5) * slotW;
          const y = PAD_T + 6;
          return (
            <g key={`pat-${idx}`}>
              <circle cx={xCenter} cy={y} r={5} fill="#7c3aed" stroke="#5b21b6" strokeWidth={1} />
              <title>
                {plist
                  .map(
                    (p) =>
                      `${displayTechnicalLabel(p.pattern_name)} (${p.direction})`,
                  )
                  .join("; ")}
              </title>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 border-t border-zinc-100 pt-2 text-[11px] text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-emerald-500" aria-hidden />
          Chiusura ≥ apertura
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-red-500" aria-hidden />
          Chiusura &lt; apertura
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm bg-amber-400/40 ring-1 ring-amber-600/50" aria-hidden />
          Fascia = candela contesto opportunità
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-violet-600" aria-hidden />
          Pattern rilevato
        </span>
      </div>
    </div>
  );
}
