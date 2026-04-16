"use client";

import { Suspense, useMemo } from "react";

import { useExecutedSignals } from "@/hooks/useExecutedSignals";
import { useIBKRStatus } from "@/hooks/useIBKRStatus";
import { useOpportunities } from "@/hooks/useOpportunities";
import { useOpportunityFilters } from "@/hooks/useOpportunityFilters";
import { useOpportunityPreferences } from "@/hooks/useOpportunityPreferences";
import { usePipelineControl } from "@/hooks/usePipelineControl";

import { DiscardedSection } from "./components/DiscardedSection";
import { ExecutedSignalsSection } from "./components/ExecutedSignalsSection";
import { FilterPills } from "./components/FilterPills";
import { OpportunitiesHeader } from "./components/OpportunitiesHeader";
import { OpportunitiesStateBlocks } from "./components/OpportunitiesStateBlocks";
import { PipelineMaintenanceDialog } from "./components/PipelineMaintenanceDialog";
import { PreferencesPanel } from "./components/PreferencesPanel";
import { SignalList } from "./components/SignalList";
import { pickRegimeSpy } from "./utils";

function OpportunitiesPageInner() {
  const opps = useOpportunities();
  const executed = useExecutedSignals(50);
  const prefs = useOpportunityPreferences();
  const pipeline = usePipelineControl();
  const ibkr = useIBKRStatus();

  const rows = opps.rows;
  const filters = useOpportunityFilters({ rows, isLoading: opps.isLoading });
  const regime = useMemo(() => pickRegimeSpy(rows), [rows]);

  return (
    <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-4 px-4 pb-10 pt-4 sm:px-6">
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
      />

      <PreferencesPanel
        sizing={prefs.sizingInput}
        onSizingChange={prefs.persistSizing}
        broker={prefs.broker}
        onBrokerChange={prefs.persistBroker}
      />

      <FilterPills
        decisionFilter={filters.decisionFilter}
        setDecisionFilter={filters.setDecisionFilter}
        tfFilter={filters.tfFilter}
        setTfFilter={filters.setTfFilter}
        dirFilter={filters.dirFilter}
        setDirFilter={filters.setDirFilter}
        sortBy={filters.sortBy}
        setSortBy={filters.setSortBy}
      />

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

      <PipelineMaintenanceDialog pipeline={pipeline} />
    </div>
  );
}

export default function OpportunitiesPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-4 px-4 pb-10 pt-4 sm:px-6">
          <div className="rounded-xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]" role="status">
            Caricamento opportunità…
          </div>
        </div>
      }
    >
      <OpportunitiesPageInner />
    </Suspense>
  );
}
