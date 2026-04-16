# Wireframes — Intraday Market Screener

> Fase 2 — Layout reference pre-implementazione  
> Formato: ASCII art + descrizione zone + stati + interazioni  
> Ordine = ordine di implementazione in Fase 3

---

## A) App Shell — Layout Globale

### Desktop (≥ 1024px)

```
┌────────────────────────────────────────────────────────────────────────┐
│ TOPBAR  h-12  sticky top-0  z-40  bg-canvas  border-b border-line      │
│ [≡ Logo] ──────────────── [● SPY Bull] [🕐 09:32 NY ▸ 16:00] [⚙]    │
├────────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR    │                                                            │
│ w-56       │  MAIN CONTENT AREA                                        │
│ sticky     │  max-w-[1200px]  mx-auto  px-6  pt-4  pb-12              │
│ top-12     │                                                            │
│ h-[calc(   │  <children />                                             │
│  100vh-    │                                                            │
│  3rem)]    │                                                            │
│ overflow-y │                                                            │
│            │                                                            │
│ ──────     │                                                            │
│ [⌂] Home  │                                                            │
│ [◎] Opp.  │                                                            │
│ [↺] Bktest│                                                            │
│ [~] Simul.│                                                            │
│ [⚗] Lab   │                                                            │
│ [◈] Diagn.│                                                            │
│            │                                                            │
│   ─────    │                                                            │
│ [● IBKR]  │                                                            │
│ [↺ Pipe]  │                                                            │
└────────────┴───────────────────────────────────────────────────────────┘

[Toast area] bottom-right  fixed  z-50
```

### Mobile (< 1024px)

```
┌──────────────────────────────────────────┐
│ TOPBAR  h-12                             │
│ [☰ Drawer] [Logo] ──────── [● SPY][⚙]  │
├──────────────────────────────────────────┤
│                                          │
│  CONTENT AREA  px-4                      │
│  <children />                            │
│                                          │
└──────────────────────────────────────────┘

[Drawer overlay — sheet from left]
┌────────────────────────┐
│ [✕] Close              │
│ ────────────────────── │
│ [⌂] Home               │
│ [◎] Opportunità        │
│ [↺] Backtest           │
│ [~] Simulazione        │
│ [⚗] Trade Plan Lab     │
│ [◈] Diagnostica        │
│ ────────────────────── │
│ [● IBKR LIVE connesso] │
│ [↺ Pipeline OK]        │
└────────────────────────┘
```

### Sidebar — stati

| Stato | Visualizzazione |
|-------|----------------|
| **Collapsed** (lg) | Solo icone, w-14, tooltip on hover |
| **Expanded** (lg) | Icona + label, w-56 |
| **Mobile drawer** | Sheet full-height da sx, overlay scuro |

### Topbar — zone

```
LEFT: toggle sidebar (lg) / hamburger (mobile) + Logo "IMS"
CENTER: [empty — spazio per breadcrumb futuro]
RIGHT: RegimeIndicator (SPY badge) + MarketClock + Settings icon
```

### Bottom del Sidebar — status widgets

```
┌──────────────────────┐
│ ● IBKR PAPER · conn. │  → IBKRStatusPill (hook unificato)
│ ↺ Pipeline · 14:22   │  → PipelineStatusPill
└──────────────────────┘
```

---

## B) `/` — Home Dashboard (NEW)

