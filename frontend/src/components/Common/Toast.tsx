import { useEffect, useState } from 'react';

/**
 * 轻量全局提示（Toast）—— 零第三方依赖。
 *
 * 用法：
 *   import { toast } from '../../components/Common/Toast';
 *   toast.success('工单已创建', 'WO-0012 已分配给张伟');
 *   toast.error('保存失败', err.message);
 *
 * <ToastHost /> 只需在 AppLayout 挂载一次。
 */

export type ToastKind = 'success' | 'error' | 'warning' | 'info';

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  desc?: string;
  duration: number;
}

type Listener = (items: ToastItem[]) => void;

let seq = 0;
let items: ToastItem[] = [];
const listeners = new Set<Listener>();

function emit() {
  const snapshot = [...items];
  listeners.forEach((fn) => fn(snapshot));
}

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

function push(kind: ToastKind, title: string, desc?: string, duration = 3600): number {
  const id = ++seq;
  items = [...items, { id, kind, title, desc, duration }].slice(-4);
  emit();
  if (duration > 0) window.setTimeout(() => dismiss(id), duration);
  return id;
}

export const toast = {
  success: (title: string, desc?: string, duration?: number) => push('success', title, desc, duration),
  error: (title: string, desc?: string, duration?: number) => push('error', title, desc, duration ?? 5200),
  warning: (title: string, desc?: string, duration?: number) => push('warning', title, desc, duration ?? 4400),
  info: (title: string, desc?: string, duration?: number) => push('info', title, desc, duration),
  dismiss,
};

/** 把任意异常转成可读中文提示（后端 detail 优先） */
export function describeError(err: unknown, fallback = '操作失败，请稍后重试'): string {
  const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string } | undefined;
  const detail = anyErr?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (anyErr?.message) return anyErr.message;
  return fallback;
}

const ICONS: Record<ToastKind, JSX.Element> = {
  success: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><polyline points="8 12.5 11 15.5 16 9" />
    </svg>
  ),
  error: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  warning: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  info: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="11" x2="12" y2="16" /><line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
};

const KIND_COLOR: Record<ToastKind, string> = {
  success: 'var(--accent-green)',
  error: 'var(--accent-red)',
  warning: 'var(--accent-yellow)',
  info: 'var(--accent-blue)',
};

const KIND_LABEL: Record<ToastKind, string> = {
  success: '成功',
  error: '错误',
  warning: '警告',
  info: '提示',
};

export default function ToastHost() {
  const [list, setList] = useState<ToastItem[]>(items);

  useEffect(() => {
    listeners.add(setList);
    return () => { listeners.delete(setList); };
  }, []);

  if (list.length === 0) return null;

  return (
    <div className="toast-host" role="status" aria-live="polite" aria-atomic="false">
      {list.map((item) => (
        <div key={item.id} className={`toast-item toast-${item.kind}`}>
          <span className="mt-[1px] flex-shrink-0" style={{ color: KIND_COLOR[item.kind] }} aria-hidden="true">
            {ICONS[item.kind]}
          </span>
          <div className="min-w-0 flex-1">
            <p className="toast-title">
              <span className="sr-only">{KIND_LABEL[item.kind]}：</span>
              {item.title}
            </p>
            {item.desc && <p className="toast-desc">{item.desc}</p>}
          </div>
          <button
            type="button"
            onClick={() => dismiss(item.id)}
            aria-label="关闭提示"
            className="btn btn-ghost btn-icon btn-sm flex-shrink-0"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
