import { useRef, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import html2canvas from 'html2canvas';
import api from '../../services/api';
import { useCopilotStore } from '../../services/copilotStore';
import type { Message } from '../../services/copilotStore';

const PANEL_W = 560;
const PANEL_H = 560;
const FAB_W = 56;
const FAB_H = 56;
const EDGE_GAP = 24;

export interface PageContext {
  turbine_id?: number;
  turbine_name?: string;
  fault_id?: number;
  fault_type?: string;
  [key: string]: unknown;
}

interface CopilotModelStatus {
  provider?: string;
  api_provider?: string;
  model?: string;
  label?: string;
  mode?: string;
  requires_api_key?: boolean;
  has_api_key?: boolean;
}

interface CopilotResponse {
  reply: string;
  status?: 'success' | 'error';
  error_code?: string;
  error_message?: string;
  model_status?: CopilotModelStatus;
  warnings?: string[];
  session_title?: string;
  context_sources?: ContextSource[];
}

interface ContextSource {
  context: string;
  label: string;
  tools?: string[];
}

interface AIProviderConfig {
  id: number;
  provider: string;
  display_name: string | null;
  base_url: string;
  default_model: string | null;
  model_options: string[];
  enabled: boolean;
  has_api_key: boolean;
  last_test_status: string | null;
}

interface AgentActionConfirmation {
  title: string;
  summary: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  warnings: string[];
}

interface AgentActionPlanResponse {
  status: 'pending_confirmation' | 'needs_clarification' | 'unsupported' | 'error';
  task_type?: string;
  workflow?: string;
  request_id?: string;
  action?: string;
  confidence?: number;
  confirmation?: AgentActionConfirmation;
  missing_slots?: string[];
  clarification_question?: string;
  error_code?: string;
  error_message?: string;
}

interface AgentReadTaskResponse {
  status: 'success' | 'needs_clarification' | 'unsupported' | 'error';
  task_type?: string;
  workflow?: string;
  confidence?: number;
  answer?: string;
  missing_slots?: string[];
  clarification_question?: string;
  error_code?: string;
  error_message?: string;
  display?: Record<string, unknown>;
}

interface AgentTaskStep {
  order: number;
  step: string;
  type: string;
  status: string;
  description?: string;
}

interface AgentTaskCandidate {
  id: string;
  name: string;
  category: string;
  implementation_status?: string | null;
  task_kind: string;
  score?: number | null;
}

interface AgentTaskPlanResponse {
  status: 'answered' | 'pending_confirmation' | 'needs_clarification' | 'unsupported' | 'error';
  task_type?: string;
  task_kind?: string;
  planner_source?: string;
  plan_id?: string;
  playbook_id?: string;
  workflow?: string;
  request_id?: string;
  action?: string;
  confidence?: number;
  answer?: string;
  slots?: Record<string, unknown>;
  steps?: AgentTaskStep[];
  candidates?: AgentTaskCandidate[];
  display?: Record<string, unknown>;
  confirmation?: AgentActionConfirmation;
  missing_slots?: string[];
  clarification_question?: string;
  error_code?: string;
  error_message?: string;
}

interface PendingAgentAction {
  requestId: string;
  action: string;
  taskType?: string;
  workflow?: string;
  confidence: number;
  confirmation: AgentActionConfirmation;
}

interface AgentActionConfirmResponse {
  request_id: string;
  action: string;
  status: 'success' | 'failed' | 'cancelled';
  result?: Record<string, unknown>;
  display?: Record<string, unknown>;
  error_code?: string;
  error_message?: string;
}

type CopilotStreamEvent =
  | { type: 'meta'; model_status?: CopilotModelStatus; warnings?: string[]; context_sources?: ContextSource[] }
  | { type: 'delta'; delta?: string }
  | { type: 'title'; session_title?: string }
  | { type: 'done' }
  | ({ type: 'error' } & Partial<CopilotResponse>);

const AI_ERROR_TITLES: Record<string, string> = {
  api_key_missing: 'AI密钥未配置',
  provider_unbound: 'AI密钥未绑定供应商',
  provider_mismatch: '模型与密钥供应商不匹配',
  upstream_auth_failed: 'AI供应商鉴权失败',
  model_not_found: '模型不可用',
  upstream_rate_limited: 'AI额度或频率受限',
  upstream_server_error: 'AI供应商服务异常',
  upstream_timeout: 'AI请求超时',
  network_error: '无法连接AI供应商',
  upstream_unknown: 'AI调用失败',
  ai_config_not_ready: 'AI配置未就绪',
};

function formatCopilotError(data?: Partial<CopilotResponse>, fallback = 'AI服务暂不可用，请稍后重试') {
  const code = data?.error_code || 'upstream_unknown';
  const title = AI_ERROR_TITLES[code] || 'AI调用失败';
  const status = data?.model_status || {};
  const lines = [
    `**${title}**`,
    data?.error_message || data?.reply || fallback,
    '',
    `- 错误码: \`${code}\``,
  ];
  if (status.model || status.provider || status.api_provider || status.mode) {
    lines.push(`- 当前模型: \`${status.model || '-'}\``);
    lines.push(`- 模型供应商: \`${status.provider || '-'}\``);
    lines.push(`- 密钥供应商: \`${status.api_provider || '-'}\``);
    lines.push(`- 配置状态: \`${status.mode || '-'}\``);
    lines.push(`- 是否已有密钥: \`${status.has_api_key ? '是' : '否'}\``);
  }
  if (data?.warnings?.includes('screenshot_analysis_failed')) {
    lines.push('- 附加提示: 页面截图识别失败，本次已按文本上下文处理。');
  }
  return lines.join('\n');
}

function asAgentRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function truncateAgentText(value: unknown, maxLength = 120) {
  const text = String(value ?? '').trim();
  if (!text) return '-';
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

const AGENT_SLOT_LABELS: Record<string, string> = {
  playbook_id: '任务模板',
  turbine_ref: '风机',
  turbine_id: '风机ID',
  workorder_ref: '工单',
  workorder_id: '工单ID',
  fault_id: '故障ID',
  fault_keyword: '故障词',
  fault_type: '故障类型',
  component: '部件',
  assignee_name: '负责人',
  priority: '优先级',
  target_workorder_status: '工单目标状态',
  target_processing_status: '故障目标状态',
  record_content: '记录内容',
  reason: '原因',
  provider: '供应商',
  scope: '范围',
  cost_actual: '成本',
  downtime_hours: '停机小时',
  personnel_name: '维护人员',
  email: '邮箱',
  skills: '技能',
  region: '区域',
  knowledge_node_ref: '知识节点',
  review_action: '审核动作',
  threshold_payload: '阈值配置',
  patch_fields: '修改字段',
  details_description: '详情描述',
  base_url: 'API地址',
  api_style: 'API风格',
  default_model: '默认模型',
  model_options: '常用模型',
  has_api_key: '密钥状态',
  api_key_update: '密钥更新',
};

const AGENT_FIELD_LABELS: Record<string, string> = {
  ref: '编号',
  id: 'ID',
  name: '名称',
  turbine_id: '风机ID',
  turbine_name: '风机',
  turbine_region: '风场',
  detected_at: '发现时间',
  title: '标题',
  email: '邮箱',
  role: '角色',
  region: '区域',
  skills: '技能',
  fault_type: '故障类型',
  category: '分类',
  severity: '严重度',
  priority: '优先级',
  assignee: '负责人',
  status: '状态',
  processing_status: '处理状态',
  verified: '已验证',
  confidence: '置信度',
  source: '来源',
  is_active: '启用',
  is_available: '可用',
  active_workorder_count: '未完成工单',
  deleted: '删除',
  delete_reason: '删除原因',
  review_action: '审核动作',
  review_reason: '审核原因',
  description: '描述',
  details: '详情',
  duplicate_active_fault_ids: '同类活跃故障',
  patch_fields: '修改字段',
  details_description: '详情描述',
  root_causes: '可能根因',
  solutions: '处理方案',
  spare_parts: '备件',
  cases: '案例',
  extracted_from: '来源记录',
  hi_threshold: 'HI告警阈值',
  email_enabled: '邮件通知',
  email_address: '通知邮箱',
  wechat_enabled: '企业微信通知',
  base_url: 'API地址',
  api_style: 'API风格',
  default_model: '默认模型',
  model_options: '常用模型',
  has_api_key: '密钥状态',
  api_key_update: '密钥更新',
  test_model: '测试模型',
  last_test_status: '测试状态',
  last_test_message: '测试结果',
  sample: '返回样例',
  component: '检测部件',
  analysis_window_hours: '分析窗口',
  data_source: '数据源',
  max_days: '排程天数',
  top_n: '排程数量',
  create_work_orders: '创建工单',
  turbine_count: '风机数量',
  turbine_names: '风机列表',
  affected_count: '影响数量',
  source_datasets: '数据集',
  before_items: '刷新前',
  status_summary: '状态统计',
  component_scores: '分项得分',
  window_rows: '窗口行数',
  scada_window_rows: 'SCADA窗口',
  previous_hi_value: '刷新前HI',
  previous_status: '刷新前状态',
  plan_count: '计划项',
  total_scheduled: '已排程',
  total_overflow: '溢出项',
  conflict_count: '冲突数',
  urgent_count: '紧急项',
  high_count: '高优先级项',
  total_cost_estimate: '预估总成本',
  work_orders_created: '新建工单数',
  preview_items: '排程预览',
  scheduled: '排程结果',
  overflow: '溢出排程',
  conflicts: '冲突',
  created_workorders: '新建工单',
  persist_result: '保存结果',
  persist_requested: '请求保存',
  persisted_fault_id: '新增故障ID',
  persisted_fault_ids: '新增故障ID',
  skipped_existing_faults: '跳过已有故障',
  skipped_low_confidence: '低置信跳过',
  group_summary: '分组统计',
  records: '检测记录',
  persist_note: '保存说明',
  operation: '操作',
  result_status: '结果状态',
  algorithm_status: '算法状态',
  message: '说明',
  confidence_interval: '置信区间',
};

function formatAgentSlotValue(value: unknown) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    const raw = record.value ?? record.name ?? record.id ?? value;
    const source = record.source ? `/${record.source}` : '';
    return `${truncateAgentText(raw, 48)}${source}`;
  }
  if (Array.isArray(value)) return truncateAgentText(value.join('、'), 48);
  return truncateAgentText(value, 48);
}

