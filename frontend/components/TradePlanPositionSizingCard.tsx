"use client";

import { useEffect, useMemo, useState } from "react";
import type { TradePlanV1 } from "@/lib/api";
import { computeEconomicViability, computeSimpleEconomicVerdict } from "@/lib/economicViability";
import {
  computePositionSizingPreview,
  DEFAULT_POSITION_SIZING_INPUT,
  loadPositionSizingInput,
  savePositionSizingInput,
  sizingLimitShortLineItalian,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";
import { RiskPresetComparisonBlock } from "@/components/RiskPresetComparisonBlock";
import { PositionSizingDirectAnswerCard } from "@/components/PositionSizingDirectAnswerCard";

function fmtMoney(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtUnits(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

function fmtPct(n: number): string {
  return n.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function TradePlanPositionSizingCard({ tradePlan }: { tradePlan: TradePlanV1 }) {
  const [input, setInput] = useState<PositionSizingUserInput>(DEFAULT_POSITION_SIZING_INPUT);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setInput(loadPositionSizingInput());
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    savePositionSizingInput(input);
  }, [input, mounted]);

  const preview = useMemo(
    () => computePositionSizingPreview(input, tradePlan),
    [input, tradePlan],
  );

  const viability = useMemo(
    () => computeEconomicViability(preview, input),
    [preview, input],
  );

  const simpleVerdict = useMemo(
    () => computeSimpleEconomicVerdict(preview, input, viability),
    [preview, input, viability],
  );

  function patch(p: Partial<PositionSizingUserInput>) {
    setInput((prev) => ({ ...prev, ...p }));
  }

  const detailsSummaryClass =
    "cursor-pointer list-none text-sm font-semibold text-sky-950 dark:text-sky-100 [&::-webkit-details-marker]:hidden";

  return (
    <div
      className="mt-4 rounded-md border border-sky-200/90 bg-sky-50/50 p-3 dark:border-sky-900/60 dark:bg-sky-950/25"
      role="region"
      aria-label="Rischio, puntata e convenienza economica"
    >
      <h3 className="text-sm font-semibold text-sky-950 dark:text-sky-100">Rischio e puntata</h3>
      <p className="mt-1 text-[11px] leading-snug text-sky-900/85 dark:text-sky-200/85">
        Stima non vincolante sul tuo conto. Fee e slippage sono prudenziali. Impostazioni salvate in questo
        browser.
      </p>

      <div className="mt-4">
        <PositionSizingDirectAnswerCard preview={preview} verdict={simpleVerdict} />
      </div>

      <details className="mt-4 rounded-lg border border-sky-200/80 bg-white/60 p-3 dark:border-sky-900/50 dark:bg-zinc-900/40" open>
        <summary className={detailsSummaryClass}>Impostazioni conto e costi</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Capitale conto</span>
            <input
              type="number"
              min={0}
              step={100}
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.accountCapital || ""}
              onChange={(e) => patch({ accountCapital: Number(e.target.value) })}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Rischio per trade</span>
            <select
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.riskMode}
              onChange={(e) =>
                patch({ riskMode: e.target.value as PositionSizingUserInput["riskMode"] })
              }
            >
              <option value="percent">% del conto</option>
              <option value="fixed">Importo fisso</option>
            </select>
          </label>
          {input.riskMode === "percent" ? (
            <label className="flex flex-col gap-1 text-[11px]">
              <span className="font-medium text-sky-950 dark:text-sky-100">Rischio (%)</span>
              <input
                type="number"
                min={0}
                max={100}
                step={0.1}
                className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
                value={input.riskPercent}
                onChange={(e) => patch({ riskPercent: Number(e.target.value) })}
              />
            </label>
          ) : (
            <label className="flex flex-col gap-1 text-[11px]">
              <span className="font-medium text-sky-950 dark:text-sky-100">Rischio fisso (valuta)</span>
              <input
                type="number"
                min={0}
                step={10}
                className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
                value={input.riskFixed}
                onChange={(e) => patch({ riskFixed: Number(e.target.value) })}
              />
            </label>
          )}
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Fee round-trip (% notional)</span>
            <input
              type="number"
              min={0}
              step={0.01}
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.feeRoundTripPercent}
              onChange={(e) => patch({ feeRoundTripPercent: Number(e.target.value) })}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Slippage stimato (% notional)</span>
            <input
              type="number"
              min={0}
              step={0.01}
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.slippagePercent}
              onChange={(e) => patch({ slippagePercent: Number(e.target.value) })}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Max % conto per trade</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.maxCapitalPercentPerTrade}
              onChange={(e) => patch({ maxCapitalPercentPerTrade: Number(e.target.value) })}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="font-medium text-sky-950 dark:text-sky-100">Leva massima (opz.)</span>
            <input
              type="number"
              min={0}
              step={0.5}
              placeholder="vuoto = nessun limite"
              className="rounded border border-sky-200 bg-white px-2 py-1.5 text-sm dark:border-sky-800 dark:bg-zinc-900"
              value={input.maxLeverage ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                patch({ maxLeverage: v === "" ? null : Number(v) });
              }}
            />
          </label>
        </div>
        <p className="mt-2 text-[10px] text-zinc-600 dark:text-zinc-400">
          Soglie convenienza (TP min, costi, R:R):{" "}
          <code className="rounded bg-black/5 px-1 dark:bg-white/10">economicViabilityConfig.ts</code>
        </p>
      </details>

      <details className="mt-3 rounded-lg border border-indigo-200/70 bg-indigo-50/30 p-3 dark:border-indigo-900/50 dark:bg-indigo-950/20">
        <summary className={`${detailsSummaryClass} text-indigo-950 dark:text-indigo-100`}>
          Analisi avanzata — confronto rischio 1%–5%
        </summary>
        <div className="mt-2">
          <RiskPresetComparisonBlock tradePlan={tradePlan} input={input} embedded />
        </div>
      </details>

      <details className="mt-3 rounded-lg border border-sky-200/80 bg-white/40 p-3 dark:border-sky-900/50 dark:bg-zinc-900/30">
        <summary className={detailsSummaryClass}>Dettaglio tecnico (numeri completi)</summary>
        <div className="mt-3 border-t border-sky-200/80 pt-3 text-sm dark:border-sky-900/50">
          {preview.ok && sizingLimitShortLineItalian(preview.sizingLimitedBy) ? (
            <p className="mb-3 rounded-md border border-amber-300/80 bg-amber-50/80 px-2 py-1.5 text-[11px] text-amber-950 dark:border-amber-800/60 dark:bg-amber-950/35 dark:text-amber-100">
              {sizingLimitShortLineItalian(preview.sizingLimitedBy)}
            </p>
          ) : null}
          <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Rischio target (impostazione)</dt>
              <dd className="font-mono tabular-nums text-right">{fmtMoney(preview.maxRiskMoney)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Rischio effettivo (% conto)</dt>
              <dd className="font-mono tabular-nums text-right">
                {input.accountCapital > 0
                  ? `${fmtPct((preview.estimatedLossAtStopWithCosts / input.accountCapital) * 100)}%`
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Distanza stop (abs / %)</dt>
              <dd className="font-mono tabular-nums text-right">
                {fmtMoney(preview.stopDistanceAbs)} / {fmtPct(preview.stopDistancePct)}%
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Size (unità)</dt>
              <dd className="font-mono tabular-nums text-right">{fmtUnits(preview.positionSizeUnits)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Leva implicita</dt>
              <dd className="font-mono tabular-nums text-right">{preview.impliedLeverage.toFixed(2)}×</dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Costi stimati</dt>
              <dd className="font-mono tabular-nums text-right">{fmtMoney(preview.estimatedTotalCosts)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Perdita lorda a stop</dt>
              <dd className="font-mono tabular-nums text-right text-red-700 dark:text-red-400">
                {fmtMoney(preview.estimatedLossAtStop)}
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">Utile lordo TP1 / TP2</dt>
              <dd className="font-mono tabular-nums text-right">
                {preview.estimatedGrossProfitAtTp1 != null ? fmtMoney(preview.estimatedGrossProfitAtTp1) : "—"}{" "}
                / {preview.estimatedGrossProfitAtTp2 != null ? fmtMoney(preview.estimatedGrossProfitAtTp2) : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-sky-100/80 py-1 dark:border-sky-900/40">
              <dt className="text-zinc-600 dark:text-zinc-400">R:R monetario TP1 / TP2</dt>
              <dd className="font-mono tabular-nums text-right">
                {preview.rrTp1Money != null ? preview.rrTp1Money.toFixed(2) : "—"} /{" "}
                {preview.rrTp2Money != null ? preview.rrTp2Money.toFixed(2) : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-2 py-1">
              <dt className="text-zinc-600 dark:text-zinc-400">Min. TP1 / TP2 richiesti (soglie)</dt>
              <dd className="font-mono tabular-nums text-right">
                {fmtMoney(viability.minNetProfitTp1Required)} / {fmtMoney(viability.minNetProfitTp2Required)}
              </dd>
            </div>
          </dl>
          {!preview.ok && (
            <p className="mt-2 text-xs font-medium text-amber-800 dark:text-amber-200">
              Preview non valida o vincoli non rispettati.
            </p>
          )}
          {preview.warnings.length > 0 && (
            <ul
              className="mt-2 list-disc space-y-1 pl-5 text-[11px] text-amber-950 dark:text-amber-100"
              role="alert"
            >
              {preview.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
}
