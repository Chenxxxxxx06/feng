import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import * as echarts from 'echarts';
import kbData from '../../data/fault-kb.json';
import api from '../../services/api';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

// ─── Types ───
interface FaultNode {
  id: string; fault_type: string; category: string; icon: string; severity: string;
  symptoms: { indicator: string; threshold: string; unit: string }[];
  root_causes: string[];
  solutions: { action: string; difficulty: string; downtime_hours: number }[];
  related_faults: { id: string; name: string; probability: number }[];
  spare_parts: { name: string; quantity: number; est_cost: number }[];
  cases: { turbine: string; date: string; summary: string; resolution: string; total_cost: number; downtime_days: number }[];
}

interface GraphNode {
  id: string; name: string; category: string; symbol: string; symbolSize: number;
  // Turbine
  status?: string; status_icon?: string; region?: string; fault_count?: number;
  // Fault record
  fault_type?: string; active?: boolean; detected_at?: string; status_cn?: string; confidence?: number;
  // Work order
  assignee?: string;
  // Knowledge
  severity?: string; severity_cn?: string;
  difficulty?: string; downtime_hours?: number;
  threshold?: string; unit?: string;
  quantity?: number; est_cost?: number;
  resolution?: string; total_cost?: number; downtime_days?: number;
}

interface GraphData {
  stats?: { active_faults: number; warning_turbines: number; pending_workorders: number; personnel_count: number; total_turbines: number; total_knowledge_nodes: number };
  nodes: GraphNode[]; edges: { source: string; target: string; label: string }[];
  fault_type?: string;
}

// ─── Constants ───
const SEVERITY: Record<string, string> = { low: '低', medium: '中', high: '高', critical: '紧急' };
const SEVERITY_COLOR: Record<string, string> = { low: 'bg-accent-green/20 text-accent-green', medium: 'bg-accent-yellow/20 text-accent-yellow', high: 'bg-accent-red/20 text-accent-red', critical: 'bg-red-600/30 text-red-400' };
const DIFFICULTY: Record<string, string> = { easy: '简单', medium: '中等', hard: '困难' };

const CAT_COLORS: Record<string, string> = {
  fault: '#3B82F6', symptom: '#F97316', root_cause: '#EF4444', solution: '#10B981',
  spare_part: '#8B5CF6', turbine: '#3B82F6', fault_record: '#F97316', workorder: '#F59E0B',
  personnel: '#94A3B8', case_record: '#94A3B8',
};

const STATUS_COLOR: Record<string, string> = {
  normal: '#10B981', warning: '#F97316', fault: '#EF4444', maintenance: '#3B82F6',
  open: '#EF4444', diagnosing: '#F97316', confirmed: '#F97316', resolved: '#10B981',
  pending: '#F97316', in_progress: '#3B82F6', completed: '#10B981', cancelled: '#94A3B8',
  low: '#10B981', medium: '#F97316', high: '#EF4444', critical: '#EF4444',
};

const CATEGORIES = ['全部', ...Array.from(new Set((kbData.nodes as FaultNode[]).map(n => n.category)))];

