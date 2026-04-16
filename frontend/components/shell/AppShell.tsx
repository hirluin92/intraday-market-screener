import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

interface AppShellProps {
  children: React.ReactNode;
  /** Optional regime passed from layout (available after opportunities query). */
  regime?: string | null;
}

/**
 * Application shell — wraps every page with sidebar + topbar layout.
 *
 * Layout structure:
 * ┌──────────┬─────────────────────────────────────┐
 * │ Sidebar  │ Topbar (sticky top-0)               │
 * │ (desktop)├─────────────────────────────────────┤
 * │          │ Main content (overflow-y-auto)       │
 * └──────────┴─────────────────────────────────────┘
 *
 * Mobile (<lg): Sidebar hidden, MobileDrawer triggered from Topbar.
 *
 * Note: This is a Server Component. Sidebar and Topbar are Client
 * Components imported inside, which is valid in Next.js App Router.
 */
export function AppShell({ children, regime }: AppShellProps) {
  return (
    <div className="flex flex-1 overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar regime={regime} />
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
