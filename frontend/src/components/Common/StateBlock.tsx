import type { ReactNode } from 'react';

/**
 * 空态 / 错误态 / 加载态的统一呈现。
 * 三态共用同一版式（图标 + 主文案 + 说明 + 可选操作），保证跨页面观感一致。
 */

export type StateKind = 'empty' | 'error' | 'loading';

interface StateBlockProps {
  kind: StateKind;
  /** 主文案，未传时按类型取默认值 */
  title?: string;
  /** 补充说明，建议写清楚"为什么没有数据 / 下一步该做什么" */
  desc?: string;
  /** 重试回调；传入后自动渲染「重试」按钮 */
  onRetry?: () => void;
  retryLabel?: string;
  /** 自定义操作区（例如「新建工单」） */
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}

const DEFAULT_TITLE: Record<StateKind, string> = {
  empty: '暂无数据',
  error: '数据加载失败',
  loading: '数据加载中',
};

const EmptyIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <line x1="3" y1="9" x2="21" y2="9" /><line x1="9" y1="20" x2="9" y2="9" />
  </svg>
);

const ErrorIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

export default function StateBlock({
  kind,
  title,
  desc,
  onRetry,
  retryLabel = '重试',
  action,
  className = '',
  compact = false,
}: StateBlockProps) {
  return (
    <div
      className={`state-block state-${kind} ${className}`}
      style={compact ? { minHeight: 60, padding: '12px 10px' } : undefined}
      role={kind === 'error' ? 'alert' : 'status'}
      aria-live={kind === 'loading' ? 'polite' : 'off'}
    >
      <span className="state-block-icon" aria-hidden="true">
        {kind === 'loading' ? <span className="state-spinner" /> : kind === 'error' ? ErrorIcon : EmptyIcon}
      </span>
      <p className="state-block-title">{title ?? DEFAULT_TITLE[kind]}</p>
      {desc && <p className="state-block-desc">{desc}</p>}
      {(onRetry || action) && (
        <div className="mt-1 flex items-center gap-2">
          {onRetry && (
            <button type="button" onClick={onRetry} className="btn btn-secondary btn-sm">
              {retryLabel}
            </button>
          )}
          {action}
        </div>
      )}
    </div>
  );
}