function formatAgentSlots(slots?: Record<string, unknown>) {
  if (!slots) return '';
  const parts = Object.entries(slots)
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .slice(0, 8)
    .map(([key, value]) => `${AGENT_SLOT_LABELS[key] || key}: \`${formatAgentSlotValue(value)}\``);
  return parts.join(' · ');
}

function formatAgentSteps(steps?: AgentTaskStep[]) {
  if (!steps?.length) return '';
  const visible = steps.slice(0, 6).map((step) => {
    const label = step.description || step.step;
    return `${step.order}. ${truncateAgentText(label, 34)}`;
  });
  const suffix = steps.length > visible.length ? ` 等${steps.length}步` : '';
  return `${visible.join(' -> ')}${suffix}`;
}

function pickAgentValue(snapshot: Record<string, unknown>, key: string) {
  const workorder = asAgentRecord(snapshot.workorder);
  const turbine = asAgentRecord(snapshot.turbine);
  return snapshot[key] ?? workorder[key] ?? turbine[key];
}

function formatAgentValue(value: unknown, maxLength = 120): string {
  if (value === true) return '是';
  if (value === false) return '否';
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'number') {
    if (value >= 0 && value <= 1) return `${Math.round(value * 100)}%`;
    return String(value);
  }
  if (Array.isArray(value)) {
    if (!value.length) return '-';
    const text = value.map((item) => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>;
        return String(record.action ?? record.name ?? record.summary ?? record.title ?? record.fault_type ?? record.ref ?? record.id ?? JSON.stringify(record));
      }
      return String(item);
    }).join('、');
    return truncateAgentText(text, maxLength);
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const picked = record.ref ?? record.name ?? record.title ?? record.fault_type ?? record.summary ?? record.id;
    if (picked !== undefined && picked !== null) return truncateAgentText(picked, maxLength);
    try {
      return truncateAgentText(JSON.stringify(record), maxLength);
    } catch {
      return truncateAgentText(String(value), maxLength);
    }
  }
  return truncateAgentText(value, maxLength);
}

function formatFaultContext(snapshot: Record<string, unknown>) {
  const context = asAgentRecord(snapshot.fault_context);
  if (!Object.keys(context).length) return null;
  const latest = asAgentRecord(context.latest);
  const total = context.total ?? 0;
  const active = context.active ?? 0;
  const latestType = latest.fault_type ? `，最新：${latest.fault_type}` : '';
  const confidence = typeof latest.confidence === 'number' ? ` ${Math.round(latest.confidence * 100)}%` : '';
  return `总计 ${total}，活跃 ${active}${latestType}${confidence}`;
}

