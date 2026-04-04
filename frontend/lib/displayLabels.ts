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

/** Bande pattern_quality_label dall'API (high | medium | low | unknown). */
const PATTERN_QUALITY_LABEL_IT: Record<string, string> = {
  high: "alta",
  medium: "media",
  low: "bassa",
  unknown: "sconosciuta",
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

/** Codice API: operable | monitor | discard */
export type OperationalDecisionCode = "operable" | "monitor" | "discard";

export function displayOperationalDecisionListLabel(
  code: string | null | undefined,
): string {
  switch (code) {
    case "operable":
      return "Operabile";
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
    case "operable":
      return "OPERABILE";
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
