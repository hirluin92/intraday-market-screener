import type { Metadata } from "next";
import { Geist, Geist_Mono, Space_Mono, Syne } from "next/font/google";

import { IBKRStatusBanner } from "@/components/IBKRStatusBanner";
import { AppShell } from "@/components/shell/AppShell";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

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

export const metadata: Metadata = {
  title: "Intraday Market Screener",
  description: "Applicazione di screening di mercato intraday",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="it"
      className={`${geistSans.variable} ${geistMono.variable} ${syne.variable} ${spaceMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-screen flex-col bg-canvas text-fg">
        <Providers>
          {/* IBKRStatusBanner: conditional, sticky top-0 z-50, only shown when offline */}
          <IBKRStatusBanner />

          {/* AppShell: sidebar + topbar + main content */}
          <AppShell>
            {children}
          </AppShell>
        </Providers>
      </body>
    </html>
  );
}
