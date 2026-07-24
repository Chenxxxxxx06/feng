import { useCallback, useEffect, useState } from 'react';
import {
  fetchIncidents,
  createIncident,
  fetchIncident,
  compressAlarms,
  fetchEvidenceGraph,
  addEvidenceNode,
  addEvidenceEdge,
  generateDecisionSandbox,
  checkPolicy,
  transitionIncident,
  startTrace,
  fetchTraces,
} from '../../services/incidentService';
import type {
  AgentTrace,
  AlarmCluster,
  DecisionPlan,
  EvidenceGraph,
  Incident,
  PolicyCheckResponse,
} from '../../types';

// ── helpers ──

const STAGE_LABELS: Record<string, string> = {
  detected: '已检测',
  correlated: '已关联',
  diagnosing: '诊断中',
  decision_ready: '决策就绪',
  awaiting_approval: '待审批',
  executing: '执行中',
  verifying: '验证中',
  resolved: '已解决',
  escalated: '已升级',
};

const SEV_COLOR: Record<string, string> = {
  low: 'bg-slate-500',
  medium: 'bg-yellow-500',
  high: 'bg-orange-500',
  critical: 'bg-red-600',
};

const NODE_TYPE_COLORS: Record<string, string> = {
  observation: '#3B82F6',
  hypothesis: '#F59E0B',
  check: '#8B5CF6',
  action: '#10B981',
  result: '#06B6D4',
};

const EDGE_TYPE_COLORS: Record<string, string> = {
  supports: '#10B981',
  contradicts: '#EF4444',
  requires_check: '#F59E0B',
  caused_by: '#8B5CF6',
  resolved_by: '#3B82F6',
};

// ── Main page ──

