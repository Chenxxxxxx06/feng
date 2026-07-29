import api from './api';

/**
 * 审计链篡改检测演示服务 —— 对接后端 /api/audit-demo。
 *
 * 后端的三个端点全部只读：篡改只发生在 `build_chain` 产出的**内存副本**
 * （额外 deepcopy）上，响应里的 `database_mutated` 恒为 false。
 * 前端必须把这一点显式展示出来 —— 「演示不改真实数据」本身就是设计承诺。
 */

/** 签名密钥状态（不含私钥） */
export interface AuditDemoStatus {
  signing_enabled: boolean;
  algorithm: string;
  key_source: string;
  key_path: string;
  public_key: string;
  hash_algorithm: string;
  note: string;
  default_enabled: boolean;
  demo_incident_available: boolean;
  demo_incident_id: string | null;
  checked_at: string;
}

/** 可用于演示的事件 */
export interface AuditDemoCandidate {
  /** 数据库主键，POST /audit-demo/tamper-check 的 incident_id 用的就是它 */
  id: number;
  /** 业务事件号，例如 INC-20260726-001 */
  incident_id: string;
  title: string;
  severity: string;
  /** 该事件的审计环数量 */
  audit_links: number;
}

export interface AuditDemoCandidates {
  total: number;
  candidates: AuditDemoCandidate[];
}

/** 审计链上的一环 */
export interface AuditChainLink {
  seq: number;
  action_type: string;
  agent: string;
  decision: string;
  input_hash: string;
  output_hash: string;
  /** 本环记录的前驱哈希 */
  prev_hash: string;
  /** 链上记录的当前哈希 */
  current_hash: string;
  /** 由本环内容现场重算出的哈希 */
  recomputed_hash: string;
  /** 前驱链接是否连得上 */
  link_ok: boolean;
  /** 内容哈希是否与链上记录一致 */
  hash_ok: boolean;
  valid: boolean;
  /** 中文判定说明 */
  reason: string;
  timestamp: string;
}

/** Ed25519 根签名信息块 */
export interface RootSignatureBlock {
  algorithm: string;
  enabled: boolean;
  signature: string;
  verified: boolean;
  note: string;
}

/** 一次全链校验的结构化结果 */
export interface AuditChainReport {
  total_entries: number;
  chain_valid: boolean;
  first_broken_at: number | null;
  broken_entries: number[];
  root_hash: string;
  links: AuditChainLink[];
  signature: RootSignatureBlock;
}

export interface TamperDescriptor {
  seq: number;
  field: string;
  before: string;
  after: string;
  /** 攻击者是否重算了该环哈希 */
  recomputed_hash?: boolean;
  /** 攻击者是否重算了整条下游链 */
  rechained_downstream?: boolean;
}

/** 检出手段 */
export type DetectionMethod = 'content_hash' | 'chain_linkage' | 'root_signature';

export interface TamperScenario {
  id: string;
  name: string;
  /** 该场景假设的攻击者能力 */
  attacker_capability: string;
  tamper: TamperDescriptor;
  result: AuditChainReport;
  detected: boolean;
  detected_by: Array<DetectionMethod | string>;
  conclusion: string;
  /** 场景三独有：纯哈希校验是否全部通过（true = 攻击者伪造出自洽的链） */
  hash_only_check_passed?: boolean;
  root_hash_changed?: boolean;
}

export interface TamperSummary {
  baseline_chain_valid: boolean;
  baseline_signature_verified: boolean;
  scenarios_total: number;
  scenarios_detected: number;
  all_detected: boolean;
  /** 一句话结论，可直接投屏 */
  headline: string;
}

export interface TamperCheckResponse {
  generated_at: string;
  data_source: 'real_incident' | 'synthetic_demo' | string;
  data_source_note: string;
  incident_id: string | null;
  incident_title: string | null;
  signing: Omit<AuditDemoStatus, 'default_enabled' | 'demo_incident_available' | 'demo_incident_id' | 'checked_at'>;
  tamperable_fields: string[];
  baseline: AuditChainReport;
  scenarios: TamperScenario[];
  summary: TamperSummary;
  /** 恒为 false —— 篡改只发生在内存副本上 */
  database_mutated: boolean;
  safety_note: string;
}

