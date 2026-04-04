import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Opportunità | intraday-market-screener",
  description: "Dashboard opportunità dello screener",
};

export default function OpportunitiesLayout({ children }: { children: ReactNode }) {
  return children;
}