export default function IncidentPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail states
  const [cluster, setCluster] = useState<AlarmCluster | null>(null);
  const [graph, setGraph] = useState<EvidenceGraph>({ nodes: [], edges: [] });
  const [plans, setPlans] = useState<DecisionPlan[]>([]);
  const [policy, setPolicy] = useState<PolicyCheckResponse | null>(null);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    turbine_id: 31,
    title: '',
    severity: 'high' as string,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchIncidents();
      setIncidents(list);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectIncident = useCallback(async (inc: Incident) => {
    setSelected(inc);
    setActionMsg(null);
    try {
      const [detail, g, t] = await Promise.all([
        fetchIncident(inc.id).catch(() => inc),
        fetchEvidenceGraph(inc.id).catch(() => ({ nodes: [], edges: [] })),
        fetchTraces(inc.id).catch(() => []),
      ]);
      setSelected(detail);
      setGraph(g);
      setTraces(t);
      setCluster(null);
      setPlans([]);
      setPolicy(null);
    } catch {
      // use stale data
    }
  }, []);

  const handleCreate = async () => {
    try {
      const inc = await createIncident(createForm);
      setIncidents((prev) => [inc, ...prev]);
      setShowCreate(false);
      setCreateForm({ turbine_id: 31, title: '', severity: 'high' });
      setSelected(inc);
    } catch (e: any) {
      setActionMsg('创建失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleCompress = async () => {
    if (!selected) return;
    try {
      const c = await compressAlarms(selected.id, selected.turbine_id);
      setCluster(c);
      setActionMsg(`告警压缩完成: ${c.total_alarms} → ${c.compressed_alarms}`);
      selectIncident(selected);
    } catch (e: any) {
      setActionMsg('压缩失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleAddEvidence = async () => {
    if (!selected) return;
    try {
      await addEvidenceNode(selected.id, {
        node_type: 'observation',
        label: `振动RMS异常 (${new Date().toLocaleTimeString()})`,
        source: 'scada',
        confidence: 0.9,
      });
      const g = await fetchEvidenceGraph(selected.id);
      setGraph(g);
      setActionMsg('证据节点已添加');
    } catch (e: any) {
      setActionMsg('添加失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleSandbox = async () => {
    if (!selected) return;
    try {
      const sb = await generateDecisionSandbox(selected.id);
      setPlans(sb.plans);
      setActionMsg(`沙盘生成: ${sb.plans.length} 个方案, 推荐 #${sb.recommended_index + 1}`);
      selectIncident(selected);
    } catch (e: any) {
      setActionMsg('沙盘失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handlePolicyCheck = async (action: string) => {
    if (!selected) return;
    try {
      const result = await checkPolicy({
        action,
        incident_id: selected.id,
        context: { verification_status: selected.verification_status || 'pending' },
      });
      setPolicy(result);
      setActionMsg(
        `策略检查: ${result.decision}${result.reason ? ` — ${result.reason}` : ''}`
      );
    } catch (e: any) {
      setActionMsg('策略检查失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleTransition = async (target: string) => {
    if (!selected) return;
    try {
      const updated = await transitionIncident(selected.id, target);
      setSelected(updated);
      setIncidents((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      setActionMsg(`阶段推进: → ${STAGE_LABELS[target] || target}`);
    } catch (e: any) {
      setActionMsg('推进失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleTrace = async () => {
    if (!selected) return;
    try {
      await startTrace(selected.id);
      const t = await fetchTraces(selected.id);
      setTraces(t);
      setActionMsg('飞行记录已保存');
    } catch (e: any) {
      setActionMsg('记录失败: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const NEXT_STAGES: Record<string, string[]> = {
    detected: ['correlated'],
    correlated: ['diagnosing'],
    diagnosing: ['decision_ready'],
    decision_ready: ['awaiting_approval', 'executing'],
    awaiting_approval: ['executing'],
    executing: ['verifying'],
    verifying: ['resolved', 'executing'],
    resolved: [],
    escalated: ['diagnosing', 'executing'],
  };

  return (
    <div className="h-full flex flex-col text-text-primary" style={{ background: '#071A35' }}>
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b" style={{ borderColor: 'rgba(59,130,246,0.10)' }}>
        <div>
          <h2 className="text-lg font-bold">事件指挥中心</h2>
          <p className="text-xs text-text-muted">Incident Command Center — 自主运维事件管理</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-all"
            style={{ background: 'linear-gradient(135deg, #3B82F6, #2563EB)' }}
          >
            + 新建事件
          </button>
          <button onClick={load} className="px-3 py-2 rounded-lg text-sm text-text-secondary hover:text-text-primary border" style={{ borderColor: 'rgba(255,255,255,0.1)' }}>
            刷新
          </button>
        </div>
      </header>

      {actionMsg && (
        <div className="mx-6 mt-3 px-4 py-2 rounded-lg text-sm" style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.2)' }}>
          {actionMsg}
          <button onClick={() => setActionMsg(null)} className="ml-3 text-text-muted hover:text-text-primary">×</button>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowCreate(false)}>
          <div className="rounded-xl p-6 w-[420px]" style={{ background: '#0F2347' }} onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold mb-4">新建设备事件</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-text-muted block mb-1">风机 ID</label>
                <input
                  type="number"
                  value={createForm.turbine_id}
                  onChange={(e) => setCreateForm({ ...createForm, turbine_id: +e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm border"
                  style={{ background: '#071A35', borderColor: 'rgba(255,255,255,0.1)' }}
                />
              </div>
              <div>
                <label className="text-xs text-text-muted block mb-1">事件标题</label>
                <input
                  type="text"
                  value={createForm.title}
                  onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                  placeholder="例如：齿轮箱振动异常"
                  className="w-full px-3 py-2 rounded-lg text-sm border"
                  style={{ background: '#071A35', borderColor: 'rgba(255,255,255,0.1)' }}
                />
              </div>
              <div>
                <label className="text-xs text-text-muted block mb-1">严重程度</label>
                <select
                  value={createForm.severity}
                  onChange={(e) => setCreateForm({ ...createForm, severity: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm border"
                  style={{ background: '#071A35', borderColor: 'rgba(255,255,255,0.1)' }}
                >
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                  <option value="critical">紧急</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-5">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 rounded-lg text-sm border" style={{ borderColor: 'rgba(255,255,255,0.1)' }}>取消</button>
              <button onClick={handleCreate} className="px-4 py-2 rounded-lg text-sm text-white" style={{ background: '#3B82F6' }}>创建</button>
            </div>
          </div>
        </div>
      )}

      {/* Main content: 3-column layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* ── Left: Incident list ── */}
        <div className="w-[320px] flex-shrink-0 border-r overflow-y-auto" style={{ borderColor: 'rgba(59,130,246,0.10)' }}>
          <div className="p-4">
            <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">事件列表</h3>
            {loading && <p className="text-xs text-text-muted animate-pulse">加载中...</p>}
            {error && <p className="text-xs text-red-400">{error}</p>}
            {!loading && incidents.length === 0 && (
              <p className="text-xs text-text-muted">暂无事件，点击"新建事件"创建第一个</p>
            )}
            <div className="space-y-2">
              {incidents.map((inc) => (
                <button
                  key={inc.id}
                  onClick={() => selectIncident(inc)}
                  className={`w-full text-left p-3 rounded-lg transition-all border ${
                    selected?.id === inc.id
                      ? 'border-accent-blue'
                      : 'border-transparent hover:border-border-default'
                  }`}
                  style={
                    selected?.id === inc.id
                      ? { background: 'rgba(59,130,246,0.12)' }
                      : { background: 'rgba(15,35,71,0.6)' }
                  }
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${SEV_COLOR[inc.severity] || 'bg-gray-500'}`} />
                    <span className="text-sm font-medium truncate">{inc.title || inc.incident_id}</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-text-muted">
                    <span>{inc.incident_id}</span>
                    <span>·</span>
                    <span>{STAGE_LABELS[inc.stage] || inc.stage}</span>
                    {inc.alarm_count > 0 && (
                      <>
                        <span>·</span>
                        <span className="text-accent-yellow">{inc.alarm_count} 告警</span>
                      </>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Center: Detail + Graph + Sandbox ── */}
        <div className="flex-1 overflow-y-auto p-5">
          {!selected && (
            <div className="flex items-center justify-center h-full text-text-muted text-sm">
              选择左侧事件查看详情，或创建新事件开始
            </div>
          )}

          {selected && (
            <div className="space-y-5">
              {/* Incident header */}
              <div className="rounded-xl p-5" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="text-xl font-bold">{selected.title || selected.incident_id}</h3>
                    <p className="text-xs text-text-muted mt-1">
                      {selected.incident_id} · 风机 {selected.turbine_name || selected.turbine_id} · {selected.opened_at?.slice(0, 19)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-1 rounded text-xs font-medium text-white ${SEV_COLOR[selected.severity] || 'bg-gray-500'}`}>
                      {selected.severity.toUpperCase()}
                    </span>
                    <span className="px-2 py-1 rounded text-xs font-medium border" style={{ background: 'rgba(59,130,246,0.15)', borderColor: 'rgba(59,130,246,0.25)', color: '#3B82F6' }}>
                      {STAGE_LABELS[selected.stage] || selected.stage}
                    </span>
                  </div>
                </div>

                {/* Stage transitions */}
                <div className="flex flex-wrap gap-2 mt-4">
                  <span className="text-[11px] text-text-muted self-center mr-2">推进至:</span>
                  {(NEXT_STAGES[selected.stage] || []).map((stage) => (
                    <button
                      key={stage}
                      onClick={() => handleTransition(stage)}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-all hover:opacity-80"
                      style={{ background: 'linear-gradient(135deg, #3B82F6, #2563EB)' }}
                    >
                      → {STAGE_LABELS[stage] || stage}
                    </button>
                  ))}
                  {selected.stage === 'resolved' && (
                    <span className="text-xs text-accent-green self-center">✓ 已解决</span>
                  )}
                </div>
              </div>

              {/* Action buttons grid */}
              <div className="grid grid-cols-5 gap-3">
                <ActionBtn label="📊 告警压缩" onClick={handleCompress} />
                <ActionBtn label="🔍 添加证据" onClick={handleAddEvidence} />
                <ActionBtn label="🎯 决策沙盘" onClick={handleSandbox} />
                <ActionBtn label="🛡️ 策略检查" onClick={() => handlePolicyCheck('close_incident')} />
                <ActionBtn label="📝 飞行记录" onClick={handleTrace} />
              </div>

              {/* Evidence graph */}
              {(graph.nodes.length > 0 || graph.edges.length > 0) && (
                <div className="rounded-xl p-5" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
                  <h4 className="text-sm font-semibold mb-4">🔬 因果证据图</h4>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {graph.nodes.map((node) => (
                      <span
                        key={node.id}
                        className="px-3 py-1.5 rounded-full text-xs font-medium text-white"
                        style={{ background: NODE_TYPE_COLORS[node.node_type] || '#6B7280' }}
                      >
                        {node.node_type}: {node.label.length > 30 ? node.label.slice(0, 30) + '…' : node.label}
                        <span className="ml-1 opacity-70">({(node.confidence * 100).toFixed(0)}%)</span>
                      </span>
                    ))}
                  </div>
                  {graph.edges.map((edge) => {
                    const src = graph.nodes.find((n) => n.id === edge.source_node_id);
                    const tgt = graph.nodes.find((n) => n.id === edge.target_node_id);
                    return (
                      <div key={edge.id} className="flex items-center gap-2 text-xs text-text-muted mb-1 pl-4">
                        <span style={{ color: NODE_TYPE_COLORS[src?.node_type || ''] || '#6B7280' }}>
                          {src?.label.slice(0, 25) || `#${edge.source_node_id}`}
                        </span>
                        <span style={{ color: EDGE_TYPE_COLORS[edge.edge_type] || '#6B7280' }}>
                          —{edge.edge_type}→
                        </span>
                        <span style={{ color: NODE_TYPE_COLORS[tgt?.node_type || ''] || '#6B7280' }}>
                          {tgt?.label.slice(0, 25) || `#${edge.target_node_id}`}
                        </span>
                        <span className="opacity-50">({(edge.confidence * 100).toFixed(0)}%)</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Decision sandbox */}
              {plans.length > 0 && (
                <div className="rounded-xl p-5" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
                  <h4 className="text-sm font-semibold mb-4">🎯 反事实决策沙盘</h4>
                  <div className="space-y-3">
                    {plans.map((plan, i) => (
                      <div
                        key={plan.id || i}
                        className={`rounded-lg p-4 border ${plan.is_recommended ? '' : 'opacity-75'}`}
                        style={
                          plan.is_recommended
                            ? { background: 'rgba(16,185,129,0.10)', borderColor: 'rgba(16,185,129,0.3)' }
                            : { background: 'rgba(15,35,71,0.6)', borderColor: 'rgba(255,255,255,0.06)' }
                        }
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-semibold">
                            {plan.is_recommended && '★ '}方案 {i + 1}: {plan.plan_name}
                          </span>
                          <span className="text-lg font-bold text-accent-blue">{plan.total_score} 分</span>
                        </div>
                        <div className="grid grid-cols-4 gap-3 text-xs text-text-muted">
                          <div>安全风险: <span className={plan.safety_risk > 30 ? 'text-red-400' : 'text-green-400'}>{plan.safety_risk}%</span></div>
                          <div>停机损失: ¥{plan.downtime_loss.toLocaleString()}</div>
                          <div>维修成本: ¥{plan.repair_cost.toLocaleString()}</div>
                          <div>恢复天数: {plan.recovery_days} 天</div>
                        </div>
                        {plan.decision_flip_point && (
                          <div className="mt-2 text-[11px] italic" style={{ color: '#F59E0B' }}>
                            🔄 翻转点: {plan.decision_flip_point}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Flight recorder */}
              {traces.length > 0 && (
                <div className="rounded-xl p-5" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
                  <h4 className="text-sm font-semibold mb-4">📝 Agent 飞行记录器</h4>
                  {traces.map((trace) => (
                    <div key={trace.id} className="mb-4">
                      <div className="flex items-center gap-3 mb-2 text-xs">
                        <span className="font-mono text-accent-blue">{trace.trace_id}</span>
                        <span className={`px-1.5 py-0.5 rounded ${trace.status === 'completed' ? 'bg-green-900/50 text-green-400' : 'bg-yellow-900/50 text-yellow-400'}`}>
                          {trace.status}
                        </span>
                        <span className="text-text-muted">{trace.total_duration_ms?.toFixed(0)}ms</span>
                        <span className="text-text-muted">{trace.total_spans} spans</span>
                      </div>
                      {trace.spans.length > 0 && (
                        <div className="pl-4 border-l-2 space-y-1" style={{ borderColor: 'rgba(59,130,246,0.2)' }}>
                          {trace.spans.map((span) => (
                            <div key={span.id} className="text-[11px] flex items-center gap-2 py-0.5">
                              <span className="text-text-muted w-16 text-right">{span.duration_ms?.toFixed(0)}ms</span>
                              <span className="text-text-secondary">{span.span_name}</span>
                              {span.policy_decision && (
                                <span className={`px-1 rounded text-[10px] ${span.policy_decision === 'denied' ? 'bg-red-900/50 text-red-400' : 'bg-green-900/50 text-green-400'}`}>
                                  {span.policy_decision}
                                </span>
                              )}
                              {span.error_code && (
                                <span className="text-red-400">⚠ {span.error_code}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right: Policy + Alarm cluster ── */}
        <div className="w-[300px] flex-shrink-0 border-l overflow-y-auto p-4" style={{ borderColor: 'rgba(59,130,246,0.10)' }}>
          {/* Policy check */}
          <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
            <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">🛡️ 安全策略</h4>
            {policy ? (
              <div>
                <div className={`px-3 py-2 rounded-lg text-sm font-medium mb-2 ${
                  policy.decision === 'denied' ? 'bg-red-900/30 text-red-400 border border-red-800' :
                  policy.decision === 'require_approval' ? 'bg-yellow-900/30 text-yellow-400 border border-yellow-800' :
                  'bg-green-900/30 text-green-400 border border-green-800'
                }`}>
                  {policy.decision === 'denied' ? '❌ 已拒绝' :
                   policy.decision === 'require_approval' ? '⚠️ 需要审批' :
                   '✅ 已允许'}
                </div>
                {policy.reason && <p className="text-xs text-text-muted mb-2">{policy.reason}</p>}
                {policy.matched_rules.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[10px] text-text-muted uppercase">命中规则:</p>
                    {policy.matched_rules.map((r) => (
                      <code key={r} className="block text-[10px] px-2 py-1 rounded" style={{ background: 'rgba(255,255,255,0.05)' }}>{r}</code>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-text-muted">选择事件后点击"策略检查"进行验证</p>
            )}
          </div>

          {/* Alarm cluster */}
          {cluster && (
            <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.12)' }}>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">📊 告警簇</h4>
              <div className="grid grid-cols-2 gap-2 mb-3 text-xs">
                <div className="p-2 rounded" style={{ background: 'rgba(255,255,255,0.03)' }}>
                  <span className="text-text-muted">总数</span>
                  <p className="text-lg font-bold">{cluster.total_alarms}</p>
                </div>
                <div className="p-2 rounded" style={{ background: 'rgba(255,255,255,0.03)' }}>
                  <span className="text-text-muted">压缩后</span>
                  <p className="text-lg font-bold text-accent-green">{cluster.compressed_alarms}</p>
                </div>
              </div>
              {cluster.compression_rules.length > 0 && (
                <div className="space-y-1 mb-3">
                  {cluster.compression_rules.map((rule, i) => (
                    <code key={i} className="block text-[10px] px-2 py-1 rounded" style={{ background: 'rgba(255,255,255,0.05)' }}>{rule}</code>
                  ))}
                </div>
              )}
              {cluster.primary_alarm && (
                <div className="text-xs p-2 rounded" style={{ background: 'rgba(234,179,8,0.10)', border: '1px solid rgba(234,179,8,0.2)' }}>
                  <span className="text-accent-yellow font-medium">主告警:</span>{' '}
                  {cluster.primary_alarm.alarm_type} ({cluster.primary_alarm.severity})
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ActionBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="p-3 rounded-xl text-xs font-medium text-center transition-all hover:opacity-80"
      style={{ background: 'rgba(15,35,71,0.8)', border: '1px solid rgba(59,130,246,0.15)' }}
    >
      {label}
    </button>
  );
}
