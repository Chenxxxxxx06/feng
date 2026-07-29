import type { AgentActionConfirmation } from '../../services/agentTraceService';

interface Props {
  confirmation: AgentActionConfirmation;
  requestId: string;
  action?: string | null;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function renderDiff(before: Record<string, unknown>, after: Record<string, unknown>) {
  const keys = Array.from(new Set([...Object.keys(before || {}), ...Object.keys(after || {})]));
  if (keys.length === 0) return null;
  return (
    <div className="mt-2 overflow-hidden rounded border border-border-default">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] bg-bg-secondary/70 px-2 py-1 text-[9px] font-semibold text-text-muted">
        <span>字段</span><span>变更前</span><span>变更后</span>
      </div>
      {keys.slice(0, 8).map((key) => {
        const beforeValue = before?.[key];
        const afterValue = after?.[key];
        const changed = JSON.stringify(beforeValue) !== JSON.stringify(afterValue);
        return (
          <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] border-t border-border-subtle px-2 py-1 text-[10px]">
            <span className="truncate text-text-secondary">{key}</span>
            <span className="truncate font-mono text-text-muted">{formatValue(beforeValue)}</span>
            <span className={`truncate font-mono ${changed ? 'text-accent-green' : 'text-text-muted'}`}>
              {formatValue(afterValue)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 40);
  return String(value);
}

/**
 * 守护步骤的真实确认卡 —— 对接后端两阶段确认：
 * POST /api/agent-actions/{request_id}/confirm | /cancel
 * 未点确认前，后端不会写入任何数据。
 */
export default function GuardConfirmCard({
  confirmation, requestId, action, busy, onConfirm, onCancel,
}: Props) {
  return (
    <div className="rounded-lg border border-accent-yellow/45 bg-accent-yellow/8 p-2.5">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px]">🛡</span>
        <span className="text-[11px] font-semibold text-accent-yellow">守护拦截 · 需人工确认</span>
        <span className="ml-auto rounded bg-accent-red/15 px-1.5 py-0.5 text-[9px] text-accent-red">
          require_confirmation
        </span>
      </div>

      <p className="mt-1.5 text-[11px] font-medium text-text-primary">{confirmation.title}</p>
      <p className="mt-0.5 text-[10px] leading-4 text-text-secondary">{confirmation.summary}</p>

      {renderDiff(confirmation.before || {}, confirmation.after || {})}

      {confirmation.warnings?.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {confirmation.warnings.map((warning, index) => (
            <li key={index} className="flex gap-1 text-[10px] text-accent-orange">
              <span>⚠</span><span className="min-w-0 flex-1">{warning}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={onConfirm}
          disabled={busy}
          className="rounded border border-accent-green/40 bg-accent-green/15 px-3 py-1 text-[11px] font-semibold text-accent-green transition-colors hover:bg-accent-green/25 disabled:opacity-50"
        >
          {busy ? '执行中…' : '确认执行'}
        </button>
        <button
          onClick={onCancel}
          disabled={busy}
          className="rounded border border-border-default bg-bg-secondary/70 px-3 py-1 text-[11px] text-text-secondary transition-colors hover:text-text-primary disabled:opacity-50"
        >
          取消
        </button>
        <span className="ml-auto truncate font-mono text-[9px] text-text-muted" title={requestId}>
          {action || 'action'} · {requestId.slice(0, 12)}
        </span>
      </div>
    </div>
  );
}
