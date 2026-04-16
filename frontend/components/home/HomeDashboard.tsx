"use client";

import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  BarChart2,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";

import { ActivityFeed } from "@/components/trading/ActivityFeed";
import { IBKRStatusPill } from "@/components/trading/IBKRStatusPill";
import { KPICard } from "@/components/trading/KPICard";
import { MarketClock } from "@/components/trading/MarketClock";
import { RegimeIndicator } from "@/components/trading/RegimeIndicator";
import { SignalCardCompact } from "@/components/trading/SignalCardCompact";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useDashboardData } from "@/hooks/useDashboardData";
import { cn } from "@/lib/utils";

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({
  title,
  children,
  action,
  className,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-4", className)}>
      {/* Gradient line heading */}
      <div className="flex items-center gap-3 mb-2">
        <div
          className="flex-1 h-px"
          style={{ background: "linear-gradient(90deg, transparent, hsla(0,0%,100%,0.10))" }}
        />
        <h2
          className="flex-shrink-0 text-[11px] font-semibold uppercase"
          style={{ color: "hsla(0,0%,100%,0.35)", letterSpacing: "0.12em" }}
        >
          {title}
        </h2>
        <div
          className="flex-1 h-px"
          style={{ background: "linear-gradient(90deg, hsla(0,0%,100%,0.10), transparent)" }}
        />
        {action && <div className="ml-2">{action}</div>}
      </div>
      {children}
    </section>
  );
}

// Inline style per status card glass
const STATUS_CARD_STYLE: React.CSSProperties = {
  background: "hsla(0, 0%, 100%, 0.04)",
  backdropFilter: "blur(24px) saturate(160%)",
  WebkitBackdropFilter: "blur(24px) saturate(160%)",
  border: "1px solid hsla(0, 0%, 100%, 0.08)",
  borderRadius: "12px",
  padding: "16px",
  display: "flex",
  flexDirection: "column",
  gap: "8px",
};

// ── Error card for a single section ──────────────────────────────────────────