**Scopo:** cruscotto operativo apertura giornata. Zero click per avere contesto completo.

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR  │                                                           │
│          │  ── STATUS ROW ─────────────────────────────────────────  │
│          │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
│          │  │ IBKR         │ │ Pipeline     │ │ Mercato      │       │
│          │  │ ● PAPER LIVE │ │ ↺ OK 14:22  │ │ 🟢 Aperto   │       │
│          │  │ Auto-exec ON │ │ 23 simboli  │ │ 14:31 NY    │       │
│          │  └──────────────┘ └──────────────┘ └──────────────┘      │
│          │                                                           │
│          │  ── PERFORMANCE ROW ────────────────────────────────────  │
│          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│          │  │ P&L oggi │ │ Win rate │ │ Drawdown │ │ Posiz.   │    │
│          │  │ +€ 240   │ │  68 %    │ │ -2.1 %   │ │  3 open  │    │
│          │  │ ▲ +1.4%  │ │  30 gg   │ │ corrente │ │          │    │
│          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
│          │                                                           │
│          │  ── ATTIVITÀ RECENTE ───────────────────────────────────  │
│          │  14:22  ↺ Pipeline  — 23 opportunità trovate             │
│          │  14:21  ▲ AAPL 1h LONG  eseguito @ 182.40               │
│          │  14:10  ↺ Pipeline  — 21 opportunità trovate             │
│          │  14:05  ▼ BTC 5m SHORT  eseguito @ 67,230               │
│          │  13:50  ↺ Pipeline  — 18 opportunità trovate             │
│          │                        [Vedi storico completo →]         │
│          │                                                           │
│          │  ── SEGNALI EXECUTE ────────────────────────────── [→ tutti]
│          │  ┌──────────────────┐  ┌──────────────────┐             │
│          │  │ AAPL · 1h · LONG │  │ TSLA · 5m · SHORT│             │
│          │  │ Entry 182.40     │  │ Entry 245.10     │             │
│          │  │ SL 179.90 TP 187 │  │ SL 247.50 TP 241 │             │
│          │  │ Score ████░░ 72% │  │ Score ███░░░ 58% │             │
│          │  └──────────────────┘  └──────────────────┘             │
│          │  [+ 1 altro segnale]                                      │
└──────────┴───────────────────────────────────────────────────────────┘
```

### Ordine righe (aggiornato da review)

1. **Row 1 — Status** (4 card): IBKR, Pipeline, Mercato, Regime SPY
2. **Row 2 — Performance** (4 KPI): P&L oggi, Win Rate 30gg, Drawdown, Posizioni aperte
3. **Row 3 — Activity feed**: ultime 10 azioni (review + contesto prima di agire)
4. **Row 4 — Segnali execute**: top 3-5 con CTA "Vedi tutti" (azione dopo la review)

### Componenti usati

- `KPICard` × 7 (IBKR, Pipeline, Mercato, P&L, Win%, Drawdown, Posizioni)
- `SignalCardCompact` × 3-5 (top segnali execute)
- Lista attività (feed da executed-signals + pipeline log)

### Stati

| Stato | Comportamento |
|-------|--------------|
| **Loading** | Skeleton su tutte le KPI card + placeholder 2 SignalCardCompact |
| **IBKR offline** | KPICard IBKR con border-warn, icona ⚠, testo "IBKR non risponde" |
| **Nessun segnale** | Empty state nella sezione Execute: "📡 In ascolto…" con countdown |
| **Mercato chiuso** | MarketClock con badge grigio "Chiuso · apre tra 6h 32m" |
| **Error fetch** | Ogni KPICard mostra "—" con tooltip errore; non crash l'intera home |

### Data fetching (React Server Component + Client Islands)

```
RSC:   nessun fetch bloccante — shell HTML immediato
Client islands:
  useIBKRStatus()        → KPICard IBKR + sidebar pill
  useOpportunities()     → sezione segnali execute (top 3-5)
  fetchExecutedSignals() → sezione attività recente
  MarketClock            → clock locale, nessun fetch
