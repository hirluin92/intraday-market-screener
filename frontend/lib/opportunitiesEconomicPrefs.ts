import type { EconomicListFilterMode } from "./opportunityEconomicSnapshot";

export type OpportunitiesEconomicPrefs = {
  filterMode: EconomicListFilterMode;
  /** Se true, ordina prima per convenienza economica poi per score tecnico. */
  economicRankingEnabled: boolean;
};

const STORAGE_KEY = "opportunitiesEconomicPrefsV1";

const DEFAULT: OpportunitiesEconomicPrefs = {
  filterMode: "all",
  economicRankingEnabled: false,
};

export function loadOpportunitiesEconomicPrefs(): OpportunitiesEconomicPrefs {
  if (typeof window === "undefined") return DEFAULT;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT;
    const p = JSON.parse(raw) as Partial<OpportunitiesEconomicPrefs>;
    const filterMode =
      p.filterMode === "good_only" || p.filterMode === "good_or_marginal" || p.filterMode === "all"
        ? p.filterMode
        : DEFAULT.filterMode;
    return {
      filterMode,
      economicRankingEnabled:
        typeof p.economicRankingEnabled === "boolean"
          ? p.economicRankingEnabled
          : DEFAULT.economicRankingEnabled,
    };
  } catch {
    return DEFAULT;
  }
}

export function saveOpportunitiesEconomicPrefs(p: OpportunitiesEconomicPrefs): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}
