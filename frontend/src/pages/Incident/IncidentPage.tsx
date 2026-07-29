import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  fetchIncidents, fetchIncident, createIncident, compressAlarms, fetchEvidenceGraph,
  addEvidenceNode, addEvidenceEdge, generateDecisionSandbox, checkPolicy,
  transitionIncident, startTrace, fetchTraces,
  startInvestigation, generatePlans, verifyRecovery, getEvidenceCompleteness,
  getEconomicImpact, getAuditChain, verifyAuditChain,
  getWhatIfAnalysis, getTaskPackage, getComplianceCheck,
} from '../../services/incidentService';
import api from '../../services/api';
import type {
  AgentTrace, AlarmCluster, GeneratedDecisionPlan,
  EvidenceGraph, Incident, PolicyCheckResponse, Turbine,
} from '../../types';
import EconomicImpactPanel from './components/EconomicImpactPanel';
import InvestigationPanel from './components/InvestigationPanel';
import AuditChainPanel from './components/AuditChainPanel';
import TamperCheckPanel from './components/TamperCheckPanel';
import WhatIfPanel from './components/WhatIfPanel';
import RedTeamPanel from './components/RedTeamPanel';
import CompliancePanel from './components/CompliancePanel';
import TaskPackagePanel from './components/TaskPackagePanel';
import HealthPassportPanel from './components/HealthPassportPanel';
import DeepAnalysisPanel from './components/DeepAnalysisPanel';
import TraceWaterfall from '../../components/AgentCockpit/TraceWaterfall';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import StateBlock from '../../components/Common/StateBlock';
import { Skeleton, SkeletonList, SkeletonTable } from '../../components/Common/Skeleton';
import { toast } from '../../components/Common/Toast';
import { useHasMinimumRole, READ_ONLY_PERMISSION_TITLE } from '../../services/permissions';

// ── Constants ──

const STAGE_LABELS: Record<string, string> = {
  detected: '已检测', correlated: '已关联', diagnosing: '诊断中',
  decision_ready: '决策就绪', awaiting_approval: '待审批', executing: '执行中',
  verifying: '验证中', resolved: '已解决', escalated: '已升级',
};

const VERIFICATION_LABELS: Record<string, string> = {
  pending: '待验证',
  pass: '验证通过',
  conditional: '有条件通过',
  fail: '验证未通过',
  insufficient_data: '数据不足',
};

/** 严重程度 → 统一语义徽章（颜色不是唯一表达，同时给出中文文案） */
const SEV_LABEL: Record<string, string> = {
  low: '低', medium: '中', high: '高', critical: '严重',
};
const SEV_BADGE: Record<string, string> = {
  low: 'badge badge-neutral',
  medium: 'badge badge-warning',
  high: 'badge',
  critical: 'badge badge-danger badge-pulse',
};
const SEV_DOT: Record<string, string> = {
  low: 'dot dot-neutral',
  medium: 'dot dot-warning',
  high: 'dot',
  critical: 'dot dot-danger',
};
/** high 用 orange，需单独给色（设计令牌里 orange 无对应 badge 变体） */
const SEV_INLINE: Record<string, React.CSSProperties> = {
  high: { background: 'rgba(249,115,22,0.14)', borderColor: 'rgba(249,115,22,0.30)', color: 'var(--accent-orange)' },
};
const SEV_DOT_INLINE: Record<string, React.CSSProperties> = {
  high: { color: 'var(--accent-orange)' },
};

// State machine: which stages allow which actions
const STAGE_ALLOWED: Record<string, string[]> = {
  detected: ['investigate'],
  correlated: ['investigate', 'generate_plans'],
  diagnosing: ['investigate', 'generate_plans'],
  decision_ready: ['generate_plans', 'approve'],
  awaiting_approval: ['execute'],
  executing: ['verify'],
  verifying: ['verify', 'resolve'],
  resolved: [],
  escalated: [],
};

const INCIDENT_FLOW = [
  { key: 'detected', label: '异常发现' },
  { key: 'correlated', label: '告警汇聚' },
  { key: 'diagnosing', label: '自主调查' },
  { key: 'decision_ready', label: '决策生成' },
  { key: 'awaiting_approval', label: '人工审批' },
  { key: 'executing', label: '工单执行' },
  { key: 'verifying', label: '恢复验证' },
  { key: 'resolved', label: '闭环完成' },
];

const INCIDENT_TAB_GROUPS = [
  {
    key: 'command',
    label: '指挥处置',
    tabs: [['overview', '总览'], ['evidence', '证据'], ['decision', '决策']],
  },
  {
    key: 'execution',
    label: '执行推演',
    tabs: [['package', '任务包'], ['whatif', 'What-if'], ['economic', '经济']],
  },
  {
    key: 'governance',
    label: '安全治理',
    tabs: [['compliance', '合规'], ['redteam', '红队'], ['audit', '审计']],
  },
  {
    key: 'analysis',
    label: '分析追溯',
    tabs: [['deep', '深度分析'], ['passport', '健康护照'], ['traces', '追溯']],
  },
] as const;

function buildIncidentWorkOrderLink(incident: Incident): string {
  const params = new URLSearchParams({
    incident_id: String(incident.id),
    incident_ref: incident.incident_id,
    turbine_id: String(incident.turbine_id),
    turbine_name: incident.turbine_name,
    incident_title: incident.title,
  });
  return `/workorder?${params.toString()}`;
}

