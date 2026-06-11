import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean; error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[SYS::ERROR]', error.message, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex flex-col items-center justify-center h-64 gap-4" style={{ color: '#8899AA', fontSize: '13px' }}>
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#FF1744" strokeWidth="1.2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <p style={{ fontFamily: '"Rajdhani",sans-serif', fontSize: '18px' }}>SYSTEM MALFUNCTION</p>
          <p className="font-mono text-[10px] px-3 py-1.5 max-w-lg truncate" style={{ background: 'rgba(255,23,68,0.04)', border: '1px solid rgba(255,23,68,0.12)', color: '#FF1744', borderRadius: '2px' }}>
            {this.state.error?.message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="btn-prime text-xs"
          >
            RETRY
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
