import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-full flex-col items-center justify-center gap-6 p-8">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          intraday-market-screener
        </h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Screening intraday — dashboard MVP.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/opportunities"
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          Apri opportunità
        </Link>
        <Link
          href="/backtest"
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          Backtest pattern
        </Link>
        <Link
          href="/trade-plan-lab"
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          Trade plan lab
        </Link>
        <Link
          href="/diagnostica"
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          Diagnostica
        </Link>
      </div>
    </main>
  );
}