function buildAgentSnapshotRows(snapshot: Record<string, unknown>) {
  const faultContext = formatFaultContext(snapshot);
  const orderedKeys = [
    'ref',
    'id',
    'name',
    'turbine_id',
    'turbine_name',
    'turbine_region',
    'detected_at',
    'title',
    'email',
    'role',
    'region',
    'skills',
    'fault_type',
    'category',
    'severity',
    'priority',
    'assignee',
    'status',
    'processing_status',
    'verified',
    'confidence',
    'source',
    'is_active',
    'is_available',
    'active_workorder_count',
    'deleted',
    'delete_reason',
    'review_action',
    'review_reason',
    'description',
    'details',
    'duplicate_active_fault_ids',
    'root_causes',
    'solutions',
    'spare_parts',
    'cases',
    'extracted_from',
    'hi_threshold',
    'email_enabled',
    'email_address',
    'wechat_enabled',
    'base_url',
    'api_style',
    'default_model',
    'model_options',
    'has_api_key',
    'api_key_update',
    'test_model',
    'last_test_status',
    'last_test_message',
    'sample',
    'component',
    'analysis_window_hours',
    'data_source',
    'max_days',
    'top_n',
    'create_work_orders',
    'turbine_count',
    'turbine_names',
    'affected_count',
    'source_datasets',
    'before_items',
    'status_summary',
    'component_scores',
    'window_rows',
    'scada_window_rows',
    'previous_hi_value',
    'previous_status',
    'plan_count',
    'total_scheduled',
    'total_overflow',
    'conflict_count',
    'urgent_count',
    'high_count',
    'total_cost_estimate',
    'work_orders_created',
    'preview_items',
    'scheduled',
    'overflow',
    'conflicts',
    'created_workorders',
    'persist_result',
    'persist_requested',
    'persisted_fault_id',
    'persisted_fault_ids',
    'skipped_existing_faults',
    'skipped_low_confidence',
    'group_summary',
    'records',
    'persist_note',
    'operation',
    'result_status',
    'algorithm_status',
    'message',
    'confidence_interval',
  ];
  const rows = orderedKeys
    .map((key) => ({ label: AGENT_FIELD_LABELS[key] || key, value: pickAgentValue(snapshot, key) }))
    .filter((row) => row.value !== undefined && row.value !== null && String(row.value).trim() !== '')
    .map((row) => ({ label: row.label, value: formatAgentValue(row.value) }));
  if (faultContext) rows.push({ label: '故障上下文', value: faultContext });
  return rows;
}

function buildAgentActionResultMessage(data: AgentActionConfirmResponse) {
  const result = asAgentRecord(data.result);
  const rows = buildAgentSnapshotRows(result).slice(0, 10);
  return [
    '**Agent动作已执行**',
    `动作: \`${data.action}\``,
    ...rows.map((row) => `${row.label}: \`${row.value}\``),
  ].join('\n');
}

function shouldAttachScreenshot(mode: AssistantMode, attachScreenshotOnce: boolean) {
  return mode === 'agent' || attachScreenshotOnce;
}

function compactChatMessages(messages: Array<{ role: string; content: string }>) {
  const budget = 6000;
  const kept: Array<{ role: string; content: string }> = [];
  let used = 0;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    const content = message.content || '';
    const cost = content.length + 32;
    if (kept.length >= 12 || (used + cost > budget && kept.length >= 4)) break;
    kept.unshift(message);
    used += cost;
  }
  return kept;
}

function fallbackProviderModels(provider?: AIProviderConfig | null) {
  const key = provider?.provider?.toLowerCase() || '';
  if (key === 'qwen' || key === 'dashscope') return ['qwen-plus', 'qwen-turbo', 'qwen3.6-flash'];
  if (key === 'deepseek') return ['deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-flash'];
  return [provider?.default_model].filter(Boolean) as string[];
}

const DATA_CONTEXT_STORAGE_KEY = 'copilot.selectedDataContexts.v1';
const ASSISTANT_MODE_STORAGE_KEY = 'copilot.assistantMode.v1';
type AssistantMode = 'chat' | 'agent';

const DATA_CONTEXT_OPTIONS = [
  { id: 'dashboard', label: '风场监控', hint: '总览 / 区域 / 风机' },
  { id: 'diagnosis', label: '故障诊断', hint: '故障 / 置信度 / 振动' },
  { id: 'prediction', label: '预测决策', hint: 'RUL / 维护优先级' },
  { id: 'workorder', label: '维修工单', hint: '状态 / 派工 / 闭环' },
  { id: 'knowledge', label: '知识库', hint: '根因 / 方案 / 备件' },
  { id: 'current_turbine', label: '当前风机', hint: '选中对象数据' },
];

function loadSelectedDataContexts() {
  try {
    const raw = localStorage.getItem(DATA_CONTEXT_STORAGE_KEY);
    if (raw === null) return ['dashboard'];
    const parsed = JSON.parse(raw) as string[];
    const valid = parsed.filter((id) => DATA_CONTEXT_OPTIONS.some((item) => item.id === id));
    return valid;
  } catch {
    return ['dashboard'];
  }
}

function loadAssistantMode(): AssistantMode {
  try {
    const raw = localStorage.getItem(ASSISTANT_MODE_STORAGE_KEY);
    return raw === 'agent' ? 'agent' : 'chat';
  } catch {
    return 'chat';
  }
}