```

---

## C) `/opportunities` — Dashboard Segnali LIVE

**Obiettivo refactor:** spaccare il god component in layout + sezioni + hook.

### Breakpoint preferenze (aggiornato da review)

| Breakpoint | Layout |
|------------|--------|
| **≥ 1280px (xl)** | Sidebar sinistra + main + sidebar destra (320px) sticky |
| **1024–1279px (lg)** | Sidebar sinistra + main (full). Preferenze in Drawer da pulsante header |
| **< 1024px** | Solo main + drawer mobile per navigazione + preferenze |

### Layout desktop (≥ 1280px)

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬─────────────────────────────────────────┬────────────────┤
│ SIDEBAR  │  HEADER STICKY  top-12  z-30            │ PREFERENCES    │
│          │  [● LIVE] Aggiorna [↺] Auto 60s [▓▓|░]  │ PANEL          │
│          │  [✅3] [👁12] [✗8]   [Regime: Bull]      │ w-80 sticky   │
│          │  [Strumenti ⚙]  [Sort ▼]                │ top-12         │
│          ├─────────────────────────────────────────┤                │
│          │  FILTRI PILLS                            │ Capitale       │
│          │  [Tutti] [✅ Esegui] [👁 Monitor] [Scar] │ €[_____]       │
│          │  [Tutti TF] [1h] [5m]                   │                │
│          │  [Tutti dir] [Bull] [Bear]               │ Rischio        │
│          ├─────────────────────────────────────────┤ [%] [€]        │
│          │                                          │ [___]          │
│          │  ── ESEGUI ORA ────────────────────────  │                │
│          │  ┌──────────────┐  ┌──────────────┐    │ Broker         │
│          │  │ SignalCard   │  │ SignalCard   │    │ [IBKR ▼]       │
│          │  │ (execute)    │  │ (execute)    │    │                │
│          │  └──────────────┘  └──────────────┘    │ ──────────     │
│          │                                          │ Today max: 3   │
│          │  ── MONITORA ──────────────────────────  │ Last 7d: 11    │
│          │  ┌──────────────┐  ┌──────────────┐    │                │
│          │  │ SignalCard   │  │ SignalCard   │    │                │
│          │  │ (monitor)    │  │ (monitor)    │    │                │
│          │  └──────────────┘  └──────────────┘    │                │
│          │                                          │                │
│          │  ── ⚡ SEGNALI SISTEMA ────────────────  │                │
│          │  [tabella executed signals collapsible]  │                │
│          │                                          │                │
│          │  ▼ Nell'universo (8) [collassato]        │                │
└──────────┴─────────────────────────────────────────┴────────────────┘
```

### Header sticky — zone

```
Row 1:
  LEFT:  [● LIVE animated] · [HH:MM:SS] · [↻ Aggiorna] · [Auto ☐]
  RIGHT: [IBKRStatusPill] [RegimeIndicator] [N segnali ESEGUI badge]

Row 2:
  LEFT:  OpportunitySummaryBar → [✅ 3 execute] [👁 12 monitor] [✗ 8 scarta]
  RIGHT: [⚙ Strumenti] (apre Dialog pipeline) · [Sort ▼] (DropdownMenu)

Row 3:
  Filtri pill: Decisione | Timeframe | Direzione (inline, wrap on mobile)
```

### Panel Preferenze (desktop: sidebar destra sticky, mobile: drawer)

```
┌─────────────────────────────┐
│ Preferenze                  │
│ ─────────────────────────── │
│ Capitale operativo          │
│ [€ 5.000________________]   │
│                             │
│ Modalità rischio            │
│ (•) % del capitale  ( ) €  │
│ [2___] %                    │
│                             │
│ Broker                      │
│ [IBKR ▼]                    │
│                             │
│ ─────────────────────────── │
│ Oggi max execute: 3         │
│ Ultimi 7 gg: 11             │
└─────────────────────────────┘
```

### Dialog "Strumenti" (pipeline maintenance)

```
┌──────────────────────────────────────────────┐
│ ⚙ Manutenzione Pipeline             [✕]      │
│ ──────────────────────────────────────────── │
│ POST /api/v1/pipeline/refresh                │
│                                              │
│ Provider    [Binance ▼]  Venue [________]    │
│ Simbolo     [__________]                     │
│ Timeframe   [— ▼]                            │
│ Limite ingest [2500__] Limit extract [5000]  │
│ Lookback    [50___]                          │
│                                              │
│             [Annulla]  [▶ Esegui pipeline]   │
└──────────────────────────────────────────────┘
```

