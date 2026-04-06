"use client";

import { useEffect, useMemo, useState } from "react";
import type { TradePlanV1 } from "@/lib/api";
import {
  computePositionSizingPreview,
  computeRiskPresets,
  DEFAULT_POSITION_SIZING_INPUT,
  loadPositionSizingInput,
  savePositionSizingInput,
  type PositionSizingPreview,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";

function eur(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return (
    n.toLocaleString("it-IT", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + " €"
  );
}

function pct(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return (
    n.toLocaleString("it-IT", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + "%"
  );
}

function rrStr(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toFixed(2) + ":1";
}

function units(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString("it-IT", { minimumFractionDigits: 0, maximumFractionDigits: 8 });
}

function RiskRecommendation({
  recommendedRiskPct,
  rationale,
  currentRiskPct,
  onApply,
}: {
  recommendedRiskPct: number;
  rationale: string;
  currentRiskPct: number;
  onApply: (pct: number) => void;
}) {
  const isAlreadySet = Math.abs(currentRiskPct - recommendedRiskPct) < 0.1;

  return (
    <div className="rounded-xl border border-indigo-200/80 bg-indigo-50/60 dark:border-indigo-900/60 dark:bg-indigo-950/30 p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-indigo-500 mb-1">
            Rischio consigliato per questo trade
          </p>
          <p className="text-2xl font-bold tabular-nums text-indigo-900 dark:text-indigo-100">
            {recommendedRiskPct}%
            <span className="text-sm font-normal text-indigo-600 dark:text-indigo-400 ml-2">del conto</span>
          </p>
          {rationale ? (
            <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300 leading-snug">{rationale}</p>
          ) : null}
        </div>
        {!isAlreadySet ? (
          <button
            type="button"
            onClick={() => onApply(recommendedRiskPct)}
            className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 active:scale-95 transition-all"
          >
            Usa {recommendedRiskPct}%
          </button>
        ) : (
          <span className="text-xs text-indigo-500 border border-indigo-200 dark:border-indigo-800 rounded-full px-3 py-1">
            ✓ Impostato
          </span>
        )}
      </div>
    </div>
  );
}

function ResultCard({
  preview,
  targetRiskPct,
}: {
  preview: PositionSizingPreview;
  targetRiskPct: number | null;
}) {
  if (!preview.ok) return null;

  const verdictColor =
    preview.rrNetTp1 == null
      ? "zinc"
      : preview.rrNetTp1 >= 1.2
        ? "emerald"
        : preview.rrNetTp1 >= 0.7
          ? "amber"
          : "red";

  const verdictLabel =
    preview.rrNetTp1 == null
      ? "—"
      : preview.rrNetTp1 >= 1.2
        ? "Conveniente"
        : preview.rrNetTp1 >= 0.7
          ? "Borderline"
          : "Non conveniente";

  const verdictBg: Record<string, string> = {
    emerald: "bg-emerald-50 border-emerald-200 dark:bg-emerald-950/30 dark:border-emerald-900/50",
    amber: "bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-900/50",
    red: "bg-red-50 border-red-200 dark:bg-red-950/30 dark:border-red-900/50",
    zinc: "bg-zinc-50 border-zinc-200 dark:bg-zinc-900 dark:border-zinc-800",
  };
  const verdictText: Record<string, string> = {
    emerald: "text-emerald-900 dark:text-emerald-100",
    amber: "text-amber-900 dark:text-amber-100",
    red: "text-red-900 dark:text-red-100",
    zinc: "text-zinc-700 dark:text-zinc-300",
  };
  const badgeCls: Record<string, string> = {
    emerald: "bg-emerald-600 text-white",
    amber: "bg-amber-500 text-amber-950",
    red: "bg-red-600 text-white",
    zinc: "bg-zinc-400 text-zinc-900",
  };

  return (
    <div className={`rounded-xl border p-4 ${verdictBg[verdictColor]}`}>
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
            Valutazione trade
          </p>
          <span className={`inline-block rounded-lg px-3 py-1 text-sm font-bold ${badgeCls[verdictColor]}`}>
            {verdictLabel}
          </span>
        </div>
        <div className="text-right">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
            R:R netto TP1
          </p>
          <p className={`text-xl font-bold tabular-nums ${verdictText[verdictColor]}`}>
            {rrStr(preview.rrNetTp1)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-white/70 dark:bg-zinc-900/50 p-3 border border-red-100 dark:border-red-900/30">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-red-500 mb-1">Se va male</p>
          <p className="text-lg font-bold tabular-nums text-red-700 dark:text-red-300">
            -{eur(preview.estimatedLossAtStopWithCosts)}
          </p>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {pct(preview.actualRiskPctOfAccount)} del conto · a stop (+ costi)
          </p>
        </div>

        <div className="rounded-lg bg-white/70 dark:bg-zinc-900/50 p-3 border border-emerald-100 dark:border-emerald-900/30">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-600 mb-1">TP1 netto</p>
          <p className="text-lg font-bold tabular-nums text-emerald-700 dark:text-emerald-300">
            {preview.estimatedNetProfitAtTp1 != null ? `+${eur(preview.estimatedNetProfitAtTp1)}` : "—"}
          </p>
          <p className="text-[11px] text-zinc-500 mt-0.5">dopo fee+slippage</p>
        </div>

        <div className="rounded-lg bg-white/70 dark:bg-zinc-900/50 p-3 border border-emerald-100 dark:border-emerald-900/30">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-600 mb-1">TP2 netto</p>
          <p className="text-lg font-bold tabular-nums text-emerald-700 dark:text-emerald-300">
            {preview.estimatedNetProfitAtTp2 != null ? `+${eur(preview.estimatedNetProfitAtTp2)}` : "—"}
          </p>
          <p className="text-[11px] text-zinc-500 mt-0.5">R:R {rrStr(preview.rrNetTp2)}</p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Chip label="Size" value={`${units(preview.positionSizeUnits)} unità`} />
        <Chip label="Notional" value={eur(preview.notionalPositionValue, 0)} />
        <Chip
          label="Margine usato"
          value={`${eur(preview.marginUsed, 0)} (${pct(preview.marginPctOfAccount, 1)})`}
        />
        <Chip label="Leva impostata" value={`${preview.effectiveLeverage.toFixed(1)}×`} />
      </div>

      {preview.cappedByMargin ? (
        <div className="mt-3 rounded-lg bg-amber-50/90 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
          <strong>Size ridotta dal cap margine.</strong> Rischio effettivo a stop:{" "}
          {pct(preview.actualRiskPctOfAccount)}
          {targetRiskPct != null ? (
            <>
              {" "}
              (target {pct(targetRiskPct)}). Aumenta «Max margine % conto» o riduci il rischio % per
              riallineare.
            </>
          ) : (
            <> Aumenta «Max margine % conto» se vuoi esprimere il rischio obiettivo in pieno.</>
          )}
        </div>
      ) : null}

      {preview.warnings
        .filter((w) => !w.includes("Size ridotta"))
        .map((w, i) => (
          <p key={i} className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
            ⚠ {w}
          </p>
        ))}
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/60 dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800 px-2 py-1.5">
      <p className="text-[10px] text-zinc-400 mb-0.5">{label}</p>
      <p className="font-mono text-[11px] font-semibold text-zinc-800 dark:text-zinc-200">{value}</p>
    </div>
  );
}

function RiskPresetsTable({
  presets,
  recommendedPct,
  onSelect,
}: {
  presets: ReturnType<typeof computeRiskPresets>;
  recommendedPct: number;
  onSelect: (pct: number) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[40rem] text-xs border-collapse">
        <thead>
          <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60 text-zinc-500">
            <th className="px-3 py-2 text-left font-medium">Rischio %</th>
            <th className="px-3 py-2 text-right font-medium">Perdi a stop</th>
            <th className="px-3 py-2 text-right font-medium">TP1 netto</th>
            <th className="px-3 py-2 text-right font-medium">TP2 netto</th>
            <th className="px-3 py-2 text-right font-medium">R:R TP1</th>
            <th className="px-3 py-2 text-right font-medium">Margine usato</th>
            <th className="px-3 py-2 text-right font-medium">Notional</th>
            <th className="px-3 py-2 text-right font-medium">Azione</th>
          </tr>
        </thead>
        <tbody>
          {presets.map(({ riskPct, preview: p, isRecommended: isRec }) => {
            const rrOk = p.rrNetTp1 != null && p.rrNetTp1 >= 0.7;
            return (
              <tr
                key={riskPct}
                className={`border-b border-zinc-100 dark:border-zinc-800/60 ${
                  isRec
                    ? "bg-indigo-50/60 dark:bg-indigo-950/25 ring-1 ring-inset ring-indigo-300 dark:ring-indigo-800"
                    : "hover:bg-zinc-50 dark:hover:bg-zinc-900/40"
                }`}
              >
                <td className="px-3 py-2 font-semibold">
                  {riskPct}%
                  {isRec ? (
                    <span className="ml-2 inline-block rounded-full bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white">
                      Consigliato
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 tabular-nums text-right text-red-700 dark:text-red-300 font-medium">
                  -{eur(p.estimatedLossAtStopWithCosts)}
                </td>
                <td
                  className={`px-3 py-2 tabular-nums text-right font-medium ${
                    rrOk ? "text-emerald-700 dark:text-emerald-300" : "text-zinc-500"
                  }`}
                >
                  {p.estimatedNetProfitAtTp1 != null ? `+${eur(p.estimatedNetProfitAtTp1)}` : "—"}
                </td>
                <td className="px-3 py-2 tabular-nums text-right text-emerald-700 dark:text-emerald-300">
                  {p.estimatedNetProfitAtTp2 != null ? `+${eur(p.estimatedNetProfitAtTp2)}` : "—"}
                </td>
                <td
                  className={`px-3 py-2 tabular-nums text-right font-semibold ${
                    p.rrNetTp1 == null
                      ? "text-zinc-400"
                      : p.rrNetTp1 >= 1.2
                        ? "text-emerald-700 dark:text-emerald-300"
                        : p.rrNetTp1 >= 0.7
                          ? "text-amber-700 dark:text-amber-300"
                          : "text-red-600 dark:text-red-400"
                  }`}
                >
                  {rrStr(p.rrNetTp1)}
                </td>
                <td className="px-3 py-2 tabular-nums text-right text-zinc-600 dark:text-zinc-400">
                  {eur(p.marginUsed, 0)}
                  {p.cappedByMargin ? (
                    <span className="ml-1 text-amber-500" title="Cap margine attivo">
                      ⚠
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 tabular-nums text-right text-zinc-500">
                  {eur(p.notionalPositionValue, 0)}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => onSelect(riskPct)}
                    className="rounded px-2 py-1 text-[11px] font-medium border border-zinc-200 dark:border-zinc-700 hover:border-indigo-400 hover:text-indigo-700 dark:hover:border-indigo-600 dark:hover:text-indigo-300 transition-colors"
                  >
                    Usa
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SettingsForm({
  input,
  onChange,
}: {
  input: PositionSizingUserInput;
  onChange: (patch: Partial<PositionSizingUserInput>) => void;
}) {
  const inputCls =
    "rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-indigo-400";
  const labelCls = "block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1";

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div>
        <label className={labelCls}>Capitale conto (€)</label>
        <input
          type="number"
          min={0}
          step={100}
          className={inputCls}
          value={input.accountCapital || ""}
          onChange={(e) => onChange({ accountCapital: Number(e.target.value) })}
        />
      </div>

      <div>
        <label className={labelCls}>Modalità rischio</label>
        <select
          className={inputCls}
          value={input.riskMode}
          onChange={(e) => onChange({ riskMode: e.target.value as PositionSizingUserInput["riskMode"] })}
        >
          <option value="percent">% del conto</option>
          <option value="fixed">Importo fisso (€)</option>
        </select>
      </div>

      {input.riskMode === "percent" ? (
        <div>
          <label className={labelCls}>Rischio per trade (%)</label>
          <input
            type="number"
            min={0.1}
            max={10}
            step={0.25}
            className={inputCls}
            value={input.riskPercent}
            onChange={(e) => onChange({ riskPercent: Number(e.target.value) })}
          />
          <p className="mt-1 text-[11px] text-zinc-400">
            = {eur((input.accountCapital * input.riskPercent) / 100)} perdita massima a stop (lorda)
          </p>
        </div>
      ) : (
        <div>
          <label className={labelCls}>Rischio fisso (€)</label>
          <input
            type="number"
            min={1}
            step={10}
            className={inputCls}
            value={input.riskFixed}
            onChange={(e) => onChange({ riskFixed: Number(e.target.value) })}
          />
        </div>
      )}

      <div>
        <label className={labelCls}>
          Leva massima <span className="font-normal text-zinc-400 ml-1">(1 = spot)</span>
        </label>
        <input
          type="number"
          min={1}
          max={100}
          step={0.5}
          className={inputCls}
          value={input.maxLeverage ?? 1}
          onChange={(e) => onChange({ maxLeverage: Number(e.target.value) || 1 })}
        />
        <p className="mt-1 text-[11px] text-zinc-400">Riduce il margine: notional / leva</p>
      </div>

      <div>
        <label className={labelCls}>Max margine % del conto per trade</label>
        <input
          type="number"
          min={5}
          max={100}
          step={5}
          className={inputCls}
          value={input.maxMarginPercent}
          onChange={(e) => onChange({ maxMarginPercent: Number(e.target.value) })}
        />
        <p className="mt-1 text-[11px] text-zinc-400">
          Tetto sul margine. Notional max ≈{" "}
          {eur(input.accountCapital * (input.maxMarginPercent / 100) * (input.maxLeverage ?? 1), 0)}
        </p>
      </div>

      <div>
        <label className={labelCls}>Fee round-trip (% notional)</label>
        <input
          type="number"
          min={0}
          step={0.01}
          className={inputCls}
          value={input.feeRoundTripPercent}
          onChange={(e) => onChange({ feeRoundTripPercent: Number(e.target.value) })}
        />
      </div>

      <div>
        <label className={labelCls}>Slippage stimato (% notional)</label>
        <input
          type="number"
          min={0}
          step={0.01}
          className={inputCls}
          value={input.slippagePercent}
          onChange={(e) => onChange({ slippagePercent: Number(e.target.value) })}
        />
      </div>
    </div>
  );
}

export function TradePlanPositionSizingCard({
  tradePlan,
  opportunityScore,
  variantStatus,
}: {
  tradePlan: TradePlanV1;
  opportunityScore?: number;
  variantStatus?: string | null;
}) {
  const [input, setInput] = useState<PositionSizingUserInput>(DEFAULT_POSITION_SIZING_INPUT);
  const [mounted, setMounted] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showPresets, setShowPresets] = useState(false);

  useEffect(() => {
    setInput(loadPositionSizingInput());
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted) savePositionSizingInput(input);
  }, [input, mounted]);

  const preview = useMemo(
    () => computePositionSizingPreview(input, tradePlan, opportunityScore, variantStatus),
    [input, tradePlan, opportunityScore, variantStatus],
  );

  const presets = useMemo(
    () => computeRiskPresets(input, tradePlan, opportunityScore, variantStatus),
    [input, tradePlan, opportunityScore, variantStatus],
  );

  function patch(p: Partial<PositionSizingUserInput>) {
    setInput((prev) => ({ ...prev, ...p }));
  }

  function applyRiskPct(pct: number) {
    patch({ riskMode: "percent", riskPercent: pct });
    setShowPresets(false);
  }

  const currentRiskPctForRec =
    input.riskMode === "percent" ? input.riskPercent : -1;

  const targetRiskPct = input.riskMode === "percent" ? input.riskPercent : null;

  if (!mounted) return null;

  return (
    <div className="rounded-b-2xl bg-zinc-50/50 dark:bg-zinc-950/30 px-5 py-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Rischio e sizing</h3>
        <p className="text-[11px] text-zinc-400">Stima non vincolante · salvata nel browser</p>
      </div>

      {preview.ok ? (
        <RiskRecommendation
          recommendedRiskPct={preview.recommendedRiskPct}
          rationale={preview.recommendedRiskRationale}
          currentRiskPct={currentRiskPctForRec}
          onApply={applyRiskPct}
        />
      ) : null}

      {preview.ok ? (
        <ResultCard preview={preview} targetRiskPct={targetRiskPct} />
      ) : (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-4 text-sm text-zinc-500">
          {preview.warnings[0] ?? "Preview non disponibile con i prezzi attuali."}
        </div>
      )}

      <button
        type="button"
        onClick={() => setShowPresets((s) => !s)}
        className="w-full text-left text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1"
      >
        <span>{showPresets ? "▲" : "▶"}</span>
        {showPresets ? "Nascondi" : "Mostra"} confronto rischio 0.5%–3%
      </button>

      {showPresets ? (
        <RiskPresetsTable
          presets={presets}
          recommendedPct={preview.recommendedRiskPct}
          onSelect={applyRiskPct}
        />
      ) : null}

      <button
        type="button"
        onClick={() => setShowSettings((s) => !s)}
        className="w-full text-left text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1"
      >
        <span>{showSettings ? "▲" : "▶"}</span>
        {showSettings ? "Nascondi" : "Modifica"} impostazioni conto e costi
      </button>

      {showSettings ? (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
          <SettingsForm input={input} onChange={patch} />
        </div>
      ) : null}
    </div>
  );
}