async function postCopilotStream(
  payload: Record<string, unknown>,
  onEvent: (event: CopilotStreamEvent) => void,
) {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/ai/copilot/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (response.status === 401) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.replace('/login');
    throw new Error('unauthorized');
  }
  if (!response.ok || !response.body) {
    throw new Error(`stream request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      onEvent(JSON.parse(line) as CopilotStreamEvent);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) onEvent(JSON.parse(buffer) as CopilotStreamEvent);
}

export default function CopilotFAB({ initialMessage = '', pageContext }: { initialMessage?: string; pageContext?: PageContext }) {
  const sessions = useCopilotStore((s) => s.sessions);
  const currentSessionId = useCopilotStore((s) => s.currentSessionId);
  const messages = useCopilotStore((s) => s.messages);
  const input = useCopilotStore((s) => s.input);
  const loading = useCopilotStore((s) => s.loading);
  const open = useCopilotStore((s) => s.open);
  const panelPos = useCopilotStore((s) => s.panelPos);
  const addMessage = useCopilotStore((s) => s.addMessage);
  const setInput = useCopilotStore((s) => s.setInput);
  const setLoading = useCopilotStore((s) => s.setLoading);
  const setOpen = useCopilotStore((s) => s.setOpen);
  const setPanelPos = useCopilotStore((s) => s.setPanelPos);
  const fabPos = useCopilotStore((s) => s.fabPos);
  const setFabPos = useCopilotStore((s) => s.setFabPos);
  const createSession = useCopilotStore((s) => s.createSession);
  const switchSession = useCopilotStore((s) => s.switchSession);
  const updateCurrentSessionMeta = useCopilotStore((s) => s.updateCurrentSessionMeta);
  const deleteSession = useCopilotStore((s) => s.deleteSession);
  const updateMessage = useCopilotStore((s) => s.updateMessage);
  const navigate = useNavigate();

  const chatRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const initialSent = useRef(false);
  const fabRef = useRef<HTMLButtonElement>(null);
  const fabDragging = useRef(false);
  const fabDragOffset = useRef({ x: 0, y: 0 });

function renderMessageContent(text: string, isProgress?: boolean) {
  if (isProgress) return <span>{text}</span>;
  // Simple markdown: **bold**, `code`, > quote, - list, \n breaks
  const lines = text.split('\n');
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (!line.trim()) return <br key={i} />;
        const html = line
          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          .replace(/`(.+?)`/g, '<code class="bg-bg-card px-1 rounded text-[10px]">$1</code>');
        if (line.startsWith('> ')) {
          return <div key={i} className="text-text-muted border-l-2 border-border-default pl-2 text-[11px]" dangerouslySetInnerHTML={{ __html: html.slice(2) }} />;
        }
        if (/^\d+\.\s/.test(line) || line.startsWith('- ')) {
          return <div key={i} className="flex gap-1"><span className="text-accent-blue">•</span><span dangerouslySetInnerHTML={{ __html: html.replace(/^\d+\.\s|-\s/, '') }} /></div>;
        }
        if (line.includes('📊') || line.includes('📚') || line.includes('🎯') || line.includes('🧠') || line.includes('📝')) {
          return <div key={i} className="font-medium text-accent-cyan text-[11px]" dangerouslySetInnerHTML={{ __html: html }} />;
        }
        return <p key={i} className="text-xs" dangerouslySetInnerHTML={{ __html: html }} />;
      })}
    </div>
  );
}
  const fabHasMoved = useRef(false);
  const fabDragStart = useRef({ x: 0, y: 0 });
  const fabPosRef = useRef({ x: 0, y: 0 });
  const [mode, setMode] = useState<AssistantMode>(loadAssistantMode);
  const [attachScreenshotOnce, setAttachScreenshotOnce] = useState(false);
  const [aiProviders, setAiProviders] = useState<AIProviderConfig[]>([]);
  const [modelDraft, setModelDraft] = useState('');
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null);
  const [selectedContextIds, setSelectedContextIds] = useState<string[]>(loadSelectedDataContexts);
  const [pendingAgentAction, setPendingAgentAction] = useState<PendingAgentAction | null>(null);
  const [pendingAgentPlanId, setPendingAgentPlanId] = useState<string | null>(null);
  const currentSession = sessions.find((session) => session.id === currentSessionId) || sessions[0];
  const pendingDeleteSession = pendingDeleteSessionId
    ? sessions.find((session) => session.id === pendingDeleteSessionId)
    : null;
  const conversationStarted = messages.some((message) => message.role === 'user' && !message._progress);
  const modelLocked = conversationStarted;
  const availableProviders = aiProviders.filter((provider) => (
    provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama')
  ));
  const selectedProvider = currentSession?.providerConfigId
    ? aiProviders.find((provider) => provider.id === currentSession.providerConfigId)
    : null;
  const selectedModelOptions = selectedProvider?.model_options?.length
    ? selectedProvider.model_options
    : fallbackProviderModels(selectedProvider);

  const switchMode = useCallback((nextMode: AssistantMode) => {
    setMode(nextMode);
    try {
      localStorage.setItem(ASSISTANT_MODE_STORAGE_KEY, nextMode);
    } catch {
      // Ignore storage failures; in-memory state still updates.
    }
  }, []);

  const applySessionModel = useCallback((provider: AIProviderConfig, model: string) => {
    updateCurrentSessionMeta({
      providerConfigId: provider.id,
      providerName: provider.display_name || provider.provider,
      model: model || provider.default_model || provider.model_options?.[0] || '',
      pageType: window.location.pathname.replace('/', '') || 'dashboard',
    });
  }, [updateCurrentSessionMeta]);

  const createBlankSession = useCallback(() => {
    const provider = selectedProvider || availableProviders[0];
    createSession({
      title: '新建AI会话',
      providerConfigId: provider?.id ?? null,
      providerName: provider ? (provider.display_name || provider.provider) : '',
      model: provider?.default_model || provider?.model_options?.[0] || '',
      pageType: window.location.pathname.replace('/', '') || 'dashboard',
    });
  }, [availableProviders, createSession, selectedProvider]);

  const handleProviderSelect = useCallback((providerId: string) => {
    if (modelLocked) return;
    const provider = aiProviders.find((item) => item.id === Number(providerId));
    if (!provider) return;
    const nextModel = provider.default_model || provider.model_options?.[0] || '';
    setModelDraft(nextModel);
    applySessionModel(provider, nextModel);
  }, [aiProviders, applySessionModel, modelLocked]);

  const handleModelSelect = useCallback((model: string) => {
    if (modelLocked) return;
    setModelDraft(model);
    if (selectedProvider) applySessionModel(selectedProvider, model);
  }, [applySessionModel, modelLocked, selectedProvider]);

  const toggleDataContext = useCallback((contextId: string) => {
    setSelectedContextIds((current) => {
      const exists = current.includes(contextId);
      const next = exists
        ? current.filter((id) => id !== contextId)
        : [...current, contextId];
      localStorage.setItem(DATA_CONTEXT_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const confirmDeleteSession = useCallback(() => {
    if (!pendingDeleteSessionId) return;
    deleteSession(pendingDeleteSessionId);
    setPendingDeleteSessionId(null);
  }, [deleteSession, pendingDeleteSessionId]);

  const confirmPendingAgentAction = useCallback(async () => {
    if (!pendingAgentAction) return;
    setLoading(true);
    try {
      const { data } = await api.post<AgentActionConfirmResponse>(`/agent-actions/${pendingAgentAction.requestId}/confirm`, {}, { timeout: 30000 });
      if (data.status === 'success') {
        setPendingAgentAction(null);
        if (data.display?.navigate_to) navigate(data.display.navigate_to);
        addMessage({
          role: 'assistant',
          content: buildAgentActionResultMessage(data),
        });
      } else {
        addMessage({
          role: 'error',
          content: [
            '**Agent动作执行失败**',
            data.error_message || '后端未返回具体错误。',
            '',
            `- 错误码: \`${data.error_code || 'execution_failed'}\``,
          ].join('\n'),
        });
      }
    } catch (error: any) {
      addMessage({
        role: 'error',
        content: formatCopilotError(error?.response?.data, 'Agent动作确认失败，请检查后端服务和登录状态。'),
      });
    } finally {
      setLoading(false);
    }
  }, [addMessage, navigate, pendingAgentAction, setLoading]);

  const cancelPendingAgentAction = useCallback(async () => {
    if (!pendingAgentAction) return;
    const requestId = pendingAgentAction.requestId;
    setPendingAgentAction(null);
    try {
      await api.post(`/agent-actions/${requestId}/cancel`, {}, { timeout: 10000 });
    } catch {
      // Local cancellation is enough for the user experience; the pending action expires server-side.
    }
    addMessage({ role: 'assistant', content: '已取消本次 Agent 动作。' });
  }, [addMessage, pendingAgentAction]);

  // Keep fabPosRef in sync with store
  useEffect(() => { fabPosRef.current = fabPos; }, [fabPos]);

  useEffect(() => {
    setModelDraft(currentSession?.model || selectedProvider?.default_model || selectedProvider?.model_options?.[0] || '');
  }, [currentSession?.id, currentSession?.model, selectedProvider?.default_model, selectedProvider?.model_options]);

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await api.get<AIProviderConfig[]>('/settings/ai-providers');
      setAiProviders(data);
      const enabled = data.filter((provider) => provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama'));
      const state = useCopilotStore.getState();
      const session = state.sessions.find((item) => item.id === state.currentSessionId);
      const isEmpty = !session?.messages.some((message) => message.role === 'user');
      if (enabled.length > 0 && session && isEmpty && !session.providerConfigId) {
        const provider = enabled[0];
        state.updateCurrentSessionMeta({
          providerConfigId: provider.id,
          providerName: provider.display_name || provider.provider,
          model: provider.default_model || provider.model_options?.[0] || '',
          pageType: window.location.pathname.replace('/', '') || 'dashboard',
        });
      }
    } catch {
      setAiProviders([]);
    }
  }, []);

  useEffect(() => {
    loadProviders();
    window.addEventListener('ai-providers-updated', loadProviders);
    window.addEventListener('focus', loadProviders);
    return () => {
      window.removeEventListener('ai-providers-updated', loadProviders);
      window.removeEventListener('focus', loadProviders);
    };
  }, [loadProviders]);

  useEffect(() => {
    if (open) loadProviders();
  }, [loadProviders, open]);

  // Initialize panel position to bottom-right when opened
  useEffect(() => {
    if (open) {
      const x = Math.max(0, window.innerWidth - PANEL_W - EDGE_GAP);
      const y = Math.max(0, window.innerHeight - PANEL_H - EDGE_GAP);
      setPanelPos({ x, y });
    }
  }, [open, setPanelPos]);

  // Initialize FAB position to bottom-right on first mount (sentinel -1 = uninitialized)
  useEffect(() => {
    if (fabPos.x === -1 && fabPos.y === -1) {
      setFabPos({
        x: Math.max(0, window.innerWidth - FAB_W - EDGE_GAP),
        y: Math.max(0, window.innerHeight - FAB_H - EDGE_GAP),
      });
    }
  }, [fabPos, setFabPos]);

  // Clamp panel position on window resize
  useEffect(() => {
    const handleResize = () => {
      setPanelPos({
        x: Math.max(0, Math.min(panelPos.x, window.innerWidth - PANEL_W)),
        y: Math.max(0, Math.min(panelPos.y, window.innerHeight - PANEL_H)),
      });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [panelPos.x, panelPos.y, setPanelPos]);

  // Auto-open on diagnosis/prediction pages when preference enabled
  useEffect(() => {
    const autoOpen = localStorage.getItem('autoOpenCopilot') === 'true';
    const path = window.location.pathname;
    if (autoOpen && (path.includes('diagnosis') || path.includes('prediction'))) {
      const timer = setTimeout(() => setOpen(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

  // Clamp FAB position on window resize
  useEffect(() => {
    const handleResize = () => {
      setFabPos({
        x: Math.max(0, Math.min(fabPos.x, window.innerWidth - FAB_W)),
        y: Math.max(0, Math.min(fabPos.y, window.innerHeight - FAB_H)),
      });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [fabPos.x, fabPos.y, setFabPos]);

  // Drag handlers (panel)
  const onDragStart = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    dragOffset.current = {
      x: e.clientX - panelPos.x,
      y: e.clientY - panelPos.y,
    };
    e.preventDefault();
  }, [panelPos]);

  useEffect(() => {
    const onDragMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const x = Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - PANEL_W));
      const y = Math.max(0, Math.min(e.clientY - dragOffset.current.y, window.innerHeight - PANEL_H));
      setPanelPos({ x, y });
    };
    const onDragEnd = () => {
      isDragging.current = false;
    };
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
    return () => {
      document.removeEventListener('mousemove', onDragMove);
      document.removeEventListener('mouseup', onDragEnd);
    };
  }, [setPanelPos]);

  // FAB drag handlers — direct DOM manipulation for zero-lag dragging
  const onFabMouseDown = useCallback((e: React.MouseEvent) => {
    fabDragging.current = true;
    fabHasMoved.current = false;
    fabDragStart.current = { x: e.clientX, y: e.clientY };
    const currentX = fabPosRef.current.x;
    const currentY = fabPosRef.current.y;
    fabDragOffset.current = {
      x: e.clientX - currentX,
      y: e.clientY - currentY,
    };
    // Disable transition during drag for instant response
    if (fabRef.current) fabRef.current.style.transition = 'none';
  }, []);

  useEffect(() => {
    const onFabDragMove = (e: MouseEvent) => {
      if (!fabDragging.current) return;
      if (Math.abs(e.clientX - fabDragStart.current.x) > 3 || Math.abs(e.clientY - fabDragStart.current.y) > 3) {
        fabHasMoved.current = true;
      }
      const x = Math.max(0, Math.min(e.clientX - fabDragOffset.current.x, window.innerWidth - FAB_W));
      const y = Math.max(0, Math.min(e.clientY - fabDragOffset.current.y, window.innerHeight - FAB_H));
      // Direct DOM update — no React re-render
      fabPosRef.current = { x, y };
      if (fabRef.current) {
        fabRef.current.style.left = x + 'px';
        fabRef.current.style.top = y + 'px';
      }
    };
    const onFabDragEnd = () => {
      fabDragging.current = false;
      // Commit final position to store (single re-render)
      setFabPos({ ...fabPosRef.current });
      // Re-enable transition for smooth hover effect
      if (fabRef.current) fabRef.current.style.transition = '';
    };
    document.addEventListener('mousemove', onFabDragMove);
    document.addEventListener('mouseup', onFabDragEnd);
    return () => {
      document.removeEventListener('mousemove', onFabDragMove);
      document.removeEventListener('mouseup', onFabDragEnd);
    };
  }, [setFabPos]);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  // Auto-send initialMessage from parent (e.g. KnowledgeBase "AI诊断" button)
  useEffect(() => {
    if (!initialMessage || initialSent.current) return;
    initialSent.current = true;
    setOpen(true);
    const timer = setTimeout(() => handleSend(initialMessage), 200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialMessage]);

  const captureScreenshot = async (): Promise<string | null> => {
    try {
      const mainEl = document.querySelector('main');
      if (!mainEl) return null;

      const canvas = await html2canvas(mainEl as HTMLElement, {
        useCORS: true,
        allowTaint: true,
        scale: 0.5,
        ignoreElements: (el) => el.closest('[data-copilot-ignore]') !== null,
        backgroundColor: '#080c12',
      });

      const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
      return dataUrl.split(',')[1];
    } catch (err) {
      console.warn('Screenshot capture failed:', err);
      return null;
    }
  };

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    if (mode === 'chat' && (!currentSession?.providerConfigId || !currentSession.model)) {
      addMessage({
        role: 'error',
        content: '**AI会话未选择模型**\n请先在会话栏选择供应商和模型；如果没有可选项，请到系统设置的 AI 设置页保存供应商配置。',
      });
      return;
    }
    if (mode === 'agent' && pendingAgentPlanId && /^(取消|算了|不用了|停止|终止)$/i.test(text)) {
      const planId = pendingAgentPlanId;
      addMessage({ role: 'user', content: text });
      if (!textOverride) setInput('');
      setPendingAgentPlanId(null);
      try {
        await api.post(`/agent-tasks/${planId}/cancel`, {}, { timeout: 10000 });
      } catch {
        // The local state is already cleared; stale server plans expire automatically.
      }
      addMessage({ role: 'assistant', content: '已取消本次 Agent 追问计划。' });
      return;
    }
    const userMsg: Message = { role: 'user', content: text };
    addMessage(userMsg);
    if (!textOverride) setInput('');
    setLoading(true);

    let screenshot: string | null = null;
    if (shouldAttachScreenshot(mode, attachScreenshotOnce)) {
      try {
        screenshot = await captureScreenshot();
      } catch {
        // Silently fall back to text-only mode
      }
    }

    // Build page_context: merge auto-detected info with page-specific context from props
    const baseContext: Record<string, unknown> = {
      page_type: window.location.pathname.replace('/', '') || 'dashboard',
      url: window.location.href,
    };
    if (pageContext) Object.assign(baseContext, pageContext);

    try {
      // Get all messages currently in store (including the one just added)
      const currentMsgs = useCopilotStore.getState().messages;
      const allMsgs = [...currentMsgs]
        .filter((m) => (m.role === 'user' || m.role === 'assistant') && !m._progress)
        .map((m) => ({ role: m.role, content: m.content }));
      const session = useCopilotStore.getState().sessions.find((item) => item.id === useCopilotStore.getState().currentSessionId);
      const compactMsgs = compactChatMessages(allMsgs);
      const sessionMsgs = session?.summary
        ? [{ role: 'system', content: `这是从上一会话继承的摘要，请作为背景参考，不要逐字复述：\n${session.summary}` }, ...compactMsgs]
        : compactMsgs;

      let reply: string | null = null;

      if (mode === 'agent') {
        const progressId = Date.now().toString();
        addMessage({ role: 'assistant', content: `分析任务中...`, _progress: true, _progressId: progressId });

        try {
          const { data: taskPlan } = await api.post<AgentTaskPlanResponse>('/agent-tasks/plan', {
            message: text,
            page_context: baseContext,
            plan_id: pendingAgentPlanId,
            provider_config_id: session?.providerConfigId,
            model: session?.model,
          }, { timeout: 120000 });

          useCopilotStore.getState().removeMessage(progressId);
          const display = taskPlan.display || {};
          const slotSummary = formatAgentSlots(taskPlan.slots);
          const stepSummary = formatAgentSteps(taskPlan.steps);
          if (display.navigate_to && typeof display.navigate_to === 'string') {
            navigate(display.navigate_to);
          }

          if (taskPlan.status === 'pending_confirmation' && taskPlan.request_id && taskPlan.action && taskPlan.confirmation) {
            setPendingAgentPlanId(null);
            setPendingAgentAction({
              requestId: taskPlan.request_id,
              action: taskPlan.action,
              taskType: taskPlan.task_type,
              workflow: taskPlan.workflow,
              confidence: taskPlan.confidence || 0,
              confirmation: taskPlan.confirmation,
            });
            addMessage({
              role: 'assistant',
              content: [
                '**Agent已识别到数据变更动作，等待确认。**',
                taskPlan.confirmation.summary,
                taskPlan.playbook_id ? `任务模板: \`${taskPlan.playbook_id}\`` : '',
                taskPlan.task_kind ? `任务类型: \`${taskPlan.task_kind}\`` : '',
                taskPlan.planner_source ? `规划来源: \`${taskPlan.planner_source}\`` : '',
                slotSummary ? `槽位: ${slotSummary}` : '',
                stepSummary ? `任务步骤: ${stepSummary}` : '',
                `解析置信度: ${Math.round((taskPlan.confidence || 0) * 100)}%`,
              ].filter(Boolean).join('\n'),
            });
            return;
          }

          if (taskPlan.status === 'needs_clarification') {
            setPendingAgentPlanId(taskPlan.plan_id || null);
            addMessage({
              role: 'assistant',
              content: [
                taskPlan.clarification_question || '请补充必要信息后再执行。',
                taskPlan.playbook_id ? `\n> 任务模板：${taskPlan.playbook_id}` : '',
                taskPlan.task_kind ? `\n> 任务类型：${taskPlan.task_kind}` : '',
                taskPlan.planner_source ? `\n> 规划来源：${taskPlan.planner_source}` : '',
                slotSummary ? `\n> 已识别槽位：${slotSummary}` : '',
                stepSummary ? `\n> 任务步骤：${stepSummary}` : '',
              ].filter(Boolean).join(''),
            });
            return;
          }

          if (taskPlan.status === 'error') {
            setPendingAgentPlanId(null);
            addMessage({
              role: 'error',
              content: [
                '**Agent任务无法处理**',
                taskPlan.error_message || taskPlan.answer || '请求未通过后端校验。',
                '',
                `- 错误码: \`${taskPlan.error_code || 'agent_task_failed'}\``,
                taskPlan.playbook_id ? `- 任务模板: \`${taskPlan.playbook_id}\`` : '',
                taskPlan.task_kind ? `- 任务类型: \`${taskPlan.task_kind}\`` : '',
                taskPlan.planner_source ? `- 规划来源: \`${taskPlan.planner_source}\`` : '',
                slotSummary ? `- 已识别槽位: ${slotSummary}` : '',
                stepSummary ? `- 任务步骤: ${stepSummary}` : '',
              ].join('\n'),
            });
            return;
          }

          const meta = [
            taskPlan.playbook_id ? `任务模板: \`${taskPlan.playbook_id}\`` : '',
            taskPlan.task_kind ? `任务类型: \`${taskPlan.task_kind}\`` : '',
            taskPlan.planner_source ? `规划来源: \`${taskPlan.planner_source}\`` : '',
            taskPlan.workflow ? `流程: \`${taskPlan.workflow}\`` : '',
            `置信度: ${Math.round((taskPlan.confidence || 0) * 100)}%`,
          ].filter(Boolean);
          const candidates = (taskPlan.candidates || [])
            .slice(0, 3)
            .map((item) => `\`${item.id}\``)
            .join('、');
          const body = taskPlan.answer || taskPlan.error_message || 'Agent已完成任务识别，但未生成额外文本。';
          addMessage({
            role: taskPlan.status === 'unsupported' ? 'assistant' : 'assistant',
            content: [
              body,
              '',
              `> ${meta.join(' · ')}`,
              slotSummary ? `> 已识别槽位：${slotSummary}` : '',
              stepSummary ? `> 任务步骤：${stepSummary}` : '',
              candidates ? `> 候选任务：${candidates}` : '',
            ].filter(Boolean).join('\n'),
          });
          setPendingAgentPlanId(null);
          return;
        } catch (error: any) {
          useCopilotStore.getState().removeMessage(progressId);
          addMessage({
            role: 'error',
            content: formatCopilotError(error?.response?.data, 'Agent任务规划失败，请确认后端服务、登录状态和网络连接正常。'),
          });
          return;
        }
      } else {
        // AI 对话模式 — 走 Copilot 对话链路
        const payload: Record<string, unknown> = {
          messages: sessionMsgs,
          page_context: baseContext,
          selected_contexts: selectedContextIds,
          session_id: session?.id,
          provider_config_id: session?.providerConfigId,
          model: session?.model,
          session_title_needed: !session?.title || session.title === '新建AI会话' || session.title.endsWith(' - 新模型'),
        };
        if (screenshot) payload.screenshot = screenshot;
        const streamId = `stream-${Date.now()}`;
        let streamedReply = '';
        let contextSources: ContextSource[] = [];
        let streamFailed = false;
        addMessage({ role: 'assistant', content: 'AI生成中...', _progress: true, _progressId: streamId });
        await postCopilotStream(payload, (event) => {
          if (event.type === 'meta') {
            contextSources = event.context_sources || [];
            return;
          }
          if (event.type === 'delta') {
            streamedReply += event.delta || '';
            updateMessage(streamId, { content: streamedReply || 'AI生成中...', _progress: true });
            return;
          }
          if (event.type === 'title' && event.session_title) {
            updateCurrentSessionMeta({ title: event.session_title });
            return;
          }
          if (event.type === 'error') {
            streamFailed = true;
            updateMessage(streamId, {
              role: 'error',
              content: formatCopilotError(event),
              _progress: false,
            });
          }
        });
        if (streamFailed) return;
        if (contextSources.length) {
          const labels = contextSources
            .map((source) => source.tools?.length ? `${source.label}（${source.tools.join('、')}）` : source.label)
            .join('、');
          streamedReply = `${streamedReply}\n\n> 本次参考数据：${labels}`;
        }
        updateMessage(streamId, {
          content: streamedReply || '本次未收到AI回复内容。',
          _progress: false,
        });
      }

      if (reply !== null) addMessage({ role: 'assistant', content: reply });
    } catch (error: any) {
      addMessage({
        role: 'error',
        content: formatCopilotError(error?.response?.data, 'AI服务请求失败，请确认后端服务、登录状态和网络连接正常。'),
      });
    } finally {
      setAttachScreenshotOnce(false);
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <>
      {/* Floating Action Button — draggable */}
      {fabPos.x >= 0 && !open && (
        <button
          ref={fabRef}
          data-copilot-ignore
          onMouseDown={onFabMouseDown}
          onClick={() => { if (!fabHasMoved.current) setOpen(true); }}
          className="fixed z-50 w-14 h-14 rounded-full bg-accent-blue shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center select-none"
          style={{ left: fabPos.x, top: fabPos.y, boxShadow: '0 0 20px rgba(88,166,255,0.4)' }}
        >
          <span className="text-2xl">💬</span>
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-accent-green border-2 border-bg-primary animate-pulse" />
        </button>
      )}

      {/* Chat Panel — draggable */}
      {open && (
        <div
          ref={panelRef}
          data-copilot-ignore
          className="fixed z-50 shadow-2xl flex flex-col overflow-hidden rounded-xl border border-border-default bg-bg-card"
          style={{ left: panelPos.x, top: panelPos.y, width: PANEL_W, height: PANEL_H }}
        >
          {/* Header — drag handle */}
          <div
            className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-bg-secondary cursor-move select-none"
            onMouseDown={onDragStart}
          >
            <div className="flex items-center gap-2">
              <span className="text-lg">🤖</span>
              <div>
                <h3 className="text-sm font-medium">风调AI助手</h3>
                <p className="text-[10px] text-accent-green">
                  {mode === 'agent'
                    ? 'Agent任务 · 自动执行'
                    : `${currentSession?.model || '未选择模型'} · 在线`}
                </p>
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-primary text-lg">✕</button>
          </div>

          {/* Mode Toggle — AI对话 / Agent诊断 */}
          <div className="flex gap-1 px-4 py-2 border-b border-border-default bg-bg-secondary">
            <button
              onClick={() => switchMode('chat')}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                mode === 'chat'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
              }`}
            >
              💬 AI对话
            </button>
            <button
              onClick={() => switchMode('agent')}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                mode === 'agent'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
              }`}
            >
              🔧 Agent任务
            </button>
          </div>

          <div className="flex min-h-0 flex-1">
            <aside className="w-36 shrink-0 border-r border-border-default bg-bg-secondary/70 px-2 py-3">
              <div className="mb-2 px-1">
                <p className="text-[11px] font-medium text-text-primary">数据栏</p>
                <p className="mt-0.5 text-[9px] leading-3 text-text-muted">可选；不选则由AI自行判断需求</p>
              </div>
              <div className="space-y-1">
                {DATA_CONTEXT_OPTIONS.map((item) => {
                  const active = selectedContextIds.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => toggleDataContext(item.id)}
                      title={item.hint}
                      className={`w-full rounded-md border px-2 py-1.5 text-left transition-colors ${
                        active
                          ? 'border-accent-blue bg-accent-blue/15 text-text-primary'
                          : 'border-border-default bg-bg-card text-text-muted hover:border-accent-blue hover:text-text-primary'
                      }`}
                    >
                      <span className="block text-[11px] font-medium leading-4">{item.label}</span>
                      <span className="block truncate text-[9px] leading-3 opacity-75">{item.hint}</span>
                    </button>
                  );
                })}
              </div>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
          {/* Session and model controls */}
          <div className="px-4 py-2 border-b border-border-default bg-bg-secondary space-y-2">
            <div className="flex gap-2">
              <select
                value={currentSessionId}
                onChange={(e) => switchSession(e.target.value)}
                className="min-w-0 flex-1 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue"
              >
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.title} · {session.model || '未选模型'}
                  </option>
                ))}
              </select>
              <button
                onClick={createBlankSession}
                className="px-2 py-1.5 rounded-md border border-border-default text-[11px] text-text-secondary hover:text-accent-blue hover:border-accent-blue"
                title="新建会话"
              >
                新建
              </button>
              <button
                onClick={() => setPendingDeleteSessionId(currentSessionId)}
                disabled={sessions.length <= 1}
                className="px-2 py-1.5 rounded-md border border-border-default text-[11px] text-text-secondary hover:text-accent-red hover:border-accent-red disabled:opacity-40"
                title="删除当前会话"
              >
                删除
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={currentSession?.providerConfigId || ''}
                onChange={(e) => handleProviderSelect(e.target.value)}
                disabled={modelLocked}
                title={modelLocked ? '会话已开始，供应商已锁定' : '选择本会话供应商'}
                className="min-w-0 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-60"
              >
                <option value="">选择供应商</option>
                {availableProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.display_name || provider.provider}
                    {provider.last_test_status === 'error' ? ' (连接异常)' : ''}
                  </option>
                ))}
              </select>
              <select
                value={modelDraft}
                onChange={(e) => handleModelSelect(e.target.value)}
                disabled={modelLocked || !selectedProvider}
                title={modelLocked ? '会话已开始，模型已锁定' : '选择本会话模型'}
                className="min-w-0 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-60"
              >
                {selectedModelOptions.length === 0 && <option value="">无可选模型</option>}
                {selectedModelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            {modelLocked && (
              <p className="text-[10px] text-text-muted">当前会话已开始，供应商和模型已锁定；需要切换模型时请新建会话。</p>
            )}
            {availableProviders.length === 0 && (
              <p className="text-[10px] text-accent-yellow">
                暂无可用AI供应商，请先到系统设置的 AI 设置页保存并测试供应商配置。
              </p>
            )}
            {pendingDeleteSession && (
              <div className="rounded-md border border-accent-red/30 bg-accent-red/10 px-3 py-2">
                <p className="text-[11px] font-medium text-accent-red">确认删除当前会话？</p>
                <p className="mt-1 line-clamp-2 text-[10px] text-text-secondary">
                  {pendingDeleteSession.title} · {pendingDeleteSession.model || '未选模型'}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setPendingDeleteSessionId(null)}
                    className="rounded border border-border-default px-3 py-1.5 text-[11px] text-text-secondary hover:text-text-primary"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={confirmDeleteSession}
                    className="rounded border border-accent-red/40 bg-accent-red/15 px-3 py-1.5 text-[11px] text-accent-red hover:bg-accent-red/20"
                  >
                    删除
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Messages */}
          <div ref={chatRef} className="flex-1 overflow-auto p-4 space-y-3 text-xs">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 ${
                  m.role === 'user'
                    ? 'bg-accent-blue/20 text-text-primary'
                    : m.role === 'error'
                    ? 'bg-accent-red/10 text-accent-red'
                    : m._progress
                    ? 'bg-accent-cyan/10 text-accent-cyan animate-pulse'
                    : 'bg-bg-hover text-text-primary'
                }`}>
                  {renderMessageContent(m.content, m._progress)}
                </div>
              </div>
            ))}
            {loading && <p className="text-text-muted animate-pulse">AI思考中...</p>}
          </div>

          {/* Input */}
          <div className="p-3 border-t border-border-default">
            {pendingAgentAction && (
              <div className="mb-3 rounded-lg border border-accent-blue/40 bg-accent-blue/10 p-3 text-xs">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium text-text-primary">{pendingAgentAction.confirmation.title}</p>
                    <p className="mt-1 text-text-secondary">{pendingAgentAction.confirmation.summary}</p>
                    {(pendingAgentAction.workflow || pendingAgentAction.taskType) && (
                      <p className="mt-1 text-[10px] text-text-muted">
                        {pendingAgentAction.workflow || pendingAgentAction.taskType}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 rounded border border-accent-blue/30 px-2 py-0.5 text-[10px] text-accent-blue">
                    {Math.round(pendingAgentAction.confidence * 100)}%
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  {[
                    { title: '执行前', rows: buildAgentSnapshotRows(pendingAgentAction.confirmation.before) },
                    { title: '执行后', rows: buildAgentSnapshotRows(pendingAgentAction.confirmation.after) },
                  ].map((group) => (
                    <div key={group.title} className="rounded border border-border-default bg-bg-card p-2">
                      <p className="mb-1 text-text-muted">{group.title}</p>
                      {group.rows.length > 0 ? (
                        <div className="space-y-1">
                          {group.rows.map((row) => (
                            <p key={`${group.title}-${row.label}`} className="break-words">
                              <span className="text-text-muted">{row.label}: </span>{row.value}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-text-muted">无现有记录</p>
                      )}
                    </div>
                  ))}
                </div>
                {pendingAgentAction.confirmation.warnings.length > 0 && (
                  <div className="mt-2 rounded border border-accent-yellow/30 bg-accent-yellow/10 p-2 text-[10px] text-accent-yellow">
                    {pendingAgentAction.confirmation.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                  </div>
                )}
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={cancelPendingAgentAction}
                    disabled={loading}
                    className="rounded border border-border-default px-3 py-1.5 text-[11px] text-text-secondary hover:text-text-primary disabled:opacity-40"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={confirmPendingAgentAction}
                    disabled={loading}
                    className="rounded border border-accent-blue/40 bg-accent-blue px-3 py-1.5 text-[11px] text-white hover:opacity-90 disabled:opacity-40"
                  >
                    确认执行
                  </button>
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  mode === 'agent'
                    ? '输入任务指令，如：查看故障诊断页面'
                    : '输入问题, 如: 当前风场运行状态如何?'
                }
                className="flex-1 bg-bg-secondary border border-border-default rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              />
              {mode === 'chat' && (
                <button
                  type="button"
                  onClick={() => setAttachScreenshotOnce((value) => !value)}
                  disabled={loading}
                  title="仅本次发送附加当前页面截图"
                  className={`px-3 py-2 rounded-lg border text-xs transition-colors disabled:opacity-40 ${
                    attachScreenshotOnce
                      ? 'border-accent-blue bg-accent-blue/15 text-accent-blue'
                      : 'border-border-default text-text-muted hover:text-accent-blue hover:border-accent-blue'
                  }`}
                >
                  {attachScreenshotOnce ? '已附图' : '附图'}
                </button>
              )}
              <button
                onClick={() => handleSend()}
                disabled={loading || !input.trim()}
                className="px-4 py-2 bg-accent-blue text-white rounded-lg text-xs hover:opacity-90 disabled:opacity-40 transition-opacity"
              >
                发送
              </button>
            </div>
            <div className="flex gap-2 mt-2">
              {(mode === 'agent'
                ? ['查看故障诊断页面', '查看维护人员工作量', '查看所有工单']
                : ['总结当前状态', '最近故障', '健康趋势分析']
              ).map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="text-[10px] px-2 py-1 rounded border border-border-default text-text-muted hover:text-accent-blue hover:border-accent-blue transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
