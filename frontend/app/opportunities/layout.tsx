import type { ReactNode } from "react";
import { Space_Mono, Syne } from "next/font/google";

import "./trader-theme.css";

const syne = Syne({
  subsets: ["latin"],
  variable: "--font-trader-sans",
  display: "swap",
  weight: ["400", "600", "700", "800"],
});

const spaceMono = Space_Mono({
  subsets: ["latin"],
  variable: "--font-trader-mono",
  display: "swap",
  weight: ["400", "700"],
});

export default function OpportunitiesLayout({ children }: { children: ReactNode }) {
  return (
    <div
      className={`trader-dashboard ${syne.variable} ${spaceMono.variable} min-h-[calc(100vh-3rem)] bg-[var(--bg-base)] text-[var(--text-primary)] antialiased`}
    >
      {children}
    </div>
  );
}
