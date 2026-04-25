"use client";

import { Component, type ReactNode } from "react";

interface Props {
  label: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Per-section error boundary so a single panel failure (e.g. /api/state/today
 * 500s) doesn't lock the whole dashboard in a skeleton state.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    if (typeof console !== "undefined") {
      console.error(`[${this.props.label}]`, error);
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div
          className="shc-card p-4 text-[11.5px]"
          style={{
            background: "var(--negative-soft)",
            borderColor: "var(--negative)",
          }}
        >
          <div className="flex items-baseline justify-between mb-1">
            <span className="font-medium text-[var(--text-primary)]">
              {this.props.label} failed to render
            </span>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="text-[10px] underline text-[var(--text-muted)]"
            >
              retry
            </button>
          </div>
          <code className="text-[10.5px] text-[var(--text-muted)] break-all">
            {this.state.error.message}
          </code>
        </div>
      );
    }
    return this.props.children;
  }
}
