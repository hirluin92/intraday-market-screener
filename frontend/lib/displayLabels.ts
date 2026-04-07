/**
 * Mappature solo per la UI: i valori API restano in inglese (enum/string).
 * Chiavi in minuscolo per confronto case-insensitive.
 */
export const DISPLAY_ENUM_LABELS: Record<string, string> = {
  trend: "trend",
  range: "laterale",
  bullish: "rialzista",
  bearish: "ribassista",
  neutral: "neutrale",
  compression: "compressione",
  expansion: "espansione",
  high: "alta",
  normal: "normale",
  low: "bassa",
};

export function displayEnumLabel(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const key = value.toLowerCase().trim();
  return DISPLAY_ENUM_LABELS[key] ?? value;
}

/** Etichetta per le option timeframe nei filtri (valore API invariato). */
export function timeframeFilterLabel(tf: string): string {
  return tf || "Tutti";
}

/** Bande pattern_quality_label dall'API (high | medium | low | unknown | insufficient). */
const PATTERN_QUALITY_LABEL_IT: Record<string, string> = {
  high: "alta",
  medium: "media",
  low: "bassa",
  unknown: "sconosciuta",
  insufficient: "insufficiente",
};

export function displayPatternQualityLabel(v: string): string {
  return PATTERN_QUALITY_LABEL_IT[v] ?? v;
}

/** Bande final_opportunity_label dall’API (strong | moderate | weak | minimal). */
const FINAL_OPPORTUNITY_LABEL_IT: Record<string, string> = {
  strong: "eccellente",
  moderate: "buono",
  weak: "debole",
  minimal: "minimo",
};

export function displayFinalOpportunityLabel(v: string): string {
  return FINAL_OPPORTUNITY_LABEL_IT[v] ?? v;
}

/** Esito policy pattern+timeframe (na | ok | marginal | poor | unknown). */
const PATTERN_TF_GATE_LABEL_IT: Record<string, string> = {
  na: "non applicabile",
  ok: "accettabile sul TF",
  marginal: "debole sul TF",
  poor: "insufficiente sul TF",
  unknown: "storico non disponibile",
};

export function displayPatternTimeframeGateLabel(v: string): string {
  return PATTERN_TF_GATE_LABEL_IT[v] ?? v;
}

/** Livello alert opportunità (chiavi API v1). */
const ALERT_LEVEL_IT: Record<string, string> = {
  alta_priorita: "Alta priorità",
  media_priorita: "Media priorità",
  nessun_alert: "Nessun alert",
};

export function displayAlertLevelLabel(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  return ALERT_LEVEL_IT[v] ?? v;
}

export function alertLevelBadgeClass(level: string): string {
  switch (level) {
    case "alta_priorita":
      return "bg-rose-100 text-rose-900 dark:bg-rose-950/60 dark:text-rose-100";
    case "media_priorita":
      return "bg-amber-100 text-amber-950 dark:bg-amber-950/50 dark:text-amber-100";
    case "nessun_alert":
    default:
      return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  }
}

/** Etichette score / pattern snake_case dall’API (solo UI). */
const TECHNICAL_LABELS_IT: Record<string, string> = {
  strong_bearish: "forte ribassista",
  strong_bullish: "forte rialzista",
  moderate_bullish: "moderato rialzista",
  moderate_bearish: "moderato ribassista",
  impulsive_bullish_candle: "candela impulsiva rialzista",
  impulsive_bearish_candle: "candela impulsiva ribassista",
  compression_to_expansion_transition: "transizione compressione → espansione",
  range_expansion_breakout_candidate: "possibile breakout da espansione",
};

/**
 * Mappa etichette tecniche note (score_label, pattern_name, …); altrimenti restituisce il valore grezzo.
 */
export function displayTechnicalLabel(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const exact = TECHNICAL_LABELS_IT[value];
  if (exact != null) return exact;
  return value;
}

/** Coerenza tra direzione score e direzione ultimo pattern (solo UI). */
export type SignalAlignment = "aligned" | "mixed" | "conflicting";

const SIGNAL_ALIGNMENT_IT: Record<SignalAlignment, string> = {
  aligned: "allineato",
  mixed: "misto",
  conflicting: "conflittuale",
};

function normDirection(s: string | null | undefined): string | null {
  if (s == null || String(s).trim() === "") return null;
  return String(s).toLowerCase().trim();
}

/** Tooltip intestazioni tabella opportunità (italiano). */
export const TOOLTIP_DIR_SCORE_IT =
  "Interpretazione direzionale del contesto live dello screener (score del titolo). Corrisponde al campo score_direction dell’API.";

