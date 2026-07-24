import { useCallback, useEffect, useState } from 'react';
import {
  fetchIncidents, createIncident, compressAlarms, fetchEvidenceGraph,
  addEvidenceNode, addEvidenceEdge, generateDecisionSandbox, checkPolicy,
  transitionIncident, startTrace, fetchTraces,
  startInvestigation, generatePlans, verifyRecovery, getEvidenceCompleteness,
  getEconomicImpact, getAuditChain, verifyAuditChain,
  getWhatIfAnalysis, getTaskPackage, getComplianceCheck,
} from '../../services/incidentService';
import type {
  AgentTrace, AlarmCluster, DecisionPlan,
  EvidenceGraph, Incident, PolicyCheckResponse,
} from '../../types';
import EconomicImpactPanel from './components/EconomicImpactPanel';
import InvestigationPanel from './components/InvestigationPanel';
import AuditChainPanel from './components/AuditChainPanel';

// ── Constants ──

const STAGE_LABELS: Record<string, string> = {
  detected: '已检测', correlated: '已关联', diagnosing: '诊断中',
  decision_ready: '决策就绪', awaiting_approval: '待审批', executing: '执行中',
  verifying: '验证中', resolved: '已解决', escalated: '已升级',
};

const SEV_COLOR: Record<string, string> = {
  low: 'bg-slate-500', medium: 'bg-yellow-500', high: 'bg-orange-500', critical: 'bg-red-600',
};
const SEV_BADGE: Record<string, string> = {
  low: 'bg-slate-600/30 text-slate-300 border-slate-500/30',
  medium: 'bg-yellow-600/20 text-yellow-300 border-yellow-500/30',
  high: 'bg-orange-600/20 text-orange-300 border-orange-500/30',
  critical: 'bg-red-600/20 text-red-300 border-red-500/50 animate-pulse',
};
const SEV_DOT: Record<string, string> = {
  low: 'bg-slate-400 shadow-slate-400/50',
  medium: 'bg-yellow-400 shadow-yellow-400/50',
  high: 'bg-orange-400 shadow-orange-400/50',
  critical: 'bg-red-500 shadow-red-500/70',
};

// ── Main page ──