### Mobile layout

```
┌──────────────────────────────┐
│ TOPBAR (hamburger + logo)    │
│ ── HEADER STICKY ─────────── │
│ ● LIVE · 14:32 · [↻] [Auto] │
│ [✅3] [👁12] [✗8]  [SPY Bull]│
│ ──────────────────────────── │
│ [Tutti][✅ Eseg.][👁 Mon.]   │
│ [1h][5m]  [Bull][Bear]       │
│ ──────────────────────────── │
│  SignalCard (full width)     │
│  SignalCard (full width)     │
│  [Preferenze ▼] (collapsed)  │
│  [Monitora ▼]                │
└──────────────────────────────┘
```

### Stati

| Stato | Visualizzazione |
|-------|----------------|
| **Loading iniziale** | Skeleton × 4 SignalCard placeholder |
| **Re-fetch (poll)** | Spinner piccolo nell'header, card non spariscono |
| **Error** | Alert full-width con messaggio + pulsante retry |
| **Empty (tutti filtri)** | EmptyState "📡 In ascolto…" con countdown |
| **Empty (filtro attivo)** | EmptyState "Nessun segnale per questo filtro" + CTA "Mostra tutti" |

---

## D) `/opportunities/[symbol]/[timeframe]` — Dettaglio Serie

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR  │  ← Torna  AAPL · 1h · LONG · NASDAQ  [↻ Aggiorna]       │
│          │  ──────────────────────────────────────────────────────── │
│          │                                                           │
│          │  ┌─────────────────────────────────────────────────────┐ │
│          │  │                                                     │ │
│          │  │   CANDLESTICK CHART (Lightweight Charts)            │ │
│          │  │   OHLC + Volume + Marker pattern                    │ │
│          │  │   h-[500px] resizable                               │ │
│          │  │                                                     │ │
│          │  │   [crosshair OHLCV tooltip on hover]               │ │
│          │  │                                                     │ │
│          │  └─────────────────────────────────────────────────────┘ │
│          │                                                           │
│          │  ┌────────────────────────┐  ┌──────────────────────────┐│
│          │  │ TRADE PLAN             │  │ CONTESTO & FEATURES      ││
│          │  │                        │  │                          ││
│          │  │ Score: ████████░ 82%  │  │ Regime SPY: Bull         ││
│          │  │                        │  │ ADX: 34  ATR: 1.2       ││
│          │  │ Entry:  182.40         │  │ Volume rel: 1.8x         ││
│          │  │ Stop:   179.90 (-1.4%) │  │ RSI: 62                 ││
│          │  │ TP1:    186.80 (+2.4%) │  │ VWAP: ↑ above           ││
│          │  │ TP2:    190.00 (+4.2%) │  │ ────────────────────── ││
│          │  │ RR:     1.8            │  │ PATTERN RILEVATI         ││
│          │  │ ────────────────────── │  │                          ││
│          │  │ POSITION SIZING        │  │ ▲ Bullish Engulfing      ││
│          │  │ Qty: 27 azioni         │  │   Forza: 78%  Conf: 82% ││
│          │  │ Rischio: €54.00 (1.1%) │  │   [3 confirm / 1 discard]││
│          │  │ Profit TP1: €116.10    │  │                          ││
│          │  └────────────────────────┘  └──────────────────────────┘│
└──────────┴───────────────────────────────────────────────────────────┘
```

### Loading per-sezione (5 fetch parallele)

```
┌──────────────────────────────────────────────────────────────┐
│  [Skeleton chart h-500]                                      │
│                                                              │
│  ┌────────────────────────┐  ┌─────────────────────────────┐│
│  │ [Skeleton trade plan ] │  │ [Skeleton features 4 rows ] ││
│  └────────────────────────┘  └─────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘

