import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[ErrorBoundary]', error.message, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="flex flex-col items-center justify-center h-64 text-text-muted text-sm gap-3">
            <span className="text-2xl">⚠</span>
            <p>页面渲染出错</p>
            <p className="text-xs font-mono bg-bg-card rounded px-3 py-1.5 max-w-lg truncate">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-4 py-1.5 border border-border-default rounded text-xs hover:border-accent-blue hover:text-accent-blue transition-colors"
            >
              重试
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
