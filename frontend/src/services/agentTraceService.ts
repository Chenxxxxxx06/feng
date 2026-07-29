/**
 * Agent 玻璃驾驶舱 / 飞行记录器 数据服务
 *
 * 对应后端：
 *   POST /api/agent-tasks/plan              统一任务规划（读任务直接作答，写任务返回待确认）
 *   POST /api/agent-tasks/{plan_id}/cancel  取消追问计划
 *   POST /api/agent-actions/plan            动作网关规划（两阶段确认第一阶段）
 *   POST /api/agent-actions/{rid}/confirm   两阶段确认第二阶段 — 真正写库
 *   POST /api/agent-actions/{rid}/cancel    放弃写操作
 *   GET  /api/incidents/{id}/trace          事件级飞行记录（trace + spans）
 *   POST /api/incidents/{id}/trace/start    新建飞行记录会话
 *
 * 说明：后端目前没有「按 trace_id 直接查 span」或「全局 trace 列表」端点，
 * 飞行记录器页面通过 GET /api/incidents 拿事件列表后逐个拉取事件级 trace 聚合。
 */

import api from './api';
import type { AgentSpan, AgentTrace, Incident } from '../types';

// ══════════════════════════════════════════════════════════
// 后端 schema 镜像
// ══════════════════════════════════════════════════════════

export interface AgentActionConfirmation {
  title: string;
  summary: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  warnings: string[];
}

export interface AgentTaskStep {
  order: number;
  step: string;
  type: string;
  status: string;
  description?: string;
}

export interface AgentTaskCandidate {
  id: string;
  name: string;
  category: string;
  implementation_status?: string | null;
  task_kind: string;
  score?: number | null;
}

