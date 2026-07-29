import { useMemo, useState } from 'react';
import {
  SEGMENT_META, formatClock, formatDuration, inferSegment,
} from '../../services/agentTraceService';
import type { AgentSegment } from '../../services/agentTraceService';
import type { AgentSpan, AgentTrace } from '../../types';

interface Props {
  trace: AgentTrace;
}

interface Row {
  span: AgentSpan;
  segment: AgentSegment;
  leftPct: number;
  widthPct: number;
  offsetMs: number;
}

const MIN_WIDTH_PCT = 1.2;

function buildRows(spans: AgentSpan[]): { rows: Row[]; windowMs: number; sequential: boolean } {
  if (spans.length === 0) return { rows: [], windowMs: 0, sequential: false };

  const ordered = [...spans].sort((a, b) => {
    const orderDiff = (a.step_order ?? 0) - (b.step_order ?? 0);
    if (orderDiff !== 0) return orderDiff;
    return new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
  });

  const starts = ordered.map((span) => new Date(span.started_at).getTime());
  const valid = starts.filter((value) => Number.isFinite(value));
  const t0 = valid.length ? Math.min(...valid) : 0;
  const ends = ordered.map((span, index) => {
    const start = Number.isFinite(starts[index]) ? starts[index] : t0;
    const explicit = span.ended_at ? new Date(span.ended_at).getTime() : NaN;
    return Number.isFinite(explicit) ? explicit : start + (Number(span.duration_ms) || 0);
  });
  const windowMs = Math.max(...ends) - t0;

  // 全部 span 时间戳几乎相同（duration 记为 0）时退化为等宽顺序布局
  if (!Number.isFinite(windowMs) || windowMs <= 0) {
    const slot = 100 / ordered.length;
    return {
      sequential: true,
      windowMs: 0,
      rows: ordered.map((span, index) => ({
        span,
        segment: inferSegment(span),
        leftPct: index * slot,
        widthPct: Math.max(slot - 0.6, MIN_WIDTH_PCT),
        offsetMs: 0,
      })),
    };
  }

  return {
    sequential: false,
    windowMs,
    rows: ordered.map((span, index) => {
      const start = Number.isFinite(starts[index]) ? starts[index] : t0;
      const offsetMs = start - t0;
      const duration = Math.max(ends[index] - start, 0);
      return {
        span,
        segment: inferSegment(span),
        offsetMs,
        leftPct: Math.min((offsetMs / windowMs) * 100, 99),
        widthPct: Math.max((duration / windowMs) * 100, MIN_WIDTH_PCT),
      };
    }),
  };
}

/**
 * Agent 飞行记录瀑布图。
 * 横条 = span 时长；颜色 = 六段类型；policy_decision=denied 标红；approval_by 标黄菱形。
 */
