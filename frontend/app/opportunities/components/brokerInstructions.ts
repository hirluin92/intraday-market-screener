import type { TraderBrokerId } from "@/lib/traderPrefs";

export type InstructionTemplate = {
  short: string[];
  long: string[];
  warning: { short: string; long?: string };
};

export const BROKER_INSTRUCTIONS: Record<
  Exclude<TraderBrokerId, "other">,
  InstructionTemplate
> = {
  ibkr: {
    short: [
      "Cerca {symbol} su IBKR",
      'Clicca "Ordine di vendita" (short)',
      "Tipo ordine: Limit → Prezzo: {entry}",
      "Quantità: {qty} azioni",
      "Allega Stop Loss: {stop}",
      "Allega Take Profit: {tp}",
      'Clicca "Invia ordine"',
    ],
    long: [
      "Cerca {symbol} su IBKR",
      'Clicca "Ordine di acquisto"',
      "Tipo ordine: Limit → Prezzo: {entry}",
      "Quantità: {qty} azioni",
      "Allega Stop Loss: {stop}",
      "Allega Take Profit: {tp}",
      'Clicca "Invia ordine"',
    ],
    warning: {
      short:
        "⚠️ Short: richiede conto a margine. Conto cash non supporta la vendita allo scoperto.",
      long: "ℹ️ Verifica disponibilità e tipo di mercato (US stock vs CFD).",
    },
  },
  xtb: {
    short: [
      "Cerca {symbol} come CFD su XTB",
      "Apri ordine limite vendita",
      "Prezzo limite: {entry}",
      "Volume: {qty}",
      "Stop Loss: {stop}",
      "Take Profit: {tp}",
      "Conferma vendita",
    ],
    long: [
      "Cerca {symbol} come CFD su XTB",
      "Apri ordine limite acquisto",
      "Prezzo limite: {entry}",
      "Volume: {qty}",
      "Stop Loss: {stop}",
      "Take Profit: {tp}",
      "Conferma acquisto",
    ],
    warning: {
      short:
        "⚠️ Disponibile solo se il simbolo ha un CFD listato su XTB.",
      long: "ℹ️ Controlla che il sottostante sia negoziabile sulla tua piattaforma.",
    },
  },
};

export function fillInstructionTemplate(
  lines: string[],
  vars: Record<string, string>,
): string[] {
  return lines.map((line) =>
    line.replace(/\{(\w+)\}/g, (_, k: string) => vars[k] ?? `{${k}}`),
  );
}
