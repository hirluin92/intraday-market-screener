"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
  DEFAULT_POSITION_SIZING_INPUT,
  type PositionSizingUserInput,
} from "@/lib/positionSizing";
import type { TraderBrokerId } from "@/lib/traderPrefs";
import { cn } from "@/lib/utils";

// ── Zod validation ────────────────────────────────────────────────────────────

const PrefsSchema = z.object({
  accountCapital: z.number().min(1, "Capitale deve essere > 0"),
  riskPercent: z
    .number()
    .min(0.1, "Rischio minimo 0.1%")
    .max(10, "Rischio massimo 10%"),
});

// ── Inner form content (shared between sidebar + sheet) ────────────────────────

interface PrefsFormProps {
  sizing: PositionSizingUserInput;
  onSizingChange: (s: PositionSizingUserInput) => void;
  broker: TraderBrokerId;
  onBrokerChange: (b: TraderBrokerId) => void;
}

function PrefsForm({ sizing, onSizingChange, broker, onBrokerChange }: PrefsFormProps) {
  const [capitalInput, setCapitalInput] = useState(String(sizing.accountCapital));
  const [capitalError, setCapitalError] = useState<string | null>(null);
  const [riskPct, setRiskPct] = useState(
    sizing.riskMode === "percent" ? sizing.riskPercent : 1.5,
  );

  const debounceRef = useRef<number | undefined>(undefined);

  // Sync controlled input when external state changes
  useEffect(() => {
    setCapitalInput(String(sizing.accountCapital));
  }, [sizing.accountCapital]);

  const commitCapital = useCallback(
    (raw: string) => {
      const n = Number(raw);
      const result = PrefsSchema.shape.accountCapital.safeParse(n);
      if (!result.success) {
        setCapitalError(result.error.issues[0]?.message ?? "Valore non valido");
        return;
      }
      setCapitalError(null);
      onSizingChange({ ...sizing, accountCapital: n });
    },
    [sizing, onSizingChange],
  );

  const handleCapitalChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCapitalInput(e.target.value);
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => commitCapital(e.target.value), 300);
  };

  const handleRiskChange = (values: number[]) => {
    const v = values[0] ?? riskPct;
    setRiskPct(v);
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      onSizingChange({ ...sizing, riskMode: "percent", riskPercent: v });
    }, 300);
  };

  const handleReset = () => {
    setCapitalInput(String(DEFAULT_POSITION_SIZING_INPUT.accountCapital));
    setRiskPct(DEFAULT_POSITION_SIZING_INPUT.riskPercent ?? 1.5);
    setCapitalError(null);
    onSizingChange(DEFAULT_POSITION_SIZING_INPUT);
    onBrokerChange("ibkr");
  };

  return (
    <div className="space-y-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-fg-2">
        Preferenze conto
      </p>

      {/* Capitale */}
      <div className="space-y-1.5">
        <label className="text-xs text-fg-2" htmlFor="prefs-capital">
          Capitale operativo (€)
        </label>
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 font-mono text-sm text-fg-3">
            €
          </span>
          <Input
            id="prefs-capital"
            type="number"
            min={1}
            step={100}
            value={capitalInput}
            onChange={handleCapitalChange}
            className={cn(
              "pl-7 font-mono tabular-nums",
              "bg-surface-2 border-line text-fg",
              capitalError && "border-bear focus-visible:ring-bear/30",
            )}
          />
        </div>
        {capitalError && (
          <p className="text-[10px] text-bear">{capitalError}</p>
        )}
      </div>

      {/* Rischio % — slider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs text-fg-2">Rischio per trade</label>
          <span className="font-mono text-sm font-semibold tabular-nums text-fg">
            {riskPct.toFixed(1)}%
          </span>
        </div>
        <Slider
          min={0.1}
          max={5}
          step={0.1}
          value={[riskPct]}
          onValueChange={handleRiskChange}
          className="[&_[data-slot=slider-track]]:bg-surface-2 [&_[data-slot=slider-range]]:bg-neutral [&_[data-slot=slider-thumb]]:border-neutral"
          aria-label="Rischio per trade in percentuale"
        />
        <div className="flex justify-between">
          <span className="text-[10px] text-fg-3">0.1%</span>
          <span className="text-[10px] text-fg-3">5%</span>
        </div>
      </div>

      {/* Broker */}
      <div className="space-y-1.5">
        <label className="text-xs text-fg-2">Broker / istruzioni</label>
        <Select
          value={broker}
          onValueChange={(v) => onBrokerChange(v as TraderBrokerId)}
        >
          <SelectTrigger className="bg-surface-2 border-line text-fg font-mono text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface border-line text-fg">
            <SelectItem value="ibkr">IBKR</SelectItem>
            <SelectItem value="xtb">XTB</SelectItem>
            <SelectItem value="other">Altro</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Reset */}
      <Button
        variant="ghost"
        size="sm"
        className="w-full text-xs text-fg-3 hover:text-fg"
        onClick={handleReset}
        type="button"
      >
        Reset preferenze
      </Button>
    </div>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

interface PreferencesPanelProps extends PrefsFormProps {
  /** "sidebar" = sticky panel inside xl layout. "sheet" = Sheet overlay for <xl. */
  mode: "sidebar" | "sheet";
  sheetOpen: boolean;
  onSheetClose: () => void;
}

export function PreferencesPanel({
  sizing,
  onSizingChange,
  broker,
  onBrokerChange,
  mode,
  sheetOpen,
  onSheetClose,
}: PreferencesPanelProps) {
  const formProps = { sizing, onSizingChange, broker, onBrokerChange };

  if (mode === "sidebar") {
    return (
      <div
        className="rounded-xl border border-line bg-surface p-4"
        aria-label="Pannello preferenze conto"
      >
        <PrefsForm {...formProps} />
      </div>
    );
  }

  // Sheet mode — rendered outside the grid, triggered by header button on <xl
  return (
    <Sheet open={sheetOpen} onOpenChange={(open) => !open && onSheetClose()}>
      <SheetContent
        side="right"
        className="w-full bg-surface border-line sm:max-w-md overflow-y-auto"
      >
        <SheetHeader className="mb-6">
          <SheetTitle className="text-fg">Preferenze conto</SheetTitle>
        </SheetHeader>
        <PrefsForm {...formProps} />
      </SheetContent>
    </Sheet>
  );
}
