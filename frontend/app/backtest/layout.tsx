import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Backtest | intraday-market-screener",
  description: "Aggregati rendimenti a termine dei pattern",
};

export default function BacktestLayout({ children }: { children: ReactNode }) {
  return children;
}