export const TOOLTIP_DIR_PATTERN_IT =
  "Direzione implicita dall’ultimo pattern rilevato sulla serie. Corrisponde al campo latest_pattern_direction dell’API.";

export const TOOLTIP_ALLINEAMENTO_SEGNALE_IT =
  "Allineamento tra direzione score e direzione pattern: allineato se coincidono; misto se manca un dato o un lato è neutrale; conflittuale se entrambi sono direzionali ma in disaccordo (es. rialzista vs ribassista).";

/**
 * - allineato: score_direction e latest_pattern_direction uguali (non neutri)
 * - misto: uno assente o neutrale
 * - conflittuale: entrambi direzionali e discordi
 */
export function computeSignalAlignment(
  scoreDirection: string,
  patternDirection: string | null | undefined,
): SignalAlignment {
  const sd = normDirection(scoreDirection);
  const pd = normDirection(patternDirection);
  if (sd == null || pd == null) return "mixed";
  if (sd === "neutral" || pd === "neutral") return "mixed";
  if (sd === pd) return "aligned";
  return "conflicting";
}

export function displaySignalAlignmentLabel(a: SignalAlignment): string {
  return SIGNAL_ALIGNMENT_IT[a];
}

export function signalAlignmentBadgeClass(a: SignalAlignment): string {
  switch (a) {
    case "aligned":
      return "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-300";
    case "mixed":
      return "bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-300";
    case "conflicting":
      return "bg-red-100 text-red-900 dark:bg-red-950/60 dark:text-red-300";
    default:
      return "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200";
  }
}

/** Tooltip legenda colonna «Fonte piano» (lista opportunità). */
export const FONTE_PIANO_LEGENDA = {
  promossa:
    "Promossa: usa la best variant validata dal backtest varianti (livelli da entry/stop/TP storici).",
  watchlist:
    "Watchlist: usa la variante con affidabilità media (campione ≥ soglia watchlist live).",
  fallback:
    "Fallback standard: nessuna variante affidabile per le regole live; motore base v1.",
} as const;

export function fontePianoListLabel(r: {
  trade_plan_source?: string;
  selected_trade_plan_variant_status?: string | null;
}): string {
  if ((r.trade_plan_source ?? "default_fallback") === "variant_backtest") {
    if (r.selected_trade_plan_variant_status === "promoted") return "Promossa";
    if (r.selected_trade_plan_variant_status === "watchlist") return "Watchlist";
  }
  return "Fallback standard";
}

export function fontePianoListTitle(r: {
  trade_plan_source?: string;
  selected_trade_plan_variant_status?: string | null;
}): string {
  if ((r.trade_plan_source ?? "default_fallback") === "variant_backtest") {
    if (r.selected_trade_plan_variant_status === "promoted") return FONTE_PIANO_LEGENDA.promossa;
    if (r.selected_trade_plan_variant_status === "watchlist") return FONTE_PIANO_LEGENDA.watchlist;
  }
  return FONTE_PIANO_LEGENDA.fallback;
}

export function tradePlanFallbackReasonIt(code: string | null | undefined): string {
  if (!code) return "";
  switch (code) {
    case "no_pattern":
      return "Nessun pattern sul timeframe: motore standard senza bucket variant.";
    case "no_variant_bucket":
      return "Nessuna variante trovata per questo bucket (dati backtest varianti assenti o filtri).";
    case "variant_rejected":
      return "Variante respinta (sample o expectancy non sufficienti per stato promosso/watchlist).";
    case "watchlist_insufficient_sample":
      return "Watchlist con campione sotto la soglia minima per uso live (≥30).";
    default:
      return code;
  }
}

/** Codice API: execute | monitor | discard (operable legacy) */
export type OperationalDecisionCode = "execute" | "monitor" | "discard";

export function displayOperationalDecisionListLabel(
  code: string | null | undefined,
): string {
  switch (code) {
    case "execute":
    case "operable":
      return "Esegui";
    case "monitor":
      return "Da monitorare";
    case "discard":
      return "Scartare";
    default:
      return "—";
  }
}

/** Badge dettaglio grande (maiuscolo). */
export function displayOperationalDecisionBadgeShort(
  code: string | null | undefined,
): string {
  switch (code) {
    case "execute":
    case "operable":
      return "ESEGUI";
    case "monitor":
      return "MONITORA";
    case "discard":
      return "SCARTA";
    default:
      return "—";
  }
}

