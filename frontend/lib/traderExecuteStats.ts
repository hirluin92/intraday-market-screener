/**
 * Stima locale "max execute simultanei in lista" per giorno (localStorage).
 * Non sostituisce uno storico server-side.
 */

const STORAGE_KEY = "trader_execute_daily_max_v1";

type DailyMaxMap = Record<string, number>;

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function readMap(): DailyMaxMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const p = JSON.parse(raw) as DailyMaxMap;
    return typeof p === "object" && p !== null ? p : {};
  } catch {
    return {};
  }
}

function writeMap(m: DailyMaxMap): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(m));
  } catch {
    /* ignore */
  }
}

/** Dopo ogni fetch: aggiorna il massimo numero di righe execute viste oggi. */
export function recordExecuteListMax(executeCount: number): void {
  const k = todayKey();
  const m = readMap();
  const prev = m[k] ?? 0;
  m[k] = Math.max(prev, executeCount);
  writeMap(m);
}

export function getTodayMaxExecute(): number {
  const m = readMap();
  return m[todayKey()] ?? 0;
}

export function getWeekSumLast7Days(): number {
  const m = readMap();
  let sum = 0;
  for (let i = 0; i < 7; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    sum += m[key] ?? 0;
  }
  return sum;
}
