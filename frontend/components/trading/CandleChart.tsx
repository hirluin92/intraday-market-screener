"use client";

import dynamic from "next/dynamic";
import { cn } from "@/lib/utils";
import type { CandleChartProps } from "./CandleChartImpl";

// ── Skeleton ─────────────────────────────────────────────────────────────────

function ChartSkeleton({ height = 500, className }: { height?: number; className?: string }) {
  return (
    <div
      className={cn(
        "w-full animate-pulse overflow-hidden rounded-xl bg-surface",
        "relative flex flex-col",
        className,
      )}
      style={{ height }}
      aria-busy="true"
      aria-label="Caricamento grafico…"
    >
      {/* Fake price scale on right */}
      <div className="absolute right-0 top-0 flex h-full w-16 flex-col justify-between py-4 pr-2">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-2 w-12 rounded bg-surface-2" />
        ))}
      </div>
      {/* Fake candles area */}
      <div className="flex h-4/5 items-end gap-1 px-4 pb-2 pr-20">
        {Array.from({ length: 24 }).map((_, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm bg-surface-2"
            style={{ height: `${30 + Math.sin(i * 0.7) * 20 + 20}%` }}
          />
        ))}
      </div>
      {/* Fake volume bars */}
      <div className="flex h-1/5 items-end gap-1 border-t border-line px-4 pb-1 pr-20">
        {Array.from({ length: 24 }).map((_, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm bg-surface-2"
            style={{ height: `${20 + Math.random() * 60}%` }}
          />
        ))}
      </div>
    </div>
  );
}

// ── Dynamic wrapper (SSR: false — lightweight-charts needs window/document) ───

const CandleChartDynamic = dynamic(
  () => import("./CandleChartImpl").then((m) => ({ default: m.CandleChartImpl })),
  {
    ssr: false,
    loading: () => <ChartSkeleton />,
  },
);

// ── Public export ─────────────────────────────────────────────────────────────

export type { CandleChartProps } from "./CandleChartImpl";

export function CandleChart(props: CandleChartProps) {
  if (!props.candles || props.candles.length === 0) {
    return (
      <div
        className={cn(
          "flex w-full items-center justify-center rounded-xl border border-dashed border-line bg-surface",
          props.className,
        )}
        style={{ height: props.height ?? 500 }}
      >
        <p className="text-sm text-fg-2">Nessuna candela disponibile</p>
      </div>
    );
  }
  return <CandleChartDynamic {...props} />;
}
