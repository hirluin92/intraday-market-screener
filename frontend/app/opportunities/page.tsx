"use client";

import { Suspense, useMemo, useState } from "react";

import { useExecutedSignals } from "@/hooks/useExecutedSignals";
import { useIBKRStatus } from "@/hooks/useIBKRStatus";
import { useOpportunities } from "@/hooks/useOpportunities";
import { useOpportunityFilters } from "@/hooks/useOpportunityFilters";
import { useOpportunityPreferences } from "@/hooks/useOpportunityPreferences";
import { usePipelineControl } from "@/hooks/usePipelineControl";

import { DiscardedSection } from "./components/DiscardedSection";
import { ExecutedSignalsSection } from "./components/ExecutedSignalsSection";
import { OpportunitiesHeader } from "./components/OpportunitiesHeader";
import { OpportunitiesStateBlocks } from "./components/OpportunitiesStateBlocks";
import { PipelineMaintenanceDialog } from "./components/PipelineMaintenanceDialog";
import { PreferencesPanel } from "./components/PreferencesPanel";
import { SignalList } from "./components/SignalList";
import { pickRegimeSpy } from "./utils";

function OpportunitiesPageInner() {
  const opps = useOpportunities();
  const executed = useExecutedSignals(100);
  const prefs = useOpportunityPreferences();
  const pipeline = usePipelineControl();
  const ibkr = useIBKRStatus();
  const [prefsSheetOpen, setPrefsSheetOpen] = useState(false);

  const rows = opps.rows;
  const filters = useOpportunityFilters({ rows, isLoading: opps.isLoading });
  const regime = useMemo(() => pickRegimeSpy(rows), [rows]);

  return (
    <div className="flex min-h-full flex-col">
      {/* ── Sticky header ───────────────────────────────────────────── */}
      <OpportunitiesHeader
        ibkr={ibkr}
        regime={regime}
        isLoading={opps.isLoading}
        isFetching={opps.isFetching}
        autoRefresh={opps.autoRefresh}
        onAutoRefreshChange={opps.setAutoRefresh}
        secondsToRefresh={opps.secondsToRefresh}
        lastUpdate={opps.lastUpdate}
        onRefresh={opps.refetch}
        totalExecute={filters.totalExecute}
        timeLabelReady={opps.timeLabelReady}
        onPipelineOpen={pipeline.openDialog}
        onPreferencesOpen={() => setPrefsSheetOpen(true)}
        counts={filters.counts}
        decisionFilter={filters.decisionFilter}
        setDecisionFilter={filters.setDecisionFilter}
        tfFilter={filters.tfFilter}
        setTfFilter={filters.setTfFilter}
        dirFilter={filters.dirFilter}
        setDirFilter={filters.setDirFilter}
        sortBy={filters.sortBy}
        setSortBy={filters.setSortBy}
      />

      {/* ── Content + sidebar grid ──────────────────────────────────── */}
      <div className="mx-auto flex w-full max-w-[1440px] flex-1 items-start gap-6 px-4 pb-12 pt-4 sm:px-6">
        {/* Main content */}
        <div className="min-w-0 flex-1 space-y-5">
          <OpportunitiesStateBlocks
            isLoading={opps.isLoading}
            error={opps.error}
            hasRows={rows.length > 0}
            emptyExecute={filters.emptyExecute}
            autoRefresh={opps.autoRefresh}
            secondsToRefresh={opps.secondsToRefresh}
          />
          <ExecutedSignalsSection
            signals={executed.data?.signals ?? []}
            expanded={filters.signalsExpanded}
            onToggleExpanded={() => filters.setSignalsExpanded((v) => !v)}
            statusFilter={filters.signalsStatusFilter}
            onStatusFilterChange={filters.setSignalsStatusFilter}
          />
          <SignalList
            executeRows={filters.sorted.execute}
            monitorRows={filters.sorted.monitor}
            showExecuteBlock={filters.showExecuteBlock}
            showMonitorBlock={filters.showMonitorBlock}
            sizingInput={prefs.sizingInput}
            broker={prefs.broker}
            onBrokerChange={prefs.persistBroker}
            expandedCardId={filters.expandedCardId}
            onExpandedChange={filters.setExpandedCardId}
          />
          <DiscardedSection
            rows={filters.sorted.discard}
            showDiscardBlock={filters.showDiscardBlock}
            showDiscarded={filters.showDiscarded}
            onToggle={filters.toggleShowDiscarded}
          />
        </div>

        {/* ── Sticky sidebar dx — visibile solo ≥xl ─────────────────── */}
        <aside className="hidden w-80 shrink-0 xl:block">
          <div className="sticky top-[calc(theme(spacing.12)+1px)] max-h-[calc(100vh-4rem)] overflow-y-auto">
            <PreferencesPanel
              sizing={prefs.sizingInput}
              onSizingChange={prefs.persistSizing}
              broker={prefs.broker}
              onBrokerChange={prefs.persistBroker}
              sheetOpen={false}
              onSheetClose={() => {}}
              mode="sidebar"
            />
          </div>
        </aside>
      </div>

      {/* ── Sheet Preferences per <xl ───────────────────────────────── */}
      <PreferencesPanel
        sizing={prefs.sizingInput}
        onSizingChange={prefs.persistSizing}
        broker={prefs.broker}
        onBrokerChange={prefs.persistBroker}
        sheetOpen={prefsSheetOpen}
        onSheetClose={() => setPrefsSheetOpen(false)}
        mode="sheet"
      />

      <PipelineMaintenanceDialog pipeline={pipeline} />
    </div>
  );
}

export default function OpportunitiesPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-full flex-col">
          <div className="sticky top-0 z-20 h-12 border-b border-line bg-canvas/95 backdrop-blur-md" />
          <div className="mx-auto w-full max-w-[1440px] px-4 py-4 sm:px-6">
            <div className="h-32 animate-pulse rounded-xl bg-surface" />
          </div>
        </div>
      }
    >
      <OpportunitiesPageInner />
    </Suspense>
  );
}