export interface TamperCheckRequest {
  /** 事件数据库主键；留空则后端自动挑审计环最多的事件 */
  incident_id?: number | null;
  /** 篡改第几环（1 起）；留空则取链条中部 */
  tamper_seq?: number | null;
  tamper_field?: string;
  tamper_value?: string;
  allow_synthetic?: boolean;
}

const BASE = '/audit-demo';

/** 查询签名能力状态（只读） */
export async function fetchAuditDemoStatus(): Promise<AuditDemoStatus> {
  const { data } = await api.get(`${BASE}/status`);
  return data;
}

/** 列出可用于演示的事件（按审计环数从多到少） */
export async function fetchAuditDemoCandidates(): Promise<AuditDemoCandidates> {
  const { data } = await api.get(`${BASE}/candidates`);
  return data;
}

/** 运行篡改检测演示。后端全程只对数据库做 SELECT，不写库。 */
export async function runTamperCheck(payload: TamperCheckRequest = {}): Promise<TamperCheckResponse> {
  const { data } = await api.post(`${BASE}/tamper-check`, payload, { timeout: 60000 });
  return data;
}

// ── 展示层辅助 ────────────────────────────────────────────────

/** 长哈希截断显示（完整值请挂到 title 上供 hover 查看） */
export function shortHash(hash?: string | null, head = 12): string {
  if (!hash) return '—';
  if (hash.length <= head) return hash;
  return `${hash.slice(0, head)}…`;
}

/** 检出手段 → 中文标签与说明 */
export const DETECTION_META: Record<string, { label: string; desc: string }> = {
  content_hash: {
    label: '内容哈希',
    desc: '重算该环内容的 SHA-256，与链上记录不一致即暴露',
  },
  chain_linkage: {
    label: '链式链接',
    desc: '下一环记录的前驱哈希与上一环实际哈希对不上，链断裂',
  },
  root_signature: {
    label: 'Ed25519 根签名',
    desc: '根哈希变化后，用原始签名验签失败 —— 攻击者没有私钥，无法重新签名',
  },
};

export function detectionLabel(method: string): string {
  return DETECTION_META[method]?.label ?? method;
}

/** 可篡改字段 → 中文标签 */
export const TAMPER_FIELD_LABEL: Record<string, string> = {
  decision: 'decision（决策结论）',
  output_hash: 'output_hash（输出摘要）',
  input_hash: 'input_hash（输入摘要）',
  action_type: 'action_type（动作类型）',
  agent: 'agent（执行体）',
};

export function tamperFieldLabel(field: string): string {
  return TAMPER_FIELD_LABEL[field] ?? field;
}

/** 场景 id → 用于并排对比的短标题 */
export const SCENARIO_SHORT_NAME: Record<string, string> = {
  content_tamper: '场景一 · 只改内容',
  hash_recompute: '场景二 · 改内容 + 重算本环',
  full_rechain: '场景三 · 重写整条下游链',
};

export function scenarioShortName(id: string, fallback: string): string {
  return SCENARIO_SHORT_NAME[id] ?? fallback;
}

/** 从错误对象里提取可读的中文提示 */
export function describeAuditDemoError(err: unknown): string {
  const anyErr = err as {
    response?: { status?: number; data?: { detail?: string } };
    message?: string;
  };
  const status = anyErr?.response?.status;
  const detail = anyErr?.response?.data?.detail;
  if (status === 401) return '登录已过期，请重新登录后运行演示';
  if (status === 403) return '当前账号无权运行审计链演示';
  if (status === 404) return String(detail || '该事件没有可供演示的 Agent 审计记录');
  if (detail) return String(detail);
  if (!anyErr?.response) return '无法连接后端服务，请确认服务已启动';
  return anyErr?.message || '篡改检测演示执行失败';
}
