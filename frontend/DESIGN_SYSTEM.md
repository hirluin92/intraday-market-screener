# Design System — Intraday Market Screener

> Versione: Fase 2 — approvazione pre-implementazione  
> Dark mode first. Ispirazione: Bloomberg Terminal / TradingView.

---

## 0. Architettura token

Il progetto usa **Tailwind CSS v4**, che sostituisce `tailwind.config.ts` con configurazione **CSS-based**.  
I token sono definiti in `app/globals.css` via blocco `@theme {}`.

### Come funziona Tailwind v4 `@theme`

```css
/* In app/globals.css */
@theme {
  --color-bull: hsl(168 100% 42%);   /* → genera bg-bull, text-bull, border-bull */
  --radius-md: 8px;                  /* → genera rounded-md */
}
```

**Nessun `tailwind.config.ts` è necessario.** Se si aggiunge una dipendenza che richiede config JS, usare `postcss.config.mjs` per la configurazione del plugin.

### Gerarchia token

```
Primitive values (oklch/hsl raw)
        ↓
@theme {} → CSS var + utility class generata
        ↓
:root { legacy aliases } → backward compat con codebase esistente
        ↓
Componenti → usano utility classes (bg-bull) O CSS var (var(--color-bull))
```

---

## 1. Palette colori

### Accenti semantici

| Token | Utility Tailwind | HSL | Hex (approssimato) | Uso |
|-------|-----------------|-----|---------------------|-----|
| `--color-bull` | `bg-bull` `text-bull` `border-bull` | `hsl(168 100% 42%)` | `#00d4aa` | Bullish, profitto, success, confirm |
| `--color-bull-dim` | `bg-bull-dim` | `hsl(168 100% 42% / 0.15)` | — | Sfondo tinted bull |
| `--color-bear` | `bg-bear` `text-bear` `border-bear` | `hsl(349 100% 63%)` | `#ff4466` | Bearish, perdita, danger, stop |
| `--color-bear-dim` | `bg-bear-dim` | `hsl(349 100% 63% / 0.15)` | — | Sfondo tinted bear |
| `--color-neutral` | `bg-neutral` `text-neutral` `border-neutral` | `hsl(229 57% 63%)` | `#6b7fd7` | Monitor, info, link, CTA secondaria |
| `--color-warn` | `bg-warn` `text-warn` `border-warn` | `hsl(38 92% 60%)` | `#f5a623` | Warning, IBKR offline, skip |
| `--color-warn-dim` | `bg-warn-dim` | `hsl(38 92% 60% / 0.15)` | — | Sfondo tinted warn |

### Regola cromatica operativa

> **Bull = teal** `#00d4aa` — non verde puro (evita confusione con "safety green" UI generica)  
> **Bear = red-pink** `#ff4466` — non rosso puro (più leggibile su dark background)  
> **Monitor = blue-purple** `#6b7fd7` — colore neutro-caldo, non urgente  

### Surfaces (dark)

| Token | Utility | HSL | Uso |
|-------|---------|-----|-----|
| `--color-canvas` | `bg-canvas` | `hsl(246 24% 6%)` | Sfondo pagina (più scuro) |
| `--color-surface` | `bg-surface` | `hsl(245 22% 8%)` | Card, panel |
| `--color-surface-2` | `bg-surface-2` | `hsl(244 20% 10%)` | Input, dropdown, riga tabella |
| `--color-surface-3` | `bg-surface-3` | `hsl(243 18% 13%)` | Hover state, tooltip bg |

### Borders

| Token | Utility | HSL | Uso |
|-------|---------|-----|-----|
| `--color-line` | `border-line` | `hsl(240 24% 14%)` | Bordo default |
| `--color-line-hi` | `border-line-hi` | `hsl(240 20% 20%)` | Bordo focus, hover, active |

### Testo / Foreground

| Token | Utility | HSL | Uso |
|-------|---------|-----|-----|
| `--color-fg` | `text-fg` | `hsl(240 13% 96%)` | Testo primario, headings, valori |
| `--color-fg-2` | `text-fg-2` | `hsl(240 15% 48%)` | Testo secondario, label, meta |
| `--color-fg-3` | `text-fg-3` | `hsl(240 18% 27%)` | Testo muted, placeholder, ghost |

### Legacy aliases (backward compat)

I seguenti CSS variables vengono mantenuti in `:root` e puntano ai nuovi token.  
**Non usarli in nuovi componenti.** Saranno rimossi in Fase 5 (cleanup).

