"use client";

import { useMemo } from "react";
import type { TradePlanV1 } from "@/lib/api";
import { compareRiskPresets, type RiskPresetComparisonRow } from "@/lib/riskPresetComparison";
import type { PositionSizingPreview, PositionSizingUserInput } from "@/lib/positionSizing";

function fmtMoney(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtUnits(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

/** Perdita a stop+costi espressa come % del capitale. */
function effectiveRiskPctOfAccount(
  preview: PositionSizingPreview,
  accountCapital: number,
): string {
  if (!(accountCapital > 0)) return "—";
  const pct = (preview.estimatedLossAtStopWithCosts / accountCapital) * 100;
  return `${pct.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

/**
 * Quanto dell'obiettivo € (maxRiskMoney) non diventa perdita lorda a stop perché la size è inferiore
 * a quella necessaria. ~0 se il target è raggiunto; cresce con il % quando sei al cap notional.
 */
function riskEuroUnusedVsTarget(preview: PositionSizingPreview): number {
  const gap = preview.maxRiskMoney - preview.estimatedLossAtStop;
  return Math.max(0, gap);
}

function viabilityShort(v: RiskPresetComparisonRow["viability"]): string {
  if (v.status === "good") return "Conviene";
  if (v.status === "marginal") return "Marginale";
  return "Non conviene";
}

function statoLabel(row: RiskPresetComparisonRow): string {
  if (row.rowStatus === "recommended") return "Consigliato";
  if (row.rowStatus === "acceptable") return "Accettabile";
  return "Non conveniente";
}

function rowClass(row: RiskPresetComparisonRow): string {
  if (row.rowStatus === "recommended") {
    return "bg-emerald-100/90 ring-2 ring-emerald-500 dark:bg-emerald-950/50 dark:ring-emerald-600";
  }
  if (row.rowStatus === "acceptable") {
    return "bg-zinc-50/80 dark:bg-zinc-900/40";
  }
  return "bg-red-50/50 opacity-95 dark:bg-red-950/20";
}

type Props = {
  tradePlan: TradePlanV1;
  input: PositionSizingUserInput;
  /** Se true: solo tabella e nota breve (es. dentro «Analisi avanzata»). */
  embedded?: boolean;
};

export function RiskPresetComparisonBlock({ tradePlan, input, embedded = false }: Props) {
  const comparison = useMemo(
    () => compareRiskPresets(input, tradePlan),
    [input, tradePlan],
  );

  const presetLabel = comparison.rows.map((r) => `${r.riskPercent}%`).join(" · ");

  const stakeSummary = useMemo(() => {
    const rows = comparison.rows;
    if (rows.length === 0) return null;
    const notionals = rows.map((r) => r.preview.notionalPositionValue);
    const minN = Math.min(...notionals);
    const maxN = Math.max(...notionals);
    const p0 = rows[0].preview;
    const n0 = p0.notionalPositionValue;
    const allSameNotional = rows.every(
      (r) => Math.abs(r.preview.notionalPositionValue - n0) < 1e-6,
    );
    const maxNotionalCap =
      input.accountCapital > 0 ? (input.accountCapital * input.maxCapitalPercentPerTrade) / 100 : 0;
    return {
      notional: n0,
      minNotional: minN,
      maxNotional: maxN,
      units: p0.positionSizeUnits,
      allSameNotional,
      maxCapPct: input.maxCapitalPercentPerTrade,
      maxNotionalCap,
    };
  }, [comparison.rows, input.accountCapital, input.maxCapitalPercentPerTrade]);

  return (
    <div
      className="mb-4 rounded-lg border border-indigo-200/90 bg-indigo-50/40 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/30"
      role="region"
      aria-label="Confronto sizing multi-rischio"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-indigo-900 dark:text-indigo-200">
        {embedded ? "Confronto rischio %" : "Confronto puntata per rischio %"} ({presetLabel})
      </h3>

      {embedded ? (
        <p className="mt-2 text-[11px] leading-snug text-indigo-900/90 dark:text-indigo-200/85">
          Stesso capitale e costi del form; varia solo il rischio % come se provassi 1%…5% uno alla volta.
          Se molte colonne sono uguali, il «Max % conto per trade» fissa già la puntata al tetto.
        </p>
      ) : null}

      {!embedded && stakeSummary != null && stakeSummary.maxNotional > 0 ? (
        <div
          className="mt-3 rounded-lg border-2 border-indigo-400/90 bg-white/95 px-3 py-3 shadow-sm dark:border-indigo-600 dark:bg-indigo-950/80"
          role="region"
          aria-label="Quanto puntare: esposizione effettiva"
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-indigo-800 dark:text-indigo-200">
            Quanto puntare (risposta diretta)
          </p>
          {stakeSummary.allSameNotional ? (
            <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-indigo-950 dark:text-indigo-50">
              {fmtMoney(stakeSummary.notional)} €
            </p>
          ) : (
            <p className="mt-1 text-xl font-bold tabular-nums tracking-tight text-indigo-950 dark:text-indigo-50">
              da {fmtMoney(stakeSummary.minNotional)} € a {fmtMoney(stakeSummary.maxNotional)} €
            </p>
          )}
          <p className="mt-0.5 text-[11px] text-zinc-700 dark:text-zinc-300">
            Esposizione = valore posizione (notional).
            {stakeSummary.allSameNotional ? (
              <>
                {" "}
                Size in strumento:{" "}
                <span className="font-mono tabular-nums">{fmtUnits(stakeSummary.units)}</span> unità (uguale per
                tutti i preset se la puntata è unica).
              </>
            ) : (
              <> La size in unità varia per riga: usa la tabella sotto.</>
            )}
          </p>
          <p className="mt-2 border-t border-indigo-200/80 pt-2 text-[11px] leading-snug text-zinc-800 dark:text-zinc-200">
            <strong>Non devi usare tutto il conto sul trade</strong> se non lo vuoi. Il tetto massimo di
            esposizione è <strong>capitale × «Max % conto per trade»</strong>: ora hai impostato{" "}
            <strong>{stakeSummary.maxCapPct.toLocaleString("it-IT")}%</strong>, quindi la puntata non può
            superare <strong>{fmtMoney(stakeSummary.maxNotionalCap)} €</strong> (con questo capitale). Per
            puntare meno, <strong>abbassa «Max % conto per trade»</strong> nei campi sopra (es. 25–50%).
          </p>
          {stakeSummary.allSameNotional ? (
            <p className="mt-2 text-[11px] leading-snug text-indigo-950 dark:text-indigo-100">
              <strong>Per tutti i preset della tabella vale la stessa puntata</strong> perché, con capitale{" "}
              {fmtMoney(input.accountCapital)} € e «Max % conto per trade» al{" "}
              {stakeSummary.maxCapPct.toLocaleString("it-IT")}%, la size è già al massimo consentito:{" "}
              <strong>questo è l’importo che metti in gioco</strong> (non aumenta alzando il 1% al 5% finché
              resti al tetto). Per puntare di più devi alzare il capitale, il massimo % conto, o accettare uno
              stop più lontano che richieda meno unità per lo stesso obiettivo €.
            </p>
          ) : (
            <p className="mt-2 text-[11px] leading-snug text-indigo-950 dark:text-indigo-100">
              La <strong>puntata in € cambia per riga</strong> in base al rischio %: usa la colonna «Puntata
              (notional €)» per il valore esatto per ogni scenario.
            </p>
          )}
        </div>
      ) : !embedded && stakeSummary != null ? (
        <p className="mt-2 text-[11px] text-amber-900 dark:text-amber-200">
          Puntata non calcolabile (controlla capitale, prezzi piano o vincoli).
        </p>
      ) : null}

      {!embedded ? (
      <p className="mt-3 text-[11px] leading-snug text-indigo-900/85 dark:text-indigo-200/85">
        Ogni riga applica un <strong>rischio % diverso sul capitale</strong> (come se impostassi quel % nel
        form): vedi <strong>puntata</strong> (notional), <strong>quanto puoi perdere</strong> a stop
        (inclusi costi) e <strong>quanto potresti guadagnare</strong> a TP1/TP2. Se il «Max % conto per
        trade» limita la size, la puntata può restare uguale su più righe: in quel caso non stai
        «puntando di più» alzando il % — vedi l’avviso sotto.
      </p>
      ) : null}
      {comparison.notionalCapBindsAllPresets ? (
        <p
          className="mt-2 rounded-md border border-amber-300/90 bg-amber-50/90 px-2 py-2 text-[11px] leading-snug text-amber-950 dark:border-amber-800/80 dark:bg-amber-950/40 dark:text-amber-100"
          role="status"
        >
          {embedded ? (
            <>
              <strong>Stesse puntate e stessi numeri:</strong> sei al tetto del «Max % conto per trade». La
              colonna «Rischio € non utilizzato» spiega quanto manca rispetto all’obiettivo %.
            </>
          ) : (
            <>
              <strong>Perché P&L identici?</strong> Guadagni e perdite dipendono dalla <strong>size</strong> (e
              quindi dalla puntata). Qui tutte le righe usano la <strong>stessa size</strong> perché il
              notional è già al tetto: non stai «aprendo un trade più grande» al passare dal 1% al 5%. Il 5% è
              solo un obiettivo € più alto che <em>non puoi esprimere</em> senza superare il cap — vedi la
              colonna <strong>Rischio € non utilizzato</strong>, che cresce riga per riga mentre la perdita
              reale resta uguale. Per puntate diverse servono più capitale, un cap % più alto, o uno stop più
              lontano.
            </>
          )}
        </p>
      ) : null}
      {!embedded ? (
      <p className="mt-2 text-xs text-indigo-950 dark:text-indigo-100">
        {comparison.recommendedRiskPercent == null ? (
          <>
            <span className="font-medium text-red-800 dark:text-red-200">
              Nessun sizing consigliato per questo capitale con i parametri attuali.
            </span>
            <span className="mt-1 block text-[11px] font-normal text-indigo-900/90 dark:text-indigo-200/85">
              {comparison.recommendationMessage}
            </span>
          </>
        ) : (
          <span>
            Suggerimento: rischio al <strong>{comparison.recommendedRiskPercent}%</strong> del conto.{" "}
            {comparison.recommendationMessage}
          </span>
        )}
      </p>
      ) : null}

      <div className="mt-3 overflow-x-auto rounded-md border border-indigo-200/70 dark:border-indigo-900/50">
        <table className="w-full min-w-[72rem] border-collapse text-left text-[11px]">
          <thead>
            <tr className="border-b border-indigo-200/80 bg-indigo-100/50 dark:border-indigo-900/60 dark:bg-indigo-950/60">
              <th className="px-2 py-2 font-medium" title="Rischio % sul conto per questa riga">
                Rischio %
              </th>
              <th className="px-2 py-2 font-medium" title="Valore posizione (size × prezzo) = puntata in €">
                Puntata (notional €)
              </th>
              <th className="px-2 py-2 font-medium">Size (unità)</th>
              <th
                className="px-2 py-2 font-medium text-red-900 dark:text-red-200"
                title="Perdita se colpito lo stop, inclusi fee e slippage stimati"
              >
                Perdita max (stop+costi)
              </th>
              <th
                className="px-2 py-2 font-medium text-emerald-900 dark:text-emerald-200"
                title="Utile netto stimato se raggiunto TP1"
              >
                Guadagno netto TP1
              </th>
              <th
                className="px-2 py-2 font-medium text-emerald-900 dark:text-emerald-200"
                title="Utile netto stimato se raggiunto TP2"
              >
                Guadagno netto TP2
              </th>
              <th className="px-2 py-2 font-medium" title="Capitale × rischio % — obiettivo prima del cap notional">
                Rischio € obiettivo
              </th>
              <th
                className="px-2 py-2 font-medium text-amber-950 dark:text-amber-100"
                title={
                  "Obiettivo € meno perdita lorda a stop: se >0, la size non basta per rischiare l’importo indicato (tipico con cap notional). " +
                  "Cresce alzando il % mentre la perdita reale resta uguale."
                }
              >
                Rischio € non utilizzato
              </th>
              <th
                className="px-2 py-2 font-medium"
                title="(Perdita stop+costi) ÷ capitale: rischio % effettivo con questa puntata"
              >
                Rischio effettivo (% conto)
              </th>
              <th className="px-2 py-2 font-medium">% conto in puntata</th>
              <th className="px-2 py-2 font-medium">Costi st.</th>
              <th className="px-2 py-2 font-medium">R:R TP1</th>
              <th className="px-2 py-2 font-medium">R:R TP2</th>
              <th className="px-2 py-2 font-medium">Convenienza</th>
              <th className="px-2 py-2 font-medium">Stato</th>
            </tr>
          </thead>
          <tbody>
            {comparison.rows.map((row) => (
              <tr
                key={row.riskPercent}
                className={`border-b border-indigo-100/80 dark:border-indigo-900/40 ${rowClass(row)}`}
              >
                <td className="whitespace-nowrap px-2 py-1.5 font-mono font-medium">
                  {row.riskPercent}%
                  {row.preview.positionSizingCappedByNotional ? (
                    <span
                      className="ml-1 rounded bg-amber-200/90 px-1 text-[9px] font-semibold uppercase text-amber-950 dark:bg-amber-900/80 dark:text-amber-50"
                      title="Size limitata dal massimo % conto: puntata e P&L possono coincidere con altre righe"
                    >
                      cap
                    </span>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums font-medium text-indigo-950 dark:text-indigo-100">
                  {fmtMoney(row.preview.notionalPositionValue)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums">
                  {fmtUnits(row.preview.positionSizeUnits)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-red-800 dark:text-red-300">
                  {fmtMoney(row.preview.estimatedLossAtStopWithCosts)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-emerald-900 dark:text-emerald-300">
                  {row.preview.estimatedNetProfitAtTp1 != null
                    ? fmtMoney(row.preview.estimatedNetProfitAtTp1)
                    : "—"}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-emerald-900 dark:text-emerald-300">
                  {row.preview.estimatedNetProfitAtTp2 != null
                    ? fmtMoney(row.preview.estimatedNetProfitAtTp2)
                    : "—"}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-zinc-800 dark:text-zinc-200">
                  {fmtMoney(row.preview.maxRiskMoney)}
                </td>
                <td
                  className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-amber-950 dark:text-amber-100"
                  title="Quanto manca perché la perdita a stop lorda resta sotto l’obiettivo € (size limitata)"
                >
                  {fmtMoney(riskEuroUnusedVsTarget(row.preview))}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-indigo-950 dark:text-indigo-100">
                  {effectiveRiskPctOfAccount(row.preview, input.accountCapital)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums">
                  {row.preview.accountCapitalPctAllocated.toFixed(1)}%
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums">
                  {fmtMoney(row.preview.estimatedTotalCosts)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums">
                  {row.preview.rrTp1Money != null ? row.preview.rrTp1Money.toFixed(2) : "—"}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums">
                  {row.preview.rrTp2Money != null ? row.preview.rrTp2Money.toFixed(2) : "—"}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5">{viabilityShort(row.viability)}</td>
                <td className="whitespace-nowrap px-2 py-1.5 font-medium">{statoLabel(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
