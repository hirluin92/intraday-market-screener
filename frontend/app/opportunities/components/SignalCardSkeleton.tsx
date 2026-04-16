import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function SignalCardSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface p-4 space-y-3",
        className,
      )}
      aria-busy="true"
      aria-label="Caricamento segnale…"
    >
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-5 w-14 rounded-md" />
          <Skeleton className="h-5 w-16 rounded-md" />
          <Skeleton className="h-5 w-20 rounded-md" />
        </div>
        <Skeleton className="h-6 w-16 rounded-md" />
      </div>
      {/* Symbol */}
      <Skeleton className="h-7 w-24" />
      <Skeleton className="h-4 w-32" />
      {/* Prices */}
      <div className="grid grid-cols-4 gap-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-3 w-8" />
            <Skeleton className="h-5 w-14" />
          </div>
        ))}
      </div>
      {/* Strength bar */}
      <div className="space-y-1">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-2 w-full" />
      </div>
    </div>
  );
}