Ogni sezione si popola indipendentemente:
  candles   → chart appare per prima (tipicamente più veloce)
  features  → contesto appare
  patterns  → marker vengono aggiunti al chart già visibile
  context   → colonna destra si completa
```

### Error per-sezione

```
┌──────────────────────────────────────────┐
│  [Chart OK]                              │
│                                          │
│  ┌──────────────────┐  ┌──────────────┐ │
│  │ Trade Plan OK    │  │ ⚠ Contesto  │ │
│  │                  │  │ non caricato │ │
│  │                  │  │ [Riprova]    │ │
│  └──────────────────┘  └──────────────┘ │
└──────────────────────────────────────────┘
```

### CandleChart — elementi visivi

```
Componente: <CandleChart /> (wrapper Lightweight Charts)
├── Candlestick series (OHLC colorato bull/bear)
├── Volume histogram (sotto, separato, altezza 20%)
├── Linea VWAP (se disponibile)
├── Marker pattern (triangolo ▲▼ sul candle di trigger)
└── Crosshair con tooltip OHLCV
```

---

## E) `/backtest` — Analisi Pattern

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR  │  ── TOOLBAR STICKY ──────────────────────────────────── ─│
│          │  [TF: 1h ▼] [Dir: tutti ▼] [Pattern ▼] [Applica] [Reset]│
│          │  [Export CSV ↓]  ·  N risultati: 342                      │
│          │  ─────────────────────────────────────────────────────── │
│          │  ┌──────────────────────────────────────────────────────┐│
│          │  │ TABELLA VIRTUALIZZATA (TanStack Table + Virtual)     ││
│          │  │                                                      ││
│          │  │ Pattern       TF   Dir   N    WR%   AvgR  IC  Sign  ││
│          │  │ ─────────     ──   ───   ──   ───   ────  ──  ────  ││
│          │  │ Engulfing     1h   Bull  234  64.2  1.32  .22  **   ││
│          │  │ Hammer        1h   Bull  189  61.8  1.18  .18  *    ││
│          │  │ ...           ...  ...   ...  ...   ...   ...  ...  ││
│          │  │  ↓ scroll virtualizzato (solo DOM visibile)         ││
│          │  └──────────────────────────────────────────────────────┘│
└──────────┴───────────────────────────────────────────────────────────┘
```

### Toolbar — zone

```
LEFT:  Filtri: [Timeframe ▼] [Direzione ▼] [Pattern search ___] [Applica] [Reset]
RIGHT: [N risultati: 342]  [Export CSV ↓]
```

### Tabella — colonne (sortable, click header)

```
Pattern | TF | Direzione | N trades | Win Rate % | Avg R | IC | Significatività
```

### Stati

| Stato | Visualizzazione |
|-------|----------------|
| **Loading** | Skeleton tabella (10 righe placeholder) + skeleton toolbar |
| **Empty** | EmptyState "Nessun pattern trovato con i filtri attuali" |
| **Error** | Alert full-width + retry |
| **5000 righe** | Virtualizzato: solo ~20 righe in DOM, scroll fluido |

---

