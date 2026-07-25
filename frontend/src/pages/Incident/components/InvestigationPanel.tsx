interface Props {
  data: any;
}

const STEP_ICONS: Record<string, string> = {
  init_trace: '🔍',
  collect_scada: '📡',
  collect_alarms: '🔔',
  vibration_diagnosis: '📊',
  health_diagnosis: '💚',
  query_rul: '⏳',
  query_similar_cases: '📚',
  build_hypotheses: '💡',
  evaluate_evidence: '⚖️',
  transition_decision: '🎯',
};

export default function InvestigationPanel({ data }: Props) {
  if (!data || !data.steps) return null;

  const steps = data.steps || [];
  const completed = steps.filter((s: any) => s.status === 'completed').length;
  const degraded = steps.filter((s: any) => s.degraded).length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">
          🔍 自主调查进度: {completed}/{steps.length} 步骤
        </h3>
        <div className="flex gap-2 text-xs">
          <span className={`px-2 py-0.5 rounded ${
            data.status === 'completed' ? 'bg-emerald-600/30 text-emerald-300' :
            data.status === 'failed' ? 'bg-red-600/30 text-red-300' :
            'bg-blue-600/30 text-blue-300'
          }`}>
            {data.status}
          </span>
          {degraded > 0 && (
            <span className="px-2 py-0.5 rounded bg-yellow-600/30 text-yellow-300">
              {degraded} 步骤降级
            </span>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-slate-700/50 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-500 ${
            data.status === 'completed' ? 'bg-emerald-500' :
            data.status === 'failed' ? 'bg-red-500' : 'bg-blue-500'
          }`}
          style={{ width: `${(completed / Math.max(steps.length, 1)) * 100}%` }}
        />
      </div>

      {/* Step list */}
      <div className="space-y-1">
        {steps.map((step: any) => (
          <div key={step.step_id}
            className={`flex items-center gap-3 p-2 rounded text-sm transition-colors ${
              step.status === 'completed' ? 'bg-emerald-950/10 text-emerald-200' :
              step.status === 'running' ? 'bg-blue-950/20 text-blue-200' :
              step.status === 'failed' ? 'bg-red-950/10 text-red-200' :
              step.status === 'degraded' ? 'bg-yellow-950/10 text-yellow-200' :
              'text-slate-500'
            }`}>
            <span className="text-lg">{STEP_ICONS[step.step_id] || '○'}</span>
            <span className="flex-1">{step.step_name}</span>
            <span className="text-xs text-slate-600">
              {step.status === 'completed' ? '✓' :
               step.status === 'failed' ? '✗' :
               step.status === 'degraded' ? '⚠ 降级' :
               step.status === 'running' ? '⏳' : '○'}
            </span>
            {step.output_summary && (
              <span className="text-xs text-slate-400 truncate max-w-xs hidden lg:block">
                {step.output_summary}
              </span>
            )}
          </div>
        ))}
      </div>

      {data.trace_id && (
        <div className="text-xs text-slate-600">
          Trace: <code>{data.trace_id}</code>
        </div>
      )}
    </div>
  );
}
