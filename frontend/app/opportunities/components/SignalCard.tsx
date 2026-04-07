"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { OpportunityRow } from "@/lib/api";
import { seriesDetailHref } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatPrice } from "@/lib/formatPrice";
import { computeOpportunityEconomicSnapshot } from "@/lib/opportunityEconomicSnapshot";
import type { PositionSizingUserInput } from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";
import { TradeInstructions } from "./TradeInstructions";

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
  if (m && typeof m === "object" && "name" in m && typeof (m as { name: unknown }).name === "string") {
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
  const risk = snap?.preview.ok ? snap.preview.estimatedLossAtStopWithCosts.toFixed(2) : "—";
  const profit = snap?.preview.ok && snap.preview.estimatedNetProfitAtTp1 != null
    ? snap.preview.estimatedNetProfitAtTp1.toFixed(2)
    : "—";
  const riskPct =
    sizing.riskMode === "percent" ? `${sizing.riskPercent}%` : "fisso";

  return [
    `${row.symbol} — ${dirLabel}`,
    `Entry: ${formatPrice(plan.entry_price)}`,
    `Stop Loss: ${formatPrice(plan.stop_loss)}${stopPct}`,
    `Take Profit: ${formatPrice(plan.take_profit_1)}${tpPct}`,
    `R/R: ${rr}`,
    `Quantità consigliata: ${qty} azioni`,
    `Rischio: ${currencyLabel}${risk} (${riskPct} capitale)`,
    `Guadagno atteso TP1: ${currencyLabel}${profit}`,
  ].join("\n");
}

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

