import type { ReactNode } from "react";

/**
 * Opportunities layout — global design system tokens from globals.css are
 * sufficient. The old .trader-dashboard scoped CSS was migrated to :root in
 * globals.css (Step 2) and trader-theme.css is now deleted.
 */
export default function OpportunitiesLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
