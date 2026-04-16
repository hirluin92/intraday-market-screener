"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  /** If provided, shown as context in the error message */
  label?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Per-route / per-section error boundary.
 * Catches render errors and shows a recoverable UI instead of white screen.
 * The user can click "Riprova" to force a re-render.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", this.props.label ?? "unknown", error, info);
  }

  reset() {
    this.setState({ hasError: false, error: null });
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    return (
      <div
        className="flex flex-col items-center justify-center gap-4 rounded-lg border border-bear/30 bg-bear/5 p-8 text-center"
        role="alert"
      >
        <AlertTriangle className="h-8 w-8 text-bear" aria-hidden />
        <div>
          <p className="font-sans text-sm font-semibold text-fg">
            {this.props.label
              ? `Errore in "${this.props.label}"`
              : "Qualcosa è andato storto"}
          </p>
          {this.state.error?.message && (
            <p className="mt-1 font-mono text-xs text-fg-2">
              {this.state.error.message}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => this.reset()}
          className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-4 py-2 text-sm text-fg hover:border-line-hi transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral/50"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Riprova
        </button>
      </div>
    );
  }
}

/** Convenience wrapper for functional components */
export function withErrorBoundary<T extends object>(
  Component: React.ComponentType<T>,
  label?: string,
) {
  return function WithBoundary(props: T) {
    return (
      <ErrorBoundary label={label}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
