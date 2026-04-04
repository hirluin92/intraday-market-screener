"use client";

import type { PositionSizingPreview } from "@/lib/positionSizing";
import { sizingLimitShortLineItalian } from "@/lib/positionSizing";
import type { SimpleEconomicVerdict } from "@/lib/economicViability";

function fmtMoney(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function verdictWrapClass(verdict: SimpleEconomicVerdict["verdictKey"]): string {
  if (verdict === "good") {
    return "border-emerald-400 bg-emerald-50/95 dark:border-emerald-700 dark:bg-emerald-950/50";
  }
  if (verdict === "marginal") {
    return "border-amber-400 bg-amber-50/95 dark:border-amber-800 dark:bg-amber-950/40";
  }
  return "border-red-400 bg-red-50/95 dark:border-red-800 dark:bg-red-950/40";
}

function verdictBadgeClass(verdict: SimpleEconomicVerdict["verdictKey"]): string {
  if (verdict === "good") return "bg-emerald-600 text-white dark:bg-emerald-700";
  if (verdict === "marginal") return "bg-amber-500 text-amber-950 dark:bg-amber-600 dark:text-amber-50";
  return "bg-red-600 text-white dark:bg-red-700";
}

type Props = {
  preview: PositionSizingPreview;
  verdict: SimpleEconomicVerdict;
};

export function PositionSizingDirectAnswerCard({ preview, verdict }: Props) {
  const ok = preview.ok && preview.notionalPositionValue > 0;
  const net1 = preview.estimatedNetProfitAtTp1;
  const net2 = preview.estimatedNetProfitAtTp2;

  return (
    <div
      className={`rounded-xl border-2 p-4 shadow-sm ${verdictWrapClass(verdict.verdictKey)}`}
      role="region"
      aria-label="Risposta diretta: puntata e risultati stimati"
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
        Risposta diretta
      </p>
      <p className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400">
        La puntata in € è <strong>calcolata automaticamente</strong> da capitale, rischio % (o € fissi), stop,
        fee/slippage e tetti (allocazione % conto, leva). Non va inserita a mano.
      </p>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <section>
          <h4 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Quanto puntare</h4>
          <p className="mt-1 text-2xl font-bold tabular-nums text-zinc-950 dark:text-zinc-50">
            {ok ? `${fmtMoney(preview.notionalPositionValue)} €` : "—"}
          </p>
          <p className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400">
            Valore posizione stimato (notional), con le tue impostazioni.
          </p>
        </section>

        <section>
          <h4 className="text-xs font-semibold text-red-900 dark:text-red-200">Se va male</h4>
          <p className="mt-1 text-xl font-semibold tabular-nums text-red-800 dark:text-red-300">
            Perdita max: {ok ? `${fmtMoney(preview.estimatedLossAtStopWithCosts)} €` : "—"}
          </p>
          <p className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400">
            Stop + costi stimati (fee e slippage sul notional).
          </p>
        </section>

        <section className="sm:col-span-2">
          <h4 className="text-xs font-semibold text-emerald-900 dark:text-emerald-200">Se va bene</h4>
          <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <p>
              <span className="text-zinc-600 dark:text-zinc-400">TP1 netto: </span>
              <span className="font-semibold tabular-nums text-emerald-800 dark:text-emerald-300">
                {net1 != null ? `${fmtMoney(net1)} €` : "—"}
              </span>
            </p>
            <p>
              <span className="text-zinc-600 dark:text-zinc-400">TP2 netto: </span>
              <span className="font-semibold tabular-nums text-emerald-800 dark:text-emerald-300">
                {net2 != null ? `${fmtMoney(net2)} €` : "—"}
              </span>
            </p>
          </div>
        </section>

        <section className="sm:col-span-2">
          <h4 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Conto impegnato</h4>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {ok ? `${preview.accountCapitalPctAllocated.toFixed(1)}%` : "—"}{" "}
            <span className="text-sm font-normal text-zinc-600 dark:text-zinc-400">
              del capitale in puntata (notional / conto)
            </span>
          </p>
        </section>
      </div>

      {ok && sizingLimitShortLineItalian(preview.sizingLimitedBy) ? (
        <p className="mt-3 rounded-md border border-zinc-200/90 bg-zinc-50/95 px-2 py-2 text-[11px] leading-snug text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900/50 dark:text-zinc-200">
          <strong className="text-zinc-900 dark:text-zinc-100">Nota sizing: </strong>
          {sizingLimitShortLineItalian(preview.sizingLimitedBy)}
        </p>
      ) : null}

      <div className="mt-4 border-t border-zinc-200/80 pt-4 dark:border-zinc-700/80">
        <h4 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Valutazione</h4>
        <p className="mt-2">
          <span
            className={`inline-block rounded-md px-3 py-1.5 text-sm font-bold uppercase tracking-wide ${verdictBadgeClass(verdict.verdictKey)}`}
          >
            {verdict.verdictLabel}
          </span>
        </p>
        <p className="mt-2 text-sm leading-snug text-zinc-800 dark:text-zinc-200">
          {verdict.verdictKey === "good"
            ? "Buon compromesso rischio/rendimento rispetto al capitale e ai costi impostati."
            : verdict.verdictKey === "marginal"
              ? "Il piano può essere tecnicamente valido ma il rendimento netto o il rapporto rischio/rendimento sono deboli per questo conto."
              : "Per questo capitale l’utile netto atteso è troppo basso, i costi pesano troppo, o il rischio/rendimento non regge."}
        </p>
        {verdict.economicReason.length > 0 ? (
          <div className="mt-3">
            <p className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400">Perché:</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[11px] leading-snug text-zinc-800 dark:text-zinc-200">
              {verdict.economicReason.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