export function operationalDecisionBadgeClass(code: string | null | undefined): string {
  switch (code) {
    case "execute":
    case "operable":
      return "bg-emerald-600 text-white shadow-md shadow-emerald-900/20 dark:bg-emerald-700";
    case "monitor":
      return "bg-amber-500 text-amber-950 shadow-md shadow-amber-900/15 dark:bg-amber-600 dark:text-amber-50";
    case "discard":
      return "bg-zinc-500 text-white shadow-md dark:bg-zinc-600";
    default:
      return "bg-zinc-400 text-zinc-950";
  }
}

export function operationalDecisionListCellClass(code: string | null | undefined): string {
  switch (code) {
    case "execute":
    case "operable":
      return "font-medium text-emerald-800 dark:text-emerald-300";
    case "monitor":
      return "text-amber-800 dark:text-amber-300";
    case "discard":
      return "font-medium text-zinc-500 dark:text-zinc-500";
    default:
      return "text-zinc-600 dark:text-zinc-400";
  }
}

/** Badge pill per colonna Decisione in tabella lista (più leggibile della sola tinta testo). */
export function operationalDecisionBadgePillClass(code: string | null | undefined): string {
  switch (code) {
    case "execute":
    case "operable":
      return "bg-emerald-100 text-emerald-900 ring-1 ring-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-200 dark:ring-emerald-800";
    case "monitor":
      return "bg-amber-100 text-amber-900 ring-1 ring-amber-300 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-800";
    case "discard":
      return "bg-zinc-200 text-zinc-700 ring-1 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700";
    default:
      return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  }
}

/** Prima riga (o prime due) di decision_rationale per attributo title / tooltip in lista. */
export function decisionRationaleTitleAttr(r: {
  operational_decision?: string;
  decision_rationale?: string[];
}): string {
  const lines = r.decision_rationale ?? [];
  if (lines.length > 0) return lines.slice(0, 2).join(" · ");
  return displayOperationalDecisionListLabel(r.operational_decision);
}

const PATTERN_STALE_TOOLTIP =
  "Ritardo in barre rispetto all’ultimo contesto sullo stesso timeframe. " +
  "Soglie tipiche (backend): 1m→10, 5m→8, 15m→5, 1h→3, 1d→2 barre; modificabili in pattern_staleness.py. " +
  "Se datato, il semaforo non resta «Operabile» anche con promossa + alert.";

/** Riga dettaglio: «N barre / soglia T» (TF mostrato a parte nella serie). */
export function displayPatternAgeVsThresholdLine(r: {
  pattern_age_bars?: number | null;
  pattern_stale_threshold_bars?: number;
  latest_pattern_name?: string | null;
}): string {
  if (r.latest_pattern_name == null || String(r.latest_pattern_name).trim() === "") {
    return "";
  }
  const th = r.pattern_stale_threshold_bars ?? 5;
  const n = r.pattern_age_bars;
  if (n == null) return `— / soglia ${th}`;
  return `${n} barre / soglia ${th}`;
}

/** Tooltip colonna lista Età pat.: età, soglia TF, esito recente/datato. */
export function patternAgeListTooltip(r: {
  timeframe?: string;
  pattern_age_bars?: number | null;
  pattern_stale?: boolean;
  pattern_stale_threshold_bars?: number;
  latest_pattern_name?: string | null;
}): string {
  const tf = r.timeframe ?? "—";
  const th = r.pattern_stale_threshold_bars ?? 5;
  if (r.latest_pattern_name == null || String(r.latest_pattern_name).trim() === "") {
    return "Nessun pattern rilevato.";
  }
  const n = r.pattern_age_bars;
  if (n == null) {
    return `Età: non calcolabile · Soglia TF ${tf}: ${th} barre · Esito: —`;
  }
  const esito = r.pattern_stale
    ? "datato (oltre soglia)"
    : "recente (entro soglia)";
  return `Età: ${n} barre · Soglia TF ${tf}: ${th} barre · Esito: ${esito}`;
}

/** Testo compatto colonna lista «età pattern». */
export function displayPatternAgeListLabel(r: {
  pattern_age_bars?: number | null;
  latest_pattern_name?: string | null;
}): string {
  if (r.latest_pattern_name == null || String(r.latest_pattern_name).trim() === "") {
    return "—";
  }
  const n = r.pattern_age_bars;
  if (n == null) return "—";
  if (n === 0) return "0 barre";
  return `${n} barre fa`;
}

export function patternAgeListCellClass(stale: boolean | undefined): string {
  if (stale) {
    return "font-medium text-amber-800 dark:text-amber-300";
  }
  return "text-zinc-600 dark:text-zinc-400";
}

export { PATTERN_STALE_TOOLTIP };