export default function IncidentPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState('overview');

  // Detail states
  const [cluster, setCluster] = useState<AlarmCluster | null>(null);
  const [graph, setGraph] = useState<EvidenceGraph>({ nodes: [], edges: [] });
  const [plans, setPlans] = useState<DecisionPlan[]>([]);
  const [policy, setPolicy] = useState<PolicyCheckResponse | null>(null);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Phase 1-2 state
  const [investigation, setInvestigation] = useState<any>(null);
  const [economicData, setEconomicData] = useState<any>(null);
  const [auditChain, setAuditChain] = useState<any>(null);
  const [ecoRefresh, setEcoRefresh] = useState(0);

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

  // Economic impact live refresh
  useEffect(() => {
    if (!selected) return;
    const timer = setInterval(() => {
      getEconomicImpact(selected.id).then(setEconomicData).catch(() => {});
      setEcoRefresh(c => c + 1);
    }, 30000);
    getEconomicImpact(selected.id).then(setEconomicData).catch(() => {});
    return () => clearInterval(timer);
  }, [selected?.id]);

  const selectIncident = useCallback(async (inc: Incident) => {
    setSelected(inc);
    setActionMsg(null);
    setInvestigation(null);
    setAuditChain(null);
    setPlans([]);  // Don't pre-empty — only clear on explicit action
    try {
      const [g, t] = await Promise.all([
        fetchEvidenceGraph(inc.id).catch(() => ({ nodes: [], edges: [] })),
        fetchTraces(inc.id).catch(() => []),
      ]);
      setGraph(g); setTraces(t);
    } catch { /* ignore */ }
  }, []);

  const doAction = async (label: string, fn: () => Promise<any>) => {
    setActionLoading(true); setActionMsg(`${label}...`);
    try {
      const result = await fn();
      setActionMsg(`${label} ✓`);
      return result;
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || `${label} 失败`;
      setActionMsg(`✗ ${typeof msg === 'string' ? msg : JSON.stringify(msg)}`);
      throw e;
    } finally { setActionLoading(false); }
  };

  const handleStartInvestigation = () => {
    if (!selected) return;
    doAction('启动自主调查', () => startInvestigation(selected.id))
      .then(setInvestigation)
      .then(() => selectIncident(selected));
  };

  const handleGeneratePlans = () => {
    if (!selected) return;
    doAction('生成决策方案', () => generatePlans(selected.id))
      .then((result) => setPlans(result.plans || []));
  };

  const handleVerifyRecovery = () => {
    if (!selected) return;
    doAction('运行恢复验证', () => verifyRecovery(selected.id))
      .then(() => selectIncident(selected));
  };

  const handleTransition = async (target: string) => {
    if (!selected) return;
    try {
      await doAction(`状态转换→${STAGE_LABELS[target] || target}`, () =>
        transitionIncident(selected.id, target, ''));
      await selectIncident(selected);
    } catch { /* doAction already sets error */ }
  };

  // ── Render ──

  if (loading) return <div className="flex items-center justify-center h-64 text-slate-400">加载事件列表...</div>;
  if (error) return <div className="p-6 text-red-400 bg-red-950/30 rounded-lg border border-red-800">⚠ {error}<button onClick={load} className="ml-4 underline">重试</button></div>;

  return (
    <div className="h-full flex gap-4 p-4">
      {/* ── Left: Incident list ── */}
      <div className="w-80 flex-shrink-0 bg-slate-900/60 rounded-lg border border-slate-700/50 flex flex-col">
        <div className="p-3 border-b border-slate-700/50 flex justify-between items-center">
          <h2 className="font-semibold text-slate-200">事件列表</h2>
          <button onClick={() => setShowCreate(!showCreate)} className="text-xs px-2 py-1 bg-blue-600 hover:bg-blue-500 rounded text-white">
            + 新建
          </button>
        </div>
        {showCreate && <CreateForm onCreated={load} onClose={() => setShowCreate(false)} />}
        <div className="flex-1 overflow-y-auto">
          {incidents.length === 0 ? (
            <div className="p-6 text-center text-slate-500 text-sm">暂无事件</div>
          ) : (
            incidents.map(inc => (
              <button
                key={inc.id}
                onClick={() => selectIncident(inc)}
                className={`w-full text-left p-3 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                  selected?.id === inc.id ? 'bg-blue-950/40 border-l-2 border-l-blue-500' : ''
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full shadow-lg ${SEV_DOT[inc.severity] || 'bg-slate-500'}`} />
                  <span className="text-sm font-medium text-slate-200 truncate">{inc.title}</span>
                </div>
                <div className="flex justify-between mt-1 text-xs text-slate-500">
                  <span>{inc.incident_id}</span>
                  <span>{STAGE_LABELS[inc.stage] || inc.stage}</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* ── Right: Detail with tabs ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selected ? (
          <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-slate-900/40 to-slate-800/20 rounded-lg border border-slate-700/30">
            <div className="text-center space-y-2">
              <div className="text-5xl mb-3">📋</div>
              <div className="text-slate-400 text-lg font-medium">选择一个事件查看详情</div>
              <div className="text-slate-600 text-sm">左侧事件列表中点击任意事件开始</div>
            </div>
          </div>
        ) : (
          <>
            {/* Incident header */}
            <div className="bg-gradient-to-r from-slate-900/80 via-slate-900/60 to-slate-900/40 rounded-lg border border-slate-700/50 p-4 mb-4 backdrop-blur">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <span className={`px-2 py-0.5 text-xs rounded border ${SEV_BADGE[selected.severity]}`}>
                      {selected.severity === 'critical' ? '🔴 ' : selected.severity === 'high' ? '🟠 ' : selected.severity === 'medium' ? '🟡 ' : ''}{selected.severity}
                    </span>
                    <h2 className="text-lg font-bold text-white">{selected.title}</h2>
                    <span className="text-xs text-slate-500">{selected.incident_id}</span>
                  </div>
                  <div className="flex items-center gap-4 mt-2 text-sm text-slate-400">
                    <span>阶段: {STAGE_LABELS[selected.stage] || selected.stage}</span>
                    <span>状态: {selected.status}</span>
                    <span>验证: {selected.verification_status || '待验证'}</span>
                    {selected.trace_id && <span className="text-xs text-slate-600">Trace: {selected.trace_id}</span>}
                  </div>
                </div>
                {/* Quick actions */}
                <div className="flex gap-2">
                  <button onClick={handleStartInvestigation} disabled={actionLoading}
                    className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm rounded transition-colors">
                    🔍 自主调查
                  </button>
                  <button onClick={handleGeneratePlans} disabled={actionLoading}
                    className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded transition-colors">
                    📊 决策分析
                  </button>
                  <button onClick={handleVerifyRecovery} disabled={actionLoading}
                    className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm rounded transition-colors">
                    ✅ 恢复验证
                  </button>
                </div>
              </div>
              {actionMsg && (
                <div className={`mt-2 text-sm px-3 py-1.5 rounded ${
                  actionMsg.includes('✓') ? 'bg-emerald-950/40 text-emerald-300' :
                  actionMsg.includes('✗') ? 'bg-red-950/40 text-red-300' :
                  'bg-slate-800 text-slate-300'
                }`}>
                  {actionMsg}
                </div>
              )}
            </div>

            {/* Tab navigation */}
            <div className="flex gap-1 border-b border-slate-700/50 mb-4 overflow-x-auto">
              {[
                ['overview', '📊 总览'], ['evidence', '🔗 证据'], ['decision', '🎯 决策'],
                ['economic', '💰 经济'], ['audit', '🔐 审计'], ['traces', '📡 追溯'],
              ].map(([key, label]) => (
                <button key={key} onClick={() => setActiveTab(key)}
                  className={`px-4 py-2.5 text-sm rounded-t transition-all duration-200 whitespace-nowrap ${
                    activeTab === key
                      ? 'bg-slate-800 text-white border-t-2 border-t-blue-500 font-medium shadow-lg shadow-blue-500/10'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                  }`}>
                  {label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto">
              {activeTab === 'overview' && <OverviewTab selected={selected} investigation={investigation} traces={traces} />}
              {activeTab === 'evidence' && <EvidenceTab incidentId={selected.id} graph={graph} />}
              {activeTab === 'decision' && <DecisionTab plans={plans} selected={selected} onTransition={handleTransition} />}
              {activeTab === 'economic' && <EconomicImpactPanel incidentId={selected.id} data={economicData} refresh={ecoRefresh} />}
              {activeTab === 'audit' && <AuditChainPanel incidentId={selected.id} />}
              {activeTab === 'traces' && <TracesTab traces={traces} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ──

function CreateForm({ onCreated, onClose }: { onCreated: () => void; onClose: () => void }) {
  const [form, setForm] = useState({ turbine_id: 31, title: '', severity: 'high' });
  const [submitting, setSubmitting] = useState(false);
  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await createIncident(form);
      onCreated(); onClose();
    } finally { setSubmitting(false); }
  };
  return (
    <div className="p-3 border-b border-slate-700/50 bg-slate-800/30">
      <input placeholder="事件标题" value={form.title}
        onChange={e => setForm({ ...form, title: e.target.value })}
        className="w-full p-2 text-sm bg-slate-700 border border-slate-600 rounded text-white mb-2" />
      <select value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
        className="w-full p-2 text-sm bg-slate-700 border border-slate-600 rounded text-white mb-2">
        <option value="low">低</option><option value="medium">中</option>
        <option value="high">高</option><option value="critical">严重</option>
      </select>
      <div className="flex gap-2">
        <button onClick={handleSubmit} disabled={submitting}
          className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50">
          {submitting ? '创建中...' : '创建事件'}
        </button>
        <button onClick={onClose} className="px-3 py-1 bg-slate-600 text-white text-sm rounded hover:bg-slate-500">取消</button>
      </div>
    </div>
  );
}

function OverviewTab({ selected, investigation, traces }: { selected: Incident; investigation: any; traces: AgentTrace[] }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="事件阶段" value={STAGE_LABELS[selected.stage] || selected.stage} />
        <StatCard label="严重程度" value={selected.severity} />
        <StatCard label="验证状态" value={selected.verification_status || '未开始'} />
      </div>
      {investigation && <InvestigationPanel data={investigation} />}
      {!investigation && traces.length === 0 && (
        <div className="p-8 text-center text-slate-500 bg-slate-900/30 rounded-lg border border-slate-700/30">
          <div className="text-3xl mb-2">🔍</div>
          <div>点击"自主调查"启动自动化调查流程</div>
          <div className="text-xs mt-1 text-slate-600">系统将自动完成SCADA分析、振动诊断、RUL预测、根因假设</div>
        </div>
      )}
      {traces.length > 0 && (
        <div className="text-sm text-slate-400">
          飞行记录: {traces.reduce((s, t) => s + (t.total_spans || 0), 0)} 个Span,
          {traces.length} 条Trace
        </div>
      )}
    </div>
  );
}

function EvidenceTab({ incidentId, graph }: { incidentId: number; graph: EvidenceGraph }) {
  const [completeness, setCompleteness] = useState<any>(null);
  useEffect(() => {
    getEvidenceCompleteness(incidentId).then(setCompleteness).catch(() => {});
  }, [incidentId]);

  return (
    <div className="space-y-4">
      {completeness && (
        <div className={`p-4 rounded-lg border ${
          completeness.can_confirm_diagnosis
            ? 'bg-emerald-950/20 border-emerald-700/30'
            : 'bg-yellow-950/20 border-yellow-700/30'
        }`}>
          <div className="font-semibold text-white">
            证据完整度: {(completeness.completeness_ratio * 100).toFixed(0)}%
          </div>
          <div className="text-sm text-slate-400 mt-1">
            {completeness.satisfied_count}/{completeness.required_count} 类型满足
            {!completeness.can_confirm_diagnosis && (
              <span className="text-yellow-400 ml-2">⚠ {completeness.recommendation}</span>
            )}
          </div>
          {completeness.missing_evidence?.length > 0 && (
            <div className="text-xs text-red-400 mt-1">
              缺失: {completeness.missing_evidence.join(', ')}
            </div>
          )}
        </div>
      )}
      {graph.nodes.length === 0 ? (
        <div className="p-8 text-center text-slate-500">暂无证据节点。启动自主调查后自动生成。</div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {graph.nodes.map((n: any) => (
            <div key={n.id} className="p-3 bg-slate-800/50 rounded border border-slate-700/30 text-sm">
              <div className="text-slate-200 font-medium">{n.label}</div>
              <div className="text-xs text-slate-500 mt-1">
                类型: {n.node_type} | 来源: {n.source} | 置信度: {((n.confidence || 0) * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionTab({ plans, selected, onTransition }: { plans: DecisionPlan[]; selected: Incident; onTransition: (t: string) => void }) {
  return (
    <div className="space-y-4">
      {plans.length === 0 ? (
        <div className="p-8 text-center text-slate-500">点击"决策分析"生成维修方案。</div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3">
            {plans.map((p: any) => (
              <div key={p.id || p.strategy} className={`p-4 rounded-lg border ${
                p.is_recommended ? 'border-emerald-500/50 bg-emerald-950/20' :
                !p.is_feasible ? 'border-red-500/30 bg-red-950/10' :
                'border-slate-700/30 bg-slate-800/30'
              }`}>
                <div className="flex justify-between items-start">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-white">{p.plan_name}</span>
                      {p.is_recommended && <span className="text-xs px-1.5 py-0.5 bg-emerald-600 text-white rounded">推荐</span>}
                      {!p.is_feasible && <span className="text-xs px-1.5 py-0.5 bg-red-600 text-white rounded">不可行</span>}
                    </div>
                    <div className="text-xs text-slate-500 mt-1">{p.strategy}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-white">{p.total_score?.toFixed(0)}</div>
                    <div className="text-xs text-slate-500">总分</div>
                  </div>
                </div>
                <div className="grid grid-cols-5 gap-2 mt-3 text-xs">
                  <div className="text-center"><div className="text-slate-400">安全</div><div className="text-white">{p.safety_score?.toFixed(0)}</div></div>
                  <div className="text-center"><div className="text-slate-400">经济</div><div className="text-white">{p.economic_score?.toFixed(0)}</div></div>
                  <div className="text-center"><div className="text-slate-400">资源</div><div className="text-white">{p.resource_score?.toFixed(0)}</div></div>
                  <div className="text-center"><div className="text-slate-400">恢复</div><div className="text-white">{p.recovery_time_score?.toFixed(0)}</div></div>
                  <div className="text-center"><div className="text-slate-400">风险</div><div className="text-white">{p.safety_risk?.toFixed(0)}%</div></div>
                </div>
                {!p.is_feasible && p.infeasible_reasons?.length > 0 && (
                  <div className="mt-2 text-xs text-red-400">不可行原因: {p.infeasible_reasons.join('; ')}</div>
                )}
                {p.data_quality_warnings?.length > 0 && (
                  <div className="mt-2 text-xs text-yellow-400">⚠ {p.data_quality_warnings.join('; ')}</div>
                )}
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={() => onTransition('awaiting_approval')}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm transition-colors">
              → 提交审批
            </button>
            <button onClick={() => onTransition('executing')}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-sm transition-colors">
              → 开始执行
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function TracesTab({ traces }: { traces: AgentTrace[] }) {
  if (traces.length === 0) return <div className="p-8 text-center text-slate-500">暂无飞行记录</div>;
  return (
    <div className="space-y-4">
      {traces.map(t => (
        <div key={t.trace_id} className="p-4 bg-slate-800/50 rounded-lg border border-slate-700/30">
          <div className="flex justify-between text-sm">
            <span className="text-slate-200 font-mono">{t.trace_id}</span>
            <span className={`px-2 py-0.5 rounded text-xs ${
              t.status === 'completed' ? 'bg-emerald-600' : t.status === 'failed' ? 'bg-red-600' : 'bg-yellow-600'
            } text-white`}>{t.status}</span>
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {t.total_spans} spans | {(t.total_duration_ms / 1000).toFixed(1)}s
            {t.error_code && <span className="text-red-400 ml-2">错误: {t.error_code}</span>}
          </div>
          {t.spans?.map((s: any) => (
            <div key={s.span_id} className="mt-2 ml-4 text-xs text-slate-400 flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${
                s.status === 'completed' ? 'bg-emerald-500' : s.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500'
              }`} />
              <span className="text-slate-300">{s.span_name}</span>
              <span className="text-slate-600">{s.duration_ms?.toFixed(0)}ms</span>
              {s.policy_decision && <span className="text-purple-400">[{s.policy_decision}]</span>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 bg-slate-800/40 rounded-lg border border-slate-700/30">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-white mt-1">{value || '—'}</div>
    </div>
  );
}
