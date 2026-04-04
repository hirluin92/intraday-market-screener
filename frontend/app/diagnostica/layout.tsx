import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Diagnostica | intraday-market-screener",
  description: "Panoramica comportamento screener e pattern",
};

export default function DiagnosticaLayout({ children }: { children: ReactNode }) {
  return children;
}