export default function TraceWaterfall({ trace }: Props) {
  const [activeSpanId, setActiveSpanId] = useState<string | null>(null);
  const { rows, windowMs, sequential } = useMemo(
    () => buildRows(trace.spans || []),
    [trace],
  );

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-8 text-center">
        <div className="text-2xl">🛬</div>
        <p className="mt-2 text-sm text-text-muted">该航段暂无 span 记录</p>
        <p className="mt-1 text-xs text-text-muted">
          事件执行「自主调查 / 状态推进」后，飞行记录器会自动写入 span。
        </p>
      </div>
    );
  }

  const activeSpan = rows.find((row) => row.span.span_id === activeSpanId)?.span || null;

  return (
    <div className="space-y-3">
      {/* 时间轴刻度 */}
      <div className="flex items-center justify-between text-[10px] text-text-muted">
        <span className="font-mono">{formatClock(trace.started_at)}</span>
        <span>
          {sequential ? '时间窗为 0（span 为瞬时记录），按步序等宽展示' : `窗口 ${formatDuration(windowMs)}`}
        </span>
        <span className="font-mono">{trace.ended_at ? formatClock(trace.ended_at) : '进行中'}</span>
      </div>

      <div className="space-y-1">
        {rows.map((row) => {
          const meta = SEGMENT_META[row.segment];
          const denied = row.span.policy_decision === 'denied';
          const failed = row.span.status === 'failed' || row.span.status === 'error';
          const barColor = denied || failed ? '#EF4444' : meta.color;
          const isActive = row.span.span_id === activeSpanId;
          return (
            <button
              key={row.span.span_id}
              onClick={() => setActiveSpanId(isActive ? null : row.span.span_id)}
              className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition-colors ${
                isActive ? 'bg-bg-active' : 'hover:bg-bg-hover'
              }`}
            >
              <span className="w-6 shrink-0 text-right font-mono text-[10px] text-text-muted">
                {row.span.step_order}
              </span>
              <span
                className="w-[168px] shrink-0 truncate text-[11px]"
                style={{ color: denied || failed ? '#EF4444' : undefined }}
                title={row.span.span_name}
              >
                <span className="mr-1">{meta.icon}</span>
                {row.span.span_name}
              </span>

              <span className="relative h-4 min-w-0 flex-1 rounded bg-bg-secondary/60">
                <span
                  className="absolute top-0.5 h-3 rounded-sm"
                  style={{
                    left: `${row.leftPct}%`,
                    width: `${Math.min(row.widthPct, 100 - row.leftPct)}%`,
                    background: barColor,
                    opacity: denied || failed ? 0.95 : 0.8,
                    boxShadow: denied ? '0 0 10px rgba(239,68,68,0.55)' : undefined,
                  }}
                />
                {row.span.approval_by && (
                  <span
                    className="absolute top-[3px] h-2.5 w-2.5 rotate-45 border border-[#0A1F3F]"
                    style={{
                      left: `calc(${Math.min(row.leftPct + row.widthPct, 99)}% - 5px)`,
                      background: '#F59E0B',
                      boxShadow: '0 0 8px rgba(245,158,11,0.6)',
                    }}
                    title={`人工审批：${row.span.approval_by}`}
                  />
                )}
              </span>

              <span className="w-16 shrink-0 text-right font-mono text-[10px] text-text-muted">
                {formatDuration(row.span.duration_ms)}
              </span>
              {denied ? (
                <span className="w-14 shrink-0 rounded bg-accent-red/20 text-center text-[9px] text-accent-red">denied</span>
              ) : row.span.policy_decision ? (
                <span className="w-14 shrink-0 rounded bg-accent-green/15 text-center text-[9px] text-accent-green">
                  {row.span.policy_decision}
                </span>
              ) : (
                <span className="w-14 shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      {/* 图例 */}
      <div className="flex flex-wrap items-center gap-3 border-t border-border-subtle pt-2 text-[10px] text-text-muted">
        {(Object.keys(SEGMENT_META) as AgentSegment[]).map((segment) => (
          <span key={segment} className="flex items-center gap-1">
            <span className="h-2 w-3 rounded-sm" style={{ background: SEGMENT_META[segment].color }} />
            {SEGMENT_META[segment].label}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="h-2.5 w-2.5 rotate-45" style={{ background: '#F59E0B' }} />
          人工审批
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm" style={{ background: '#EF4444' }} />
          策略拦截 / 失败
        </span>
      </div>

      {/* span 详情 */}
      {activeSpan && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/50 p-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text-primary">{activeSpan.span_name}</span>
            <span className="rounded bg-bg-card px-1.5 py-0.5 font-mono text-[9px] text-text-muted">
              {activeSpan.span_id}
            </span>
            <span className={`ml-auto rounded px-1.5 py-0.5 text-[9px] ${
              activeSpan.status === 'completed'
                ? 'bg-accent-green/15 text-accent-green'
                : activeSpan.status === 'failed'
                  ? 'bg-accent-red/15 text-accent-red'
                  : 'bg-accent-yellow/15 text-accent-yellow'
            }`}>
              {activeSpan.status}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
            <Field label="Agent" value={activeSpan.agent_name} />
            <Field label="工具" value={activeSpan.tool_name} />
            <Field label="策略判定" value={activeSpan.policy_decision} />
            <Field label="审批人" value={activeSpan.approval_by} />
            <Field label="开始" value={formatClock(activeSpan.started_at)} />
            <Field label="结束" value={activeSpan.ended_at ? formatClock(activeSpan.ended_at) : '进行中'} />
            <Field label="错误码" value={activeSpan.error_code} />
            <Field label="耗时" value={formatDuration(activeSpan.duration_ms)} />
          </div>
          <div className="mt-2 space-y-1">
            <Digest label="输入摘要" value={activeSpan.input_digest} />
            <Digest label="输出摘要" value={activeSpan.output_digest} />
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex gap-2">
      <span className="w-14 shrink-0 text-text-muted">{label}</span>
      <span className="min-w-0 flex-1 truncate text-text-secondary">{value || '—'}</span>
    </div>
  );
}

function Digest({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="rounded border border-border-subtle bg-bg-primary/40 p-1.5">
      <p className="text-[9px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="mt-0.5 break-words font-mono text-[10px] leading-4 text-text-secondary">{value}</p>
    </div>
  );
}