function SectionError({
  label,
  onRetry,
}: {
  label: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-warn/30 bg-warn/5 p-4">
      <AlertTriangle className="h-4 w-4 shrink-0 text-warn" aria-hidden />
      <p className="text-sm text-fg-2">
        {label} non disponibile.
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="ml-2 font-medium text-fg underline underline-offset-2 hover:text-bull transition-colors"
          >
            Riprova
          </button>
        )}
      </p>
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export function HomeDashboard() {
  const { ibkr, pipeline, regime, topSignals, activity, performance } =
    useDashboardData();

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-6 animate-stagger">
      {/* ── ROW 1 — Status ──────────────────────────────────────────────── */}
      <ErrorBoundary label="Status">
        <Section title="Status sistema">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {/* IBKR */}
            <div style={STATUS_CARD_STYLE} role="article" aria-label="Stato connessione IBKR">
              <span style={{fontSize:"11px",fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",color:"hsla(0,0%,100%,0.4)"}}>IBKR</span>
              <IBKRStatusPill
                variant="pill"
                className={ibkr.isLoading ? "opacity-50" : ""}
              />
              {ibkr.data?.auto_execute && (
                <span className="text-[10px] text-fg-3">
                  Auto-exec ON · max {ibkr.data.max_simultaneous_positions ?? "—"} posizioni
                </span>
              )}
            </div>

            {/* Pipeline */}
            <div style={STATUS_CARD_STYLE} role="article" aria-label="Stato pipeline">
              <span style={{fontSize:"11px",fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",color:"hsla(0,0%,100%,0.4)"}}>Pipeline</span>
              <div className="flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-fg-3" aria-hidden />
                <span className="font-mono text-xs text-fg-3">
                  {pipeline.placeholderNote ?? "Non disponibile"}
                </span>
              </div>
              <span className="text-[10px] text-fg-3">
                Usa il pannello in /opportunità per avviare manualmente
              </span>
            </div>

            {/* Regime SPY */}
            <div style={STATUS_CARD_STYLE} role="article" aria-label={`Regime SPY: ${regime.value ?? "non disponibile"}`}>
              <span style={{fontSize:"11px",fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",color:"hsla(0,0%,100%,0.4)"}}>Regime SPY</span>
              {regime.isLoading ? (
                <div className="skeleton h-6 w-24 rounded-full" />
              ) : regime.error ? (
                <span className="text-xs text-fg-3">—</span>
              ) : (
                <RegimeIndicator regime={regime.value} />
              )}
            </div>

            {/* Market clock */}
            <div style={STATUS_CARD_STYLE} role="article" aria-label="Orario mercato">
              <span style={{fontSize:"11px",fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",color:"hsla(0,0%,100%,0.4)"}}>Mercato</span>
              <MarketClock />
            </div>
          </div>
        </Section>
      </ErrorBoundary>

      {/* ── ROW 2 — Performance KPIs ────────────────────────────────────── */}
      <ErrorBoundary label="Performance">
        <Section title="Performance">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {/* P&L oggi — placeholder */}
            <KPICard
              label={performance.pnlToday.label}
              value={null}
              icon={Wallet}
              placeholder={performance.pnlToday.placeholder}
              placeholderNote="Richiede GET /api/v1/performance/kpis"
              tooltip="P&L realizzato oggi in EUR (endpoint backend mancante)"
            />

            {/* Win rate — placeholder */}
            <KPICard
              label="Win Rate 30gg"
              value={null}
              icon={TrendingUp}
              placeholder
              placeholderNote="Richiede GET /api/v1/performance/kpis"
              tooltip="% trade chiusi in profitto (endpoint backend mancante)"
            />

            {/* Posizioni aperte — real */}
            <KPICard
              label={performance.openPositions.label}
              value={
                performance.openPositions.value !== null
                  ? performance.openPositions.value
                  : "—"
              }
              icon={Activity}
              loading={performance.openPositions.value === null && !performance.pnlToday.placeholder}
              variant={
                performance.openPositions.value !== null && performance.openPositions.value > 0
                  ? "bull"
                  : "neutral"
              }
              href="/opportunities"
            />

            {/* Drawdown — placeholder */}
            <KPICard
              label={performance.drawdown.label}
              value={null}
              icon={TrendingDown}
              placeholder={performance.drawdown.placeholder}
              placeholderNote="Richiede GET /api/v1/performance/kpis"
              tooltip="Drawdown corrente % (endpoint backend mancante)"
            />
          </div>
        </Section>
      </ErrorBoundary>

      {/* ── ROW 3 — Activity feed ────────────────────────────────────────── */}
      <ErrorBoundary label="Attività recente">
        <Section title="Attività recente">
          {activity.error ? (
            <SectionError
              label="Feed attività"
              onRetry={() => activity.refetch()}
            />
          ) : (
            <div
              style={{
                background: "hsla(0, 0%, 100%, 0.03)",
                backdropFilter: "blur(24px)",
                WebkitBackdropFilter: "blur(24px)",
                border: "1px solid hsla(0, 0%, 100%, 0.07)",
                borderRadius: "12px",
                padding: "8px",
              }}
            >
              <ActivityFeed
                items={activity.items}
                loading={activity.isLoading}
                maxItems={10}
              />
            </div>
          )}
        </Section>
      </ErrorBoundary>

      {/* ── ROW 4 — Top signals execute ─────────────────────────────────── */}
      <ErrorBoundary label="Segnali operativi">
        <Section
          title="Segnali operativi"
          action={
            <Link
              href="/opportunities"
              prefetch={true}
              className="flex items-center gap-1 text-xs text-neutral hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50 rounded"
            >
              <Zap className="h-3 w-3" aria-hidden />
              Vedi tutti i segnali
            </Link>
          }
        >
          {topSignals.error ? (
            <SectionError
              label="Segnali execute"
              onRetry={() => topSignals.refetch()}
            />
          ) : topSignals.isLoading ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="skeleton h-44 rounded-lg"
                  aria-hidden
                />
              ))}
            </div>
          ) : topSignals.data.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line py-10 text-center">
              <BarChart2 className="h-8 w-8 text-fg-3" aria-hidden />
              <div>
                <p className="text-sm text-fg-2">
                  📡 Nessun segnale operativo al momento
                </p>
                <p className="mt-1 text-xs text-fg-3">
                  Il refresh automatico è attivo su{" "}
                  <Link href="/opportunities" className="text-neutral underline underline-offset-2">
                    /opportunità
                  </Link>
                </p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {topSignals.data.map((opp) => (
                <SignalCardCompact
                  key={`${opp.symbol}-${opp.timeframe}-${opp.exchange}`}
                  opportunity={opp}
                />
              ))}
            </div>
          )}
        </Section>
      </ErrorBoundary>
    </div>
  );
}

