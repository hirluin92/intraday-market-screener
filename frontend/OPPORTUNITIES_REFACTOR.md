# Opportunities Page — Refactor Map

> Step 3A: estrazione hook + split componenti, ZERO cambi visivi.  
> Step 3B: redesign visivo + sticky preferences sidebar (step successivo).

---

## Inventario `useState` — prima/dopo

| # | State | Tipo | Chi legge | Chi scrive | → Destinazione |
|---|-------|------|-----------|------------|----------------|
| 1 | `rows` | `OpportunityRow[]` | tutta la page | `load()` | `useOpportunities` (TQ data) |
| 2 | `executedSignals` | `ExecutedSignalRow[]` | ExecutedSignalsSection | `load()` | `useExecutedSignals` (TQ data) |
| 3 | `signalsExpanded` | `boolean` | ExecutedSignalsSection | toggle button | `useOpportunityFilters` |
| 4 | `signalsStatusFilter` | `'all'|'open'|'skipped'|'cancelled'` | ExecutedSignalsSection | select | `useOpportunityFilters` |
| 5 | `loading` | `boolean` | rendering guards | `load()` | `useOpportunities` (isLoading) |
| 6 | `error` | `string\|null` | error block | `load()` | `useOpportunities` (error) |
| 7 | `decisionFilter` | `DecisionFilter` | applyClientFilters | FilterPills | `useOpportunityFilters` |
| 8 | `tfFilter` | `TfFilter` | applyClientFilters | FilterPills | `useOpportunityFilters` |
| 9 | `dirFilter` | `DirFilter` | applyClientFilters | FilterPills | `useOpportunityFilters` |
| 10 | `sortBy` | `OpportunitySortBy` | sort functions | select dropdown | `useOpportunityFilters` |
| 11 | `expandedCardId` | `string\|null` | SignalCard | set/clear on filter change, deep link | `useOpportunityFilters` |
| 12 | `showDiscarded` | `boolean` | DiscardedSection | toggle button | `useOpportunityFilters` |
| 13 | `skipFilterClearRef` | `Ref<boolean>` | filter-clear guard | deep link handler | `useOpportunityFilters` (internal) |
| 14 | `deepLinkHandled` | `boolean` | deep link guard | deep link effect | `useOpportunityFilters` (internal) |
| 15 | `sizingInput` | `PositionSizingUserInput` | SignalCard, SignalList | OpportunityPreferencesBar | `useOpportunityPreferences` |
| 16 | `broker` | `TraderBrokerId` | SignalCard | OpportunityPreferencesBar | `useOpportunityPreferences` |
| 17 | `lastUpdate` | `Date\|null` | countdown, header timestamp | `load()` | `useOpportunities` (dataUpdatedAt) |
| 18 | `ibkrStatus` | `IbkrStatus\|null` | header IBKR pill | `load()` | `useIBKRStatus` (già esistente) |
| 19 | `ibkrFetchFailed` | `boolean` | header warn pill | `load()` | `useIBKRStatus` (error !== null) |
| 20 | `autoRefresh` | `boolean` | auto-poll control | checkbox | `useOpportunities` (refetchInterval config) |
| 21 | `timeLabelReady` | `boolean` | hydration guard | mount effect | `useOpportunities` (mounted guard) |
| 22 | `secondsToRefresh` | `number` | countdown UI | 1s interval | `useOpportunities` (derived from dataUpdatedAt) |
| 23 | `pipeProvider` | `string` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 24 | `pipeExchangeOverride` | `string` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 25 | `pipeSymbol` | `string` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 26 | `pipeTimeframe` | `string` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 27 | `pipeIngestLimit` | `number` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 28 | `pipeExtractLimit` | `number` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 29 | `pipeLookback` | `number` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 30 | `pipeLoading` | `boolean` | pipeline form | PipelineMaintenanceDialog | `usePipelineControl` |
| 31 | `pipeMessage` | `string\|null` | pipeline feedback | PipelineMaintenanceDialog | `usePipelineControl` |
| 32 | `pipeError` | `string\|null` | pipeline feedback | PipelineMaintenanceDialog | `usePipelineControl` |

**Riduzione**: da 32 useState nel god component a:
- 0 useState in `page.tsx` (solo hook calls)
- `useOpportunities`: 2 interni (autoRefresh, timeLabelReady) + secondsToRefresh derivato
- `useOpportunityFilters`: 9 interni (decision, tf, dir, sort, expanded, showDiscarded, signalsExpanded, signalsStatusFilter, deepLinkHandled) + skipFilterClearRef
- `useOpportunityPreferences`: 0 (solo localStorage I/O via existing lib)
- `usePipelineControl`: 7 interni (form fields + loading/message/error)

---

## Inventario `useEffect`

