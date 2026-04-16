"use client";

import Link from "next/link";
import { seriesDetailHref } from "@/lib/api";
import type { OpportunityRow } from "@/lib/api";
import { formatPrice } from "@/lib/formatPrice";
import { cn } from "@/lib/utils";

interface HomeSignalCardProps {
  opportunity: OpportunityRow;
  className?: string;
}

function priceDelta(price: string | null | undefined, ref: string | null | undefined): string | null {
  const p = price ? Number(price) : null;
  const r = ref  ? Number(ref)   : null;
  if (!p || !r || r === 0) return null;
  const d = ((p - r) / Math.abs(r)) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(2)}%`;
}

function strengthPct(row: OpportunityRow): number {
  const s = row.latest_pattern_strength;
  if (s == null) return 0;
  const n = typeof s === "number" ? s : Number(s);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n <= 1 ? n * 100 : n));
}

// ── Inline styles ────────────────────────────────────────────────────────────

const CARD_BASE: React.CSSProperties = {
  borderRadius: "14px",
  overflow: "hidden",
  transition: "box-shadow 200ms, border-color 200ms",
};

export function HomeSignalCard({ opportunity: row, className }: HomeSignalCardProps) {
  const isExecute = row.operational_decision === "execute";
  const plan = row.trade_plan;
  const isBull = (row.latest_pattern_direction ?? "").toLowerCase() === "bullish"
    || plan?.trade_direction === "long";
  const strPct = strengthPct(row);
  const scoreInt = Math.round(row.final_opportunity_score ?? 0);
  const scoreLabel = row.final_opportunity_label ?? "minimal";
  const currentPrice = row.current_price != null ? formatPrice(String(row.current_price)) : "—";
  const entryS = plan?.entry_price != null ? formatPrice(plan.entry_price) : "—";
  const stopS  = plan?.stop_loss   != null ? formatPrice(plan.stop_loss)   : "—";
  const tp1S   = plan?.take_profit_1 != null ? formatPrice(plan.take_profit_1) : "—";
  const rrS    = plan?.risk_reward_ratio ?? "—";
  const stopDelta = priceDelta(plan?.stop_loss ?? null, plan?.entry_price ?? null);
  const tp1Delta  = priceDelta(plan?.take_profit_1 ?? null, plan?.entry_price ?? null);

  const detailHref = seriesDetailHref(row.symbol, row.timeframe, row.exchange, {
    provider: row.provider, asset_type: row.asset_type,
  });

  const cardStyle: React.CSSProperties = {
    ...CARD_BASE,
    background: "hsla(228, 15%, 12%, 0.85)",
    border: isExecute
      ? "1px solid rgba(0, 212, 160, 0.30)"
      : "1px solid rgba(255, 255, 255, 0.08)",
    boxShadow: isExecute
      ? "0 0 32px -6px rgba(0, 212, 160, 0.25), 0 4px 20px rgba(0,0,0,0.4)"
      : "0 4px 20px rgba(0,0,0,0.3)",
  };

  return (
    <div style={cardStyle} className={cn("flex flex-col", className)}>
      {/* ── Top row: badges + price ────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 pt-4 pb-2">
        {/* Decision badge */}
        <span
          className="rounded-full px-2.5 py-1 font-mono text-[11px] font-bold"
          style={isExecute ? {
            background: "rgba(0,212,160,0.12)",
            border: "1px solid rgba(0,212,160,0.35)",
            color: "#00d4a0",
          } : {
            background: "rgba(245,162,36,0.12)",
            border: "1px solid rgba(245,162,36,0.30)",
            color: "#f5a224",
          }}
        >
          {isExecute ? "EXECUTE" : "MONITOR"}
        </span>

        {/* Timeframe */}
        <span
          className="rounded-md px-2 py-0.5 font-mono text-[11px]"
          style={{ background: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.6)", border: "1px solid rgba(255,255,255,0.08)" }}
        >
          {row.timeframe}
        </span>

        {/* Score */}
        <span
          className="rounded-md px-2 py-0.5 font-mono text-[11px]"
          style={{ background: "rgba(139,127,212,0.15)", border: "1px solid rgba(139,127,212,0.3)", color: "#a89fd4" }}
        >
          {scoreInt} · {scoreLabel}
        </span>

        {/* Current price */}
        <span
          className="ml-auto font-mono text-sm font-semibold tabular-nums"
          style={{ color: "rgba(255,255,255,0.85)" }}
        >
          {currentPrice}
        </span>
      </div>

      {/* ── Symbol ──────────────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <h3 className="font-sans text-2xl font-bold tracking-tight" style={{ color: "#f2f2f2" }}>
          {row.symbol}
        </h3>
      </div>

      {/* ── Price grid ──────────────────────────────────────────────── */}
      {plan && (
        <div
          className="mx-4 mb-3 grid grid-cols-4 gap-3 rounded-lg px-3 py-3"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.05)" }}
        >
          {[
            { label: "ENTRY", value: entryS, delta: null, color: "rgba(255,255,255,0.9)" },
            { label: "STOP",  value: stopS,  delta: stopDelta, color: "#ff4d7a" },
            { label: "TP1",   value: tp1S,   delta: tp1Delta,  color: "#00d4a0" },
            { label: "R/R",   value: String(rrS), delta: null, color: "rgba(255,255,255,0.9)" },
          ].map(({ label, value, delta, color }) => (
            <div key={label}>
              <p className="mb-0.5 font-sans text-[9px] font-semibold uppercase tracking-widest"
                style={{ color: "rgba(255,255,255,0.35)", letterSpacing: "0.1em" }}>
                {label}
              </p>
              <p className="font-mono text-sm font-semibold tabular-nums" style={{ color }}>
                {value}
              </p>
              {delta && (
                <p className="font-mono text-[10px] tabular-nums" style={{ color: color + "99" }}>
                  {delta}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Strength bar ─────────────────────────────────────────────── */}
      {plan && (
        <div className="px-4 pb-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="font-mono text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
              {(row.latest_pattern_name ?? "pattern").replace(/_/g, " ")}
            </span>
            <span className="font-mono text-[11px]" style={{ color: "rgba(255,255,255,0.4)" }}>
              {Math.round(strPct)}%
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
            <div
              className="h-full rounded-full"
              style={{
                width: `${strPct}%`,
                background: "linear-gradient(90deg, #8b7fd4, #00d4a0)",
                boxShadow: "0 0 8px rgba(0,212,160,0.5)",
              }}
            />
          </div>
        </div>
      )}

      {/* ── Action buttons ───────────────────────────────────────────── */}
      <div
        className="flex items-center gap-2 border-t px-4 py-3"
        style={{ borderColor: "rgba(255,255,255,0.07)" }}
      >
        {isExecute && (
          <button
            type="button"
            className="flex-1 rounded-lg py-2 font-sans text-sm font-semibold transition-all"
            style={{
              background: "rgba(0,212,160,0.12)",
              border: "1px solid rgba(0,212,160,0.30)",
              color: "#00d4a0",
            }}
          >
            Esegui
          </button>
        )}
        <Link
          href={detailHref}
          className="flex-1 rounded-lg py-2 text-center font-sans text-sm font-semibold transition-all"
          style={{
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.10)",
            color: "rgba(255,255,255,0.75)",
          }}
        >
          Monitora
        </Link>
        <button
          type="button"
          className="flex-1 rounded-lg py-2 font-sans text-sm font-semibold transition-all"
          style={{
            background: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.06)",
            color: "rgba(255,255,255,0.35)",
          }}
        >
          Scarta
        </button>
      </div>
    </div>
  );
}
