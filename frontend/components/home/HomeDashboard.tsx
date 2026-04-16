"use client";

import Link from "next/link";
import { Activity, BarChart2, RefreshCw, TrendingDown, TrendingUp, Wallet, Zap } from "lucide-react";

import { ActivityFeed }   from "@/components/trading/ActivityFeed";
import { HomeSignalCard } from "@/components/trading/HomeSignalCard";
import { ErrorBoundary }  from "@/components/ErrorBoundary";
import { useDashboardData } from "@/hooks/useDashboardData";
import { cn } from "@/lib/utils";

// ─── Inline style constants ───────────────────────────────────────────────────

const GLASS_CARD: React.CSSProperties = {
  background: "hsla(0, 0%, 100%, 0.04)",
  backdropFilter: "blur(24px) saturate(160%)",
  WebkitBackdropFilter: "blur(24px) saturate(160%)",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "14px",
  padding: "20px",
};

const LABEL_STYLE: React.CSSProperties = {
  fontSize: "10px",
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.12em",
  color: "rgba(255,255,255,0.35)",
  marginBottom: "10px",
};

const VALUE_LARGE: React.CSSProperties = {
  fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
  fontSize: "2.2rem",
  fontWeight: 700,
  lineHeight: 1,
  letterSpacing: "-0.02em",
  fontVariantNumeric: "tabular-nums",
};

// ─── Section heading ──────────────────────────────────────────────────────────

function SectionHeading({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="flex-1 h-px" style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.10))" }} />
      <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.14em", color: "rgba(255,255,255,0.32)" }}>
        {title}
      </span>
      <div className="flex-1 h-px" style={{ background: "linear-gradient(90deg, rgba(255,255,255,0.10), transparent)" }} />
      {action && <div className="ml-1">{action}</div>}
    </div>
  );
}

// ─── Status card — IBKR ───────────────────────────────────────────────────────

function IBKRStatusCard({ ibkr }: { ibkr: ReturnType<typeof useDashboardData>["ibkr"] }) {
  const connected = ibkr.connectionStatus === "connected";
  const style: React.CSSProperties = {
    ...GLASS_CARD,
    ...(connected ? {
      borderColor: "rgba(0,212,160,0.28)",
      boxShadow: "0 0 28px -6px rgba(0,212,160,0.20)",
    } : {}),
  };

  return (
    <div style={style} role="article" aria-label="Stato IBKR">
      <div className="flex items-center justify-between mb-3">
        <p style={LABEL_STYLE}>IBKR</p>
        <Activity className="h-4 w-4" style={{ color: "rgba(255,255,255,0.25)" }} aria-hidden />
      </div>
      {ibkr.isLoading ? (
        <div className="skeleton h-8 w-28 rounded" />
      ) : (
        <>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              {connected && <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ background: "#00d4a0" }} />}
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ background: connected ? "#00d4a0" : ibkr.connectionStatus === "error" ? "#ff4d7a" : "rgba(255,255,255,0.25)" }} />
            </span>
            <p style={{ ...VALUE_LARGE, fontSize: "1.7rem", color: connected ? "#00d4a0" : ibkr.connectionStatus === "disconnected" ? "#f5a224" : ibkr.connectionStatus === "error" ? "#ff4d7a" : "rgba(255,255,255,0.5)" }}>
              {connected ? "Online" : ibkr.connectionStatus === "disconnected" ? "Disconnesso" : ibkr.connectionStatus === "error" ? "Errore" : "—"}
            </p>
          </div>
          {connected && ibkr.data && (
            <p style={{ fontSize: "11px", color: "rgba(255,255,255,0.35)" }}>
              {ibkr.data.paper_trading ? "Paper trading" : "Live trading"}
              {ibkr.data.auto_execute && " · auto-exec ON"}
            </p>
          )}
          {!connected && (
            <p style={{ fontSize: "11px", color: "rgba(255,255,255,0.2)", fontStyle: "italic" }}>
              {ibkr.connectionStatus === "disabled" ? "Non configurato" : "TWS non risponde"}
            </p>
          )}
        </>
      )}
    </div>
  );
}

// ─── Status card — Pipeline ───────────────────────────────────────────────────

function PipelineCard() {
  return (
    <div style={GLASS_CARD} role="article" aria-label="Stato pipeline">
      <div className="flex items-center justify-between mb-3">
        <p style={LABEL_STYLE}>PIPELINE</p>
        <RefreshCw className="h-4 w-4" style={{ color: "rgba(255,255,255,0.2)" }} aria-hidden />
      </div>
      <p style={{ ...VALUE_LARGE, fontSize: "1.5rem", color: "rgba(255,255,255,0.3)" }}>In attesa</p>
      <p style={{ fontSize: "11px", color: "rgba(255,255,255,0.18)", fontStyle: "italic", marginTop: "6px" }}>
        Endpoint non configurato
      </p>
    </div>
  );
}

// ─── Status card — Regime SPY ─────────────────────────────────────────────────

