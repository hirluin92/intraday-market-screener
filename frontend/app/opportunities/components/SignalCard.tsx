"use client";

import { memo, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, Clipboard, ClipboardCheck, ExternalLink } from "lucide-react";

import type { OpportunityRow } from "@/lib/api";
import { seriesDetailHref } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatPrice } from "@/lib/formatPrice";
import { computeOpportunityEconomicSnapshot } from "@/lib/opportunityEconomicSnapshot";
import type { PositionSizingUserInput } from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TradeInstructions } from "./TradeInstructions";

// ── Exchange display label ─────────────────────────────────────────────────────

function exchangeTag(row: OpportunityRow): string | null {
  const provider = (row.provider ?? "").toLowerCase();
  if (provider === "binance") return null; // /USDT già identificativo
  const ex = (row.exchange ?? "").toUpperCase();
  if (ex === "LSE") return "LSE";
  if (ex === "NYSE") return "NYSE";
  if (ex === "NASDAQ" || ex === "NSDQ") return "NSDQ";
  if (ex === "ARCA") return "ARCA";
  if (ex === "BATS") return "BATS";
  if (ex === "YAHOO_US") return "US";
  return ex || null;
}

// ── Pure helpers (same as before, no logic change) ────────────────────────────

function num(v: string | null | undefined): number | null {
  if (v == null || String(v).trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function strengthPct(row: OpportunityRow): number {
  const s = row.latest_pattern_strength;
  if (s == null) return 0;
  const n = typeof s === "number" ? s : Number(s);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n <= 1 ? n * 100 : n));
}

function displayName(row: OpportunityRow): string {
  const m = row.market_metadata;
  if (
    m &&
    typeof m === "object" &&
    "name" in m &&
    typeof (m as { name: unknown }).name === "string"
  ) {
    return (m as { name: string }).name;
  }
  return row.symbol;
}

function buildCopyParamsText(
  row: OpportunityRow,
  sizing: PositionSizingUserInput,
  currencyLabel: string,
): string {
  const plan = row.trade_plan;
  if (!plan) return "";
  const snap = computeOpportunityEconomicSnapshot(
    plan,
    sizing,
    row.final_opportunity_score,
    row.selected_trade_plan_variant_status,
  );
  const entry = num(plan.entry_price);
  const stop = num(plan.stop_loss);
  const tp = num(plan.take_profit_1);
  const short = plan.trade_direction === "short";
  const dirLabel = short ? "SHORT" : "LONG";
  let stopPct = "";
  let tpPct = "";
  if (entry != null && entry > 0 && stop != null) {
    const d = ((stop - entry) / entry) * 100;
    stopPct = ` (${d >= 0 ? "+" : ""}${d.toFixed(2)}%)`;
  }
  if (entry != null && entry > 0 && tp != null) {
    const d = ((tp - entry) / entry) * 100;
    tpPct = ` (${d >= 0 ? "+" : ""}${d.toFixed(2)}%)`;
  }
  const rr = plan.risk_reward_ratio ? String(plan.risk_reward_ratio) : "—";
  const qty = snap?.preview.ok
    ? String(Math.max(0, Math.round(snap.preview.positionSizeUnits)))
    : "—";
  const risk = snap?.preview.ok
    ? snap.preview.estimatedLossAtStopWithCosts.toFixed(2)
    : "—";
  const profit =
    snap?.preview.ok && snap.preview.estimatedNetProfitAtTp1 != null
      ? snap.preview.estimatedNetProfitAtTp1.toFixed(2)
      : "—";
  const riskPct =
    sizing.riskMode === "percent" ? `${sizing.riskPercent}%` : "fisso";
  const tp2 = num(plan.take_profit_2);
  let tp2Pct = "";
  if (entry != null && entry > 0 && tp2 != null) {
    const d = ((tp2 - entry) / entry) * 100;
    tp2Pct = ` (${d >= 0 ? "+" : ""}${d.toFixed(2)}%)`;
  }
  return [
    `${row.symbol} — ${dirLabel}`,
    `Entry: ${formatPrice(plan.entry_price)}`,
    `Stop Loss: ${formatPrice(plan.stop_loss)}${stopPct}`,
    `Take Profit 1: ${formatPrice(plan.take_profit_1)}${tpPct}`,
    ...(plan.take_profit_2 != null ? [`Take Profit 2: ${formatPrice(plan.take_profit_2)}${tp2Pct}`] : []),
    `R/R: ${rr}`,
    `Quantità consigliata: ${qty} azioni`,
    `Rischio: ${currencyLabel}${risk} (${riskPct} capitale)`,
    `Guadagno atteso TP1: ${currencyLabel}${profit}`,
  ].join("\n");
}

// ── Props (unchanged from 3A — contract preserved) ────────────────────────────

