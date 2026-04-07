"use client";

type Regime = "bullish" | "bearish" | "neutral" | "unknown" | "n/a" | string;

function normalizeRegime(raw: string | undefined): Regime {
  const s = (raw ?? "unknown").toLowerCase().trim();
  if (s === "bullish" || s === "bearish" || s === "neutral") return s;
  if (s === "n/a") return "n/a";
  return "unknown";
}

export function RegimeBadge({ regime }: { regime: string | undefined }) {
  const r = normalizeRegime(regime);
  const label =
    r === "bullish"
      ? "BULLISH"
      : r === "bearish"
        ? "BEARISH"
        : r === "neutral"
          ? "NEUTRAL"
          : r === "n/a"
            ? "N/D"
            : "—";

  const cls =
    r === "bullish"
      ? "border-[var(--accent-bull)] bg-[var(--accent-bull)]/15 text-[var(--accent-bull)] shadow-[var(--glow-bull)]"
      : r === "bearish"
        ? "border-[var(--accent-bear)] bg-[var(--accent-bear)]/15 text-[var(--accent-bear)] shadow-[var(--glow-bear)]"
        : r === "neutral"
          ? "border-[var(--accent-neutral)] bg-[var(--accent-neutral)]/15 text-[var(--accent-neutral)]"
          : "border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-[family-name:var(--font-trader-sans)] text-xs font-bold tracking-wide ${cls}`}
      aria-label={`Regime SPY: ${label}`}
    >
      <span aria-hidden className="text-base leading-none">
        {r === "bullish" ? "📈" : r === "bearish" ? "📉" : r === "neutral" ? "↔️" : "◯"}
      </span>
      <span>SPY {label}</span>
    </span>
  );
}
