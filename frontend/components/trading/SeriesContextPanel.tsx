"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ContextRow, FeatureRow, PatternRow } from "@/lib/api";
import { displayEnumLabel, displayTechnicalLabel } from "@/lib/displayLabels";

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  try {
    const diff = (new Date(iso).getTime() - Date.now()) / 1000;
    const abs = Math.abs(diff);
    const rtf = new Intl.RelativeTimeFormat("it", { numeric: "auto", style: "short" });
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    return rtf.format(Math.round(diff / 86400), "day");
  } catch {
    return iso;
  }
}

function SectionError({ label, onRetry }: { label: string; onRetry?: () => void }) {
  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2"
      role="alert"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />
      <span className="text-xs text-fg-2">{label} non disponibile</span>
      {onRetry && (
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-6 px-2 text-[10px] text-fg-2"
          onClick={onRetry}
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
      )}
    </div>
  );
}

// ── Context sub-section ───────────────────────────────────────────────────────

interface ContextSubSectionProps {
  contexts: ContextRow[] | null;
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
}

function ContextSubSection({ contexts, isLoading, error, onRetry }: ContextSubSectionProps) {
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error || !contexts) return <SectionError label="Contesto regime" onRetry={onRetry} />;

  const latest = contexts[0];
  if (!latest) return <p className="text-xs text-fg-3">Nessun contesto disponibile.</p>;

  const regime = (latest.market_regime ?? "").toLowerCase();
  const regimeCls =
    regime.includes("bullish") ? "border-bull/30 bg-bull/10 text-bull"
    : regime.includes("bearish") ? "border-bear/30 bg-bear/10 text-bear"
    : "border-line bg-surface-2 text-fg-2";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline" className={cn("font-mono text-xs", regimeCls)}>
          ● {displayEnumLabel(latest.market_regime)}
        </Badge>
        <Badge variant="outline" className="font-mono text-xs border-line bg-surface-2 text-fg-2">
          {displayEnumLabel(latest.volatility_regime)}
        </Badge>
        <Badge variant="outline" className="font-mono text-xs border-line bg-surface-2 text-fg-2">
          {displayEnumLabel(latest.direction_bias)}
        </Badge>
      </div>
      <p className="text-[10px] text-fg-3">
        Aggiornato {relativeTime(latest.timestamp)}
      </p>
    </div>
  );
}

// ── Features sub-section ──────────────────────────────────────────────────────

interface FeaturesSubSectionProps {
  features: FeatureRow[] | null;
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
}

function FeaturesSubSection({ features, isLoading, error, onRetry }: FeaturesSubSectionProps) {
  if (isLoading) return <Skeleton className="h-20 w-full" />;
  if (error || !features) return <SectionError label="Indicatori" onRetry={onRetry} />;

  const latest = features[0];
  if (!latest) return <p className="text-xs text-fg-3">Nessun indicatore disponibile.</p>;

  const rows: { label: string; value: string }[] = [
    { label: "Vol. ratio", value: latest.volume_ratio_vs_prev != null ? Number(latest.volume_ratio_vs_prev).toFixed(2) + "x" : "—" },
    { label: "Body", value: (Number(latest.body_size) * 100).toFixed(1) + "%" },
    { label: "Range", value: (Number(latest.range_size) * 100).toFixed(1) + "%" },
    { label: "Close pos.", value: (Number(latest.close_position_in_range) * 100).toFixed(0) + "%" },
    { label: "Ritorno 1", value: latest.pct_return_1 != null ? (Number(latest.pct_return_1) * 100).toFixed(2) + "%" : "—" },
    { label: "Direzione", value: latest.is_bullish ? "Bullish ▲" : "Bearish ▼" },
  ];

  return (
    <table className="w-full text-xs" aria-label="Indicatori tecnici">
      <thead>
        <tr>
          <th className="pb-1 text-left font-medium text-fg-3" scope="col">Indicatore</th>
          <th className="pb-1 text-right font-medium text-fg-3" scope="col">Valore</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ label, value }) => (
          <tr key={label} className="border-b border-line/30">
            <td className="py-1 text-fg-2">{label}</td>
            <td className={cn(
              "py-1 text-right font-mono tabular-nums",
              label === "Direzione" && value.includes("Bullish") ? "text-bull" :
              label === "Direzione" && value.includes("Bearish") ? "text-bear" : "text-fg",
            )}>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Patterns sub-section ──────────────────────────────────────────────────────

interface PatternsSubSectionProps {
  patterns: PatternRow[] | null;
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
}

function PatternsSubSection({ patterns, isLoading, error, onRetry }: PatternsSubSectionProps) {
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error || !patterns) return <SectionError label="Pattern" onRetry={onRetry} />;
  if (patterns.length === 0) return <p className="text-xs text-fg-3">Nessun pattern rilevato.</p>;

  return (
    <ul className="space-y-1.5" aria-label="Pattern rilevati">
      {patterns.slice(0, 8).map((p) => {
        const isBull = p.direction.toLowerCase() === "bullish";
        const strength = Math.round(Number(p.pattern_strength) * 100);
        return (
          <li key={p.id} className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                "font-mono text-[10px] font-bold",
                isBull ? "text-bull" : "text-bear",
              )}
              aria-hidden
            >
              {isBull ? "▲" : "▼"}
            </span>
            <span className="flex-1 truncate text-fg-2">
              {displayTechnicalLabel(p.pattern_name)}
            </span>
            <span className="font-mono text-[10px] tabular-nums text-fg-3">
              {strength}%
            </span>
            <span className="shrink-0 text-[10px] text-fg-3" title={p.timestamp}>
              {relativeTime(p.timestamp)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

interface SeriesContextPanelProps {
  contexts: ContextRow[] | null;
  contextsLoading: boolean;
  contextsError: unknown;
  onContextRetry?: () => void;

  features: FeatureRow[] | null;
  featuresLoading: boolean;
  featuresError: unknown;
  onFeaturesRetry?: () => void;

  patterns: PatternRow[] | null;
  patternsLoading: boolean;
  patternsError: unknown;
  onPatternsRetry?: () => void;
}

export function SeriesContextPanel({
  contexts, contextsLoading, contextsError, onContextRetry,
  features, featuresLoading, featuresError, onFeaturesRetry,
  patterns, patternsLoading, patternsError, onPatternsRetry,
}: SeriesContextPanelProps) {
  return (
    <div className="space-y-5 rounded-xl border border-line bg-surface p-4">
      {/* Regime / Context */}
      <section aria-label="Contesto regime">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-fg-2">
          Contesto
        </h3>
        <ContextSubSection
          contexts={contexts}
          isLoading={contextsLoading}
          error={contextsError}
          onRetry={onContextRetry}
        />
      </section>

      {/* Indicatori */}
      <section aria-label="Indicatori tecnici" className="border-t border-line/50 pt-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-fg-2">
          Indicatori
        </h3>
        <FeaturesSubSection
          features={features}
          isLoading={featuresLoading}
          error={featuresError}
          onRetry={onFeaturesRetry}
        />
      </section>

      {/* Pattern rilevati */}
      <section aria-label="Pattern rilevati" className="border-t border-line/50 pt-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-fg-2">
          Pattern rilevati
        </h3>
        <PatternsSubSection
          patterns={patterns}
          isLoading={patternsLoading}
          error={patternsError}
          onRetry={onPatternsRetry}
        />
      </section>
    </div>
  );
}
