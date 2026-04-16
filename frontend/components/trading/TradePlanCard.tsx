"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { TradePlanV1, OpportunityRow } from "@/lib/api";
import { computeOpportunityEconomicSnapshot } from "@/lib/opportunityEconomicSnapshot";
import {
  loadPositionSizingInput,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";

// ── Price display helper ───────────────────────────────────────────────────────

function fmt(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return n.toPrecision(6).replace(/\.?0+$/, "");
}

function pctDiff(price: string | null | undefined, ref: string | null | undefined): string | null {
  const p = price != null ? Number(price) : null;
  const r = ref != null ? Number(ref) : null;
  if (p == null || r == null || r === 0 || Number.isNaN(p) || Number.isNaN(r)) return null;
  const d = ((p - r) / Math.abs(r)) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(2)}%`;
}

function rrColor(rr: string | null | undefined): string {
  const n = rr != null ? Number(rr) : NaN;
  if (Number.isNaN(n)) return "border-line bg-surface-2 text-fg-2";
  if (n >= 2) return "border-bull/30 bg-bull/10 text-bull";
  if (n >= 1) return "border-neutral/30 bg-neutral/10 text-neutral";
  return "border-bear/30 bg-bear/10 text-bear";
}

function dirBadgeClass(dir: TradePlanV1["trade_direction"]): string {
  if (dir === "long")  return "border-bull/40 bg-bull/10 text-bull";
  if (dir === "short") return "border-bear/40 bg-bear/10 text-bear";
  return "border-line bg-surface-2 text-fg-2";
}

// ── Component ─────────────────────────────────────────────────────────────────

interface TradePlanCardProps {
  opportunity: OpportunityRow | null;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}

export function TradePlanCard({ opportunity, isLoading, error, onRetry }: TradePlanCardProps) {
  const [sizing, setSizing] = useState<PositionSizingUserInput | null>(null);

  useEffect(() => {
    setSizing(loadPositionSizingInput());
  }, []);

  if (isLoading || !sizing) {
    return (
      <div className="space-y-3 rounded-xl border border-line bg-surface p-4">
        <Skeleton className="h-6 w-32" />
        <div className="grid grid-cols-3 gap-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
        <Skeleton className="h-12" />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-xl border border-warn/30 bg-warn/5 p-4"
        role="alert"
      >
        <p className="text-sm text-fg-2">Trade plan non disponibile.</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 text-xs text-neutral underline underline-offset-2"
          >
            Riprova
          </button>
        )}
      </div>
    );
  }

  if (!opportunity) {
    return (
      <div className="rounded-xl border border-line bg-surface p-4">
        <p className="text-sm text-fg-2">Opportunità non trovata per questa serie.</p>
      </div>
    );
  }

  const plan = opportunity.trade_plan;

  if (!plan || plan.trade_direction === "none") {
    return (
      <div className="rounded-xl border border-line bg-surface p-4">
        <p className="text-sm text-fg-2">
          Nessun trade plan attivo per questa serie.
        </p>
        {opportunity.decision_rationale?.[0] && (
          <p className="mt-1 text-xs text-fg-3">{opportunity.decision_rationale[0]}</p>
        )}
      </div>
    );
  }

  const snap = computeOpportunityEconomicSnapshot(
    plan,
    sizing,
    opportunity.final_opportunity_score,
    opportunity.selected_trade_plan_variant_status,
  );

  const isLong = plan.trade_direction === "long";
  const rrLabel = plan.risk_reward_ratio
    ? `${Number(plan.risk_reward_ratio).toFixed(2)}:1`
    : "—";
  const score = Math.round(opportunity.final_opportunity_score ?? 0);

  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-sans text-sm font-semibold uppercase tracking-wide text-fg-2">
          Trade Plan
        </h3>
        <Badge
          variant="outline"
          className={cn("font-mono text-xs", dirBadgeClass(plan.trade_direction))}
        >
          {isLong ? "▲ LONG" : "▼ SHORT"}
        </Badge>
        <Badge variant="outline" className={cn("font-mono text-xs", rrColor(plan.risk_reward_ratio))}>
          R:R {rrLabel}
        </Badge>
        <Badge variant="outline" className="ml-auto font-mono text-xs tabular-nums border-line bg-surface-2 text-fg">
          Score {score}
        </Badge>
      </div>

      {/* Price grid */}
      <div className="grid grid-cols-3 gap-3">
        {[
          {
            label: "Entry",
            value: fmt(plan.entry_price),
            delta: null,
            cls: "text-fg",
          },
          {
            label: "Stop Loss",
            value: fmt(plan.stop_loss),
            delta: pctDiff(plan.stop_loss, plan.entry_price),
            cls: "text-bear",
          },
          {
            label: "Take Profit",
            value: fmt(plan.take_profit_1),
            delta: pctDiff(plan.take_profit_1, plan.entry_price),
            cls: "text-bull",
          },
        ].map(({ label, value, delta, cls }) => (
          <div key={label} className="rounded-lg border border-line/50 bg-surface-2 p-3">
            <p className="text-[10px] text-fg-3">{label}</p>
            <p className={cn("mt-0.5 font-mono text-lg font-bold tabular-nums", cls)}>
              {value}
            </p>
            {delta && (
              <p className={cn("font-mono text-[10px] tabular-nums", cls, "opacity-80")}>
                {delta}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Position sizing */}
      {snap?.preview.ok && (
        <div className="grid grid-cols-3 gap-3 border-t border-line/50 pt-3 text-sm">
          <div>
            <p className="text-[10px] text-fg-3">Quantità</p>
            <p className="font-mono font-semibold tabular-nums text-fg">
              {Math.max(0, Math.round(snap.preview.positionSizeUnits))}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-fg-3">Rischio</p>
            <p className="font-mono font-semibold tabular-nums text-bear">
              {snap.preview.estimatedLossAtStopWithCosts.toFixed(2)} €
            </p>
          </div>
          <div>
            <p className="text-[10px] text-fg-3">Reward TP1</p>
            <p className="font-mono font-semibold tabular-nums text-bull">
              {snap.preview.estimatedNetProfitAtTp1?.toFixed(2) ?? "—"} €
            </p>
          </div>
        </div>
      )}

      {/* Entry strategy + rationale */}
      <div className="border-t border-line/50 pt-3 text-xs text-fg-2">
        <span className="text-fg-3">Strategia entry: </span>
        {plan.entry_strategy === "breakout"
          ? "Breakout"
          : plan.entry_strategy === "retest"
            ? "Retest"
            : "Chiusura barra"}
        {plan.invalidation_note && (
          <p className="mt-1 text-fg-3">
            <span className="text-fg-2">Invalidazione: </span>
            {plan.invalidation_note}
          </p>
        )}
      </div>

      {/* Decision rationale */}
      {(opportunity.decision_rationale ?? []).length > 0 && (
        <div className="border-t border-line/50 pt-3">
          <p className="mb-1 text-[10px] text-fg-3">Motivazione decisione</p>
          {opportunity.decision_rationale!.map((line, i) => (
            <p key={i} className="text-xs text-fg-2">{line}</p>
          ))}
        </div>
      )}
    </div>
  );
}