export interface AgentTaskPlanResponse {
  status: 'answered' | 'pending_confirmation' | 'needs_clarification' | 'unsupported' | 'error';
  task_type?: string | null;
  task_kind?: string | null;
  planner_source?: string | null;
  plan_id?: string | null;
  playbook_id?: string | null;
  workflow?: string | null;
  action?: string | null;
  request_id?: string | null;
  confidence?: number;
  answer?: string | null;
  slots?: Record<string, unknown>;
  steps?: AgentTaskStep[];
  candidates?: AgentTaskCandidate[];
  display?: Record<string, any> | null;
  confirmation?: AgentActionConfirmation | null;
  missing_slots?: string[];
  clarification_question?: string | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface AgentActionConfirmResponse {
  request_id: string;
  action: string;
  status: string;
  result?: Record<string, any> | null;
  display?: Record<string, any> | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface AgentTaskCancelResponse {
  plan_id: string;
  status: string;
  error_code?: string | null;
  error_message?: string | null;
}

// ══════════════════════════════════════════════════════════
// 六段式语义（read → infer → validate → guard → write → verify）
// ══════════════════════════════════════════════════════════

export type AgentSegment =
  | 'read' | 'infer' | 'validate' | 'guard' | 'write' | 'verify' | 'system';

export interface SegmentMeta {
  label: string;
  icon: string;
  /** 波形图/图例用的 hex（内联样式，Tailwind 无法动态拼类名） */
  color: string;
  /** 文字色 class */
  text: string;
  /** 背景 class */
  bg: string;
  /** 边框 class */
  border: string;
}

export const SEGMENT_META: Record<AgentSegment, SegmentMeta> = {
  read: {
    label: '读取', icon: '📥', color: '#22D3EE',
    text: 'text-accent-cyan', bg: 'bg-accent-cyan/10', border: 'border-accent-cyan/30',
  },
  infer: {
    label: '推理', icon: '🧠', color: '#8B5CF6',
    text: 'text-accent-purple', bg: 'bg-accent-purple/10', border: 'border-accent-purple/30',
  },
  validate: {
    label: '校验', icon: '🔎', color: '#3B82F6',
    text: 'text-accent-blue', bg: 'bg-accent-blue/10', border: 'border-accent-blue/30',
  },
  guard: {
    label: '守护', icon: '🛡', color: '#F59E0B',
    text: 'text-accent-yellow', bg: 'bg-accent-yellow/10', border: 'border-accent-yellow/30',
  },
  write: {
    label: '写入', icon: '✏️', color: '#10B981',
    text: 'text-accent-green', bg: 'bg-accent-green/10', border: 'border-accent-green/30',
  },
  verify: {
    label: '验证', icon: '✅', color: '#F97316',
    text: 'text-accent-orange', bg: 'bg-accent-orange/10', border: 'border-accent-orange/30',
  },
  system: {
    label: '系统', icon: '⚙️', color: '#64748B',
    text: 'text-text-muted', bg: 'bg-text-muted/10', border: 'border-text-muted/30',
  },
};

export const SEGMENT_ORDER: AgentSegment[] = [
  'read', 'infer', 'validate', 'guard', 'write', 'verify', 'system',
];

/** playbook step.type → 六段类型（后端 primitive_actions.json 的 action_types） */
export function segmentOfStepType(type?: string | null): AgentSegment {
  const value = String(type || '').toLowerCase();
  if (value === 'read' || value === 'infer' || value === 'validate'
    || value === 'guard' || value === 'write' || value === 'verify') {
    return value as AgentSegment;
  }
  if (value === 'knowledge' || value === 'retrieve') return 'read';
  return 'system';
}

/**
 * Span 没有显式 type 字段，按 span_name / tool_name / agent_name 推断六段归属。
 * 后端 span_name 主要来自 incident_orchestrator 的英文步骤名与 stage_transition。
 */
export function inferSegment(span: Pick<AgentSpan, 'span_name' | 'tool_name' | 'agent_name' | 'policy_decision'>): AgentSegment {
  const raw = `${span.span_name || ''} ${span.tool_name || ''}`.toLowerCase();
  if (/verif|recovery|readback|read_back|回读|验证/.test(raw)) return 'verify';
  if (/validat|evaluat|completeness|consistency|校验|完整度/.test(raw)) return 'validate';
  if (/policy|guard|approval|approve|confirm|拦截|守护|审批/.test(raw)) return 'guard';
  if (/write|create|update|transition|execute|dispatch|commit|close|assign|写入|执行/.test(raw)) return 'write';
  if (/analy|diagnos|hypothes|predict|infer|assess|reason|forecast|推理|诊断/.test(raw)) return 'infer';
  if (/collect|query|fetch|read|get|load|scan|search|retriev|取数|检索/.test(raw)) return 'read';
  return 'system';
}

// ══════════════════════════════════════════════════════════
// API 封装
// ══════════════════════════════════════════════════════════

export interface PlanAgentTaskBody {
  message: string;
  page_context?: Record<string, unknown>;
  plan_id?: string | null;
  provider_config_id?: number | null;
  model?: string | null;
}

export async function planAgentTask(body: PlanAgentTaskBody): Promise<AgentTaskPlanResponse> {
  const { data } = await api.post<AgentTaskPlanResponse>('/agent-tasks/plan', {
    message: body.message,
    page_context: body.page_context || {},
    plan_id: body.plan_id || undefined,
    provider_config_id: body.provider_config_id || undefined,
    model: body.model || undefined,
  }, { timeout: 120000 });
  return data;
}

export async function cancelAgentTaskPlan(planId: string): Promise<AgentTaskCancelResponse | null> {
  try {
    const { data } = await api.post<AgentTaskCancelResponse>(`/agent-tasks/${planId}/cancel`, {}, { timeout: 10000 });
    return data;
  } catch {
    // 服务端计划会自然过期，本地已清理即可
    return null;
  }
}

export async function planAgentAction(
  message: string,
  pageContext: Record<string, unknown> = {},
): Promise<AgentTaskPlanResponse> {
  const { data } = await api.post<AgentTaskPlanResponse>('/agent-actions/plan', {
    message,
    page_context: pageContext,
  }, { timeout: 60000 });
  return data;
}

export async function confirmAgentAction(requestId: string): Promise<AgentActionConfirmResponse> {
  const { data } = await api.post<AgentActionConfirmResponse>(
    `/agent-actions/${requestId}/confirm`, {}, { timeout: 30000 },
  );
  return data;
}

export async function cancelAgentAction(requestId: string): Promise<AgentActionConfirmResponse | null> {
  try {
    const { data } = await api.post<AgentActionConfirmResponse>(
      `/agent-actions/${requestId}/cancel`, {}, { timeout: 10000 },
    );
    return data;
  } catch {
    return null;
  }
}

export async function fetchIncidentTraces(incidentId: number): Promise<AgentTrace[]> {
  const { data } = await api.get<AgentTrace[]>(`/incidents/${incidentId}/trace`);
  return Array.isArray(data) ? data : [];
}

export async function startIncidentTrace(incidentId: number): Promise<AgentTrace> {
  const { data } = await api.post<AgentTrace>(`/incidents/${incidentId}/trace/start`);
  return data;
}

// ══════════════════════════════════════════════════════════
// 飞行记录器：全局 trace 聚合
// ══════════════════════════════════════════════════════════

export interface TraceWithContext extends AgentTrace {
  incident_ref: string;
  incident_title: string;
  turbine_name: string;
  incident_severity: string;
}

export interface AllTracesResult {
  traces: TraceWithContext[];
  incidentsScanned: number;
  failedIncidents: number;
}

async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<R>,
): Promise<R[]> {
  const output: R[] = new Array(items.length);
  let cursor = 0;
  const runners = new Array(Math.min(limit, items.length || 1)).fill(0).map(async () => {
    for (;;) {
      const index = cursor++;
      if (index >= items.length) return;
      output[index] = await worker(items[index]);
    }
  });
  await Promise.all(runners);
  return output;
}

/**
 * 聚合全部飞行记录。
 * 后端没有 `GET /agent-traces` 这类全局端点，只能先取事件列表再逐事件取 trace。
 */
export async function fetchAllTraces(options: { maxIncidents?: number } = {}): Promise<AllTracesResult> {
  const { data } = await api.get<Incident[]>('/incidents');
  const incidents = Array.isArray(data) ? data : [];
  const scan = incidents.slice(0, options.maxIncidents ?? 40);

  let failedIncidents = 0;
  const chunks = await mapWithConcurrency(scan, 6, async (inc) => {
    try {
      const traces = await fetchIncidentTraces(inc.id);
      return traces.map((trace): TraceWithContext => ({
        ...trace,
        spans: Array.isArray(trace.spans) ? trace.spans : [],
        incident_ref: inc.incident_id,
        incident_title: inc.title,
        turbine_name: inc.turbine_name,
        incident_severity: inc.severity,
      }));
    } catch {
      failedIncidents += 1;
      return [] as TraceWithContext[];
    }
  });

  const traces = chunks.flat();
  traces.sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  return { traces, incidentsScanned: scan.length, failedIncidents };
}

// ══════════════════════════════════════════════════════════
// 统计
// ══════════════════════════════════════════════════════════

export interface TraceStats {
  spanCount: number;
  totalDurationMs: number;
  maxDurationMs: number;
  slowest: AgentSpan | null;
  completed: number;
  failed: number;
  running: number;
  denied: number;
  approvals: number;
  segments: { segment: AgentSegment; count: number; durationMs: number }[];
  wallClockMs: number;
}

export function summarizeTrace(trace: AgentTrace | null | undefined): TraceStats {
  const spans = trace?.spans || [];
  const buckets = new Map<AgentSegment, { count: number; durationMs: number }>();
  let completed = 0;
  let failed = 0;
  let running = 0;
  let denied = 0;
  let approvals = 0;
  let totalDurationMs = 0;
  let maxDurationMs = 0;
  let slowest: AgentSpan | null = null;

  for (const span of spans) {
    const segment = inferSegment(span);
    const bucket = buckets.get(segment) || { count: 0, durationMs: 0 };
    const duration = Number(span.duration_ms) || 0;
    bucket.count += 1;
    bucket.durationMs += duration;
    buckets.set(segment, bucket);

    totalDurationMs += duration;
    if (duration > maxDurationMs) { maxDurationMs = duration; slowest = span; }
    if (span.status === 'completed' || span.status === 'success') completed += 1;
    else if (span.status === 'failed' || span.status === 'error') failed += 1;
    else running += 1;
    if (span.policy_decision === 'denied') denied += 1;
    if (span.approval_by) approvals += 1;
  }

  const times = spans
    .map((span) => new Date(span.started_at).getTime())
    .filter((value) => Number.isFinite(value));
  const ends = spans
    .map((span) => (span.ended_at ? new Date(span.ended_at).getTime() : NaN))
    .filter((value) => Number.isFinite(value));
  const wallClockMs = times.length && ends.length
    ? Math.max(0, Math.max(...ends) - Math.min(...times))
    : 0;

  return {
    spanCount: spans.length,
    totalDurationMs,
    maxDurationMs,
    slowest,
    completed,
    failed,
    running,
    denied,
    approvals,
    wallClockMs,
    segments: SEGMENT_ORDER
      .map((segment) => ({ segment, ...(buckets.get(segment) || { count: 0, durationMs: 0 }) }))
      .filter((item) => item.count > 0),
  };
}

export function formatDuration(ms: number | null | undefined): string {
  const value = Number(ms) || 0;
  if (value < 1) return '<1ms';
  if (value < 1000) return `${value.toFixed(0)}ms`;
  if (value < 60000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.floor(value / 60000)}m${((value % 60000) / 1000).toFixed(0)}s`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', { hour12: false });
}

// ══════════════════════════════════════════════════════════
// 实时执行链：把 plan 响应翻译成可视化的状态卡
// ══════════════════════════════════════════════════════════

export type ChainStatus = 'done' | 'running' | 'pending' | 'blocked' | 'failed' | 'skipped';

export interface ExecutionChainStep {
  key: string;
  segment: AgentSegment;
  /** 卡片主标题，如「理解」「规划」「工具」 */
  title: string;
  /** 明细，如 意图=xxx 槽位=xxx(置信0.94) */
  detail: string;
  status: ChainStatus;
  /** 右上角附注，如 127ms / L2写操作 */
  meta?: string;
  /** 该步是否为需要人工确认的守护步 */
  isGuard?: boolean;
}

export const CHAIN_STATUS_META: Record<ChainStatus, { icon: string; text: string; border: string; bg: string; label: string }> = {
  done: { icon: '✓', text: 'text-accent-green', border: 'border-accent-green/35', bg: 'bg-accent-green/8', label: '已完成' },
  running: { icon: '▶', text: 'text-accent-blue', border: 'border-accent-blue/40', bg: 'bg-accent-blue/10', label: '进行中' },
  pending: { icon: ' ', text: 'text-text-muted', border: 'border-border-default', bg: 'bg-bg-secondary/40', label: '等待' },
  blocked: { icon: '⛔', text: 'text-accent-red', border: 'border-accent-red/45', bg: 'bg-accent-red/10', label: '已拦截' },
  failed: { icon: '✗', text: 'text-accent-red', border: 'border-accent-red/40', bg: 'bg-accent-red/8', label: '失败' },
  skipped: { icon: '–', text: 'text-text-muted', border: 'border-border-subtle', bg: 'bg-bg-secondary/25', label: '跳过' },
};

/** 执行链所处阶段 */
export type ChainPhase = 'idle' | 'planning' | 'planned' | 'executing' | 'executed' | 'cancelled' | 'failed';

function formatSlots(slots?: Record<string, unknown> | null): string {
  if (!slots) return '无';
  const entries = Object.entries(slots).filter(([, value]) => (
    value !== null && value !== undefined && value !== '' && !(Array.isArray(value) && value.length === 0)
  ));
  if (entries.length === 0) return '无';
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value).slice(0, 28) : String(value)}`)
    .join(' ');
}

