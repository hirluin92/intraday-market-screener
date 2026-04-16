"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CandleChart } from "@/components/trading/CandleChart";
import { SeriesContextPanel } from "@/components/trading/SeriesContextPanel";
import { TradePlanCard } from "@/components/trading/TradePlanCard";
import { RegimeIndicator } from "@/components/trading/RegimeIndicator";
import {
  useSeriesSnapshot,
  useSeriesCandles,
  useSeriesFeatures,
  useSeriesContext,
  useSeriesPatterns,
  useInvalidateSeries,
  type SeriesParams,
} from "@/hooks/useSeriesData";

// ── Inner component (needs Suspense for useSearchParams) ──────────────────────

function SeriesDetailInner() {
  const router = useRouter();
  const rawParams = useParams();
  const searchParams = useSearchParams();

  const symbol    = decodeURIComponent(String(rawParams.symbol ?? ""));
  const timeframe = decodeURIComponent(String(rawParams.timeframe ?? ""));
  const exchange  = searchParams?.get("exchange") ?? "";
  const provider  = searchParams?.get("provider") ?? undefined;
  const assetType = searchParams?.get("asset_type") ?? undefined;

  const params: SeriesParams = { symbol, timeframe, exchange, provider, asset_type: assetType };

  // ── 5 independent hooks ───────────────────────────────────────────────────
  const snapshot  = useSeriesSnapshot(params);
  const candles   = useSeriesCandles(params, 200);
  const features  = useSeriesFeatures(params, 50);
  const context   = useSeriesContext(params, 10);
  const patterns  = useSeriesPatterns(params, 50);
  const invalidate = useInvalidateSeries(params);

  const regime = snapshot.data?.regime_spy ?? null;

  return (
    <div className="mx-auto max-w-[1440px] space-y-5 px-4 pb-12 pt-4 sm:px-6">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 text-fg-2 hover:text-fg"
          onClick={() => router.back()}
          aria-label="Torna alla lista opportunità"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          <span className="hidden sm:inline">Opportunità</span>
        </Button>

        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-fg-3">
          <Link href="/opportunities" className="hover:text-fg transition-colors">
            Opportunità
          </Link>
          <span aria-hidden>/</span>
          <span className="font-mono font-bold text-fg">{symbol}</span>
          <span aria-hidden>/</span>
          <Badge variant="outline" className="font-mono text-[10px] border-line">
            {timeframe}
          </Badge>
        </nav>

        {regime && <RegimeIndicator regime={regime} className="ml-1" />}

        <div className="ml-auto flex items-center gap-2">
          {(snapshot.isFetching || candles.isFetching) && (
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-fg-3" aria-hidden />
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs text-fg-2"
            onClick={() => void invalidate()}
            aria-label="Aggiorna tutti i dati"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Aggiorna</span>
          </Button>
        </div>
      </header>

      {/* ── Chart row ───────────────────────────────────────────────── */}
      <section aria-label="Grafico candele">
        {candles.error ? (
          <div
            className="flex h-[500px] items-center justify-center rounded-xl border border-warn/30 bg-warn/5"
            role="alert"
          >
            <div className="text-center">
              <p className="text-sm text-fg-2">Grafico non disponibile.</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-2 text-xs text-neutral"
                onClick={() => void candles.refetch()}
              >
                Riprova
              </Button>
            </div>
          </div>
        ) : (
          <CandleChart
            candles={candles.data ?? []}
            patterns={patterns.data ?? []}
            height={500}
            className={candles.isLoading ? "opacity-0" : "opacity-100 transition-opacity duration-300"}
          />
        )}
      </section>

      {/* ── Content grid ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Trade plan */}
        <section aria-label="Trade plan e position sizing">
          <TradePlanCard
            opportunity={snapshot.data ?? null}
            isLoading={snapshot.isLoading}
            error={snapshot.error}
            onRetry={() => void snapshot.refetch()}
          />
        </section>

        {/* Context, features, patterns */}
        <section aria-label="Contesto tecnico">
          <SeriesContextPanel
            contexts={context.data ?? null}
            contextsLoading={context.isLoading}
            contextsError={context.error}
            onContextRetry={() => void context.refetch()}

            features={features.data ?? null}
            featuresLoading={features.isLoading}
            featuresError={features.error}
            onFeaturesRetry={() => void features.refetch()}

            patterns={patterns.data ?? null}
            patternsLoading={patterns.isLoading}
            patternsError={patterns.error}
            onPatternsRetry={() => void patterns.refetch()}
          />
        </section>
      </div>
    </div>
  );
}

// ── Page export ───────────────────────────────────────────────────────────────

export default function SeriesDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1440px] space-y-5 px-4 pb-12 pt-4 sm:px-6">
          <div className="h-8 w-48 animate-pulse rounded-lg bg-surface" />
          <div className="h-[500px] animate-pulse rounded-xl bg-surface" />
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div className="h-64 animate-pulse rounded-xl bg-surface" />
            <div className="h-64 animate-pulse rounded-xl bg-surface" />
          </div>
        </div>
      }
    >
      <SeriesDetailInner />
    </Suspense>
  );
}