export function SignalCard({
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
  const router = useRouter();
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
  const dirLabel =
    row.latest_pattern_direction === "bearish" || short
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

  const borderAccent = isExecute
    ? "border-l-[var(--accent-bull)] animate-glow-execute"
    : isMonitor
      ? "border-l-amber-400/90"
      : "border-l-[var(--border)]";

  const goDetail = (e: React.MouseEvent) => {
    e.stopPropagation();
    router.push(
      seriesDetailHref(row.symbol, row.timeframe, row.exchange, {
        provider: row.provider,
        asset_type: row.asset_type,
      }),
    );
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

  const entryS = plan?.entry_price != null ? formatPrice(plan.entry_price) : "—";
  const stopS = plan?.stop_loss != null ? formatPrice(plan.stop_loss) : "—";
  const tpS = plan?.take_profit_1 != null ? formatPrice(plan.take_profit_1) : "—";
  const rrS = plan?.risk_reward_ratio ?? "—";
  const qtyS = snap?.preview.ok
    ? String(Math.max(0, Math.round(snap.preview.positionSizeUnits)))
    : "—";

  const regime = (row.regime_spy ?? "unknown").toLowerCase();
  const regimeCls =
    regime === "bearish"
      ? "text-[var(--accent-bear)]"
      : regime === "bullish"
        ? "text-[var(--accent-bull)]"
        : "text-[var(--text-secondary)]";

  return (
    <article
      id={`card-${cardId}`}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`Segnale ${row.symbol}, espandi dettaglio`}
      className={`animate-[slide-in_0.35s_ease-out] cursor-pointer rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4 ${borderAccent} border-l-4 backdrop-blur-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-neutral)]`}
      style={{ animationFillMode: "both" }}
      onClick={handleCardActivate}
      onKeyDown={handleKeyDown}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-md px-2 py-0.5 font-[family-name:var(--font-trader-sans)] text-xs font-bold ${
              isExecute
                ? "bg-[var(--accent-bull)]/20 text-[var(--accent-bull)]"
                : isMonitor
                  ? "bg-amber-500/20 text-amber-300"
                  : "bg-[var(--bg-surface-2)] text-[var(--text-secondary)]"
            }`}
          >
            {isExecute ? "✅ ESEGUI" : "👁 MONITOR"}
          </span>
          <span className="font-[family-name:var(--font-trader-mono)] text-xs font-semibold text-[var(--text-secondary)]">
            {dirLabel} {short ? "↓" : "↑"} · {row.timeframe}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-[family-name:var(--font-trader-mono)] text-lg font-bold text-[var(--text-primary)]">
            {priceLive}
          </span>
          <button
            type="button"
            className="rounded p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            aria-expanded={expanded}
            aria-label={expanded ? "Comprimi dettaglio" : "Espandi dettaglio"}
            onClick={toggleExpand}
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      <h3 className="mt-3 font-[family-name:var(--font-trader-sans)] text-xl font-bold tracking-tight text-[var(--text-primary)]">
        {row.symbol}
      </h3>
      <p className="text-sm text-[var(--text-secondary)]">{displayName(row)}</p>

      {plan && (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 font-[family-name:var(--font-trader-mono)] text-xs sm:grid-cols-4">
            <div>
              <dt className="text-[var(--text-muted)]">Entry</dt>
              <dd className="text-[var(--text-primary)]">{entryS}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-muted)]">Stop</dt>
              <dd className="text-[var(--text-primary)]">{stopS}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-muted)]">TP1</dt>
              <dd className="text-[var(--text-primary)]">{tpS}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-muted)]">R/R</dt>
              <dd className="text-[var(--text-primary)]">{rrS}</dd>
            </div>
          </dl>

          <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--text-secondary)]">
            <span>
              Rischio: {currencySymbol}
              {snap?.preview.ok ? snap.preview.estimatedLossAtStopWithCosts.toFixed(2) : "—"}
            </span>
            <span>·</span>
            <span>
              Guadagno TP1: {currencySymbol}
              {snap?.preview.ok && snap.preview.estimatedNetProfitAtTp1 != null
                ? snap.preview.estimatedNetProfitAtTp1.toFixed(2)
                : "—"}
            </span>
          </div>

          <div className="mt-3">
            <div className="mb-1 flex justify-between text-xs text-[var(--text-muted)]">
              <span className="truncate font-[family-name:var(--font-trader-sans)]">
                {row.latest_pattern_name?.replace(/_/g, " ") ?? "Pattern"}
              </span>
              <span className="font-[family-name:var(--font-trader-mono)]">{Math.round(strPct)}%</span>
            </div>
            <div
              className="h-2 overflow-hidden rounded-full bg-[var(--bg-surface-2)]"
              role="progressbar"
              aria-valuenow={Math.round(strPct)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-[var(--accent-neutral)] to-[var(--accent-bull)]"
                style={{ width: `${strPct}%` }}
              />
            </div>
          </div>
        </>
      )}

      {plan && (
        <div className="mt-4 flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={onCopy}
            className="rounded-lg border border-[var(--border-active)] bg-[var(--bg-surface-2)] px-3 py-2 text-xs font-semibold text-[var(--text-primary)] hover:border-[var(--accent-neutral)]"
          >
            {copied ? "✓ Copiato" : "📋 Copia parametri"}
          </button>
          <button
            type="button"
            onClick={goDetail}
            className="rounded-lg border border-transparent px-3 py-2 text-xs text-[var(--accent-neutral)] underline-offset-2 hover:underline"
          >
            Pagina serie →
          </button>
        </div>
      )}

      {expanded && plan && (
        <div
          className="mt-4 space-y-4 border-t border-[var(--border)] pt-4"
          onClick={(e) => e.stopPropagation()}
        >
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

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs text-[var(--text-muted)]">Pattern</p>
              <p className="text-[var(--text-primary)]">
                {row.latest_pattern_name?.replace(/_/g, " ") ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-[var(--text-muted)]">Qualità</p>
              <p className="text-[var(--text-primary)]">
                {row.pattern_quality_score != null
                  ? `${row.pattern_quality_score.toFixed(1)}/100`
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-[var(--text-muted)]">Regime SPY</p>
              <p className={regimeCls}>{row.regime_spy ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-[var(--text-muted)]">Prezzo vs entry</p>
              <p
                className={
                  row.price_stale ? "text-amber-400" : "text-[var(--text-secondary)]"
                }
              >
                {row.price_distance_pct != null
                  ? `${row.price_distance_pct > 0 ? "+" : ""}${row.price_distance_pct.toFixed(2)}% dall'entry`
                  : "—"}
              </p>
            </div>
          </div>

          {(row.decision_rationale ?? []).length > 0 && (
            <div>
              <p className="mb-1 text-xs text-[var(--text-muted)]">Motivazione</p>
              {(row.decision_rationale ?? []).map((line, i) => (
                <p key={i} className="text-xs text-[var(--text-secondary)]">
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
