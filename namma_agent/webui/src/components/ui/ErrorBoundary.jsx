import { Component } from "react";

// Phase 9: one broken section must never blank the whole window. Wrap a
// region in this; if it throws while rendering, the region shows a short
// message with a retry button; the error goes to the console.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error(`[${this.props.name || "ui"}] render failed:`, error, info?.componentStack || "");
  }

  componentDidUpdate(prev) {
    // A different section (resetKey) gets a fresh start.
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="rounded-lg border border-danger/40 bg-surface p-4 text-sm">
        <p className="font-medium text-fg">{this.props.title || "This section couldn't be shown."}</p>
        <p className="mt-1 text-fg-muted break-words">{String(this.state.error?.message || this.state.error)}</p>
        <button type="button" onClick={() => this.setState({ error: null })}
                className="mt-3 h-8 px-3 rounded-md border border-border text-fg hover:bg-surface-hover">Try again</button>
      </div>
    );
  }
}