## F) `/simulation` — Backtest Engine

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬────────────────────┬─────────────────────────────────────┤
│ SIDEBAR  │ FORM PARAMETRI     │  RISULTATI                          │
│          │ sticky top-12      │                                     │
│          │ w-72               │  ┌───────────────────────────────┐  │
│          │                    │  │ TABS: [Equity] [OOS] [W-Fwd]  │  │
│          │ Pattern            │  └───────────────────────────────┘  │
│          │ [__________]       │                                     │
│          │                    │  ── TAB: EQUITY CURVE ─────────────  │
│          │ Timeframe          │  ┌───────────────────────────────┐  │
│          │ [1h ▼]             │  │                               │  │
│          │                    │  │  GRAFICO EQUITY (Recharts)    │  │
│          │ Data inizio        │  │  Linea cumulativa P&L         │  │
│          │ [2025-01-01]       │  │  h-[400px]                    │  │
│          │                    │  │                               │  │
│          │ Data fine          │  └───────────────────────────────┘  │
│          │ [2026-04-01]       │                                     │
│          │                    │  Metriche: Total R, WR%, MaxDD,     │
│          │ Capitale €         │  Sharpe, N trades                   │
│          │ [10000_____]       │                                     │
│          │                    │  ── TAB: OOS ──────────────────────  │
│          │ [▶ Esegui sim.]    │  [form OOS + grafico]               │
│          │ [▶ Valida OOS]     │                                     │
│          │ [▶ Walk-Forward]   │  ── TAB: WALK-FORWARD ─────────────  │
│          │                    │  [ProgressBar se in corso]          │
│          │ Walk-Forward:      │  [tabella window results]           │
│          │ ████████░░ 78%     │                                     │
│          │ (solo se in corso) │                                     │
└──────────┴────────────────────┴─────────────────────────────────────┘
```

### Walk-Forward — progress state (120s max)

```
┌──────────────────────────────────────────────────────────┐
│  🔄 Walk-Forward in corso...                             │
│  ████████████░░░░░░░░░░░░░░░░ 45%  · 54s trascorsi     │
│                                                          │
│  (auto-update ogni 2s)                                   │
│  [Annulla]                                               │
└──────────────────────────────────────────────────────────┘
```

> **Nota implementativa:** il backend non espone SSE/websocket per il progresso.
> Soluzione: mostare progress bar "indeterminata" con timer locale (incremento costante) fino a risposta.

---

## G) `/diagnostica` — KPI Allineamento

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR  │  ── KPI ROW ─────────────────────────────────────────── │
│          │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│          │  │ Pattern  │ │ Signal   │ │ Allinea- │ │ Coverage │   │
│          │  │ totali   │ │ oggi     │ │ mento %  │ │ universo │   │
│          │  │  342     │ │  3       │ │  68%     │ │  89%     │   │
│          │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│          │                                                           │
│          │  ── BEST / WORST PER TIMEFRAME ─────────────────────── │
│          │  ┌─────────────────────────────┐                        │
│          │  │ 1h — Best: Engulfing 64.2%  │                        │
│          │  │     Worst: Doji       48.1% │                        │
│          │  │ 5m — Best: Hammer     61.8% │                        │
│          │  │     Worst: Harami     43.2% │                        │
│          │  └─────────────────────────────┘                        │
│          │                                                           │
│          │  ── TOP OPPORTUNITÀ LIVE ────────────────────────────── │
│          │  ┌──────────────────────────────────────────────────┐   │
│          │  │ # │ Simbolo │ TF │ Score │ Pattern    │ Decisione│   │
│          │  │ 1 │ AAPL    │ 1h │  82%  │ Engulfing  │ ✅ Esegui│   │
│          │  │ 2 │ TSLA    │ 5m │  74%  │ Hammer     │ ✅ Esegui│   │
│          │  │ 3 │ BTC     │ 1h │  69%  │ Breakout   │ 👁 Monitor│  │
│          │  └──────────────────────────────────────────────────┘   │
│          │  → Click riga: naviga a /opportunities/[sym]/[tf]        │
└──────────┴───────────────────────────────────────────────────────────┘
```

### Stati

| Stato | Visualizzazione |
|-------|----------------|
| **Loading** | Skeleton KPI row + skeleton tabella |
| **Fetch parziale** | Sezioni che hanno dati mostrano dati; sezioni in errore mostrano badge "⚠ N/D" |
| **Nessuna opportunità** | EmptyState nella sezione "Top opportunità" |

---

## H) `/trade-plan-lab` — Lab Varianti