```
--accent-bull    → var(--color-bull)
--accent-bear    → var(--color-bear)
--accent-neutral → var(--color-neutral)
--bg-base        → var(--color-canvas)
--bg-surface     → var(--color-surface)
--bg-surface-2   → var(--color-surface-2)
--border         → var(--color-line)
--border-active  → var(--color-line-hi)
--text-primary   → var(--color-fg)
--text-secondary → var(--color-fg-2)
--text-muted     → var(--color-fg-3)
--glow-bull      → 0 0 20px hsl(168 100% 42% / 0.18)
--glow-bear      → 0 0 20px hsl(349 100% 63% / 0.18)
```

---

## 2. Tipografia

### Font stack

| Ruolo | Font primario | Fallback | CSS var | Nota |
|-------|--------------|----------|---------|------|
| **UI / headings** | Syne (loaded via next/font) | Geist Sans → Inter → system-ui | `--font-sans` | Display, nav, titoli |
| **Prezzi / ticker / numeri** | Space Mono (loaded via next/font) | Geist Mono → JetBrains Mono → ui-monospace | `--font-mono` | Numeri, codice, timestamp |

> **Fase 3:** valutare sostituzione Space Mono con JetBrains Mono (più condensato, migliore leggibilità su celle strette). Richiede aggiunta in `layout.tsx`.

### Regola tabular-nums

Ogni colonna numerica **deve** avere `font-variant-numeric: tabular-nums` per allineamento verticale delle cifre.  
Usare:
- Utility Tailwind: `tabular-nums` (class `tabular-nums`)
- HTML attribute: `data-numeric` (applicato globalmente in globals.css)
- Font mono: `font-mono` include già questa proprietà via `font-feature-settings: "tnum"`

### Scala tipografica

| Variabile | Dimensione | Line height | Uso tipico |
|-----------|-----------|-------------|-----------|
| `text-xs` | 11px | 1.4 | Label muted, timestamp, badge tiny |
| `text-sm` | 12px | 1.5 | Body secondario, cell tabella |
| `text-base` | 14px | 1.5 | Body principale (default body) |
| `text-md` | 15px | 1.5 | Label importante |
| `text-lg` | 16px | 1.4 | Subheading, sezione |
| `text-xl` | 18px | 1.35 | Heading pagina secondaria |
| `text-2xl` | 22px | 1.3 | Heading pagina principale |
| `text-3xl` | 28px | 1.2 | KPI value (P&L, win rate) |

> **Nota:** Tailwind v4 usa la scala di default. Le dimensioni sopra sono le default Tailwind e non richiedono override.

---

## 3. Spacing

Base: **4px grid** (Tailwind default `spacing-1 = 4px`).

| Uso | Valore | Tailwind class |
|-----|--------|---------------|
| Gap interno card | 12px | `gap-3` |
| Padding card | 16px | `p-4` |
| Padding sezione | 24px | `p-6` |
| Gap tra card in grid | 16px | `gap-4` |
| Margin sezione | 32px | `mt-8` |
| Max width content area | 1152px | `max-w-5xl` o `max-w-6xl` |

---

## 4. Border radius

| Token | Utility | Valore | Uso |
|-------|---------|--------|-----|
| `--radius-xs` | `rounded-xs` | 3px | Badge tiny, chip |
| `--radius-sm` | `rounded-sm` | 4px | Input, pill |
| `--radius-md` | `rounded-md` | 8px | Card, button |
| `--radius-lg` | `rounded-lg` | 12px | Dialog, panel |
| `--radius-xl` | `rounded-xl` | 16px | Sidebar, sheet |
| `--radius-2xl` | `rounded-2xl` | 20px | Modal large |
| `--radius-full` | `rounded-full` | 9999px | Badge arrotondato, avatar |

---

## 5. Shadows / Glow effects

Gli shadows su dark theme devono essere **additivi** (più luminosi, non più scuri).

| Token CSS | Uso |
|-----------|-----|
| `var(--glow-bull)` | Box-shadow su card/pulsante "execute" |
| `var(--glow-bear)` | Box-shadow su warning/stop/bear signal |
| `shadow-sm` | Tailwind default — per card overlay |
| `shadow-md` | Dialog, dropdown |
| `shadow-lg` | Modal, tooltip |

```css
/* Esempio uso glow in componente */
.card-execute {
  box-shadow: var(--glow-bull);
  animation: glow-execute 3.2s ease-in-out infinite;
}
```

---

## 6. Animazioni

Definite in `globals.css`, disponibili globalmente (non più scoped a `.trader-dashboard`).

| Classe | Keyframe | Durata | Uso |
|--------|----------|--------|-----|
| `.animate-pulse-live` | `pulse-live` | 1.4s | Indicatore LIVE |
| `.animate-glow-execute` | `glow-execute` | 3.2s | Card segnale execute |
| `.animate-slide-in` | `slide-in` | 0.35s | Comparsa card/section |
| `.animate-fade-in` | `fade-in` | 0.25s | Toast, tooltip, overlay |
| `.skeleton` | `skeleton-shimmer` | 1.6s | Loading placeholder |

