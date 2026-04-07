/**
 * Formattazione prezzi USD per UI (max 2–4 decimali significativi).
 */
export function formatPrice(price: number | string | null | undefined): string {
  if (price === null || price === undefined) return "—";
  if (typeof price === "string" && price.trim() === "") return "—";
  const n = typeof price === "string" ? parseFloat(price) : price;
  if (!Number.isFinite(n)) return "—";

  if (n >= 1000) {
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (n >= 100) return `$${n.toFixed(2)}`;
  if (n >= 10) return `$${n.toFixed(2)}`;
  if (n >= 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(4)}`;
}
