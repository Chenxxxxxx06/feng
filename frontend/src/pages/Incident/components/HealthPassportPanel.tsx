import { useCallback, useEffect, useMemo, useState } from 'react';
import { getHealthPassport } from '../../../services/incidentService';

interface Props {
  turbineId: number;
  turbineName?: string;
}

type TimelineKind = 'incident' | 'fault' | 'work_order' | 'rul';

interface TimelineEntry {
  kind: TimelineKind;
  time: number;
  timeLabel: string;
  title: string;
  detail: string;
  tone: string;
  badge: string;
}

const TREND_META: Record<string, { label: string; tone: string }> = {
  improving: { label: '↗ 改善中', tone: 'text-accent-green' },
  stable: { label: '→ 平稳', tone: 'text-accent-blue' },
  declining: { label: '↘ 恶化中', tone: 'text-accent-orange' },
  critical: { label: '⚠ 危急', tone: 'text-accent-red' },
};

const KIND_META: Record<TimelineKind, { icon: string; label: string; color: string }> = {
  incident: { icon: '🚨', label: '事件', color: '#EF4444' },
  fault: { icon: '🔧', label: '故障', color: '#F59E0B' },
  work_order: { icon: '📋', label: '工单', color: '#3B82F6' },
  rul: { icon: '⏳', label: 'RUL 预测', color: '#8B5CF6' },
};