function RegimeSPYCard({ regime }: { regime: { value: string | null; isLoading: boolean } }) {
  const r = (regime.value ?? "").toLowerCase();
  const color =
    r === "bullish" ? "#00d4a0" :
    r === "bearish" ? "#ff4d7a" :
    r === "neutral" ? "#9b8fd4" : "rgba(255,255,255,0.3)";
  const biasLabel =
    r === "bullish" ? "Bias: rialzista" :
    r === "bearish" ? "Bias: ribassista" :
    r === "neutral" ? "Bias: laterale" : "Dati non disponibili";

  const style: React.CSSProperties = {
    ...GLASS_CARD,
    ...(regime.value && regime.value !== "unknown" ? {
      borderColor: color + "44",
      boxShadow: `0 0 24px -8px ${color}33`,
    } : {}),
  };

  return (
    <div style={style} role="article" aria-label={`Regime SPY: ${regime.value ?? "nd"}`}>
      <div className="flex items-center justify-between mb-3">
        <p style={LABEL_STYLE}>REGIME SPY</p>
        <BarChart2 className="h-4 w-4" style={{ color: "rgba(255,255,255,0.2)" }} aria-hidden />
      </div>
      {regime.isLoading ? (
        <div className="skeleton h-8 w-24 rounded" />
      ) : (
        <>
          <p style={{ ...VALUE_LARGE, fontSize: "1.7rem", color, textTransform: "capitalize" as const }}>
            {regime.value ? regime.value.charAt(0).toUpperCase() + regime.value.slice(1) : "—"}
          </p>
          <p style={{ fontSize: "11px", color: "rgba(255,255,255,0.28)", marginTop: "6px" }}>{biasLabel}</p>
        </>
      )}
    </div>
  );
}

// ─── Status card — Mercato ────────────────────────────────────────────────────

function MercatoCard() {
  const [time, setTime] = React.useState<{ str: string; open: boolean } | null>(null);

  React.useEffect(() => {
    function tick() {
      const ny = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
      const h = ny.getHours(), m = ny.getMinutes(), d = ny.getDay();
      const total = h * 60 + m;
      const open = d >= 1 && d <= 5 && total >= 9 * 60 + 30 && total < 16 * 60;
      const str = ny.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
      setTime({ str, open });
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const style: React.CSSProperties = {
    ...GLASS_CARD,
    ...(time?.open ? {
      borderColor: "rgba(0,212,160,0.22)",
      boxShadow: "0 0 24px -8px rgba(0,212,160,0.15)",
    } : {}),
  };

  return (
    <div style={style} role="article" aria-label="Orario mercato">
      <div className="flex items-center justify-between mb-2">
        <p style={LABEL_STYLE}>MERCATO</p>
        {time?.open && (
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ background: "#00d4a0" }} />
            <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: "#00d4a0" }} />
          </span>
        )}
      </div>
      {time ? (
        <>
          <p style={{ ...VALUE_LARGE, fontSize: "2.2rem", color: "#f2f2f2" }} suppressHydrationWarning>
            {time.str}
          </p>
          <p style={{ fontSize: "13px", fontWeight: 600, color: "rgba(255,255,255,0.5)", marginTop: "2px" }}>NY</p>
          <span
            className="inline-block rounded-md px-2 py-0.5 font-mono text-xs font-bold mt-2"
            style={time.open ? {
              background: "rgba(0,212,160,0.10)",
              border: "1px solid rgba(0,212,160,0.30)",
              color: "#00d4a0",
              boxShadow: "0 0 10px rgba(0,212,160,0.25)",
            } : {
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "rgba(255,255,255,0.3)",
            }}
          >
            {time.open ? "OPEN" : "CLOSED"}
          </span>
        </>
      ) : (
        <div className="skeleton h-8 w-24 rounded" />
      )}
    </div>
  );
}

// ─── Performance KPI card ─────────────────────────────────────────────────────

function PerfCard({
  label, value, sub, icon: Icon, color, glow, placeholder, placeholderNote,
}: {
  label: string;
  value?: string | null;
  sub?: string;
  icon: React.ElementType;
  color: string;
  glow?: string;
  placeholder?: boolean;
  placeholderNote?: string;
}) {
  const hasData = !placeholder && value != null;
  const style: React.CSSProperties = {
    ...GLASS_CARD,
    ...(hasData && glow ? { borderColor: glow + "44", boxShadow: `0 0 28px -8px ${glow}30` } : {}),
  };
  return (
    <div style={style} role="article">
      <div className="flex items-center justify-between mb-3">
        <p style={LABEL_STYLE}>{label}</p>
        <Icon className="h-4 w-4" style={{ color: hasData ? color : "rgba(255,255,255,0.2)" }} aria-hidden />
      </div>
      {placeholder ? (
        <>
          <p style={{ ...VALUE_LARGE, color: "rgba(255,255,255,0.2)" }}>—</p>
          {placeholderNote && <p style={{ fontSize: "10px", color: "rgba(255,255,255,0.15)", fontStyle: "italic", marginTop: "6px" }}>{placeholderNote}</p>}
        </>
      ) : (
        <>
          <p style={{ ...VALUE_LARGE, color }}>{value ?? "—"}</p>
          {sub && <p style={{ fontSize: "11px", color: "rgba(255,255,255,0.32)", marginTop: "6px" }}>{sub}</p>}
        </>
      )}
    </div>
  );
}