---

## 7. Componenti — pattern visivi

### SignalCard — stati cromatici

```
Execute   → border-bull + bg-bull-dim + shadow glow-bull
Monitor   → border-warn  + bg-warn-dim
Discard   → border-line  + bg-surface (opacità ridotta)
```

### Badge / Pill — anatomomia

```
[● LIVE]         → bg-bull-dim border-bull text-bull rounded-full
[▲ LONG]         → bg-bull-dim text-bull px-1.5 py-0.5 rounded-xs text-[10px] font-bold
[▼ SHORT]        → bg-bear-dim text-bear
[⚠ IBKR offline] → bg-warn-dim border-warn text-warn
[● SPY Bull]     → bg-bull-dim text-bull
[● SPY Bear]     → bg-bear-dim text-bear
[● SPY Neutral]  → bg-neutral/15 text-neutral
```

### Tabella — anatomy

```
thead  → text-fg-3 font-medium border-b border-line
tbody tr  → hover:bg-surface-3 border-b border-line/50
td numerico → font-mono tabular-nums
td bull     → text-bull
td bear     → text-bear
```

### Input / Select — anatomy

```
border border-line bg-surface-2 text-fg
rounded-md px-3 py-2 text-sm
focus:outline-none focus:ring-1 focus:ring-neutral/50 focus:border-line-hi
placeholder:text-fg-3
```

### Button — varianti

```
Primary:   bg-bull text-canvas font-semibold rounded-md px-4 py-2
Secondary: bg-surface-2 border border-line text-fg hover:border-line-hi
Ghost:     text-fg-2 hover:text-fg hover:bg-surface-3
Danger:    bg-bear-dim border border-bear text-bear
```

---

## 8. Griglia layout applicazione

```
┌─────────────────────────────────────────────────────────┐
│ Topbar (h-12, sticky top-0, z-40)                       │
├──────────┬──────────────────────────────────────────────┤
│ Sidebar  │                                              │
│ w-56     │   Content area                               │
│ (lg:     │   max-w-[1200px] mx-auto px-4 sm:px-6       │
│ sticky,  │   pt-4 pb-12                                 │
│ h-screen)│                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘

Mobile (< lg):
┌─────────────────────────────────────────────────────────┐
│ Topbar (hamburger sx + logo centro + actions dx)        │
│ MobileDrawer overlay (sidebar come sheet)               │
├─────────────────────────────────────────────────────────┤
│ Content area (full width, px-4)                         │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Stack tecnico (da installare in Fase 3)

| Pacchetto | Versione | Motivo |
|-----------|----------|--------|
| `@tanstack/react-query` | latest | Fetching + cache + poll dedup |
| `@tanstack/react-table` | latest | Tabelle sortable/filterable |
| `@tanstack/react-virtual` | latest | Virtualizzazione liste lunghe |
| `lightweight-charts` | latest | Grafico OHLC TradingView |
| `sonner` | latest | Toast (raccomandato da shadcn) |
| `lucide-react` | latest | Icone (usato da shadcn) |
| `shadcn/ui` (CLI) | latest | Primitivi UI themed |

> **Non installare:** framer-motion, axios, date-fns (Intl API sufficiente).  
> **zustand:** skip se global state non è necessario dopo refactor; le preferenze utente restano in localStorage.

### shadcn/ui — componenti da installare

```
button dialog dropdown-menu toast tabs table skeleton badge
card input select switch separator scroll-area tooltip
```

### Configurazione shadcn con token custom

Al momento dell'installazione (`npx shadcn@latest init`), impostare:
- Base color: `neutral`
- CSS variables: `yes`
- Poi sovrascrivere `components.json` e `app/globals.css` con i nostri token

---

## 10. Accessibilità

- `aria-live="polite"` su: countdown refresh, aggiornamento conteggi segnali
- `aria-label` su: pulsanti icon-only, indicatori numerici
- `role="status"` su: loading states
- `role="alert"` su: errori
- Emoji come contenuto: wrappare in `<span aria-hidden>` + aggiungere testo screen-reader
- Focus visible: `focus-visible:ring-2 focus-visible:ring-neutral/70`

---

## 11. Performance budget

| Metrica | Target |
|---------|--------|
| LCP | < 1.5s |
| TTI | < 2.0s |
| CLS | < 0.1 |
| Bundle JS iniziale | < 200KB gzipped |
| Chunk chart (lightweight-charts) | lazy via `next/dynamic` |
| Chunk recharts | lazy via `next/dynamic` |
| Chunk TanStack Virtual | colocato con le tabelle |