function toTime(value?: string | null): number {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function label(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', { hour12: false });
}

/**
 * 健康数字护照（时间线卡片布局）
 * GET /api/turbines/{turbine_id}/health-passport
 * 跨事件数字主线：健康指数 → 事件 → 故障 → RUL → 维修 → Agent 决策 → 模型版本
 */
export default function HealthPassportPanel({ turbineId, turbineName }: Props) {
  const [passport, setPassport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | TimelineKind>('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getHealthPassport(turbineId);
      setPassport(result);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : e?.message || '健康护照加载失败');
    } finally {
      setLoading(false);
    }
  }, [turbineId]);

  useEffect(() => { void load(); }, [load]);

  const timeline = useMemo<TimelineEntry[]>(() => {
    if (!passport) return [];
    const entries: TimelineEntry[] = [];

    for (const item of passport.incidents || []) {
      entries.push({
        kind: 'incident',
        time: toTime(item.opened_at),
        timeLabel: label(item.opened_at),
        title: item.title || item.incident_id,
        detail: `${item.incident_id} · 严重度 ${item.severity} · 阶段 ${item.stage}${item.trace_id ? ` · trace ${item.trace_id}` : ''}`,
        tone: item.severity === 'critical' ? 'text-accent-red' : 'text-text-primary',
        badge: item.status || item.stage,
      });
    }
    for (const item of passport.recent_faults || []) {
      entries.push({
        kind: 'fault',
        time: toTime(item.detected_at),
        timeLabel: label(item.detected_at),
        title: item.fault_type,
        detail: `置信 ${((item.confidence || 0) * 100).toFixed(0)}% · 优先级 ${item.priority || '—'} · 处理人 ${item.handler || '未分配'}`,
        tone: 'text-text-primary',
        badge: item.status || '—',
      });
    }
    for (const item of passport.maintenance_history || []) {
      entries.push({
        kind: 'work_order',
        time: toTime(item.completed_at || item.created_at),
        timeLabel: label(item.completed_at || item.created_at),
        title: item.title,
        detail: `${item.assignee || '未指派'} · 成本 ¥${(item.cost_actual ?? item.cost_estimate ?? 0).toLocaleString('zh-CN')} · 停机 ${item.downtime_hours ?? 0}h`,
        tone: 'text-text-primary',
        badge: item.status || '—',
      });
    }
    for (const item of passport.rul_predictions || []) {
      entries.push({
        kind: 'rul',
        time: toTime(item.predicted_at),
        timeLabel: label(item.predicted_at),
        title: `${item.component} 剩余寿命 ${item.remaining_life_days} 天`,
        detail: `置信区间 [${item.confidence_lower ?? '—'}, ${item.confidence_upper ?? '—'}] 天`,
        tone: 'text-text-primary',
        badge: 'RUL',
      });
    }

    return entries
      .filter((entry) => filter === 'all' || entry.kind === filter)
      .sort((a, b) => b.time - a.time);
  }, [passport, filter]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-24 w-full" />
        {[0, 1, 2, 3].map((index) => <div key={index} className="skeleton h-16 w-full" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-4 text-sm text-accent-red">
        ⚠ {error}
        <button onClick={() => { void load(); }} className="ml-3 underline">重试</button>
      </div>
    );
  }

  if (!passport) {
    return <div className="p-8 text-center text-sm text-text-muted">暂无健康护照数据</div>;
  }

  const trend = TREND_META[passport.health_trend] || TREND_META.stable;

  return (
    <div className="space-y-4">
      {/* 护照头 */}
      <div className="rounded-lg border border-accent-purple/30 bg-accent-purple/8 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-text-primary">
            🪪 {passport.turbine_name || turbineName || `风机 #${turbineId}`} 健康数字护照
          </span>
          <span className="rounded bg-bg-card px-2 py-0.5 text-[10px] text-text-muted">
            {passport.turbine_model || '型号未知'} · {passport.power_mw ?? '—'}MW · {passport.region || '—'}
          </span>
          <span className={`ml-auto text-xs font-semibold ${trend.tone}`}>{trend.label}</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
          <Tile
            label="当前健康指数"
            value={passport.current_health_index != null ? Number(passport.current_health_index).toFixed(1) : '—'}
            tone={Number(passport.current_health_index) < 70 ? 'text-accent-red' : 'text-accent-green'}
          />
          <Tile label="历史事件" value={String(passport.total_incidents ?? 0)} />
          <Tile label="历史故障" value={String(passport.total_faults ?? 0)} />
          <Tile label="维修工单" value={String(passport.total_work_orders ?? 0)} />
          <Tile
            label="累计维修成本"
            value={`¥${Number(passport.total_maintenance_cost || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`}
          />
        </div>
        {passport.commissioned_at && (
          <p className="mt-2 text-[10px] text-text-muted">投运时间 {label(passport.commissioned_at)}</p>
        )}
      </div>

      {/* 过滤 */}
      <div className="flex flex-wrap gap-1">
        {([['all', '全部'], ['incident', '🚨 事件'], ['fault', '🔧 故障'], ['work_order', '📋 工单'], ['rul', '⏳ RUL']] as const)
          .map(([key, text]) => (
            <button
              key={key}
              onClick={() => setFilter(key as 'all' | TimelineKind)}
              className={`rounded border px-2.5 py-1 text-[11px] transition-colors ${
                filter === key
                  ? 'border-accent-blue/45 bg-accent-blue/15 text-accent-blue'
                  : 'border-border-default text-text-muted hover:text-text-secondary'
              }`}
            >
              {text}
            </button>
          ))}
      </div>

      {/* 时间线 */}
      {timeline.length === 0 ? (
        <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-8 text-center text-sm text-text-muted">
          该风机暂无可展示的履历记录
        </div>
      ) : (
        <div className="relative space-y-2 pl-6">
          <span className="absolute left-[9px] top-2 bottom-2 w-px bg-border-default" />
          {timeline.map((entry, index) => {
            const meta = KIND_META[entry.kind];
            return (
              <div key={`${entry.kind}-${index}`} className="relative">
                <span
                  className="absolute -left-[21px] top-3 h-2.5 w-2.5 rounded-full"
                  style={{ background: meta.color, boxShadow: `0 0 8px ${meta.color}` }}
                />
                <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-3 transition-colors hover:border-border-active">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px]">{meta.icon}</span>
                    <span className={`text-[12px] font-medium ${entry.tone}`}>{entry.title}</span>
                    <span className="rounded bg-bg-card px-1.5 py-0.5 text-[9px] text-text-muted">{entry.badge}</span>
                    <span className="ml-auto font-mono text-[10px] text-text-muted">{entry.timeLabel}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-text-muted">{entry.detail}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Agent 决策履历 */}
      {Array.isArray(passport.agent_decisions) && passport.agent_decisions.length > 0 && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
          <h4 className="mb-2 text-xs font-semibold text-text-primary">🤖 Agent 决策履历</h4>
          <div className="space-y-1">
            {passport.agent_decisions.slice(0, 8).map((item: any, index: number) => (
              <div key={index} className="flex items-center gap-2 rounded bg-bg-primary/40 p-2 text-[10px]">
                <span className={`shrink-0 ${item.is_recommended ? 'text-accent-green' : 'text-text-muted'}`}>
                  {item.is_recommended ? '★推荐' : '候选'}
                </span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">
                  {item.plan_name} · {item.strategy}
                </span>
                <span className="shrink-0 font-mono text-text-muted">
                  分 {Number(item.total_score || 0).toFixed(0)} · 风险 {Number(item.safety_risk || 0).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 模型版本 */}
      {passport.model_versions && Object.keys(passport.model_versions).length > 0 && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
          <h4 className="mb-2 text-xs font-semibold text-text-primary">🧬 参与决策的模型版本</h4>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {Object.entries(passport.model_versions).map(([key, value]) => (
              <div key={key} className="rounded border border-border-default bg-bg-primary/40 p-2">
                <div className="truncate text-[10px] text-text-muted">{key}</div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-text-secondary">{String(value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-[10px] text-text-muted">生成时间 {passport.generated_at || '—'}</p>
    </div>
  );
}

function Tile({ label: text, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border-default bg-bg-secondary/50 p-2">
      <div className="text-[10px] text-text-muted">{text}</div>
      <div className={`mt-0.5 truncate font-mono text-base font-semibold ${tone || 'text-text-primary'}`}>{value}</div>
    </div>
  );
}
