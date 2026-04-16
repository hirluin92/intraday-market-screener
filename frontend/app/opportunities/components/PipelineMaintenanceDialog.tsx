"use client";

import { Wrench } from "lucide-react";
import { toast } from "sonner";
import { useEffect } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { usePipelineControl } from "@/hooks/usePipelineControl";

type PipelineControl = ReturnType<typeof usePipelineControl>;

// ── Toast side-effects for pipeline feedback ──────────────────────────────────

function PipelineFeedbackToast({
  message,
  error,
}: {
  message: string | null;
  error: string | null;
}) {
  useEffect(() => {
    if (message) toast.success("Pipeline rigenerata", { description: message });
  }, [message]);

  useEffect(() => {
    if (error) toast.error("Pipeline fallita", { description: error });
  }, [error]);

  return null;
}

// ── Main dialog ───────────────────────────────────────────────────────────────

interface PipelineMaintenanceDialogProps {
  pipeline: PipelineControl;
}

export function PipelineMaintenanceDialog({
  pipeline,
}: PipelineMaintenanceDialogProps) {
  return (
    <>
      <PipelineFeedbackToast
        message={pipeline.message}
        error={pipeline.error}
      />

      <Dialog
        open={pipeline.dialogOpen}
        onOpenChange={(open) => !open && pipeline.closeDialog()}
      >
        <DialogContent className="max-w-2xl bg-surface border-line text-fg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-fg">
              <Wrench className="h-4 w-4 text-fg-2" aria-hidden />
              Manutenzione Pipeline
            </DialogTitle>
            <DialogDescription className="text-fg-2">
              Esegue ingest → features → context → patterns
              (POST /api/v1/pipeline/refresh). Uso avanzato.
            </DialogDescription>
          </DialogHeader>

          {/* Form grid */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Provider</label>
              <Select
                value={pipeline.provider}
                onValueChange={(v) =>
                  pipeline.setProvider(v as "binance" | "yahoo_finance")
                }
              >
                <SelectTrigger className="bg-surface-2 border-line text-fg text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface border-line text-fg">
                  <SelectItem value="binance">Binance</SelectItem>
                  <SelectItem value="yahoo_finance">Yahoo Finance</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Venue (opz.)</label>
              <Input
                className="bg-surface-2 border-line text-fg text-sm"
                value={pipeline.exchangeOverride}
                onChange={(e) => pipeline.setExchangeOverride(e.target.value)}
                placeholder="default"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Simbolo</label>
              <Input
                className="bg-surface-2 border-line text-fg text-sm font-mono"
                value={pipeline.symbol}
                onChange={(e) => pipeline.setSymbol(e.target.value)}
                placeholder="es. AAPL"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Timeframe</label>
              <Select
                value={pipeline.timeframe}
                onValueChange={pipeline.setTimeframe}
              >
                <SelectTrigger className="bg-surface-2 border-line text-fg font-mono text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface border-line text-fg">
                  {pipeline.timeframeOptions.map((tf) => (
                    <SelectItem key={tf || "all"} value={tf} className="font-mono">
                      {tf === "" ? "— tutti —" : tf}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Limite ingest</label>
              <Input
                type="number"
                min={1}
                className="bg-surface-2 border-line text-fg font-mono text-sm"
                value={pipeline.ingestLimit}
                onChange={(e) => pipeline.setIngestLimit(Number(e.target.value))}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Limite extract</label>
              <Input
                type="number"
                min={1}
                className="bg-surface-2 border-line text-fg font-mono text-sm"
                value={pipeline.extractLimit}
                onChange={(e) => pipeline.setExtractLimit(Number(e.target.value))}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-fg-2">Lookback</label>
              <Input
                type="number"
                min={3}
                className="w-24 bg-surface-2 border-line text-fg font-mono text-sm"
                value={pipeline.lookback}
                onChange={(e) => pipeline.setLookback(Number(e.target.value))}
              />
            </div>
          </div>

          {/* Action: confirm dialog nested */}
          <div className="flex justify-end gap-3 border-t border-line pt-4">
            <Button
              variant="ghost"
              size="sm"
              className="text-fg-2"
              onClick={pipeline.closeDialog}
            >
              Annulla
            </Button>

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  size="sm"
                  className={cn(
                    "bg-fg text-canvas hover:bg-fg/90",
                    pipeline.isRefreshing && "opacity-50 pointer-events-none",
                  )}
                  disabled={pipeline.isRefreshing}
                >
                  {pipeline.isRefreshing ? "Elaborazione…" : "Rigenera segnali"}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="bg-surface border-line text-fg">
                <AlertDialogHeader>
                  <AlertDialogTitle className="text-fg">
                    Conferma rigenerazione pipeline
                  </AlertDialogTitle>
                  <AlertDialogDescription className="text-fg-2">
                    Verrà eseguita la pipeline completa (ingest → features → context →
                    patterns). L&apos;operazione può richiedere alcuni minuti e aggiornerà
                    tutti i segnali. Continuare?
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel className="bg-surface-2 border-line text-fg hover:bg-surface-3">
                    Annulla
                  </AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-fg text-canvas hover:bg-fg/90"
                    onClick={() => void pipeline.refresh()}
                  >
                    Avvia pipeline
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
