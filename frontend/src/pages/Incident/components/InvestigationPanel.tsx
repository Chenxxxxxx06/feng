interface Props {
  data: any;
}

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  running: '执行中',
  failed: '已失败',
  degraded: '降级',
  pending: '待执行',
};

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  completed: { bg: 'rgba(16,185,129,0.08)', color: 'var(--accent-green)' },
  running: { bg: 'rgba(59,130,246,0.10)', color: 'var(--accent-blue)' },
  failed: { bg: 'rgba(239,68,68,0.08)', color: 'var(--accent-red)' },
  degraded: { bg: 'rgba(245,158,11,0.08)', color: 'var(--accent-yellow)' },
};

export default function InvestigationPanel({ data }: Props) {
  if (!data || !data.steps) return null;

  const steps = data.steps || [];
  const completed = steps.filter((s: any) => s.status === 'completed').length;
  const degraded = steps.filter((s: any) => s.degraded).length;
  const pct = (completed / Math.max(steps.length, 1)) * 100;
  const barColor = data.status === 'completed'
    ? 'var(--accent-green)'
    : data.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-blue)';

  return (
    <div className="surface-card space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="section-title">
          自主调查进度：<span className="num">{completed}/{steps.length}</span> 步骤
        </h3>
        <div className="flex flex-wrap gap-2">
          <span className={`badge ${data.status === 'completed' ? 'badge-success' : data.status === 'failed' ? 'badge-danger' : 'badge-info'}`}>
            {STATUS_LABEL[data.status] || data.status}
          </span>
          {degraded > 0 && <span className="badge badge-warning"><span className="num">{degraded}</span> 步骤降级</span>}
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="h-2 w-full overflow-hidden rounded-full"
        style={{ background: 'rgba(59,130,246,0.12)' }}
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="自主调查完成度"
      >
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: barColor }} />
      </div>

      {/* Step list */}
      <ol className="space-y-1">
        {steps.map((step: any, idx: number) => {
          const s = STATUS_STYLE[step.status];
          return (
            <li
              key={step.step_id}
              className="flex items-center gap-3 rounded-md px-2.5 py-1.5 text-[11px] transition-colors"
              style={{ background: s?.bg, color: s?.color || 'var(--text-muted)' }}
              title={step.output_summary || step.step_name}
            >
              <span className="num w-5 flex-shrink-0 text-right opacity-70" aria-hidden="true">{idx + 1}</span>
              <span className="flex-1 truncate">{step.step_name}</span>
              <span className="flex-shrink-0 text-[10px] font-semibold">{STATUS_LABEL[step.status] || step.status}</span>
              {step.output_summary && (
                <span className="hidden max-w-xs flex-shrink truncate text-[10px] text-text-muted lg:block">
                  {step.output_summary}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {data.trace_id && (
        <p className="text-[10px] text-text-muted">
          Trace：<code className="num" title={data.trace_id}>{data.trace_id}</code>
        </p>
      )}
    </div>
  );
}