interface DecisionResourceSnapshot {
  fault_type?: string;
  fault_severity?: string;
  parts_status?: 'ready' | 'transfer_needed' | 'shortage' | 'unknown';
  parts_summary?: string;
  parts_earliest_ready_date?: string | null;
  parts_source_type?: 'historical' | 'simulated' | 'demo' | 'knowledge';
  spare_parts?: Array<Record<string, unknown>>;
  historical_success_rate?: number | null;
  weather_status?: 'available' | 'unavailable';
}

// ── Main page ──

export default function IncidentPage() {
  const canOperate = useHasMinimumRole('operator');
  const canEngineer = useHasMinimumRole('engineer');
  const isAdmin = useHasMinimumRole('admin');
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState('overview');

  // Detail states
  const [cluster, setCluster] = useState<AlarmCluster | null>(null);
  const [graph, setGraph] = useState<EvidenceGraph>({ nodes: [], edges: [] });
  const [plans, setPlans] = useState<GeneratedDecisionPlan[]>([]);
  const [decisionResources, setDecisionResources] = useState<DecisionResourceSnapshot | null>(null);
  const [policy, setPolicy] = useState<PolicyCheckResponse | null>(null);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [preparingDemo, setPreparingDemo] = useState(false);
  const [replayingDemo, setReplayingDemo] = useState(false);

  // Phase 1-2 state
  const [investigation, setInvestigation] = useState<any>(null);
  const [economicData, setEconomicData] = useState<any>(null);
  const [economicError, setEconomicError] = useState<string | null>(null);
  const [auditChain, setAuditChain] = useState<any>(null);
  const [ecoRefresh, setEcoRefresh] = useState(0);

  // Evidence refresh version — bumped after investigation / evidence changes
  const [evidenceVersion, setEvidenceVersion] = useState(0);

  // Create form
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const list = await fetchIncidents();
      setIncidents(list);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Refresh selected incident from server (preserves investigation state) ──
  const refreshSelected = useCallback(async (incidentId: number) => {
    try {
      const updated = await fetchIncident(incidentId);
      setSelected(updated);
      return updated;
    } catch {
      // keep current selected on failure
      return null;
    }
  }, []);

  // ── Refresh evidence graph + traces ──
  const refreshDetailData = useCallback(async (incidentId: number) => {
    try {
      const [g, t] = await Promise.all([
        fetchEvidenceGraph(incidentId).catch(() => ({ nodes: [], edges: [] })),
        fetchTraces(incidentId).catch(() => []),
      ]);
      setGraph(g); setTraces(t);
    } catch { /* keep stale data on error */ }
  }, []);

  // Economic impact live refresh
  useEffect(() => {
    if (!selected) return;
    const fetchEco = () => {
      getEconomicImpact(selected.id)
        .then((d) => { setEconomicData(d); setEconomicError(null); })
        .catch((e) => {
          setEconomicError(e?.response?.data?.detail || e?.message || '经济数据加载失败');
        });
    };
    fetchEco();
    const timer = setInterval(fetchEco, 30000);
    return () => clearInterval(timer);
  }, [selected?.id, ecoRefresh]);

  // Guard against slow responses overwriting a newer selection
  const selectSeqRef = useRef(0);
  const selectIncident = useCallback(async (inc: Incident) => {
    const seq = ++selectSeqRef.current;
    setSelected(inc);
    setActionMsg(null);
    setInvestigation(null);
    setAuditChain(null);
    setEconomicError(null);
    setPlans([]);
    setDecisionResources(null);
    setEvidenceVersion(v => v + 1);
    try {
      const [g, t] = await Promise.all([
        fetchEvidenceGraph(inc.id).catch(() => ({ nodes: [], edges: [] })),
        fetchTraces(inc.id).catch(() => []),
      ]);
      if (seq !== selectSeqRef.current) return; // stale: another incident selected since
      setGraph(g); setTraces(t);
    } catch { /* ignore */ }
  }, []);

  const prepareCompetitionDemo = async () => {
    setPreparingDemo(true);
    try {
      const { data } = await api.post('/competition-demo/prepare');
      const list = await fetchIncidents();
      setIncidents(list);
      const demo = list.find((item) => item.id === Number(data.incident_id));
      if (demo) {
        await selectIncident(demo);
      }
      toast.success(
        '评审演示场景已重置',
        `已准备 ${data.scenario}，清理旧事件 ${data.legacy_incidents_removed || 0} 条、旧工单 ${data.legacy_workorders_removed || 0} 条`,
      );
    } catch (e: any) {
      const message = e?.response?.data?.detail || e?.message || '演示场景准备失败';
      toast.error('演示场景准备失败', typeof message === 'string' ? message : JSON.stringify(message));
    } finally {
      setPreparingDemo(false);
    }
  };

  const replayCompetitionDemoTime = async () => {
    if (!selected) return;
    setReplayingDemo(true);
    try {
      const { data } = await api.post(`/competition-demo/incidents/${selected.id}/time-replay`);
      await Promise.all([refreshSelected(selected.id), refreshDetailData(selected.id)]);
      toast.success(
        '演示时间回放完成',
        `工单 WO-${String(data.work_order_id).padStart(4, '0')} 已生成 ${data.simulated_elapsed_hours} 小时复测窗口`,
      );
    } catch (e: any) {
      const message = e?.response?.data?.detail || e?.message || '演示时间回放失败';
      toast.error('演示时间回放失败', typeof message === 'string' ? message : JSON.stringify(message));
    } finally {
      setReplayingDemo(false);
    }
  };

  const doAction = async (label: string, fn: () => Promise<any>) => {
    setActionLoading(true); setActionMsg(`${label}…`);
    try {
      const result = await fn();
      setActionMsg(`${label} 已完成`);
      toast.success(`${label} 已完成`);
      return result;
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || `${label} 失败`;
      const text = typeof msg === 'string' ? msg : JSON.stringify(msg);
      setActionMsg(`${label} 失败：${text}`);
      toast.error(`${label} 失败`, text);
      throw e;
    } finally { setActionLoading(false); }
  };

  // P0-01 FIX: Investigation result persists — refresh incident + detail data without clearing
  const handleStartInvestigation = () => {
    if (!selected) return;
    doAction('启动自主调查', () => startInvestigation(selected.id))
      .then((result) => {
        setInvestigation(result);
        // Refresh incident from server (stage may have advanced)
        return refreshSelected(selected.id);
      })
      .then(() => refreshDetailData(selected.id))
      .then(() => setEvidenceVersion(v => v + 1))
      .catch(() => {}); // doAction already sets error message
  };

  const handleGeneratePlans = () => {
    if (!selected) return;
    doAction('生成决策方案', () => generatePlans(selected.id))
      .then((result) => {
        setPlans(result.plans || []);
        setDecisionResources(result.resource_snapshot || null);
        return refreshSelected(selected.id);
      })
      .catch(() => {});
  };

  // P0-02 FIX: Use server-returned data to update state atomically
  const handleVerifyRecovery = () => {
    if (!selected) return;
    doAction('运行恢复验证', () => verifyRecovery(selected.id))
      .then((result) => {
        // Refresh incident from server to get updated verification_status
        return refreshSelected(selected.id);
      })
      .catch(() => {});
  };

  // P0-02 FIX: transitionIncident returns updated incident — use it directly
  const handleTransition = async (target: string) => {
    if (!selected) return;
    try {
      const updated = await doAction(`状态转换→${STAGE_LABELS[target] || target}`, () =>
        transitionIncident(selected.id, target, '')
      );
      // Use server-returned incident for atomic state update
      if (updated) {
        setSelected(updated);
      }
      await refreshDetailData(selected.id);
    } catch { /* doAction already sets error */ }
  };

  // ── State-machine driven button visibility ──
  const allowedActions = STAGE_ALLOWED[selected?.stage || ''] || [];

  // ── Render ──

  if (loading) {
    return (
      <div className="ops-page page-enter h-full p-4">
        <div className="flex h-full gap-4">
          <div className="surface-card w-80 flex-shrink-0 p-3">
            <Skeleton className="skeleton-title mb-3" width={72} height={14} />
            <SkeletonList rows={6} />
          </div>
          <div className="surface-card flex-1 space-y-4 p-4">
            <Skeleton className="skeleton-title" width={220} height={16} />
            <div className="grid grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} height={64} radius={12} />)}
            </div>
            <SkeletonTable rows={6} cols={4} />
          </div>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="ops-page page-enter flex h-full items-center justify-center p-6">
        <StateBlock kind="error" title="事件列表加载失败" desc={error} onRetry={load} />
      </div>
    );
  }

  return (
    <>
      <div className="ops-page page-enter h-full flex gap-4 p-4">
      {/* ── Left: Incident list ── */}
      <aside className="surface-card stagger-1 w-72 xl:w-80 flex-shrink-0 flex flex-col overflow-hidden" aria-label="事件列表">
        <div className="flex items-center justify-between gap-2 border-b p-3" style={{ borderColor: 'var(--border-default)' }}>
          <h2 className="section-title">事件列表</h2>
          <div className="flex items-center gap-1.5">
            {isAdmin && (
              <button
                onClick={prepareCompetitionDemo}
                disabled={preparingDemo}
                className="btn btn-secondary btn-sm"
                title="重置明确标注为演示的数据，并清理旧 Demo / Smoke Test 事件"
                data-testid="prepare-competition-demo"
              >
                {preparingDemo ? '准备中…' : '评审演示'}
              </button>
            )}
            <button
              onClick={() => canOperate && setShowCreate(!showCreate)}
              disabled={!canOperate}
              title={canOperate ? '录入新的异常事件' : READ_ONLY_PERMISSION_TITLE}
              className={`btn btn-sm ${showCreate ? 'btn-secondary' : 'btn-primary'}`}
              aria-expanded={showCreate}
            >
              {showCreate ? '收起' : '+ 新建'}
            </button>
          </div>
        </div>
        {showCreate && <CreateForm onCreated={load} onClose={() => setShowCreate(false)} />}
        <div className="flex-1 overflow-y-auto">
          {incidents.length === 0 ? (
            <StateBlock kind="empty" title="暂无事件" desc="点击右上角「新建」录入一条事件，或等待告警自动汇聚。" />
          ) : (
            incidents.map(inc => {
              const active = selected?.id === inc.id;
              return (
                <button
                  key={inc.id}
                  onClick={() => selectIncident(inc)}
                  title={`${inc.title} · ${SEV_LABEL[inc.severity] || inc.severity}`}
                  aria-current={active ? 'true' : undefined}
                  className="w-full border-b p-3 text-left transition-colors hover:bg-bg-hover"
                  style={{
                    borderColor: 'var(--border-subtle)',
                    background: active ? 'rgba(59,130,246,0.14)' : undefined,
                    boxShadow: active ? 'inset 3px 0 0 var(--accent-blue)' : undefined,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className={SEV_DOT[inc.severity] || 'dot dot-neutral'} style={SEV_DOT_INLINE[inc.severity]} aria-hidden="true" />
                    <span className="truncate text-[12px] font-medium text-text-primary">{inc.title}</span>
                  </div>
                  <div className="mt-1 flex justify-between gap-2 text-[10px] text-text-muted">
                    <span className="num truncate">{inc.incident_id}</span>
                    <span className="flex-shrink-0">{STAGE_LABELS[inc.stage] || inc.stage}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* ── Right: Detail with tabs ── */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="surface-card stagger-1 mb-3 px-4 py-3">
          <h1 className="text-[16px] font-bold text-text-primary">事件指挥工作台</h1>
          <p className="mt-1 text-[12px] leading-5 text-text-secondary">
            跨模块异常处置工作台：汇聚异常、组织调查与证据、生成决策，经人工审批后进入维修执行和恢复验证。
          </p>
        </div>
        {!selected ? (
          <div className="surface-card flex flex-1 items-center justify-center">
            <StateBlock
              kind="empty"
              title="请选择一个事件查看详情"
              desc="在左侧事件列表中点击任意事件，即可进入调查、决策、审批与复盘的完整闭环。"
            />
          </div>
        ) : (
          <>
            {/* Incident header */}
            <div className="surface-card stagger-1 mb-3 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className={SEV_BADGE[selected.severity] || 'badge badge-neutral'} style={SEV_INLINE[selected.severity]}>
                      {SEV_LABEL[selected.severity] || selected.severity}
                    </span>
                    <h2 className="truncate text-[15px] font-bold text-text-primary" title={selected.title}>{selected.title}</h2>
                    <span className="num text-[10px] text-text-muted">{selected.incident_id}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-secondary">
                    <span>阶段：<span className="text-text-primary">{STAGE_LABELS[selected.stage] || selected.stage}</span></span>
                    <span>状态：<span className="text-text-primary">{selected.status}</span></span>
                    <span>验证：<span className="text-text-primary">{VERIFICATION_LABELS[selected.verification_status || 'pending'] || selected.verification_status}</span></span>
                    {selected.trace_id && <span className="num truncate text-[10px] text-text-muted" title={selected.trace_id}>Trace: {selected.trace_id}</span>}
                  </div>
                </div>
                {/* Quick actions — state-machine driven */}
                <div className="flex flex-wrap gap-2">
                  <Link
                    to={buildIncidentWorkOrderLink(selected)}
                    className="btn btn-secondary btn-sm"
                    data-testid="incident-create-workorder"
                  >
                    {canOperate ? '进入维修工单' : '查看维修工单'}
                  </Link>
                  {isAdmin
                    && selected.incident_id === 'INC-DEMO-YJ-A-013'
                    && ['executing', 'verifying'].includes(selected.stage) && (
                    <button
                      onClick={replayCompetitionDemoTime}
                      disabled={replayingDemo || actionLoading}
                      className="btn btn-secondary btn-sm"
                      title="仅回放明确标注的比赛演示数据，不修改正常生产数据"
                      data-testid="demo-time-replay"
                    >
                      {replayingDemo ? '回放中…' : '演示时间回放'}
                    </button>
                  )}
                  {allowedActions.includes('investigate') && (
                    <button
                      onClick={handleStartInvestigation}
                      disabled={actionLoading || !canOperate}
                      title={canOperate ? '启动自主调查' : READ_ONLY_PERMISSION_TITLE}
                      className="btn btn-primary btn-sm"
                    >
                      {actionLoading && <span className="btn-spinner" aria-hidden="true" />}自主调查
                    </button>
                  )}
                  {allowedActions.includes('generate_plans') && (
                    <button
                      onClick={handleGeneratePlans}
                      disabled={actionLoading || !canEngineer}
                      title={canEngineer ? '生成决策方案' : '需要工程师或更高权限'}
                      className="btn btn-success btn-sm"
                    >
                      {actionLoading && <span className="btn-spinner" aria-hidden="true" />}决策分析
                    </button>
                  )}
                  {allowedActions.includes('verify') && (
                    <button
                      onClick={handleVerifyRecovery}
                      disabled={actionLoading || !canEngineer}
                      title={canEngineer ? '运行恢复验证' : '需要工程师或更高权限'}
                      className="btn btn-sm"
                    >
                      {actionLoading && <span className="btn-spinner" aria-hidden="true" />}恢复验证
                    </button>
                  )}
                  {allowedActions.includes('approve') && (
                    <button
                      onClick={() => handleTransition('awaiting_approval')}
                      disabled={actionLoading || !canOperate}
                      title={canOperate ? '提交审批' : READ_ONLY_PERMISSION_TITLE}
                      className="btn btn-primary btn-sm"
                    >
                      提交审批
                    </button>
                  )}
                  {allowedActions.includes('execute') && (
                    <button
                      onClick={() => handleTransition('executing')}
                      disabled={actionLoading || !canOperate}
                      title={canOperate ? '开始执行' : READ_ONLY_PERMISSION_TITLE}
                      className="btn btn-success btn-sm"
                    >
                      开始执行
                    </button>
                  )}
                  {allowedActions.includes('resolve') && (
                    <button
                      onClick={() => handleTransition('resolved')}
                      disabled={actionLoading || !canOperate || selected.verification_status !== 'pass'}
                      className="btn btn-success btn-sm"
                      title={!canOperate
                        ? READ_ONLY_PERMISSION_TITLE
                        : selected.verification_status === 'pass'
                          ? '关闭事件并完成处置闭环'
                          : '恢复验证通过后才能关闭事件'}
                    >
                      {selected.verification_status === 'pass' ? '标记解决' : '验证通过后关闭'}
                    </button>
                  )}
                  {allowedActions.length === 0 && selected.stage !== 'resolved' && selected.stage !== 'escalated' && (
                    <span className="self-center px-2 text-[11px] text-text-muted">当前阶段无可执行操作</span>
                  )}
                </div>
              </div>
              <IncidentFlowBar stage={selected.stage} verificationStatus={selected.verification_status} />
              {actionMsg && (
                <p
                  className="mt-2 rounded-lg px-3 py-1.5 text-[11px]"
                  role="status"
                  style={
                    actionMsg.includes('已完成')
                      ? { background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)' }
                      : actionMsg.includes('失败')
                        ? { background: 'rgba(239,68,68,0.12)', color: 'var(--accent-red)' }
                        : { background: 'rgba(59,130,246,0.10)', color: 'var(--text-secondary)' }
                  }
                >
                  {actionMsg}
                </p>
              )}
              {/* P1-10: Show error states for degraded data */}
              {economicError && (
                <p className="mt-2 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[11px]" role="alert"
                  style={{ background: 'rgba(245,158,11,0.10)', borderColor: 'rgba(245,158,11,0.28)', color: 'var(--accent-yellow)' }}>
                  经济数据：{economicError}
                  <button onClick={() => setEcoRefresh(c => c + 1)} className="btn btn-ghost btn-xs" style={{ color: 'var(--accent-yellow)' }}>重试</button>
                </p>
              )}
            </div>

            {/* Two-level navigation keeps the command surface at four stable groups. */}
            <div className="mb-2 flex gap-2 overflow-x-auto" aria-label="事件功能分组">
              {INCIDENT_TAB_GROUPS.map((group) => {
                const active = group.tabs.some(([key]) => key === activeTab);
                return (
                  <button
                    key={group.key}
                    className={`btn btn-sm ${active ? 'btn-primary' : 'btn-secondary'}`}
                    aria-pressed={active}
                    onClick={() => setActiveTab(group.tabs[0][0])}
                  >
                    {group.label}
                  </button>
                );
              })}
            </div>
            <div className="mb-3 flex gap-1 overflow-x-auto border-b" style={{ borderColor: 'var(--border-default)' }} role="tablist" aria-label="事件详情视图">
              {(INCIDENT_TAB_GROUPS.find((group) => group.tabs.some(([key]) => key === activeTab))?.tabs
                || INCIDENT_TAB_GROUPS[0].tabs).map(([key, label]) => {
                const on = activeTab === key;
                return (
                  <button
                    key={key}
                    role="tab"
                    aria-selected={on}
                    onClick={() => setActiveTab(key)}
                    className="whitespace-nowrap px-3.5 py-2 text-[12px] transition-all duration-200"
                    style={{
                      borderTopLeftRadius: 'var(--radius-sm)',
                      borderTopRightRadius: 'var(--radius-sm)',
                      background: on ? 'rgba(59,130,246,0.12)' : 'transparent',
                      boxShadow: on ? 'inset 0 2px 0 var(--accent-blue)' : undefined,
                      color: on ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: on ? 600 : 500,
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto">
              {activeTab === 'overview' && <OverviewTab selected={selected} investigation={investigation} traces={traces} />}
              {activeTab === 'evidence' && <EvidenceTab incidentId={selected.id} graph={graph} refreshVersion={evidenceVersion} />}
              {activeTab === 'decision' && (
                <DecisionTab
                  plans={plans}
                  resourceSnapshot={decisionResources}
                  selected={selected}
                  onTransition={handleTransition}
                  allowedActions={allowedActions}
                  canOperate={canOperate}
                />
              )}
              {activeTab === 'package' && <TaskPackagePanel key={selected.id} incidentId={selected.id} />}
              {activeTab === 'whatif' && <WhatIfPanel key={selected.id} incidentId={selected.id} />}
              {activeTab === 'compliance' && <CompliancePanel key={selected.id} incidentId={selected.id} />}
              {activeTab === 'redteam' && <RedTeamPanel key={selected.id} incidentId={selected.id} />}
              {activeTab === 'deep' && (
                <DeepAnalysisPanel key={selected.id} incidentId={selected.id} turbineId={selected.turbine_id} />
              )}
              {activeTab === 'passport' && (
                <HealthPassportPanel
                  key={selected.turbine_id}
                  turbineId={selected.turbine_id}
                  turbineName={selected.turbine_name}
                />
              )}
              {activeTab === 'economic' && <EconomicImpactPanel incidentId={selected.id} data={economicData} refresh={ecoRefresh} />}
              {activeTab === 'audit' && (
                <div className="space-y-4">
                  <AuditChainPanel incidentId={selected.id} />
                  {/* 篡改检测演示：与审计链同属「可追溯」语义，放在同一 Tab 内讲完整个故事 */}
                  <TamperCheckPanel key={selected.id} incidentId={selected.id} />
                </div>
              )}
              {activeTab === 'traces' && <TracesTab traces={traces} />}
            </div>
          </>
        )}
      </div>
      </div>
      <CopilotFAB
        pageContext={{
          page_type: 'incident',
          incident_id: selected?.id,
          incident_ref: selected?.incident_id,
          turbine_id: selected?.turbine_id,
          turbine_name: selected?.turbine_name,
          incident_stage: selected?.stage,
          verification_status: selected?.verification_status,
          evidence_count: graph.nodes.length,
          decision_plan_count: plans.length,
          agent_trace_count: traces.length,
        }}
      />
    </>
  );
}

// ── Sub-components ──

function IncidentFlowBar({ stage, verificationStatus }: { stage: string; verificationStatus?: string | null }) {
  const currentIndex = INCIDENT_FLOW.findIndex((item) => item.key === stage);
  const nextStep = stage === 'verifying' && verificationStatus !== 'pass'
    ? '补充观察数据并重新验证'
    : currentIndex >= 0 && currentIndex < INCIDENT_FLOW.length - 1
    ? INCIDENT_FLOW[currentIndex + 1].label
    : stage === 'resolved'
      ? '已完成处置闭环'
      : '等待人工研判';

  return (
    <div className="mt-4 rounded-xl border border-border-default bg-bg-deep/45 px-3 py-3" aria-label="事件处置闭环">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12px] font-semibold text-text-primary">事件处置闭环</span>
        <span className="text-[11px] text-text-secondary">
          下一步：<strong className="text-accent-blue">{nextStep}</strong>
        </span>
      </div>
      <ol className="grid grid-cols-4 gap-2 xl:grid-cols-8">
        {INCIDENT_FLOW.map((item, index) => {
          const complete = currentIndex >= 0 && index < currentIndex;
          const active = index === currentIndex;
          return (
            <li
              key={item.key}
              className="relative rounded-lg border px-2 py-2 text-center text-[11px] font-medium"
              aria-current={active ? 'step' : undefined}
              style={{
                borderColor: active
                  ? 'rgba(59,130,246,0.55)'
                  : complete
                    ? 'rgba(16,185,129,0.35)'
                    : 'var(--border-subtle)',
                background: active
                  ? 'rgba(59,130,246,0.15)'
                  : complete
                    ? 'rgba(16,185,129,0.08)'
                    : 'rgba(15,23,42,0.28)',
                color: active
                  ? 'var(--accent-blue)'
                  : complete
                    ? 'var(--accent-green)'
                    : 'var(--text-muted)',
              }}
            >
              <span className="num mr-1">{complete ? '✓' : index + 1}</span>
              {item.label}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function CreateForm({ onCreated, onClose }: { onCreated: () => void; onClose: () => void }) {
  const [form, setForm] = useState({ turbine_id: 0, title: '', severity: 'high' });
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.get('/turbines/')
      .then(({ data }) => {
        const list: Turbine[] = data?.turbines || [];
        setTurbines(list);
        setForm(f => (f.turbine_id || !list.length ? f : { ...f, turbine_id: list[0].id }));
      })
      .catch(() => setTurbines([]));
  }, []);

  const handleSubmit = async () => {
    if (!form.title.trim()) { setFormError('请输入事件标题'); return; }
    if (!form.turbine_id) { setFormError('请选择风机'); return; }
    setSubmitting(true); setFormError(null);
    try {
      await createIncident({ ...form, title: form.title.trim() });
      toast.success('事件已创建', form.title.trim());
      onCreated(); onClose();
    } catch (e: any) {
      let message: string;
      if (e?.response?.status === 403) {
        message = '当前账号权限不足，需 operator 及以上';
      } else {
        const detail = e?.response?.data?.detail;
        message = typeof detail === 'string' ? detail : e?.message || '创建失败';
      }
      setFormError(message);
      toast.error('事件创建失败', message);
    } finally { setSubmitting(false); }
  };
  return (
    <div className="space-y-2 border-b p-3" style={{ borderColor: 'var(--border-default)', background: 'rgba(59,130,246,0.05)' }}>
      <label className="field-label block" htmlFor="incident-turbine">关联风机</label>
      <select id="incident-turbine" value={form.turbine_id} onChange={e => setForm({ ...form, turbine_id: Number(e.target.value) })}
        className="form-input w-full">
        <option value={0}>{turbines.length === 0 ? '正在加载风机列表…' : '请选择风机'}</option>
        {turbines.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <label className="field-label block" htmlFor="incident-title">事件标题</label>
      <input id="incident-title" placeholder="例如：3 号机组齿轮箱温升异常" value={form.title}
        onChange={e => setForm({ ...form, title: e.target.value })}
        className="form-input w-full" />
      <label className="field-label block" htmlFor="incident-severity">严重程度</label>
      <select id="incident-severity" value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
        className="form-input w-full">
        <option value="low">低</option><option value="medium">中</option>
        <option value="high">高</option><option value="critical">严重</option>
      </select>
      {formError && <p className="text-[10px]" style={{ color: 'var(--accent-red)' }} role="alert">{formError}</p>}
      <div className="flex gap-2 pt-1">
        <button onClick={handleSubmit} disabled={submitting} className="btn btn-primary btn-sm flex-1">
          {submitting && <span className="btn-spinner" aria-hidden="true" />}
          {submitting ? '创建中…' : '创建事件'}
        </button>
        <button onClick={onClose} className="btn btn-secondary btn-sm">取消</button>
      </div>
    </div>
  );
}

function OverviewTab({ selected, investigation, traces }: { selected: Incident; investigation: any; traces: AgentTrace[] }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="事件阶段" value={STAGE_LABELS[selected.stage] || selected.stage} />
        <StatCard label="严重程度" value={SEV_LABEL[selected.severity] || selected.severity} />
        <StatCard label="验证状态" value={VERIFICATION_LABELS[selected.verification_status || 'pending'] || selected.verification_status || '未开始'} />
      </div>
      {investigation && <InvestigationPanel data={investigation} />}
      {!investigation && traces.length === 0 && (
        <div className="surface-card">
          <StateBlock
            kind="empty"
            title="尚未启动自主调查"
            desc="点击页面顶部的「自主调查」，系统将自动完成 SCADA 分析、振动诊断、RUL 预测与根因假设，并沉淀为可审计的证据链。"
          />
        </div>
      )}
      {traces.length > 0 && (
        <p className="text-[11px] text-text-secondary">
          飞行记录：<span className="num text-text-primary">{traces.reduce((s, t) => s + (t.total_spans || 0), 0)}</span> 个 Span ·
          <span className="num text-text-primary"> {traces.length}</span> 条 Trace
        </p>
      )}
    </div>
  );
}

// P0-03 FIX: refreshVersion dependency triggers re-fetch on investigation/evidence changes
function EvidenceTab({ incidentId, graph, refreshVersion }: { incidentId: number; graph: EvidenceGraph; refreshVersion: number }) {
  const [completeness, setCompleteness] = useState<any>(null);
  const [completenessError, setCompletenessError] = useState<string | null>(null);
  useEffect(() => {
    setCompletenessError(null);
    getEvidenceCompleteness(incidentId)
      .then((d) => { setCompleteness(d); setCompletenessError(null); })
      .catch((e) => {
        setCompletenessError(e?.response?.data?.detail || e?.message || '证据完整度加载失败');
      });
  }, [incidentId, refreshVersion]);

  return (
    <div className="space-y-3">
      {completenessError && (
        <p className="rounded-lg border px-3 py-2 text-[11px]" role="alert"
          style={{ background: 'rgba(245,158,11,0.10)', borderColor: 'rgba(245,158,11,0.28)', color: 'var(--accent-yellow)' }}>
          {completenessError}
        </p>
      )}
      {completeness && (
        <div
          className="surface-card p-4"
          style={completeness.can_confirm_diagnosis
            ? { background: 'rgba(16,185,129,0.08)', borderColor: 'rgba(16,185,129,0.28)' }
            : { background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.28)' }}
        >
          <div className="flex items-center gap-2">
            <span className={`dot ${completeness.can_confirm_diagnosis ? 'dot-success' : 'dot-warning'}`} aria-hidden="true" />
            <span className="section-title">证据完整度 <span className="num">{(completeness.completeness_ratio * 100).toFixed(0)}%</span></span>
          </div>
          <p className="mt-1.5 text-[11px] text-text-secondary">
            <span className="num">{completeness.satisfied_count}/{completeness.required_count}</span> 类证据已满足
            {!completeness.can_confirm_diagnosis && (
              <span className="ml-2" style={{ color: 'var(--accent-yellow)' }}>{completeness.recommendation}</span>
            )}
          </p>
          {completeness.missing_evidence?.length > 0 && (
            <p className="mt-1 text-[10px]" style={{ color: 'var(--accent-red)' }}>
              缺失：{completeness.missing_evidence.join('、')}
            </p>
          )}
        </div>
      )}
      {graph.nodes.length === 0 ? (
        <div className="surface-card">
          <StateBlock kind="empty" title="暂无证据节点" desc="启动「自主调查」后，系统会自动生成证据节点并建立关联。" />
        </div>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
          {graph.nodes.map((n: any) => (
            <div key={n.id} className="surface-card-flat surface-card-hover p-3" title={n.label}>
              <p className="truncate text-[12px] font-medium text-text-primary">{n.label}</p>
              <p className="mt-1 text-[10px] text-text-muted">
                类型 {n.node_type} · 来源 {n.source} · 置信度 <span className="num">{((n.confidence || 0) * 100).toFixed(0)}%</span>
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionTab({ plans, resourceSnapshot, selected, onTransition, allowedActions, canOperate }: {
  plans: GeneratedDecisionPlan[];
  resourceSnapshot: DecisionResourceSnapshot | null;
  selected: Incident;
  onTransition: (t: string) => void;
  allowedActions: string[];
  canOperate: boolean;
}) {
  const partsStatus = resourceSnapshot?.parts_status || 'unknown';
  const partsStatusLabel = {
    ready: '资源信息已给出',
    transfer_needed: '资源需协调',
    shortage: '资源存在缺口',
    unknown: '执行资源待审核',
  }[partsStatus];
  const partsStatusClass = {
    ready: 'badge badge-success',
    transfer_needed: 'badge badge-warning',
    shortage: 'badge badge-danger',
    unknown: 'badge badge-neutral',
  }[partsStatus];

  return (
    <div className="space-y-3">
      {plans.length === 0 ? (
        <div className="surface-card">
              <StateBlock kind="empty" title="尚未生成决策方案" desc="点击页面顶部的「决策分析」，系统将结合诊断证据、维护窗口与安全约束生成候选维修方案；执行资源由人工审核确认。" />
        </div>
      ) : (
        <>
          {resourceSnapshot && (
            <div
              className="flex flex-wrap items-center gap-x-4 gap-y-2 border-y px-3 py-2.5 text-[11px]"
              style={{ borderColor: 'var(--border-default)', background: 'rgba(15, 23, 42, 0.28)' }}
              role="status"
            >
              <span className={partsStatusClass}>{partsStatusLabel}</span>
              <span className="text-text-secondary">
                故障类型：<strong className="text-text-primary">{resourceSnapshot.fault_type || '待识别'}</strong>
              </span>
              {resourceSnapshot.parts_earliest_ready_date && (
                <span className="text-text-secondary">
                  最早可执行：<strong className="num text-text-primary">{resourceSnapshot.parts_earliest_ready_date}</strong>
                </span>
              )}
              <span className="text-text-muted">
                {resourceSnapshot.parts_source_type === 'knowledge'
                  ? '所需备件来自故障知识库，可用性由工单审核确认'
                  : '执行资源状态待人工确认'}
              </span>
              {resourceSnapshot.parts_summary && (
                <p className="basis-full text-text-secondary">{resourceSnapshot.parts_summary}</p>
              )}
              {resourceSnapshot.weather_status === 'unavailable' && (
                <p className="basis-full text-accent-yellow">天气数据尚未接入，方案中的天气条件为待现场确认项。</p>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 gap-3">
            {plans.map((p) => (
              <div
                key={p.id || p.strategy}
                className="surface-card p-4"
                style={p.is_recommended
                  ? { borderColor: 'rgba(16,185,129,0.45)', background: 'rgba(16,185,129,0.07)' }
                  : !p.is_feasible
                    ? { borderColor: 'rgba(239,68,68,0.32)', background: 'rgba(239,68,68,0.05)' }
                    : undefined}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="section-title">{p.plan_name}</span>
                      {p.is_recommended && <span className="badge badge-success">推荐方案</span>}
                      {!p.is_feasible && <span className="badge badge-danger">不可行</span>}
                    </div>
                    <p className="mt-1 text-[10px] text-text-muted">{p.strategy}</p>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <div className="num text-[20px] font-bold leading-none text-text-primary">{p.total_score?.toFixed(0)}</div>
                    <div className="field-label mt-1">总分</div>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-5 gap-2">
                  {[
                    ['安全', p.safety_score?.toFixed(0)],
                    ['经济', p.economic_score?.toFixed(0)],
                    ['资源', p.resource_score?.toFixed(0)],
                    ['恢复', p.recovery_time_score?.toFixed(0)],
                    ['风险', `${p.safety_risk?.toFixed(0)}%`],
                  ].map(([k, v]) => (
                    <div key={k} className="surface-inset py-1.5 text-center">
                      <div className="field-label">{k}</div>
                      <div className="num mt-0.5 text-[13px] font-semibold text-text-primary">{v}</div>
                    </div>
                  ))}
                </div>
                {!p.is_feasible && p.infeasible_reasons?.length > 0 && (
                  <p className="mt-2 text-[10px]" style={{ color: 'var(--accent-red)' }}>不可行原因：{p.infeasible_reasons.join('；')}</p>
                )}
                {p.data_quality_warnings?.length > 0 && (
                  <p className="mt-2 text-[10px]" style={{ color: 'var(--accent-yellow)' }}>数据质量提示：{p.data_quality_warnings.join('；')}</p>
                )}
              </div>
            ))}
          </div>
          {/* P1-09 FIX: State-machine driven buttons instead of always-visible */}
          <div className="mt-3 flex gap-2">
            {allowedActions.includes('approve') && (
              <button
                onClick={() => onTransition('awaiting_approval')}
                disabled={!canOperate}
                title={canOperate ? '提交审批' : READ_ONLY_PERMISSION_TITLE}
                className="btn btn-primary"
              >
                提交审批
              </button>
            )}
            {allowedActions.includes('execute') && (
              <button
                onClick={() => onTransition('executing')}
                disabled={!canOperate}
                title={canOperate ? '开始执行' : READ_ONLY_PERMISSION_TITLE}
                className="btn btn-success"
              >
                开始执行
              </button>
            )}
            {!allowedActions.includes('approve') && !allowedActions.includes('execute') && plans.length > 0 && (
              <span className="self-center text-[11px] text-text-muted">
                当前阶段（{STAGE_LABELS[selected.stage] || selected.stage}）不支持此操作，请先在事件头部完成前置流转。
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function TracesTab({ traces }: { traces: AgentTrace[] }) {
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null);
  if (traces.length === 0) {
    return (
      <div className="surface-card">
        <StateBlock kind="empty" title="暂无飞行记录" desc="事件尚未触发 Agent 执行，或追溯数据仍在生成中。" />
      </div>
    );
  }

  const active = traces.find(t => t.trace_id === activeTraceId) || traces[traces.length - 1];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="field-label">航段：</span>
        {traces.map(t => (
          <button
            key={t.trace_id}
            onClick={() => setActiveTraceId(t.trace_id)}
            className={`btn btn-xs num ${t.trace_id === active.trace_id ? '' : 'btn-secondary'}`}
            title={t.trace_id}
          >
            {t.trace_id.slice(-12)} · {t.spans?.length || t.total_spans || 0} spans
          </button>
        ))}
      </div>

      <div className="surface-card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="num text-[12px] text-text-primary" title={active.trace_id}>{active.trace_id}</span>
          <span className={`badge ${active.status === 'completed' ? 'badge-success' : active.status === 'failed' ? 'badge-danger' : 'badge-warning'}`}>
            {active.status === 'completed' ? '已完成' : active.status === 'failed' ? '已失败' : '执行中'}
          </span>
          <span className="num text-[10px] text-text-muted">
            {active.spans?.length || active.total_spans || 0} spans · {(active.total_duration_ms / 1000).toFixed(1)}s
          </span>
          {active.error_code && <span className="badge badge-danger">错误 {active.error_code}</span>}
        </div>
        <TraceWaterfall trace={active} />
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-card p-3.5">
      <div className="field-label">{label}</div>
      <div className="mt-1 truncate text-[15px] font-semibold text-text-primary" title={value || '—'}>{value || '—'}</div>
    </div>
  );
}