function riskLabel(plan: AgentTaskPlanResponse): string {
  if (plan.confirmation) return 'high';
  if (plan.task_kind === 'advanced_workflow') return 'medium';
  return 'low';
}

/**
 * 把一次 Agent 任务规划渲染成七步闭环状态卡：
 * 理解 → 规划 → (playbook 六段步骤) → 守护确认 → 写入 → 验证
 */
export function buildExecutionChain(
  plan: AgentTaskPlanResponse | null,
  phase: ChainPhase,
  extra: { elapsedMs?: number; resultSummary?: string } = {},
): ExecutionChainStep[] {
  if (!plan) {
    if (phase === 'planning') {
      return [{
        key: 'understand',
        segment: 'infer',
        title: '理解',
        detail: '正在解析意图与槽位…',
        status: 'running',
      }];
    }
    return [];
  }

  const steps: ExecutionChainStep[] = [];
  const confidence = typeof plan.confidence === 'number' ? plan.confidence : 0;
  const isError = plan.status === 'error' || plan.status === 'unsupported';
  const needsClarification = plan.status === 'needs_clarification';

  // 1. 理解
  steps.push({
    key: 'understand',
    segment: 'infer',
    title: '理解',
    detail: `意图=${plan.task_type || plan.playbook_id || '未识别'} 槽位=${formatSlots(plan.slots)}（置信 ${confidence.toFixed(2)}）`,
    status: isError ? 'failed' : needsClarification ? 'blocked' : 'done',
    meta: plan.planner_source ? `规划器 ${plan.planner_source}` : undefined,
  });

  // 2. 规划
  const playbookSteps = plan.steps || [];
  steps.push({
    key: 'plan',
    segment: 'validate',
    title: '规划',
    detail: needsClarification
      ? (plan.clarification_question || `缺失槽位：${(plan.missing_slots || []).join('、') || '未知'}`)
      : `选中工作流 ${plan.workflow || plan.playbook_id || '—'} · ${playbookSteps.length}步 · 风险级 ${riskLabel(plan)}`,
    status: isError ? 'skipped' : needsClarification ? 'pending' : 'done',
    meta: plan.task_kind ? (plan.task_kind === 'read_task' ? '只读任务' : '写任务工作流') : undefined,
  });

  // 3. playbook 六段步骤
  const guardIndex = playbookSteps.findIndex((item) => segmentOfStepType(item.type) === 'guard');
  playbookSteps.forEach((item, index) => {
    const segment = segmentOfStepType(item.type);
    let status: ChainStatus = 'pending';
    if (isError) {
      status = 'skipped';
    } else if (needsClarification) {
      status = 'pending';
    } else if (plan.status === 'answered') {
      status = 'done';
    } else if (plan.status === 'pending_confirmation') {
      if (guardIndex >= 0) {
        if (index < guardIndex) status = 'done';
        else if (index === guardIndex) status = phase === 'executed' ? 'done' : phase === 'cancelled' ? 'failed' : 'blocked';
        else status = phase === 'executed' ? 'done' : phase === 'cancelled' ? 'skipped' : 'pending';
      } else {
        status = segment === 'write' || segment === 'verify'
          ? (phase === 'executed' ? 'done' : phase === 'cancelled' ? 'skipped' : 'pending')
          : 'done';
      }
    }
    if (phase === 'executing' && status === 'pending') status = 'running';

    steps.push({
      key: `pb-${index}-${item.step}`,
      segment,
      title: SEGMENT_META[segment].label,
      detail: `${item.step}${item.description ? ` — ${item.description}` : ''}`,
      status,
      isGuard: segment === 'guard',
      meta: `#${item.order}`,
    });
  });

  // 4. 守护确认（playbook 没有显式 guard 步时补一张）
  if (plan.confirmation && guardIndex < 0) {
    let guardStatus: ChainStatus = 'blocked';
    if (phase === 'executed') guardStatus = 'done';
    else if (phase === 'cancelled') guardStatus = 'failed';
    else if (phase === 'executing') guardStatus = 'running';
    steps.push({
      key: 'guard',
      segment: 'guard',
      title: '守护',
      detail: `require_confirmation — ${plan.confirmation.title || 'L2 写操作需人工确认'}`,
      status: guardStatus,
      isGuard: true,
      meta: 'L2 写操作',
    });
  }

  // 5/6. 写入 + 验证（只读任务不追加）
  const hasWrite = playbookSteps.some((item) => segmentOfStepType(item.type) === 'write');
  const hasVerify = playbookSteps.some((item) => segmentOfStepType(item.type) === 'verify');
  const isWriteTask = Boolean(plan.confirmation) || plan.task_kind === 'advanced_workflow';

  if (isWriteTask && !hasWrite) {
    steps.push({
      key: 'write',
      segment: 'write',
      title: '写入',
      detail: phase === 'executed'
        ? (extra.resultSummary || '动作已执行并落库')
        : phase === 'cancelled' ? '用户取消，未写入任何数据' : '等待人工确认后执行',
      status: phase === 'executed' ? 'done' : phase === 'cancelled' ? 'skipped' : 'pending',
      meta: plan.action || undefined,
    });
  }
  if (isWriteTask && !hasVerify) {
    steps.push({
      key: 'verify',
      segment: 'verify',
      title: '验证',
      detail: phase === 'executed' ? '写后回读校验通过，已写入审计链' : '写入完成后自动回读校验',
      status: phase === 'executed' ? 'done' : phase === 'cancelled' ? 'skipped' : 'pending',
    });
  }

  // 只读任务的作答
  if (plan.status === 'answered' && plan.answer) {
    steps.push({
      key: 'answer',
      segment: 'read',
      title: '作答',
      detail: plan.answer.replace(/\s+/g, ' ').slice(0, 160),
      status: 'done',
      meta: extra.elapsedMs ? formatDuration(extra.elapsedMs) : undefined,
    });
  }

  if (isError) {
    steps.push({
      key: 'error',
      segment: 'system',
      title: '异常',
      detail: plan.error_message || plan.clarification_question || '后端未返回具体原因',
      status: 'failed',
      meta: plan.error_code || plan.status,
    });
  }

  return steps;
}