// ─── Error / retry ────────────────────────────────────────────────────────────

function SectionError({ label, onRetry }: { label: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-xl px-4 py-3" style={{ background: "rgba(245,162,36,0.06)", border: "1px solid rgba(245,162,36,0.15)" }} role="alert">
      <p className="text-sm" style={{ color: "rgba(255,255,255,0.5)" }}>{label} non disponibile.</p>
      {onRetry && <button type="button" onClick={onRetry} className="ml-auto text-xs" style={{ color: "#9b8fd4", textDecoration: "underline" }}>Riprova</button>}
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

import React from "react";

export function HomeDashboard() {
  const { ibkr, regime, topSignals, activity, performance } = useDashboardData();
  const openPositions = performance.openPositions.value;

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-6">

      {/* ── STATUS SISTEMA ─────────────────────────────────────────── */}
      <ErrorBoundary label="Status sistema">
        <section>
          <SectionHeading title="Status Sistema" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <IBKRStatusCard ibkr={ibkr} />
            <PipelineCard />
            <RegimeSPYCard regime={regime} />
            <MercatoCard />
          </div>
        </section>
      </ErrorBoundary>

      {/* ── PERFORMANCE ────────────────────────────────────────────── */}
      <ErrorBoundary label="Performance">
        <section>
          <SectionHeading title="Performance" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <PerfCard
              label="P&L OGGI"
              value={null}
              icon={Wallet}
              color="#00d4a0"
              glow="#00d4a0"
              placeholder
              placeholderNote="Richiede endpoint backend"
            />
            <PerfCard
              label="WIN RATE 30GG"
              value={null}
              icon={TrendingUp}
              color="#9b8fd4"
              placeholder
              placeholderNote="Richiede endpoint backend"
            />
            <PerfCard
              label="POSIZIONI APERTE"
              value={openPositions != null ? String(openPositions) : null}
              sub={openPositions === 0 ? "Nessuna posizione" : openPositions != null ? "+€— unrealized" : undefined}
              icon={Activity}
              color={openPositions != null && openPositions > 0 ? "#00d4a0" : "rgba(255,255,255,0.7)"}
              glow={openPositions != null && openPositions > 0 ? "#00d4a0" : undefined}
            />
            <PerfCard
              label="DRAWDOWN"
              value={null}
              icon={TrendingDown}
              color="#ff4d7a"
              placeholder
              placeholderNote="Richiede endpoint backend"
            />
          </div>
        </section>
      </ErrorBoundary>

      {/* ── ATTIVITÀ ───────────────────────────────────────────────── */}
      <ErrorBoundary label="Attività">
        <section>
          <SectionHeading title="Attività Recente" />
          {activity.error ? (
            <SectionError label="Feed attività" onRetry={() => activity.refetch()} />
          ) : (
            <div style={{
              background: "rgba(255,255,255,0.03)",
              backdropFilter: "blur(24px)",
              WebkitBackdropFilter: "blur(24px)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: "14px",
              padding: "8px",
            }}>
              <ActivityFeed items={activity.items} loading={activity.isLoading} maxItems={8} />
            </div>
          )}
        </section>
      </ErrorBoundary>

      {/* ── SEGNALI OPERATIVI ──────────────────────────────────────── */}
      <ErrorBoundary label="Segnali operativi">
        <section>
          <SectionHeading
            title="Segnali Operativi"
            action={
              <Link href="/opportunities" className="font-mono text-[10px] transition-colors" style={{ color: "#9b8fd4" }}>
                <Zap className="mr-1 inline h-3 w-3" aria-hidden />
                Vedi tutti
              </Link>
            }
          />

          {topSignals.isLoading ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {[0, 1].map((i) => (
                <div key={i} className="skeleton h-56 rounded-xl" />
              ))}
            </div>
          ) : topSignals.error ? (
            <SectionError label="Segnali execute" onRetry={() => topSignals.refetch()} />
          ) : topSignals.data.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl py-10 text-center" style={{ border: "1px dashed rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)" }}>
              <Zap className="h-7 w-7" style={{ color: "rgba(255,255,255,0.2)" }} aria-hidden />
              <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "14px" }}>📡 Nessun segnale operativo</p>
              <Link href="/opportunities" style={{ color: "#9b8fd4", fontSize: "12px", textDecoration: "underline" }}>
                Vai alle opportunità
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {topSignals.data.map((opp) => (
                <HomeSignalCard
                  key={`${opp.symbol}-${opp.timeframe}-${opp.exchange}`}
                  opportunity={opp}
                />
              ))}
            </div>
          )}
        </section>
      </ErrorBoundary>
    </div>
  );
}