| # | Trigger | Scopo | Cleanup | → Destinazione |
|---|---------|-------|---------|----------------|
| 1 | mount | load preferences from localStorage | — | `useOpportunityPreferences` (mount effect) |
| 2 | `[decisionFilter, tfFilter, dirFilter]` | clear expandedCardId (con guard ref) | — | `useOpportunityFilters` (interna) |
| 3 | deep link params + rows | scroll+highlight card via deep link | clear 3 timeouts | `useOpportunityFilters` (interna) |
| 4 | mount | initial load | — | `useOpportunities` (TanStack Query auto) |
| 5 | `[autoRefresh, load]` | auto-refresh interval | clearInterval | `useOpportunities` (TanStack Query refetchInterval) |
| 6 | `[lastUpdate]` | countdown timer (1s) | clearInterval | `useOpportunities` (interna) |

---

## Inventario funzioni inline → destinazione

| Funzione | Scopo | → Destinazione |
|---------|-------|----------------|
| `pickRegimeSpy(rows)` | estrae regime da rows | `app/opportunities/utils.ts` (utility file) |
| `pillClass(active, accent)` | CSS class pill filter | `app/opportunities/components/FilterPills.tsx` (locale) |
| `applyClientFilters(rows, ...)` | filtra rows lato client | già in `/lib` → usata da `useOpportunityFilters` |
| `load()` | fetch all (opportunities + IBKR + executed) | smembrata: `useOpportunities` + `useIBKRStatus` + `useExecutedSignals` |
| `persistSizing(s)` | save sizing to localStorage | `useOpportunityPreferences.persistSizing` |
| `persistBroker(b)` | save broker to localStorage | `useOpportunityPreferences.persistBroker` |
| `runPipelineRefresh()` | POST pipeline + show message | `usePipelineControl.refresh()` |

---

## Inventario sezioni JSX → componenti

| Sezione | Righe originali (approx) | → Componente |
|---------|--------------------------|--------------|
| Header sticky | 95–490 (partial) | `OpportunitiesHeader.tsx` |
| OpportunityPreferencesBar | 492–497 | `PreferencesPanel.tsx` (wrapper) |
| Filtri pill | 499–553 | `FilterPills.tsx` |
| Loading state | 556–563 | inline in `page.tsx` (3 righe) |
| Error state | 565–575 | inline in `page.tsx` (5 righe) |
| Empty (no rows) | 577–581 | inline in `page.tsx` (4 righe) |
| Empty execute state | 583–603 | inline in `page.tsx` (5 righe) |
| Executed signals section | 605–738 | `ExecutedSignalsSection.tsx` |
| Execute + Monitor grids | 741–810 | `SignalList.tsx` |
| Discarded section | 789–810 | `DiscardedSection.tsx` |
| Pipeline maintenance | 812–903 | `PipelineMaintenanceDialog.tsx` |

---

## Pre-existing bugs (da documentare, NON fixare in 3A)

1. **`autoRefresh` non persiste**: al reload la checkbox torna `true` (default). Non è in localStorage. Fix in 3B.
2. **IBKR status duplicato**: il page.tsx chiama `fetchIbkrStatus()` dentro `load()` (ogni 60s) + il layout chiama `useIBKRStatus` (ogni 30s). Step 3A risolve questo usando solo `useIBKRStatus`.
3. **`timeLabelReady` guard**: workaround per hydration mismatch su timestamp. In 3A si usa `suppressHydrationWarning` direttamente.
4. **`sortBy` non persiste**: al reload torna "default". Fix in 3B con localStorage.
5. **Deep link + discard**: se un segnale è in "discard", `showDiscarded` viene impostato ma il card non viene espanso. Comportamento corretto ma non documentato — lasciare invariato.

---

## Schema architettura post-3A

```
app/opportunities/page.tsx          (~80 righe — solo composizione)
├── hooks/useOpportunities.ts        (TanStack Query + countdown + autoRefresh)
├── hooks/useExecutedSignals.ts      (TanStack Query)
├── hooks/useOpportunityFilters.ts   (tutti i filtri + deep link)
├── hooks/useOpportunityPreferences.ts (sizing + broker → localStorage)
├── hooks/usePipelineControl.ts      (form + POST + feedback)
└── app/opportunities/
    ├── utils.ts                     (pickRegimeSpy, helpers)
    └── components/
        ├── OpportunitiesHeader.tsx  (header sticky, INVARIATO visivamente)
        ├── OpportunitiesSummaryBar.tsx (counts bar — nuovo ma inline nel header)
        ├── FilterPills.tsx          (pill buttons — INVARIATO visivamente)
        ├── ExecutedSignalsSection.tsx (tabella segnali — INVARIATO)
        ├── SignalList.tsx            (grids execute + monitor — INVARIATO)
        ├── DiscardedSection.tsx      (collapsible — INVARIATO)
        ├── PreferencesPanel.tsx      (wrapper OpportunityPreferencesBar — INVARIATO)
        └── PipelineMaintenanceDialog.tsx (Dialog wrapper — piccolo cambio visivo)
        
        [esistenti, NON toccare]
        ├── SignalCard.tsx
        ├── DiscardedCard.tsx
        ├── RegimeBadge.tsx
        └── TradeInstructions.tsx
```
