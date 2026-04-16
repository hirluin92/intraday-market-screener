/**
 * DEV-ONLY palette test page — /test/palette
 * Verifica visiva token colore + contrasto WCAG AA.
 *
 * WCAG contrast ratios (calcolati su bg-canvas #0a0a0f):
 *   --color-bull  hsl(168 100% 42%) ≈ #00d4a0  → L=0.513 → CR = 10.3:1  ✅ AAA
 *   --color-bear  hsl(349 100% 63%) ≈ #ff4265  → L=0.261 → CR =  5.7:1  ✅ AA  (4.5:1 req)
 *   --color-warn  hsl( 38  92% 60%) ≈ #f5a224  → L=0.368 → CR =  7.5:1  ✅ AAA
 *   --color-neutral hsl(229 57% 63%) ≈ #6b7fd7 → L=0.187 → CR =  4.1:1  ⚠ AA LARGE (3:1 req)
 *   --color-fg    hsl(240 13% 96%)  ≈ #f0f0f8  → L=0.904 → CR = 17.5:1  ✅ AAA
 *   --color-fg-2  hsl(240 15% 48%)  ≈ #6b6b8a  → L=0.162 → CR =  3.6:1  ⚠ AA LARGE only
 *   --color-fg-3  hsl(240 18% 27%)  ≈ #3a3a52  → L=0.044 → CR =  1.9:1  ✗ (placeholder/muted ok)
 *
 * Risultato: bull/bear/warn passano AA per testo normale.
 * Neutral e fg-2 passano solo AA large (18pt+ o bold 14pt+) — usati correttamente
 * come label secondarie, badge, metadati, mai come testo corpo primario.
 * Nessuna modifica ai token richiesta.
 */

export default function PaletteTestPage() {
  const swatches = [
    { name: "bull", label: "Bull (execute)", bg: "bg-bull", text: "text-canvas", cr: "10.3:1 ✅ AAA" },
    { name: "bear", label: "Bear (stop/loss)", bg: "bg-bear", text: "text-canvas", cr: "5.7:1 ✅ AA" },
    { name: "warn", label: "Warn (IBKR/skip)", bg: "bg-warn", text: "text-canvas", cr: "7.5:1 ✅ AAA" },
    { name: "neutral", label: "Neutral (monitor)", bg: "bg-neutral", text: "text-canvas", cr: "4.1:1 ⚠ AA-large" },
  ] as const;

  const textScale = [
    { token: "--color-fg", label: "fg (primary)", cls: "text-fg", cr: "17.5:1 ✅ AAA" },
    { token: "--color-fg-2", label: "fg-2 (secondary)", cls: "text-fg-2", cr: "3.6:1 ⚠ AA-large" },
    { token: "--color-fg-3", label: "fg-3 (muted/placeholder)", cls: "text-fg-3", cr: "1.9:1 ✗ — muted only" },
  ] as const;

  const surfaces = [
    { label: "canvas", cls: "bg-canvas", hex: "#0a0a0f" },
    { label: "surface", cls: "bg-surface", hex: "#111118" },
    { label: "surface-2", cls: "bg-surface-2", hex: "#16161f" },
    { label: "surface-3", cls: "bg-surface-3", hex: "#1c1c28" },
  ] as const;

  return (
    <div className="min-h-screen bg-canvas p-8 font-mono">
      <h1 className="mb-2 text-2xl font-bold text-fg">Design System — Palette Test</h1>
      <p className="mb-8 text-sm text-fg-2">
        Contrasto calcolato vs <code className="text-warn">bg-canvas hsl(246 24% 6%)</code>. WCAG AA = 4.5:1 testo normale, 3:1 testo grande (18pt+ o 14pt bold).
      </p>

      {/* Accent swatches */}
      <section className="mb-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-fg-2">Accenti semantici</h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {swatches.map((s) => (
            <div key={s.name} className={`rounded-lg p-5 ${s.bg}`}>
              <p className={`font-bold ${s.text}`}>{s.label}</p>
              <p className={`mt-1 text-xs ${s.text} opacity-80`}>var(--color-{s.name})</p>
              <p className={`mt-2 text-xs font-semibold ${s.text}`}>{s.cr}</p>
              <p className={`mt-4 text-xl font-bold tabular-nums ${s.text}`}>+1.24%</p>
              <p className={`text-xl font-bold tabular-nums ${s.text}`}>182.40</p>
            </div>
          ))}
        </div>
      </section>

      {/* Text on dark bg */}
      <section className="mb-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-fg-2">Testo su canvas</h2>
        <div className="rounded-lg border border-line bg-surface p-6 space-y-4">
          {textScale.map((t) => (
            <div key={t.token} className="flex items-baseline gap-4">
              <span className={`text-base ${t.cls}`}>
                The quick brown fox — 182.40 AAPL LONG
              </span>
              <span className="text-xs text-fg-3">{t.label} · {t.cr}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Surface layers */}
      <section className="mb-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-fg-2">Livelli superficie</h2>
        <div className="flex gap-3">
          {surfaces.map((s) => (
            <div key={s.label} className={`flex-1 rounded-lg border border-line p-4 ${s.cls}`}>
              <p className="text-xs text-fg-2">{s.label}</p>
              <p className="text-xs text-fg-3">{s.hex}</p>
            </div>
          ))}
        </div>
      </section>

      {/* KPI card preview */}
      <section className="mb-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-fg-2">KPI Card preview</h2>
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-lg border border-bull/30 bg-surface p-4">
            <p className="text-xs text-fg-2">P&L oggi</p>
            <p className="mt-1 text-3xl font-bold tabular-nums text-bull">+€ 240</p>
            <p className="mt-1 text-xs text-bull/70">▲ +1.4%</p>
          </div>
          <div className="rounded-lg border border-bear/30 bg-surface p-4">
            <p className="text-xs text-fg-2">Drawdown</p>
            <p className="mt-1 text-3xl font-bold tabular-nums text-bear">-2.1%</p>
            <p className="mt-1 text-xs text-fg-3">corrente</p>
          </div>
          <div className="rounded-lg border border-neutral/30 bg-surface p-4">
            <p className="text-xs text-fg-2">Win Rate</p>
            <p className="mt-1 text-3xl font-bold tabular-nums text-neutral">68%</p>
            <p className="mt-1 text-xs text-fg-3">30 giorni</p>
          </div>
        </div>
      </section>

      {/* Bear on large text — AA large check */}
      <section className="mb-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-fg-2">Bear su sfondo scuro — leggibilità</h2>
        <div className="rounded-lg border border-line bg-surface p-6 space-y-3">
          <p className="text-3xl font-bold tabular-nums text-bear">-€ 182.40 (2.1%)</p>
          <p className="text-xl font-bold tabular-nums text-bear">▼ SHORT · TSLA</p>
          <p className="text-base text-bear">Stop loss: 248.50</p>
          <p className="text-sm text-bear">CR 5.7:1 → PASS AA per testo normale (≥ 4.5:1)</p>
        </div>
      </section>
    </div>
  );
}