// ─── Component ───
export default function KnowledgeBasePage() {
  // Encyclopedia state
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('全部');
  const [severityFilter, setSeverityFilter] = useState('');
  const [detail, setDetail] = useState<FaultNode | null>(null);
  const [copilotMsg, setCopilotMsg] = useState('');

  // Graph state
  const [graphView, setGraphView] = useState<'topology' | 'knowledge'>('topology');
  const [selectedFaultType, setSelectedFaultType] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState(false);
  const [graphNode, setGraphNode] = useState<GraphNode | null>(null);

  // Topology filters
  const [filterRegion, setFilterRegion] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [availableRegions, setAvailableRegions] = useState<string[]>([]);

  const chartRef = useRef<HTMLDivElement>(null);
  const chartInst = useRef<echarts.ECharts | null>(null);
  const nodes = kbData.nodes as FaultNode[];

  // ─── Encyclopedia filter ───
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return nodes.filter(n => {
      if (category !== '全部' && n.category !== category) return false;
      if (severityFilter && n.severity !== severityFilter) return false;
      if (q) {
        return n.fault_type.toLowerCase().includes(q)
          || n.symptoms.some(s => s.indicator.toLowerCase().includes(q))
          || n.root_causes.some(r => r.toLowerCase().includes(q))
          || n.solutions.some(s => s.action.toLowerCase().includes(q));
      }
      return true;
    });
  }, [search, category, severityFilter]);

  const stats = useMemo(() => ({
    total: nodes.length,
    categories: new Set(nodes.map(n => n.category)).size,
    high: nodes.filter(n => n.severity === 'high' || n.severity === 'critical').length,
  }), []);

  // ─── Fetch graph ───
  const fetchGraph = useCallback(async () => {
    setGraphLoading(true);
    setGraphError(false);
    try {
      const params: Record<string, string | boolean> = { view: graphView };
      if (graphView === 'knowledge') {
        if (selectedFaultType) params.fault_type = selectedFaultType;
      } else {
        if (filterRegion) params.region = filterRegion;
        if (activeOnly) params.active_only = true;
      }
      const { data } = await api.get('/knowledge-graph', { params });
      setGraphData(data);
      if (data.stats?.regions) setAvailableRegions(data.stats.regions);
    } catch {
      setGraphError(true);
    } finally {
      setGraphLoading(false);
    }
  }, [graphView, selectedFaultType, filterRegion, activeOnly]);

  useEffect(() => {
    fetchGraph();
    const h = () => fetchGraph();
    window.addEventListener('focus', h);
    return () => window.removeEventListener('focus', h);
  }, [fetchGraph]);

  // ─── ECharts option ───
  const buildOption = useCallback((data: GraphData) => {
    const isTopo = graphView === 'topology';
    const cats = [...new Set(data.nodes.map(n => n.category))];

    const nodeData = data.nodes.map(n => {
      let color = CAT_COLORS[n.category] || '#94A3B8';
      let borderColor = 'transparent';
      let borderW = 0;
      let shadow = 0;

      if (isTopo) {
        // Turbine: color by operating status
        if (n.category === 'turbine') {
          color = STATUS_COLOR[n.status || 'normal'] || color;
          borderColor = color;
          borderW = 2;
        }
        // Fault record: red if active, grey if resolved
        if (n.category === 'fault_record') {
          color = n.active ? '#EF4444' : '#484f58';
          if (n.active) { borderColor = '#ff6b6b'; borderW = 1; }
        }
        // Work order: color by WO status
        if (n.category === 'workorder') {
          color = STATUS_COLOR[n.status || 'pending'] || color;
        }
      } else {
        // Knowledge: fault center node colored by severity
        if (n.category === 'fault') {
          color = STATUS_COLOR[n.severity || 'medium'] || color;
          borderColor = color;
          borderW = 3;
          shadow = 12;
        }
      }
      return {
        ...n,
        itemStyle: { color, borderColor, borderWidth: borderW, shadowBlur: shadow, shadowColor: color },
        symbolSize: n.symbolSize,
      };
    });

    const legendCats = isTopo
      ? ['turbine', 'fault_record', 'workorder', 'personnel'].filter(c => cats.includes(c))
      : ['fault', 'symptom', 'root_cause', 'solution', 'spare_part', 'case_record'].filter(c => cats.includes(c));

    return {
      tooltip: {
        formatter: (p: any) => {
          if (p.dataType === 'edge') return p.data.label || '';
          const n = p.data as GraphNode;
          const lines: string[] = [];
          lines.push(`<b>${n.name}</b>`);
          lines.push(`类型: ${n.category}`);
          if (n.status_cn || n.status) lines.push(`状态: ${n.status_cn || n.status} ${n.status_icon || ''}`);
          if (n.region) lines.push(`区域: ${n.region}`);
          if (n.fault_count !== undefined && n.fault_count > 0) lines.push(`活跃故障: ${n.fault_count}个`);
          if (n.detected_at) lines.push(`发现时间: ${n.detected_at}`);
          if (n.assignee) lines.push(`负责人: ${n.assignee}`);
          if (n.severity_cn || n.severity) lines.push(`严重度: ${n.severity_cn || SEVERITY[n.severity || ''] || n.severity}`);
          if (n.difficulty) lines.push(`难度: ${DIFFICULTY[n.difficulty] || n.difficulty}`);
          if (n.downtime_hours && n.downtime_hours > 0) lines.push(`停机: ${n.downtime_hours}h`);
          if (n.est_cost && n.est_cost > 0) lines.push(`成本: ¥${n.est_cost.toLocaleString()}`);
          if (n.confidence !== undefined) lines.push(`置信度: ${Math.round(n.confidence * 100)}%`);
          return lines.join('<br/>');
        },
      },
      legend: [{
        data: legendCats.map(c => ({ name: c, icon: 'circle' })),
        bottom: 0, textStyle: { color: '#94A3B8', fontSize: 10 },
      }],
      series: [{
        type: 'graph', layout: 'force', roam: true, draggable: true,
        force: {
          repulsion: isTopo ? 350 : 200,
          edgeLength: isTopo ? [120, 400] : [60, 180],
          gravity: isTopo ? 0.06 : 0.12,
        },
        data: nodeData,
        links: data.edges.map(e => ({
          source: e.source, target: e.target,
          label: { show: true, formatter: e.label, fontSize: 9, color: '#94A3B8' },
        })),
        categories: cats.map(c => ({ name: c, itemStyle: { color: CAT_COLORS[c] || '#94A3B8' } })),
        lineStyle: { color: '#30363d', curveness: isTopo ? 0.05 : 0.25, opacity: 0.5 },
        label: { show: true, fontSize: isTopo ? 11 : 10, color: '#c9d1d9' },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3, color: '#3B82F6' } },
      }],
    };
  }, [graphView]);

  // ─── ECharts lifecycle ───
  useEffect(() => {
    if (!chartRef.current || !graphData?.nodes?.length) return;
    if (!chartInst.current) chartInst.current = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInst.current.setOption(buildOption(graphData), true);
    const handler = (p: any) => {
      if (p.dataType === 'node') {
        const n = p.data as GraphNode;
        setGraphNode(n);
        // Topology: clicking fault_record offers "查看知识"
        if (graphView === 'topology' && n.category === 'fault_record' && n.fault_type) {
          // Don't auto-switch — user clicks button in panel
        }
      }
    };
    chartInst.current.on('click', handler);
    const obs = new ResizeObserver(() => chartInst.current?.resize());
    obs.observe(chartRef.current);
    return () => {
      obs.disconnect();
      chartInst.current?.off('click', handler);
      chartInst.current?.dispose();
      chartInst.current = null;
    };
  }, [graphData, buildOption, graphView]);

  // ─── Actions ───
  const handleAskAI = (node: FaultNode) => {
    setCopilotMsg(`请分析故障: ${node.fault_type}。症状: ${node.symptoms.map(s => s.indicator).join('、')}。严重度: ${SEVERITY[node.severity]}。请给出诊断建议。`);
  };

  const switchToKnowledge = (faultType: string) => {
    setSelectedFaultType(faultType);
    setGraphView('knowledge');
    setGraphNode(null);
  };

  const backToTopology = () => {
    setSelectedFaultType(null);
    setGraphView('topology');
    setGraphNode(null);
  };

  const gStats = graphData?.stats;

  // ─── Render ───
  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* ══════ Header: Encyclopedia ══════ */}
        <div className="border-b border-border-subtle p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold">📚 故障百科</h1>
              <p className="text-xs text-text-muted">共 {stats.total} 种 · {stats.categories} 类 · {stats.high} 高危</p>
            </div>
            <span className="text-xs text-accent-green flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
              实时数据
            </span>
          </div>
          <div className="flex gap-2 mb-3">
            <input className="flex-1 bg-bg-card border border-border-subtle rounded-lg px-3 py-1.5 text-sm placeholder-text-muted focus:outline-none focus:border-accent-blue" placeholder="搜索故障名称、症状、根因..." value={search} onChange={e => setSearch(e.target.value)} />
            <select className="bg-bg-card border border-border-subtle rounded-lg px-3 py-1.5 text-sm" value={category} onChange={e => setCategory(e.target.value)}>
              {CATEGORIES.map(c => <option key={c} value={c}>{c === '全部' ? '全部分类' : c}</option>)}
            </select>
            <select className="bg-bg-card border border-border-subtle rounded-lg px-3 py-1.5 text-sm" value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}>
              <option value="">全部严重度</option>
              <option value="critical">紧急</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option>
            </select>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'thin' }}>
            {filtered.map(node => (
              <button
                key={node.id}
                className="flex-shrink-0 w-[180px] bg-bg-card border border-border-subtle rounded-xl p-3 text-left hover:border-accent-blue/50 hover:shadow-lg transition-all group cursor-pointer"
                onClick={() => setDetail(node)}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xl">{node.icon}</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${SEVERITY_COLOR[node.severity]}`}>{SEVERITY[node.severity]}</span>
                </div>
                <div className="flex items-center gap-1.5 mb-0.5">
                  <h3 className="font-semibold text-xs group-hover:text-accent-blue">{node.fault_type}</h3>
                </div>
                <p className="text-[10px] text-text-muted">{node.category} · {node.solutions.length}方案 · {node.cases.length}案例</p>
              </button>
            ))}
          </div>
        </div>

        {/* ══════ Stats bar ══════ */}
        {gStats && graphView === 'topology' && (
          <div className="flex items-center gap-4 px-4 py-2 border-b border-border-subtle bg-bg-deep/50">
            <StatBadge icon="🔴" label="活跃故障" value={gStats.active_faults} color="text-accent-red" />
            <StatBadge icon="🟡" label="预警风机" value={gStats.warning_turbines} color="text-accent-yellow" />
            <StatBadge icon="📝" label="待处理工单" value={gStats.pending_workorders} color="text-accent-blue" />
            <StatBadge icon="👤" label="在岗人员" value={gStats.personnel_count} color="text-accent-green" />
            <span className="text-[10px] text-text-muted ml-auto">风机 {gStats.total_turbines} 台 · 知识节点 {gStats.total_knowledge_nodes} 个</span>
          </div>
        )}

        {/* ══════ Filter + View toggle ══════ */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-border-subtle">
          {graphView === 'topology' ? (
            <>
              {availableRegions.length > 0 && (
                <select className="bg-bg-card border border-border-subtle rounded px-2.5 py-1 text-xs" value={filterRegion} onChange={e => setFilterRegion(e.target.value)}>
                  <option value="">📍 全部区域</option>
                  {availableRegions.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              )}
            </>
          ) : (
            <div className="flex items-center gap-2">
              <button onClick={backToTopology} className="text-xs px-3 py-1 rounded bg-bg-card border border-border-subtle hover:border-accent-blue text-text-secondary hover:text-text-primary transition-colors">
                ← 返回运维拓扑
              </button>
              {selectedFaultType && (
                <span className="text-xs text-accent-blue font-medium">{selectedFaultType}</span>
              )}
            </div>
          )}
          <div className="ml-auto flex rounded-lg border border-border-subtle overflow-hidden text-xs">
            <button onClick={backToTopology}
              className={`px-3 py-1.5 transition-colors ${graphView === 'topology' ? 'bg-accent-blue/20 text-accent-blue font-medium' : 'bg-bg-card text-text-muted hover:text-text-primary'}`}>
              🗺️ 运维拓扑
            </button>
            <button onClick={() => { if (!selectedFaultType) { const first = nodes[0]; if (first) switchToKnowledge(first.fault_type); } }}
              className={`px-3 py-1.5 transition-colors ${graphView === 'knowledge' ? 'bg-accent-blue/20 text-accent-blue font-medium' : 'bg-bg-card text-text-muted hover:text-text-primary'}`}>
              🧠 知识网络
            </button>
          </div>
        </div>

        {/* ══════ Graph ══════ */}
        <div className="flex-1 flex">
          {graphLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-text-muted">
                  {graphView === 'topology' ? '加载运维拓扑...' : '加载知识网络...'}
                </span>
              </div>
            </div>
          ) : graphError ? (
            <div className="flex-1 flex flex-col items-center justify-center text-text-muted gap-2">
              <span className="text-3xl">⚠️</span>
              <p className="text-sm">加载失败</p>
              <button onClick={fetchGraph} className="text-xs text-accent-blue hover:underline mt-1">重试</button>
            </div>
          ) : graphData && graphData.nodes.length > 0 ? (
            <>
              <div ref={chartRef} className="flex-1" />
              {graphNode && <NodeInfoPanel node={graphNode} view={graphView} onViewKnowledge={switchToKnowledge} onClose={() => setGraphNode(null)} />}
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-text-muted gap-2">
              <span className="text-3xl">🗂️</span>
              <p className="text-sm">
                {graphView === 'topology' ? '运维拓扑暂无数据' : '知识网络暂无数据'}
              </p>
              <p className="text-xs">
                {graphView === 'topology'
                  ? '导入风机、故障记录、工单数据后生成运维拓扑'
                  : '请从百科卡片或运维拓扑中选择一个故障类型查看知识网络'}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ══════ Detail drawer (百科卡片详情) ══════ */}
      {detail && (
        <div className="w-[420px] flex-shrink-0 border-l border-border-subtle bg-bg-card overflow-auto">
          <div className="sticky top-0 bg-bg-card/95 backdrop-blur-sm border-b border-border-subtle p-5 flex items-center justify-between z-10">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{detail.icon}</span>
              <div>
                <h2 className="font-bold text-base">{detail.fault_type}</h2>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${SEVERITY_COLOR[detail.severity]}`}>{SEVERITY[detail.severity]} · {detail.category}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => switchToKnowledge(detail.fault_type)} className="text-[10px] px-2 py-1 rounded bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20">🧠 知识网络</button>
              <button onClick={() => setDetail(null)} className="text-text-muted hover:text-text-primary text-xl leading-none">&times;</button>
            </div>
          </div>
          <div className="p-5 space-y-6">
            {(detail as any).source === 'ai_extracted' && !(detail as any).verified && (
              <div className="bg-accent-yellow/10 border border-accent-yellow/30 rounded-lg p-3 flex items-center justify-between">
                <span className="text-xs text-accent-yellow">🤖 AI提取 · 置信度{Math.round(((detail as any).confidence || 0) * 100)}% · 待验证</span>
                <div className="flex gap-2">
                  <button onClick={async () => { await api.patch(`/knowledge-base/${(detail as any).id}/verify`); setDetail({...detail, verified: true, confidence: 1.0} as any); }} className="text-[10px] px-2 py-1 bg-accent-green/20 text-accent-green rounded">确认</button>
                  <button onClick={async () => { await api.delete(`/knowledge-base/${(detail as any).id}`); setDetail(null); }} className="text-[10px] px-2 py-1 bg-accent-red/20 text-accent-red rounded">删除</button>
                </div>
              </div>
            )}
            <section>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">🔍 症状指标</h3>
              <div className="space-y-1.5">
                {detail.symptoms.map((s, i) => (
                  <div key={i} className="flex justify-between text-sm bg-bg-deep rounded-lg px-3 py-2">
                    <span>{s.indicator}</span>
                    <span className="text-accent-red font-mono text-xs">{s.threshold}{s.unit ? ` ${s.unit}` : ''}</span>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">🎯 根因分析</h3>
              <ol className="space-y-1.5">
                {detail.root_causes.map((r, i) => <li key={i} className="flex gap-2 text-sm bg-bg-deep rounded-lg px-3 py-2"><span className="text-text-muted font-mono text-xs">{i + 1}.</span><span>{r}</span></li>)}
              </ol>
            </section>
            <section>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">🔧 解决方案</h3>
              <div className="space-y-2">
                {detail.solutions.map((s, i) => (
                  <div key={i} className="bg-bg-deep rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1"><span className="text-sm font-medium">{s.action}</span><span className="text-[10px] text-text-muted">{DIFFICULTY[s.difficulty]}</span></div>
                    <span className="text-[10px] text-text-muted">⏱ 预计停机 {s.downtime_hours}h</span>
                  </div>
                ))}
              </div>
            </section>
            {detail.related_faults.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">⚠️ 关联故障</h3>
                <div className="space-y-1.5">
                  {detail.related_faults.map((rf, i) => (
                    <div key={i} className="flex justify-between text-sm bg-bg-deep rounded-lg px-3 py-2">
                      <button className="text-accent-blue hover:underline text-left" onClick={() => { const n = nodes.find(x => x.id === rf.id); if (n) setDetail(n); }}>{rf.name}</button>
                      <span className="text-text-muted text-xs">{Math.round(rf.probability * 100)}% 伴生</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {detail.cases.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">📖 历史案例</h3>
                {detail.cases.map((c, i) => (
                  <div key={i} className="bg-bg-deep rounded-lg p-3 mb-2">
                    <div className="flex items-center justify-between mb-1"><span className="text-sm font-medium">{c.turbine}</span><span className="text-[10px] text-text-muted">{c.date}</span></div>
                    <p className="text-xs text-text-secondary mb-2">{c.summary}</p>
                    <div className="flex gap-3 text-[10px] text-text-muted"><span>🔧 {c.resolution}</span><span>💴 ¥{(c.total_cost / 10000).toFixed(1)}万</span><span>⏱ {c.downtime_days}天</span></div>
                  </div>
                ))}
              </section>
            )}
            {detail.spare_parts.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">📦 关联备件</h3>
                <div className="space-y-1.5">
                  {detail.spare_parts.map((sp, i) => (
                    <div key={i} className="flex justify-between text-sm bg-bg-deep rounded-lg px-3 py-2"><span>{sp.name}</span><span className="text-text-muted text-xs">x{sp.quantity} · ¥{sp.est_cost.toLocaleString()}</span></div>
                  ))}
                </div>
              </section>
            )}
            <button onClick={() => handleAskAI(detail)} className="w-full py-3 rounded-xl text-sm font-medium transition-all" style={{ background: 'linear-gradient(135deg, rgba(59,130,246,0.20), rgba(148,163,184,0.10))' }}>🤖 AI 诊断此故障</button>
          </div>
        </div>
      )}
      <CopilotFAB initialMessage={copilotMsg} />
    </div>
  );
}

// ─── Node Info Panel (right side of graph) ───
function NodeInfoPanel({ node, view, onViewKnowledge, onClose }: { node: GraphNode; view: string; onViewKnowledge: (ft: string) => void; onClose: () => void }) {
  const color = CAT_COLORS[node.category] || '#94A3B8';
  return (
    <div className="w-56 flex-shrink-0 border-l border-border-subtle bg-bg-card/95 p-4 text-xs overflow-auto">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: color }} />
        <span className="text-text-muted uppercase text-[10px] font-medium">
          {node.category === 'turbine' ? '风机' :
           node.category === 'fault_record' ? '故障事件' :
           node.category === 'workorder' ? '工单' :
           node.category === 'personnel' ? '人员' :
           node.category === 'fault' ? '故障知识' :
           node.category === 'symptom' ? '症状' :
           node.category === 'root_cause' ? '根因' :
           node.category === 'solution' ? '方案' :
           node.category === 'spare_part' ? '备件' :
           node.category === 'case_record' ? '案例' : node.category}
        </span>
        {node.active && <span className="w-1.5 h-1.5 rounded-full bg-accent-red animate-pulse flex-shrink-0" />}
      </div>

      <p className="font-semibold text-sm mb-3 leading-tight">{node.name}</p>

      <div className="space-y-1.5 text-text-secondary">
        {node.status_icon && <div><span className="text-text-muted">状态:</span> {node.status_icon} {node.status_cn || node.status}</div>}
        {!node.status_icon && node.status_cn && <div><span className="text-text-muted">状态:</span> {node.status_cn}</div>}
        {!node.status_icon && !node.status_cn && node.status && <div><span className="text-text-muted">状态:</span> {node.status}</div>}
        {node.region && <div><span className="text-text-muted">区域:</span> {node.region}</div>}
        {node.fault_count !== undefined && node.fault_count > 0 && <div><span className="text-text-muted">活跃故障:</span> <span className="text-accent-red">{node.fault_count}个</span></div>}
        {node.detected_at && <div><span className="text-text-muted">发现:</span> {node.detected_at}</div>}
        {node.assignee && <div><span className="text-text-muted">负责人:</span> {node.assignee}</div>}
        {node.severity_cn && <div><span className="text-text-muted">严重度:</span> {node.severity_cn}</div>}
        {node.difficulty && <div><span className="text-text-muted">难度:</span> {DIFFICULTY[node.difficulty] || node.difficulty}</div>}
        {node.downtime_hours !== undefined && node.downtime_hours > 0 && <div><span className="text-text-muted">停机:</span> {node.downtime_hours}h</div>}
        {node.est_cost !== undefined && node.est_cost > 0 && <div><span className="text-text-muted">成本:</span> ¥{node.est_cost.toLocaleString()}</div>}
        {node.quantity !== undefined && <div><span className="text-text-muted">数量:</span> x{node.quantity}</div>}
        {node.threshold && <div><span className="text-text-muted">阈值:</span> {node.threshold}{node.unit ? ` ${node.unit}` : ''}</div>}
        {node.confidence !== undefined && <div><span className="text-text-muted">置信度:</span> {Math.round(node.confidence * 100)}%</div>}
      </div>

      {/* Action: view knowledge from fault_record */}
      {view === 'topology' && node.category === 'fault_record' && node.fault_type && (
        <button onClick={() => onViewKnowledge(node.fault_type!)} className="w-full mt-3 py-1.5 text-[10px] rounded bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20 transition-colors">
          🧠 查看: {node.fault_type} 知识网络 →
        </button>
      )}

      <button onClick={onClose} className="w-full mt-2 py-1.5 text-[10px] text-text-muted hover:text-text-primary transition-colors border-t border-border-subtle pt-2">关闭</button>
    </div>
  );
}

// ─── Stat badge ───
function StatBadge({ icon, label, value, color }: { icon: string; label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-sm">{icon}</span>
      <span className={`text-sm font-bold ${color}`}>{value}</span>
      <span className="text-[10px] text-text-muted">{label}</span>
    </div>
  );
}
