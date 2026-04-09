import type { ReactNode } from "react";

import "./trader-theme.css";

export default function OpportunitiesLayout({ children }: { children: ReactNode }) {
  return (
    <div className="trader-dashboard min-h-[calc(100vh-3rem)] bg-[var(--bg-base)] text-[var(--text-primary)] antialiased">
      {children}
    </div>
  );
}
