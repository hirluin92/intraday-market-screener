import { z } from "zod";

// ── Activity feed ─────────────────────────────────────────────────────────────

export const ActivityItemTypeSchema = z.enum([
  "signal_executed",
  "signal_skipped",
  "signal_cancelled",
  "pipeline_run",
  "trade_closed",
  "ibkr_event",
]);
export type ActivityItemType = z.infer<typeof ActivityItemTypeSchema>;

export const ActivityItemSchema = z.object({
  id: z.string(),
  type: ActivityItemTypeSchema,
  timestamp: z.string().datetime({ offset: true }).or(z.string()),
  title: z.string(),
  description: z.string().optional(),
  href: z.string().optional(),
  variant: z.enum(["bull", "bear", "neutral", "warn"]).optional(),
});
export type ActivityItem = z.infer<typeof ActivityItemSchema>;

// ── Performance KPI ───────────────────────────────────────────────────────────

export const KPIValueSchema = z.object({
  /** null = missing backend endpoint (placeholder) */
  value: z.number().nullable(),
  label: z.string(),
  delta: z
    .object({
      value: z.number(),
      label: z.string().optional(),
    })
    .optional(),
  /** true = endpoint not yet available, show placeholder card */
  placeholder: z.boolean().optional(),
  placeholderNote: z.string().optional(),
});
export type KPIValue = z.infer<typeof KPIValueSchema>;

export const PerformanceKPIsSchema = z.object({
  openPositions:  KPIValueSchema,
  totalOrders30d: KPIValueSchema,
  pnlToday:       KPIValueSchema,
  drawdown:       KPIValueSchema,
  winRate30d:     KPIValueSchema.optional(),
});
export type PerformanceKPIs = z.infer<typeof PerformanceKPIsSchema>;

// ── Validation helpers ────────────────────────────────────────────────────────

/**
 * Validates data with Zod. In development, throws on invalid data.
 * In production, logs a warning and returns null to avoid crashing the UI.
 */
export function safeValidate<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  label: string,
): T | null {
  const result = schema.safeParse(data);
  if (result.success) return result.data;

  if (process.env.NODE_ENV === "development") {
    console.error(`[schema] Validation failed for ${label}:`, result.error.format());
  } else {
    console.warn(`[schema] ${label} validation warning — using fallback`);
  }
  return null;
}