### Layout desktop

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                               │
├──────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR  │  ── TOOLBAR ─────────────────────────────────────────── │
│          │  [Bucket ▼] [Status ▼] [TF ▼] [Applica]                 │
│          │  Promoted: 8  Watchlist: 23  Rejected: 41               │
│          │  ─────────────────────────────────────────────────────── │
│          │  ┌──────────────────────────────────────────────────────┐│
│          │  │ TABELLA varianti (sortable, TanStack Table)          ││
│          │  │                                                      ││
│          │  │ Bucket  Pattern  TF  Dir  WR%  AvgR  Status  TP/SL  ││
│          │  │ ──────  ───────  ──  ───  ───  ────  ──────  ─────  ││
│          │  │ A       Engulf   1h  Bull 64%  1.3   ✅ Promo  ...  ││
│          │  │ B       Hammer   1h  Bull 62%  1.2   👁 Watch  ...  ││
│          │  └──────────────────────────────────────────────────────┘│
└──────────┴───────────────────────────────────────────────────────────┘
```

Struttura invariata rispetto all'attuale, ma con:
- Nuovo design system (colori, font, radius)
- Toolbar come sticky header
- Badge status colorati (promoted=bull, watchlist=neutral, rejected=bear)
- shadcn Table per le righe

---

## Inventario componenti da costruire (ordine Fase 3)

### 1 — Design shell (step 1)

```
AppShell          layout wrapper (sidebar + topbar + main slot)
Sidebar           nav collapsabile, status widgets
Topbar            regime + clock + settings
MobileDrawer      sheet overlay mobile
```

### 2 — Primitivi atomici (step 2)

```
Button            primary / secondary / ghost / danger
Badge             inline / pill con varianti bull/bear/neutral/warn
KPICard           label + value + delta + sparkline opzionale
PriceDisplay      numero tabular-nums, colore automatico dal segno
RegimeIndicator   badge SPY con tooltip dettagli
IBKRStatusPill    unificato hook useIBKRStatus
PipelineStatusPill
MarketClock       apertura/chiusura mercato
CountdownRefresh  aria-live
LoadingSkeleton   varianti: card | table | chart
EmptyState        illustrazione + messaggio + CTA
ErrorBoundary     per-route con retry
```

### 3 — Componenti composti (step 3–5)

```
SignalCard        refactor dell'esistente con nuovo DS
SignalCardCompact mini-card per home dashboard
DiscardedCard     refactor con nuovo DS
OpportunitySummaryBar  resuscitata e riprogettata
CandleChart       wrapper Lightweight Charts
EquityChart       wrapper Recharts
VirtualizedTable  TanStack Table + Virtual
```

### 4 — Hook (step 3)

```
useIBKRStatus     unifica useIBKRHealth + fetchIbkrStatus
useOpportunities  TanStack Query, poll 60s
useMarketClock    stato mercato + countdown
```

---

## Note implementative Fase 3

1. **Rimuovere `.trader-dashboard` scope** da `trader-theme.css` dopo che `globals.css` è attivo
2. **`OpportunitySummaryBar`** da eliminare (dead code) e sostituire con la versione rifatta nel header
3. **`runSimulation` alias** in `api.ts` da rimuovere (usa solo `fetchBacktestSimulation`)
4. **Ordine commit** suggerito:
   - `feat(shell): add AppShell, Sidebar, Topbar, MobileDrawer`
   - `feat(atoms): add design-system primitive components`
   - `feat(home): add home dashboard with KPI cards`
   - `feat(opportunities): refactor god component + panel preferences`
   - `feat(chart): add CandleChart with lightweight-charts`
   - `feat(detail): update series detail page`
   - `feat(backtest): add virtualized table`
   - `feat(simulation): add progress bar + tabs`
   - `feat(diagnostica): update to full KPI dashboard`
   - `chore: remove dead code (OpportunitySummaryBar, runSimulation alias)`