export type SignalCardProps = {
  opportunity: OpportunityRow;
  sizingInput: PositionSizingUserInput;
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
  currencySymbol: string;
  variant: "execute" | "monitor";
  cardId: string;
  expanded: boolean;
  onExpandedChange: (next: string | null) => void;
};

// ── Price delta helper ────────────────────────────────────────────────────────

function priceDeltaPct(price: string | null, reference: string | null): string | null {
  const p = num(price);
  const r = num(reference);
  if (p == null || r == null || r === 0) return null;
  const d = ((p - r) / Math.abs(r)) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(2)}%`;
}

// ── Score label → style ───────────────────────────────────────────────────────

function scoreBadgeClass(label: string): string {
  if (label === "strong") return "border-bull/40 bg-bull/10 text-bull";
  if (label === "moderate") return "border-warn/40 bg-warn/10 text-warn";
  if (label === "weak") return "border-neutral/30 bg-neutral/5 text-neutral";
  return "border-line bg-surface-2 text-fg-3";
}

const SCORE_LABEL_IT: Record<string, string> = {
  strong: "forte",
  moderate: "buono",
  weak: "debole",
  minimal: "scarso",
};

// ── Component ─────────────────────────────────────────────────────────────────

function SignalCardInner({
  opportunity: row,
  sizingInput,
  broker,
  onBrokerChange,
  currencySymbol,
  variant,
  cardId,
  expanded,
  onExpandedChange,
}: SignalCardProps) {
  const [copied, setCopied] = useState(false);

  const snap = useMemo(
    () =>
      computeOpportunityEconomicSnapshot(
        row.trade_plan ?? null,
        sizingInput,
        row.final_opportunity_score,
        row.selected_trade_plan_variant_status,
      ),
    [row, sizingInput],
  );

  const plan = row.trade_plan;
  const short = plan?.trade_direction === "short";
  const isLong = !short && (row.latest_pattern_direction === "bullish" || plan?.trade_direction === "long");
  const isBull = isLong;

  const dirLabel = row.latest_pattern_direction === "bearish" || short
    ? "BEARISH"
    : row.latest_pattern_direction === "bullish" || plan?.trade_direction === "long"
      ? "BULLISH"
      : "—";

  const priceLive =
    row.current_price != null && Number.isFinite(row.current_price)
      ? formatPrice(row.current_price)
      : "—";

  const strPct = strengthPct(row);
  const isExecute = variant === "execute";
  const isMonitor = variant === "monitor";

  const scoreLabel = row.final_opportunity_label ?? "minimal";
  const scoreInt = Math.round(row.final_opportunity_score ?? 0);
  const regime = (row.regime_spy ?? "unknown").toLowerCase();
  const regimeCls =
    regime === "bearish"
      ? "text-bear"
      : regime === "bullish"
        ? "text-bull"
        : "text-fg-2";

  const entryS = plan?.entry_price != null ? formatPrice(plan.entry_price) : "—";
  const stopS = plan?.stop_loss != null ? formatPrice(plan.stop_loss) : "—";
  const tpS = plan?.take_profit_1 != null ? formatPrice(plan.take_profit_1) : "—";
  const tp2S = plan?.take_profit_2 != null ? formatPrice(plan.take_profit_2) : null;
  const rrS = plan?.risk_reward_ratio ?? "—";

  const stopDelta = priceDeltaPct(plan?.stop_loss ?? null, plan?.entry_price ?? null);
  const tpDelta = priceDeltaPct(plan?.take_profit_1 ?? null, plan?.entry_price ?? null);
  const tp2Delta = tp2S != null ? priceDeltaPct(plan?.take_profit_2 ?? null, plan?.entry_price ?? null) : null;

  const qtyS = snap?.preview.ok
    ? String(Math.max(0, Math.round(snap.preview.positionSizeUnits)))
    : "—";
  const riskEur = snap?.preview.ok
    ? snap.preview.estimatedLossAtStopWithCosts.toFixed(2)
    : "—";
  const profitEur =
    snap?.preview.ok && snap.preview.estimatedNetProfitAtTp1 != null
      ? snap.preview.estimatedNetProfitAtTp1.toFixed(2)
      : "—";
  const profitTp2Eur =
    snap?.preview.ok && snap.preview.estimatedNetProfitAtTp2 != null
      ? snap.preview.estimatedNetProfitAtTp2.toFixed(2)
      : null;

  const detailHref = seriesDetailHref(row.symbol, row.timeframe, row.exchange, {
    provider: row.provider,
    asset_type: row.asset_type,
  });

  const topRationale = (row.decision_rationale ?? [])[0] ?? null;

  const toggleExpand = (e?: React.SyntheticEvent) => {
    e?.stopPropagation();
    onExpandedChange(expanded ? null : cardId);
  };

  const handleCardActivate = (e: React.MouseEvent<HTMLElement>) => {
    const el = e.target as HTMLElement;
    if (el.closest("button, a, input, select, textarea, [role='tab'], label")) return;
    toggleExpand();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleExpand();
    }
  };

  const onCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const text = buildCopyParamsText(row, sizingInput, currencySymbol);
    const ok = await copyTextToClipboard(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <article
      id={`card-${cardId}`}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-labelledby={`${cardId}-title`}
      aria-label={`Segnale ${row.symbol} ${row.timeframe} ${dirLabel} — score ${scoreInt}`}
      className={cn(
        "animate-slide-up cursor-pointer rounded-xl",
        "outline-none transition-all duration-150",
        "focus-visible:ring-2 focus-visible:ring-white/20",
        // No backdrop-filter: lista lunga → performance critica
        isExecute ? "gradient-border-bull" : "",
      )}
      style={{
        background: "hsla(228, 15%, 12%, 0.85)",
        border: isExecute
          ? "1px solid hsla(168, 100%, 42%, 0.25)"
          : isMonitor
            ? "1px solid hsla(38, 92%, 60%, 0.20)"
            : "1px solid hsla(0, 0%, 100%, 0.07)",
        borderRadius: "12px",
        boxShadow: isExecute
          ? "0 0 28px -6px hsla(168, 100%, 42%, 0.22)"
          : "0 2px 8px hsla(0, 0%, 0%, 0.2)",
      }}
      onClick={handleCardActivate}
      onKeyDown={handleKeyDown}
    >
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2 p-4 pb-3">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Badge
            variant="outline"
            className={cn(
              "font-mono text-[10px]",
              isExecute
                ? "border-bull/40 bg-bull/10 text-bull"
                : "border-warn/40 bg-warn/10 text-warn",
            )}
          >
            {isExecute ? "✅ ESEGUI" : "👁 MONITOR"}
          </Badge>

          <Badge
            variant="outline"
            className={cn(
              "font-mono text-[10px]",
              isBull ? "text-bull" : "text-bear",
            )}
          >
            {isBull ? "▲" : "▼"} {dirLabel} · {row.timeframe}
          </Badge>

          <Badge
            variant="outline"
            className={cn("font-mono text-[10px] tabular-nums", scoreBadgeClass(scoreLabel))}
            title={`Score: ${row.final_opportunity_score}`}
          >
            {scoreInt} · {SCORE_LABEL_IT[scoreLabel] ?? scoreLabel}
          </Badge>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-sm font-semibold tabular-nums text-fg">
            {priceLive}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-fg-2"
            aria-expanded={expanded}
            aria-label={expanded ? "Comprimi" : "Espandi"}
            onClick={toggleExpand}
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            )}
          </Button>
        </div>
      </div>

      {/* ── Symbol + name ──────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <h3
          id={`${cardId}-title`}
          className="flex items-baseline gap-1.5 font-sans text-xl font-bold tracking-tight text-fg"
        >
          {row.symbol}
          {exchangeTag(row) && (
            <span className="font-mono text-[11px] font-medium text-fg-3 tracking-wide">
              {exchangeTag(row)}
            </span>
          )}
        </h3>
        <p className="text-xs text-fg-2">{displayName(row)}</p>
      </div>

      {/* ── Price grid (always visible) ────────────────────────────── */}
      {plan && (
        <div
          className={cn(
            "gap-x-3 gap-y-1 border-t border-line/50 px-4 py-3",
            tp2S != null ? "grid grid-cols-5" : "grid grid-cols-4",
          )}
        >
          {[
            { label: "Entry", value: entryS, cls: "text-fg", delta: null, deltaCls: "" },
            { label: "Stop", value: stopS, cls: "text-bear", delta: stopDelta, deltaCls: "text-bear" },
            { label: "TP1", value: tpS, cls: "text-bull", delta: tpDelta, deltaCls: "text-bull" },
            ...(tp2S != null
              ? [{ label: "TP2", value: tp2S, cls: "text-bull/70", delta: tp2Delta, deltaCls: "text-bull/70" }]
              : []),
            { label: "R/R", value: String(rrS), cls: "text-fg", delta: null, deltaCls: "" },
          ].map(({ label, value, cls, delta, deltaCls }) => (
            <div key={label}>
              <p className="text-[10px] text-fg-3">{label}</p>
              <p className={cn("font-mono text-sm font-semibold tabular-nums", cls)}>
                {value}
              </p>
              {delta && (
                <p className={cn("font-mono text-[10px] tabular-nums", deltaCls)}>
                  {delta}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Strength bar + top rationale ───────────────────────────── */}
      {plan && (
        <div className="px-4 pb-3">
          <div className="mb-1 flex items-center justify-between">
            <span className="truncate font-sans text-[10px] text-fg-2">
              {row.latest_pattern_name?.replace(/_/g, " ") ?? "Pattern"}
            </span>
            <span className="font-mono text-[10px] tabular-nums text-fg-2">
              {Math.round(strPct)}%
            </span>
          </div>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-surface-2"
            role="progressbar"
            aria-valuenow={Math.round(strPct)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={cn(
                "h-full rounded-full transition-all",
                isBull
                  ? "bg-gradient-to-r from-accent to-bull"
                  : "bg-gradient-to-r from-accent to-bear",
              )}
              style={{
                width: `${strPct}%`,
                boxShadow: isBull
                  ? "0 0 10px hsla(168 100% 45% / 0.4)"
                  : "0 0 10px hsla(349 100% 65% / 0.4)",
              }}
            />
          </div>
          {topRationale && !expanded && (
            <p className="mt-1 truncate font-sans text-[10px] italic text-fg-3">
              {topRationale}
            </p>
          )}
        </div>
      )}

      {/* ── Actions (always visible) ───────────────────────────────── */}
      {plan && (
        <div
          className="flex flex-wrap items-center gap-2 border-t border-line/50 px-4 py-3"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-fg-2 hover:text-fg"
            onClick={onCopy}
            aria-label="Copia parametri trade"
          >
            {copied ? (
              <ClipboardCheck className="h-3.5 w-3.5 text-bull" aria-hidden />
            ) : (
              <Clipboard className="h-3.5 w-3.5" aria-hidden />
            )}
            {copied ? "Copiato" : "Copia"}
          </Button>

          <Link
            href={detailHref}
            prefetch={true}
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-neutral hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            Dettaglio
          </Link>
        </div>
      )}

      {/* ── Expanded: trade instructions + full details ────────────── */}
      {expanded && plan && (
        <div
          className="space-y-4 border-t border-line px-4 pb-4 pt-4"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Sizing row */}
          <div className="flex flex-wrap gap-4 text-xs text-fg-2">
            <span>
              Qty:{" "}
              <span className="font-mono font-semibold text-fg">{qtyS}</span>
            </span>
            <span>
              Rischio:{" "}
              <span className="font-mono font-semibold text-bear">
                {currencySymbol}
                {riskEur}
              </span>
            </span>
            <span>
              Guadagno TP1:{" "}
              <span className="font-mono font-semibold text-bull">
                {currencySymbol}
                {profitEur}
              </span>
            </span>
            {profitTp2Eur != null && (
              <span>
                Guadagno TP2:{" "}
                <span className="font-mono font-semibold text-bull/70">
                  {currencySymbol}
                  {profitTp2Eur}
                </span>
              </span>
            )}
          </div>

          {/* Trade instructions (broker steps) */}
          <TradeInstructions
            broker={broker}
            onBrokerChange={onBrokerChange}
            direction={short ? "short" : "long"}
            symbol={row.symbol}
            entry={entryS}
            stop={stopS}
            tp={tpS}
            qty={qtyS}
          />

          {/* Context grid */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs text-fg-3">Pattern</p>
              <p className="text-fg">
                {row.latest_pattern_name?.replace(/_/g, " ") ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-fg-3">Qualità</p>
              <p className="text-fg">
                {row.pattern_quality_score != null
                  ? `${row.pattern_quality_score.toFixed(1)}/100`
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-fg-3">Regime SPY</p>
              <p className={cn("font-mono text-sm", regimeCls)}>
                {row.regime_spy ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-fg-3">Prezzo vs entry</p>
              <p
                className={cn(
                  "font-mono text-sm tabular-nums",
                  row.price_stale ? "text-warn" : "text-fg-2",
                )}
              >
                {row.price_distance_pct != null
                  ? `${row.price_distance_pct > 0 ? "+" : ""}${row.price_distance_pct.toFixed(2)}%`
                  : "—"}
              </p>
            </div>
          </div>

          {/* Decision rationale */}
          {(row.decision_rationale ?? []).length > 0 && (
            <div>
              <p className="mb-1 text-xs text-fg-3">Motivazione</p>
              {(row.decision_rationale ?? []).map((line, i) => (
                <p key={i} className="text-xs text-fg-2">
                  {line}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

// React.memo: re-render only if id or opportunity_score changes (proxy for data freshness)
export const SignalCard = memo(SignalCardInner, (prev, next) => {
  return (
    prev.opportunity.symbol === next.opportunity.symbol &&
    prev.opportunity.timeframe === next.opportunity.timeframe &&
    prev.opportunity.exchange === next.opportunity.exchange &&
    prev.opportunity.final_opportunity_score === next.opportunity.final_opportunity_score &&
    prev.opportunity.operational_decision === next.opportunity.operational_decision &&
    prev.opportunity.current_price === next.opportunity.current_price &&
    prev.expanded === next.expanded &&
    prev.sizingInput === next.sizingInput &&
    prev.broker === next.broker
  );
});
