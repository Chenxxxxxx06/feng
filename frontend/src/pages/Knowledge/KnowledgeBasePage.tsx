import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

interface FaultNode {
  id: number | string;
  fault_type: string;
  category: string;
  icon: string;
  severity: string;
  symptoms: { indicator: string; threshold: string; unit: string }[];
  root_causes: string[];
  solutions: { action: string; difficulty: string; downtime_hours: number }[];
  related_faults: { id: string; name: string; probability: number }[];
  spare_parts: { name: string; quantity: number; est_cost: number }[];
  cases: { turbine: string; date: string; summary: string; resolution: string; total_cost: number; downtime_days: number }[];
  source?: string;
  confidence?: number;
  verified?: boolean;
  review_state?: 'pending' | 'approved';
}

type KnowledgeFormMode = 'create' | 'edit';
type ReviewFilter = 'all' | 'pending' | 'approved';

interface GraphNode {
  id: string;
  name: string;
  category: string;
  symbol: string;
  symbolSize: number;
  status?: string;
  status_icon?: string;
  region?: string;
  fault_count?: number;
  fault_type?: string;
  active?: boolean;
  detected_at?: string;
  status_cn?: string;
  confidence?: number;
  assignee?: string;
  severity?: string;
  severity_cn?: string;
  difficulty?: string;
  downtime_hours?: number;
  threshold?: string;
  unit?: string;
  quantity?: number;
  est_cost?: number;
  resolution?: string;
  total_cost?: number;
  downtime_days?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  label: string;
  type?: string;
}

interface GraphData {
  stats?: {
    active_faults: number;
    warning_turbines: number;
    pending_workorders: number;
    personnel_count: number;
    total_turbines: number;
    total_knowledge_nodes: number;
    pending_knowledge_nodes?: number;
    regions?: string[];
  };
  nodes: GraphNode[];
  edges: GraphEdge[];
  fault_type?: string;
}

const ALL_CATEGORY = '全部';

const SEVERITY: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
};

const SEVERITY_COLOR: Record<string, string> = {
  low: 'bg-accent-green/15 text-accent-green border-accent-green/20',
  medium: 'bg-accent-yellow/15 text-accent-yellow border-accent-yellow/20',
  high: 'bg-accent-red/15 text-accent-red border-accent-red/20',
  critical: 'bg-red-600/25 text-red-300 border-red-500/30',
};

const DIFFICULTY: Record<string, string> = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
};

const CAT_COLORS: Record<string, string> = {
  fault: '#388bfd',
  symptom: '#f0883e',
  root_cause: '#da3633',
  solution: '#3fb950',
  spare_part: '#a371f7',
  turbine: '#58a6ff',
  fault_record: '#db6d28',
  workorder: '#f7b73c',
  personnel: '#79c0ff',
  case_record: '#8b949e',
};

const STATUS_COLOR: Record<string, string> = {
  normal: '#3fb950',
  warning: '#f0883e',
  fault: '#da3633',
  maintenance: '#58a6ff',
  open: '#da3633',
  diagnosing: '#f0883e',
  confirmed: '#db6d28',
  resolved: '#3fb950',
  pending: '#f0883e',
  in_progress: '#388bfd',
  completed: '#3fb950',
  cancelled: '#8b949e',
  low: '#3fb950',
  medium: '#f0883e',
  high: '#da3633',
  critical: '#ff4444',
};

const createBlankKnowledgeNode = (): FaultNode => ({
  id: '',
  fault_type: '',
  category: '',
  icon: '!',
  severity: 'medium',
  symptoms: [],
  root_causes: [],
  solutions: [],
  related_faults: [],
  spare_parts: [],
  cases: [],
  source: 'manual',
  confidence: 1,
  verified: true,
});

const cloneKnowledgeNode = (node: FaultNode): FaultNode => ({
  ...node,
  symptoms: (node.symptoms || []).map(item => ({ ...item })),
  root_causes: [...(node.root_causes || [])],
  solutions: (node.solutions || []).map(item => ({ ...item })),
  related_faults: (node.related_faults || []).map(item => ({ ...item })),
  spare_parts: (node.spare_parts || []).map(item => ({ ...item })),
  cases: (node.cases || []).map(item => ({ ...item })),
});

const normalizeNode = (node: FaultNode): FaultNode => ({
  ...node,
  icon: node.icon || '!',
  severity: node.severity || 'medium',
  symptoms: node.symptoms || [],
  root_causes: node.root_causes || [],
  solutions: node.solutions || [],
  related_faults: node.related_faults || [],
  spare_parts: node.spare_parts || [],
  cases: node.cases || [],
  verified: node.verified ?? true,
  confidence: node.confidence ?? 1,
});

const isPendingReview = (node: FaultNode) => node.source === 'ai_extracted' && !node.verified;

const GRAPH_EDGE_COLOR: Record<string, string> = {
  fault_record: '#58a6ff',
  workorder: '#d29922',
  personnel: '#79c0ff',
  symptom: '#f0883e',
  root_cause: '#f85149',
  solution: '#3fb950',
  spare_part: '#a371f7',
  case_record: '#8b949e',
  related_fault: '#d29922',
  default: '#30363d',
};

const graphNodeSymbol = (view: 'topology' | 'knowledge', category: string) => {
  if (view === 'topology') {
    return {
      turbine: 'circle',
      fault_record: 'diamond',
      workorder: 'roundRect',
      personnel: 'triangle',
    }[category] || 'circle';
  }

  return {
    fault: 'roundRect',
    symptom: 'circle',
    root_cause: 'diamond',
    solution: 'roundRect',
    spare_part: 'rect',
    case_record: 'triangle',
  }[category] || 'circle';
};

const inferGraphEdgeType = (sourceCategory?: string, targetCategory?: string) => {
  if (!sourceCategory || !targetCategory) return 'default';
  if (sourceCategory === 'turbine' && targetCategory === 'fault_record') return 'fault_record';
  if (sourceCategory === 'fault_record' && targetCategory === 'workorder') return 'workorder';
  if (sourceCategory === 'workorder' && targetCategory === 'personnel') return 'personnel';
  if (sourceCategory === 'fault' && targetCategory === 'symptom') return 'symptom';
  if (sourceCategory === 'fault' && targetCategory === 'root_cause') return 'root_cause';
  if (sourceCategory === 'fault' && targetCategory === 'solution') return 'solution';
  if (sourceCategory === 'fault' && targetCategory === 'spare_part') return 'spare_part';
  if (sourceCategory === 'fault' && targetCategory === 'case_record') return 'case_record';
  if (sourceCategory === 'fault' && targetCategory === 'fault') return 'related_fault';
  return 'default';
};

export default function KnowledgeBasePage() {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState(ALL_CATEGORY);
  const [severityFilter, setSeverityFilter] = useState('');
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all');
  const [detail, setDetail] = useState<FaultNode | null>(null);
  const [copilotMsg, setCopilotMsg] = useState('');
  const [nodes, setNodes] = useState<FaultNode[]>([]);
  const [kbLoading, setKbLoading] = useState(true);
  const [kbError, setKbError] = useState(false);
  const [formMode, setFormMode] = useState<KnowledgeFormMode | null>(null);
  const [formNode, setFormNode] = useState<FaultNode | null>(null);
  const [formOriginalFaultType, setFormOriginalFaultType] = useState('');
  const [formSaving, setFormSaving] = useState(false);
  const [formError, setFormError] = useState('');

  const [graphView, setGraphView] = useState<'topology' | 'knowledge'>('topology');
  const [selectedFaultType, setSelectedFaultType] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState(false);
  const [graphNode, setGraphNode] = useState<GraphNode | null>(null);

  const [filterRegion, setFilterRegion] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [availableRegions, setAvailableRegions] = useState<string[]>([]);

  const chartRef = useRef<HTMLDivElement>(null);
  const chartInst = useRef<echarts.ECharts | null>(null);

  const fetchKnowledgeBase = useCallback(async () => {
    setKbLoading(true);
    setKbError(false);
    try {
      const { data } = await api.get<{ nodes: FaultNode[] }>('/knowledge-base');
      const nextNodes = (data.nodes || []).map(normalizeNode);
      setNodes(nextNodes);
      setDetail(current => {
        if (!current) return current;
        return nextNodes.find(n => String(n.id) === String(current.id)) || null;
      });
    } catch {
      setKbError(true);
    } finally {
      setKbLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKnowledgeBase();
  }, [fetchKnowledgeBase]);

  const categories = useMemo(
    () => [ALL_CATEGORY, ...Array.from(new Set(nodes.map(n => n.category).filter(Boolean)))],
    [nodes],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return nodes.filter(n => {
      if (category !== ALL_CATEGORY && n.category !== category) return false;
      if (severityFilter && n.severity !== severityFilter) return false;
      if (reviewFilter === 'pending' && !isPendingReview(n)) return false;
      if (reviewFilter === 'approved' && isPendingReview(n)) return false;
      if (!q) return true;

      return n.fault_type.toLowerCase().includes(q)
        || n.category.toLowerCase().includes(q)
        || n.symptoms.some(s => s.indicator.toLowerCase().includes(q))
        || n.root_causes.some(r => r.toLowerCase().includes(q))
        || n.solutions.some(s => s.action.toLowerCase().includes(q));
    });
  }, [nodes, search, category, severityFilter, reviewFilter]);

  const stats = useMemo(() => ({
    total: nodes.length,
    categories: new Set(nodes.map(n => n.category)).size,
    high: nodes.filter(n => n.severity === 'high' || n.severity === 'critical').length,
    pendingReview: nodes.filter(isPendingReview).length,
    aiExtracted: nodes.filter(n => n.source === 'ai_extracted').length,
  }), [nodes]);

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

  const buildOption = useCallback((data: GraphData) => {
    const isTopo = graphView === 'topology';
    const cats = [...new Set(data.nodes.map(n => n.category))];
    const nodeCategoryById = new Map(data.nodes.map(n => [n.id, n.category]));

    const nodeData = data.nodes.map(n => {
      let color = CAT_COLORS[n.category] || '#8b949e';
      let borderColor = 'transparent';
      let borderW = 0;
      let shadow = 0;
      const isRoot = !isTopo && n.category === 'fault';

      if (isTopo) {
        if (n.category === 'turbine') {
          color = STATUS_COLOR[n.status || 'normal'] || color;
          borderColor = color;
          borderW = 2;
        }
        if (n.category === 'fault_record') {
          color = n.active ? '#da3633' : '#484f58';
          if (n.active) {
            borderColor = '#ff6b6b';
            borderW = 1;
          }
        }
        if (n.category === 'workorder') {
          color = STATUS_COLOR[n.status || 'pending'] || color;
        }
      } else if (isRoot) {
        color = STATUS_COLOR[n.severity || 'medium'] || color;
        borderColor = color;
        borderW = 3;
        shadow = 18;
      } else if (!isTopo) {
        borderColor = 'rgba(233,237,245,0.18)';
        borderW = 1;
        shadow = 6;
      }

      return {
        ...n,
        symbol: graphNodeSymbol(graphView, n.category),
        itemStyle: { color, borderColor, borderWidth: borderW, shadowBlur: shadow, shadowColor: color },
        symbolSize: isRoot ? Math.max(n.symbolSize, 62) : n.symbolSize,
        label: {
          color: isRoot ? '#ffffff' : '#c9d1d9',
          fontSize: isRoot ? 12 : (isTopo ? 11 : 10),
          fontWeight: isRoot ? 700 : 500,
        },
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
          const lines: string[] = [`<b>${n.name}</b>`, `类型: ${graphCategoryLabel(n.category)}`];
          if (n.status_cn || n.status) lines.push(`状态: ${n.status_cn || n.status} ${n.status_icon || ''}`);
          if (n.region) lines.push(`区域: ${n.region}`);
          if (n.fault_count !== undefined && n.fault_count > 0) lines.push(`活跃故障: ${n.fault_count} 个`);
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
        data: legendCats.map(c => ({ name: c, icon: graphNodeSymbol(graphView, c) })),
        bottom: 0,
        itemGap: 14,
        textStyle: { color: '#8b949e', fontSize: 10 },
        formatter: (name: string) => graphCategoryLabel(name),
      }],
      series: [{
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: false,
        force: {
          repulsion: isTopo ? 350 : 260,
          edgeLength: isTopo ? [120, 400] : [90, 220],
          gravity: isTopo ? 0.06 : 0.08,
          friction: 0.18,
        },
        data: nodeData,
        links: data.edges.map(e => {
          const type = e.type || inferGraphEdgeType(nodeCategoryById.get(e.source), nodeCategoryById.get(e.target));
          const color = GRAPH_EDGE_COLOR[type] || GRAPH_EDGE_COLOR.default;
          return {
            source: e.source,
            target: e.target,
            label: {
              show: Boolean(e.label),
              formatter: e.label,
              fontSize: 9,
              color,
              backgroundColor: 'rgba(8,12,18,0.72)',
              borderColor: 'rgba(255,255,255,0.06)',
              borderWidth: 1,
              borderRadius: 3,
              padding: [2, 4],
            },
            lineStyle: {
              color,
              opacity: isTopo ? 0.45 : 0.62,
              width: isTopo ? 1 : 1.4,
              curveness: isTopo ? 0.05 : 0.22,
            },
          };
        }),
        categories: cats.map(c => ({ name: c, itemStyle: { color: CAT_COLORS[c] || '#8b949e' } })),
        lineStyle: { color: '#30363d', curveness: isTopo ? 0.05 : 0.22, opacity: 0.5 },
        label: { show: true, formatter: '{b}' },
        edgeSymbol: isTopo ? ['none', 'none'] : ['none', 'arrow'],
        edgeSymbolSize: isTopo ? 0 : 7,
        emphasis: {
          focus: 'adjacency',
          blurScope: 'coordinateSystem',
          label: { show: true },
          lineStyle: { width: 3 },
        },
      }],
    };
  }, [graphView]);

  useEffect(() => {
    if (!chartRef.current || !graphData?.nodes?.length) return;
    if (!chartInst.current) chartInst.current = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInst.current.setOption(buildOption(graphData), true);

    const handler = (p: any) => {
      if (p.dataType === 'node') setGraphNode(p.data as GraphNode);
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
  }, [graphData, buildOption]);

  const handleAskAI = (node: FaultNode) => {
    setCopilotMsg(`请分析故障：${node.fault_type}。症状：${node.symptoms.map(s => s.indicator).join('、') || '暂无'}。严重度：${SEVERITY[node.severity] || node.severity}。请给出诊断建议。`);
  };

  const handleVerifyNode = async (node: FaultNode) => {
    await api.patch(`/knowledge-base/${node.id}/verify`);
    const next = { ...node, verified: true, confidence: 1.0, review_state: 'approved' as const };
    setNodes(prev => prev.map(n => String(n.id) === String(node.id) ? next : n));
    setDetail(next);
    fetchGraph();
  };

  const handleRejectNode = async (node: FaultNode) => {
    await api.patch(`/knowledge-base/${node.id}/reject`);
    setNodes(prev => prev.filter(n => String(n.id) !== String(node.id)));
    setDetail(null);
    fetchGraph();
  };

  const handleDeleteNode = async (node: FaultNode) => {
    const ok = window.confirm(`确认删除知识节点「${node.fault_type}」？删除后将不会出现在故障百科、知识图谱和 Copilot 知识参考中。`);
    if (!ok) return;
    await api.delete(`/knowledge-base/${node.id}`);
    setNodes(prev => prev.filter(n => String(n.id) !== String(node.id)));
    setDetail(null);
    fetchGraph();
  };

  const openCreateForm = () => {
    const defaultCategory = categories.find(c => c !== ALL_CATEGORY) || '';
    setFormMode('create');
    setFormNode({ ...createBlankKnowledgeNode(), category: defaultCategory });
    setFormOriginalFaultType('');
    setFormError('');
  };

  const openEditForm = (node: FaultNode) => {
    setFormMode('edit');
    setFormNode(cloneKnowledgeNode(node));
    setFormOriginalFaultType(node.fault_type);
    setFormError('');
  };

  const closeKnowledgeForm = () => {
    if (formSaving) return;
    setFormMode(null);
    setFormNode(null);
    setFormOriginalFaultType('');
    setFormError('');
  };

  const handleSaveKnowledgeNode = async (node: FaultNode) => {
    if (!node.fault_type.trim() || !node.category.trim()) {
      setFormError('请填写故障名称和分类');
      return;
    }

    const payload = {
      fault_type: node.fault_type.trim(),
      category: node.category.trim(),
      icon: node.icon.trim() || '!',
      severity: node.severity || 'medium',
      symptoms: node.symptoms.filter(item => item.indicator.trim()),
      root_causes: node.root_causes.filter(Boolean),
      solutions: node.solutions.filter(item => item.action.trim()),
      related_faults: node.related_faults.filter(item => item.name.trim()),
      spare_parts: node.spare_parts.filter(item => item.name.trim()),
      cases: node.cases.filter(item => item.turbine.trim() || item.summary.trim()),
      source: node.source || 'manual',
      confidence: node.confidence ?? 1,
      verified: node.verified ?? true,
    };

    setFormSaving(true);
    setFormError('');
    try {
      const { data } = formMode === 'edit'
        ? await api.patch<FaultNode>(`/knowledge-base/${node.id}`, payload)
        : await api.post<FaultNode>('/knowledge-base', payload);

      const saved = normalizeNode(data);
      setNodes(prev => {
        if (formMode === 'edit') {
          return prev.map(item => String(item.id) === String(saved.id) ? saved : item);
        }
        return [saved, ...prev];
      });
      setDetail(saved);
      setSelectedFaultType(current => current === formOriginalFaultType ? saved.fault_type : current);
      setFormMode(null);
      setFormNode(null);
      setFormOriginalFaultType('');
      fetchGraph();
    } catch (err: any) {
      const status = err.response?.status;
      setFormError(status === 409 ? '同名故障知识已存在' : '保存失败，请稍后重试');
    } finally {
      setFormSaving(false);
    }
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
  const graphSummary = useMemo(() => {
    if (!graphData?.nodes?.length) return null;
    const count = (categoryName: string) => graphData.nodes.filter(n => n.category === categoryName).length;
    if (graphView === 'topology') {
      return [
        { label: '风机', value: count('turbine'), color: CAT_COLORS.turbine },
        { label: '故障事件', value: count('fault_record'), color: CAT_COLORS.fault_record },
        { label: '工单', value: count('workorder'), color: CAT_COLORS.workorder },
        { label: '人员', value: count('personnel'), color: CAT_COLORS.personnel },
      ];
    }
    return [
      { label: '症状', value: count('symptom'), color: CAT_COLORS.symptom },
      { label: '根因', value: count('root_cause'), color: CAT_COLORS.root_cause },
      { label: '方案', value: count('solution'), color: CAT_COLORS.solution },
      { label: '备件', value: count('spare_part'), color: CAT_COLORS.spare_part },
      { label: '案例', value: count('case_record'), color: CAT_COLORS.case_record },
    ];
  }, [graphData, graphView]);

  return (
    <div className="flex h-full min-h-0 bg-bg-deep">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto overflow-x-hidden">
        <div className="border-b border-border-subtle bg-bg-panel/90 p-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-bold text-text-primary">故障百科</h1>
              <p className="mt-1 text-xs text-text-muted">沉淀故障症状、根因、方案和案例，并对 AI 抽取知识进行审核。</p>
            </div>
            <button onClick={openCreateForm} className="rounded-lg border border-accent-blue/40 bg-accent-blue/20 px-3 py-2 text-sm font-medium text-accent-blue hover:bg-accent-blue/30">
              新增知识
            </button>
          </div>

          <div className="mt-3 grid grid-cols-4 gap-2">
            <SummaryTile label="知识节点" value={stats.total} tone="blue" />
            <SummaryTile label="高危知识" value={stats.high} tone="red" />
            <SummaryTile label="待审核" value={stats.pendingReview} tone="yellow" active={reviewFilter === 'pending'} onClick={() => setReviewFilter('pending')} />
            <SummaryTile label="AI 提取" value={stats.aiExtracted} tone="cyan" />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              className="min-w-[260px] flex-1 rounded-lg border border-border-subtle bg-bg-card px-3 py-2 text-sm placeholder-text-muted focus:border-accent-blue focus:outline-none"
              placeholder="搜索故障名称、症状、根因或方案"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <select className="rounded-lg border border-border-subtle bg-bg-card px-3 py-2 text-sm" value={category} onChange={e => setCategory(e.target.value)}>
              {categories.map(c => <option key={c} value={c}>{c === ALL_CATEGORY ? '全部分类' : c}</option>)}
            </select>
            <select className="rounded-lg border border-border-subtle bg-bg-card px-3 py-2 text-sm" value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}>
              <option value="">全部严重度</option>
              <option value="critical">紧急</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
            <div className="flex overflow-hidden rounded-lg border border-border-subtle text-sm">
              <ReviewButton label="全部" active={reviewFilter === 'all'} onClick={() => setReviewFilter('all')} />
              <ReviewButton label={`待审核 ${stats.pendingReview}`} active={reviewFilter === 'pending'} onClick={() => setReviewFilter('pending')} />
              <ReviewButton label="已通过" active={reviewFilter === 'approved'} onClick={() => setReviewFilter('approved')} />
            </div>
          </div>

          <div className="mt-3 flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'thin' }}>
            {kbLoading ? (
              <div className="px-2 py-6 text-xs text-text-muted">正在加载知识库...</div>
            ) : kbError ? (
              <div className="flex items-center gap-3 px-2 py-6 text-xs text-text-muted">
                <span>知识库加载失败</span>
                <button onClick={fetchKnowledgeBase} className="text-accent-blue hover:underline">重试</button>
              </div>
            ) : filtered.length > 0 ? filtered.map(node => (
              <KnowledgeCard key={node.id} node={node} active={String(detail?.id) === String(node.id)} onClick={() => setDetail(node)} />
            )) : (
              <div className="px-2 py-6 text-xs text-text-muted">暂无符合条件的知识节点</div>
            )}
          </div>
        </div>
        {gStats && graphView === 'topology' && (
          <div className="flex items-center gap-4 border-b border-border-subtle bg-bg-deep/50 px-4 py-2">
            <StatBadge label="活跃故障" value={gStats.active_faults} color="text-accent-red" />
            <StatBadge label="预警风机" value={gStats.warning_turbines} color="text-accent-yellow" />
            <StatBadge label="待处理工单" value={gStats.pending_workorders} color="text-accent-blue" />
            <StatBadge label="在岗人员" value={gStats.personnel_count} color="text-accent-green" />
            <span className="ml-auto text-[10px] text-text-muted">风机 {gStats.total_turbines} 台 · 已审核知识 {gStats.total_knowledge_nodes} 个</span>
          </div>
        )}

        <div className="flex items-center gap-3 border-b border-border-subtle px-4 py-2">
          {graphView === 'topology' ? (
            <>
              {availableRegions.length > 0 && (
                <select className="rounded border border-border-subtle bg-bg-card px-2.5 py-1 text-xs" value={filterRegion} onChange={e => setFilterRegion(e.target.value)}>
                  <option value="">全部区域</option>
                  {availableRegions.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              )}
              <label className="flex items-center gap-2 text-xs text-text-secondary">
                <input type="checkbox" checked={activeOnly} onChange={e => setActiveOnly(e.target.checked)} />
                仅看活跃
              </label>
            </>
          ) : (
            <div className="flex items-center gap-2">
              <button onClick={backToTopology} className="rounded border border-border-subtle bg-bg-card px-3 py-1 text-xs text-text-secondary hover:border-accent-blue hover:text-text-primary">
                返回运维拓扑
              </button>
              {selectedFaultType && <span className="text-xs font-medium text-accent-blue">{selectedFaultType}</span>}
            </div>
          )}

          <div className="ml-auto flex overflow-hidden rounded-lg border border-border-subtle text-xs">
            <button onClick={backToTopology} className={`px-3 py-1.5 ${graphView === 'topology' ? 'bg-accent-blue/20 text-accent-blue' : 'bg-bg-card text-text-muted hover:text-text-primary'}`}>
              运维拓扑
            </button>
            <button
              onClick={() => {
                if (!selectedFaultType) {
                  const first = nodes.find(n => !isPendingReview(n));
                  if (first) switchToKnowledge(first.fault_type);
                } else {
                  setGraphView('knowledge');
                }
              }}
              className={`px-3 py-1.5 ${graphView === 'knowledge' ? 'bg-accent-blue/20 text-accent-blue' : 'bg-bg-card text-text-muted hover:text-text-primary'}`}
            >
              知识网络
            </button>
          </div>
        </div>

        {graphSummary && (
          <div className="flex items-center gap-3 border-b border-border-subtle bg-bg-panel/40 px-4 py-2">
            <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
              {graphView === 'topology' ? '拓扑概览' : '知识链路'}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {graphSummary.map(item => (
                <span key={item.label} className="inline-flex items-center gap-1.5 rounded border border-border-subtle bg-bg-card/70 px-2 py-1 text-[10px] text-text-secondary">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: item.color }} />
                  {item.label}
                  <b className="font-semibold text-text-primary">{item.value}</b>
                </span>
              ))}
            </div>
            {graphView === 'knowledge' && selectedFaultType && (
              <span className="ml-auto truncate text-[10px] text-text-muted">
                以「{selectedFaultType}」为中心展开症状、根因、方案、备件与案例
              </span>
            )}
          </div>
        )}

        <div className="flex min-h-[560px] flex-1">
          {graphLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-blue border-t-transparent" />
                <span className="text-sm text-text-muted">{graphView === 'topology' ? '加载运维拓扑...' : '加载知识网络...'}</span>
              </div>
            </div>
          ) : graphError ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-muted">
              <p className="text-sm">图谱加载失败</p>
              <button onClick={fetchGraph} className="mt-1 text-xs text-accent-blue hover:underline">重试</button>
            </div>
          ) : graphData && graphData.nodes.length > 0 ? (
            <>
              <div className="relative flex-1 overflow-hidden bg-[radial-gradient(circle_at_50%_35%,rgba(56,139,253,0.12),transparent_34%),linear-gradient(180deg,rgba(13,19,30,0.7),rgba(8,12,18,0.92))]">
                <div className="pointer-events-none absolute inset-0 opacity-[0.14] [background-image:linear-gradient(rgba(233,237,245,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(233,237,245,0.08)_1px,transparent_1px)] [background-size:32px_32px]" />
                <div ref={chartRef} className="relative h-full w-full" />
              </div>
              {graphNode && <NodeInfoPanel node={graphNode} view={graphView} onViewKnowledge={switchToKnowledge} onClose={() => setGraphNode(null)} />}
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-muted">
              <p className="text-sm">{graphView === 'topology' ? '运维拓扑暂无数据' : '知识网络暂无数据'}</p>
              <p className="text-xs">{graphView === 'topology' ? '导入风机、故障记录和工单后会生成拓扑。' : '请选择一个已审核知识节点查看网络。'}</p>
            </div>
          )}
        </div>
      </div>

      {detail && (
        <KnowledgeDetailDrawer
          detail={detail}
          nodes={nodes}
          onClose={() => setDetail(null)}
          onEdit={openEditForm}
          onDelete={handleDeleteNode}
          onVerify={handleVerifyNode}
          onReject={handleRejectNode}
          onAskAI={handleAskAI}
          onSwitchToKnowledge={switchToKnowledge}
          onSelectDetail={setDetail}
        />
      )}

      {formMode && formNode && (
        <KnowledgeNodeForm
          mode={formMode}
          node={formNode}
          categories={categories.filter(c => c !== ALL_CATEGORY)}
          saving={formSaving}
          error={formError}
          onChange={setFormNode}
          onClose={closeKnowledgeForm}
          onSave={handleSaveKnowledgeNode}
        />
      )}

      <CopilotFAB initialMessage={copilotMsg} />
    </div>
  );
}

function KnowledgeCard({ node, active, onClick }: { node: FaultNode; active: boolean; onClick: () => void }) {
  const pending = isPendingReview(node);
  const confidence = Math.round((node.confidence ?? 1) * 100);
  return (
    <button
      className={`flex-shrink-0 w-[230px] rounded-lg border bg-bg-card p-3 text-left transition-all hover:border-accent-blue/50 hover:shadow-lg ${active ? 'border-accent-blue/60 shadow-[0_0_18px_rgba(56,139,253,0.18)]' : 'border-border-subtle'}`}
      onClick={onClick}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-text-primary">{node.fault_type}</p>
          <p className="mt-0.5 text-[10px] text-text-muted">{node.category || '未分类'} · {node.source === 'ai_extracted' ? 'AI 提取' : '人工维护'}</p>
        </div>
        <span className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-medium ${SEVERITY_COLOR[node.severity] || SEVERITY_COLOR.medium}`}>
          {SEVERITY[node.severity] || node.severity}
        </span>
      </div>
      <div className="mb-2 line-clamp-2 min-h-[32px] text-xs leading-4 text-text-secondary">
        {node.symptoms.slice(0, 2).map(s => s.indicator).join('、') || '暂无症状指标'}
      </div>
      <div className="flex items-center justify-between text-[10px]">
        {pending ? (
          <span className="rounded bg-accent-yellow/15 px-2 py-0.5 text-accent-yellow">待审核</span>
        ) : (
          <span className="rounded bg-accent-green/10 px-2 py-0.5 text-accent-green">已通过</span>
        )}
        <span className="text-text-muted">置信度 {confidence}%</span>
      </div>
    </button>
  );
}

function KnowledgeDetailDrawer({
  detail,
  nodes,
  onClose,
  onEdit,
  onDelete,
  onVerify,
  onReject,
  onAskAI,
  onSwitchToKnowledge,
  onSelectDetail,
}: {
  detail: FaultNode;
  nodes: FaultNode[];
  onClose: () => void;
  onEdit: (node: FaultNode) => void;
  onDelete: (node: FaultNode) => void;
  onVerify: (node: FaultNode) => void;
  onReject: (node: FaultNode) => void;
  onAskAI: (node: FaultNode) => void;
  onSwitchToKnowledge: (faultType: string) => void;
  onSelectDetail: (node: FaultNode) => void;
}) {
  const pending = isPendingReview(detail);

  return (
    <div className="w-[440px] flex-shrink-0 overflow-auto border-l border-border-subtle bg-bg-card">
      <div className="sticky top-0 z-10 border-b border-border-subtle bg-bg-card/95 p-5 backdrop-blur-sm">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2">
              <span className={`rounded border px-2 py-0.5 text-[10px] font-medium ${SEVERITY_COLOR[detail.severity] || SEVERITY_COLOR.medium}`}>
                {SEVERITY[detail.severity] || detail.severity}
              </span>
              <span className="rounded bg-bg-deep px-2 py-0.5 text-[10px] text-text-muted">{detail.category}</span>
              {pending && <span className="rounded bg-accent-yellow/15 px-2 py-0.5 text-[10px] text-accent-yellow">待审核</span>}
            </div>
            <h2 className="text-base font-bold leading-snug text-text-primary">{detail.fault_type}</h2>
            <p className="mt-1 text-xs text-text-muted">
              {detail.source === 'ai_extracted' ? `AI 提取 · 置信度 ${Math.round((detail.confidence || 0) * 100)}%` : '人工维护'}
            </p>
          </div>
          <button onClick={onClose} className="text-xl leading-none text-text-muted hover:text-text-primary">&times;</button>
        </div>

        <div className="flex flex-wrap gap-2">
          <button onClick={() => onSwitchToKnowledge(detail.fault_type)} className="rounded bg-accent-blue/10 px-3 py-1.5 text-xs text-accent-blue hover:bg-accent-blue/20">知识网络</button>
          <button onClick={() => onEdit(detail)} className="rounded border border-border-subtle bg-bg-deep px-3 py-1.5 text-xs text-text-secondary hover:border-accent-blue/50 hover:text-text-primary">编辑</button>
          {pending ? (
            <>
              <button onClick={() => onVerify(detail)} className="rounded bg-accent-green/15 px-3 py-1.5 text-xs text-accent-green hover:bg-accent-green/25">通过</button>
              <button onClick={() => onReject(detail)} className="rounded bg-accent-red/15 px-3 py-1.5 text-xs text-accent-red hover:bg-accent-red/25">驳回</button>
            </>
          ) : (
            <button onClick={() => onDelete(detail)} className="rounded border border-accent-red/25 bg-accent-red/10 px-3 py-1.5 text-xs text-accent-red hover:bg-accent-red/20">删除</button>
          )}
        </div>
      </div>

      <div className="space-y-6 p-5">
        {pending && (
          <div className="rounded-lg border border-accent-yellow/30 bg-accent-yellow/10 p-3 text-xs text-accent-yellow">
            该知识由 AI 自动抽取，审核通过前不会进入知识图谱和 Copilot 知识参考。
          </div>
        )}

        <DetailSection title="症状指标">
          {detail.symptoms.length ? detail.symptoms.map((s, i) => (
            <div key={i} className="flex justify-between gap-3 rounded-lg bg-bg-deep px-3 py-2 text-sm">
              <span className="text-text-primary">{s.indicator}</span>
              <span className="font-mono text-xs text-accent-red">{s.threshold}{s.unit ? ` ${s.unit}` : ''}</span>
            </div>
          )) : <EmptyLine text="暂无症状指标" />}
        </DetailSection>

        <DetailSection title="根因分析">
          {detail.root_causes.length ? detail.root_causes.map((r, i) => (
            <div key={i} className="flex gap-2 rounded-lg bg-bg-deep px-3 py-2 text-sm">
              <span className="font-mono text-xs text-text-muted">{i + 1}.</span>
              <span>{r}</span>
            </div>
          )) : <EmptyLine text="暂无根因分析" />}
        </DetailSection>

        <DetailSection title="解决方案">
          {detail.solutions.length ? detail.solutions.map((s, i) => (
            <div key={i} className="rounded-lg bg-bg-deep p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{s.action}</span>
                <span className="text-[10px] text-text-muted">{DIFFICULTY[s.difficulty] || s.difficulty}</span>
              </div>
              <span className="text-[10px] text-text-muted">预计停机 {s.downtime_hours || 0}h</span>
            </div>
          )) : <EmptyLine text="暂无解决方案" />}
        </DetailSection>

        {detail.related_faults.length > 0 && (
          <DetailSection title="关联故障">
            {detail.related_faults.map((rf, i) => (
              <div key={i} className="flex justify-between rounded-lg bg-bg-deep px-3 py-2 text-sm">
                <button
                  className="text-left text-accent-blue hover:underline"
                  onClick={() => {
                    const n = nodes.find(x => String(x.id) === String(rf.id) || x.fault_type === rf.name);
                    if (n) onSelectDetail(n);
                  }}
                >
                  {rf.name}
                </button>
                <span className="text-xs text-text-muted">{Math.round(rf.probability * 100)}%</span>
              </div>
            ))}
          </DetailSection>
        )}

        {detail.cases.length > 0 && (
          <DetailSection title="历史案例">
            {detail.cases.map((c, i) => (
              <div key={i} className="rounded-lg bg-bg-deep p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{c.turbine}</span>
                  <span className="text-[10px] text-text-muted">{c.date}</span>
                </div>
                <p className="mb-2 text-xs text-text-secondary">{c.summary}</p>
                <div className="flex gap-3 text-[10px] text-text-muted">
                  <span>{c.resolution}</span>
                  <span>¥{Number(c.total_cost || 0).toLocaleString()}</span>
                  <span>{c.downtime_days || 0} 天</span>
                </div>
              </div>
            ))}
          </DetailSection>
        )}

        {detail.spare_parts.length > 0 && (
          <DetailSection title="关联备件">
            {detail.spare_parts.map((sp, i) => (
              <div key={i} className="flex justify-between rounded-lg bg-bg-deep px-3 py-2 text-sm">
                <span>{sp.name}</span>
                <span className="text-xs text-text-muted">x{sp.quantity} · ¥{Number(sp.est_cost || 0).toLocaleString()}</span>
              </div>
            ))}
          </DetailSection>
        )}

        <button onClick={() => onAskAI(detail)} className="w-full rounded-lg border border-accent-blue/30 bg-accent-blue/10 py-3 text-sm font-medium text-accent-blue hover:bg-accent-blue/20">
          AI 诊断此故障
        </button>
      </div>
    </div>
  );
}

function NodeInfoPanel({ node, view, onViewKnowledge, onClose }: { node: GraphNode; view: string; onViewKnowledge: (ft: string) => void; onClose: () => void }) {
  const color = CAT_COLORS[node.category] || '#8b949e';
  const metrics = [
    node.fault_count !== undefined && node.fault_count > 0 ? { label: '活跃故障', value: `${node.fault_count} 个`, tone: 'text-accent-red' } : null,
    node.confidence !== undefined ? { label: '置信度', value: `${Math.round(node.confidence * 100)}%`, tone: 'text-accent-cyan' } : null,
    node.downtime_hours !== undefined && node.downtime_hours > 0 ? { label: '预计停机', value: `${node.downtime_hours}h`, tone: 'text-accent-yellow' } : null,
    node.est_cost !== undefined && node.est_cost > 0 ? { label: '预估成本', value: `¥${node.est_cost.toLocaleString()}`, tone: 'text-accent-yellow' } : null,
    node.quantity !== undefined ? { label: '数量', value: `x${node.quantity}`, tone: 'text-text-primary' } : null,
    node.total_cost !== undefined && node.total_cost > 0 ? { label: '案例成本', value: `¥${node.total_cost.toLocaleString()}`, tone: 'text-accent-yellow' } : null,
    node.downtime_days !== undefined && node.downtime_days > 0 ? { label: '停机天数', value: `${node.downtime_days}天`, tone: 'text-accent-yellow' } : null,
  ].filter(Boolean) as { label: string; value: string; tone: string }[];

  return (
    <div className="w-72 flex-shrink-0 overflow-auto border-l border-border-subtle bg-bg-card/95 p-4 text-xs shadow-[-18px_0_36px_rgba(0,0,0,0.18)]">
      <div className="mb-4 rounded-lg border border-border-subtle bg-bg-deep/70 p-3">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-3 w-3 flex-shrink-0 rounded-full shadow-[0_0_12px_currentColor]" style={{ background: color, color }} />
          <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">{graphCategoryLabel(node.category)}</span>
          {node.active && <span className="ml-auto rounded-full border border-accent-red/30 bg-accent-red/10 px-2 py-0.5 text-[10px] text-accent-red">活跃</span>}
        </div>

        <p className="text-sm font-semibold leading-snug text-text-primary">{node.name}</p>
      </div>

      {metrics.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-2">
          {metrics.map(item => (
            <div key={item.label} className="rounded-lg border border-border-subtle bg-bg-deep/55 px-2 py-2">
              <p className="text-[10px] text-text-muted">{item.label}</p>
              <p className={`mt-1 text-sm font-semibold ${item.tone}`}>{item.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1.5 rounded-lg border border-border-subtle bg-bg-deep/45 p-3 text-text-secondary">
        {node.status_icon && <div><span className="text-text-muted">状态:</span> {node.status_icon} {node.status_cn || node.status}</div>}
        {!node.status_icon && node.status_cn && <div><span className="text-text-muted">状态:</span> {node.status_cn}</div>}
        {!node.status_icon && !node.status_cn && node.status && <div><span className="text-text-muted">状态:</span> {node.status}</div>}
        {node.region && <div><span className="text-text-muted">区域:</span> {node.region}</div>}
        {node.detected_at && <div><span className="text-text-muted">发现:</span> {node.detected_at}</div>}
        {node.assignee && <div><span className="text-text-muted">负责人:</span> {node.assignee}</div>}
        {node.severity_cn && <div><span className="text-text-muted">严重度:</span> {node.severity_cn}</div>}
        {node.difficulty && <div><span className="text-text-muted">难度:</span> {DIFFICULTY[node.difficulty] || node.difficulty}</div>}
        {node.threshold && <div><span className="text-text-muted">阈值:</span> {node.threshold}{node.unit ? ` ${node.unit}` : ''}</div>}
        {node.resolution && <div><span className="text-text-muted">处理结果:</span> {node.resolution}</div>}
      </div>

      {view === 'topology' && node.category === 'fault_record' && node.fault_type && (
        <button onClick={() => onViewKnowledge(node.fault_type!)} className="mt-3 w-full rounded-lg border border-accent-blue/30 bg-accent-blue/10 py-2 text-[10px] font-medium text-accent-blue hover:bg-accent-blue/20">
          查看 {node.fault_type} 知识网络
        </button>
      )}

      <button onClick={onClose} className="mt-2 w-full border-t border-border-subtle pt-3 text-[10px] text-text-muted hover:text-text-primary">关闭</button>
    </div>
  );
}

function KnowledgeNodeForm({
  mode,
  node,
  categories,
  saving,
  error,
  onChange,
  onClose,
  onSave,
}: {
  mode: KnowledgeFormMode;
  node: FaultNode;
  categories: string[];
  saving: boolean;
  error: string;
  onChange: (node: FaultNode) => void;
  onClose: () => void;
  onSave: (node: FaultNode) => void;
}) {
  const setField = <K extends keyof FaultNode>(key: K, value: FaultNode[K]) => {
    onChange({ ...node, [key]: value });
  };

  const updateListItem = <T,>(key: keyof FaultNode, list: T[], index: number, value: T) => {
    const next = [...list];
    next[index] = value;
    onChange({ ...node, [key]: next });
  };

  const removeListItem = <T,>(key: keyof FaultNode, list: T[], index: number) => {
    onChange({ ...node, [key]: list.filter((_, i) => i !== index) });
  };

  const categoryOptions = categories.includes(node.category) || !node.category
    ? categories
    : [node.category, ...categories];

  return (
    <div className="w-[460px] flex-shrink-0 overflow-auto border-l border-border-subtle bg-bg-card">
      <div className="sticky top-0 z-20 border-b border-border-subtle bg-bg-card/95 p-5 backdrop-blur-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold">{mode === 'create' ? '新增知识' : '编辑知识'}</h2>
            <p className="mt-1 text-xs text-text-muted">维护故障百科中的结构化知识节点</p>
          </div>
          <button onClick={onClose} disabled={saving} className="text-xl leading-none text-text-muted hover:text-text-primary">&times;</button>
        </div>
        {error && <div className="mt-3 rounded border border-accent-red/20 bg-accent-red/10 px-3 py-2 text-xs text-accent-red">{error}</div>}
      </div>

      <div className="space-y-5 p-5">
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">基本信息</h3>
          <div className="grid grid-cols-[1fr_96px] gap-2">
            <FormInput label="故障名称" value={node.fault_type} onChange={value => setField('fault_type', value)} />
            <FormInput label="图标" value={node.icon} onChange={value => setField('icon', value)} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[10px] text-text-muted">分类</span>
              <select className="form-input mt-1 w-full" value={node.category} onChange={e => setField('category', e.target.value)}>
                <option value="" disabled>请选择分类</option>
                {categoryOptions.map(item => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] text-text-muted">严重度</span>
              <select className="form-input mt-1 w-full" value={node.severity} onChange={e => setField('severity', e.target.value)}>
                <option value="low">低</option>
                <option value="medium">中</option>
                <option value="high">高</option>
                <option value="critical">紧急</option>
              </select>
            </label>
          </div>
        </section>

        <FormSection title="症状指标" onAdd={() => setField('symptoms', [...node.symptoms, { indicator: '', threshold: '', unit: '' }])}>
          {node.symptoms.map((item, index) => (
            <div key={index} className="grid grid-cols-[1fr_92px_72px_28px] gap-2">
              <input className="form-input" placeholder="指标名" value={item.indicator} onChange={e => updateListItem('symptoms', node.symptoms, index, { ...item, indicator: e.target.value })} />
              <input className="form-input" placeholder="阈值" value={item.threshold} onChange={e => updateListItem('symptoms', node.symptoms, index, { ...item, threshold: e.target.value })} />
              <input className="form-input" placeholder="单位" value={item.unit} onChange={e => updateListItem('symptoms', node.symptoms, index, { ...item, unit: e.target.value })} />
              <RemoveButton onClick={() => removeListItem('symptoms', node.symptoms, index)} />
            </div>
          ))}
        </FormSection>

        <FormSection title="根因分析" onAdd={() => setField('root_causes', [...node.root_causes, ''])}>
          {node.root_causes.map((item, index) => (
            <div key={index} className="grid grid-cols-[1fr_28px] gap-2">
              <input className="form-input" placeholder="根因" value={item} onChange={e => updateListItem('root_causes', node.root_causes, index, e.target.value)} />
              <RemoveButton onClick={() => removeListItem('root_causes', node.root_causes, index)} />
            </div>
          ))}
        </FormSection>

        <FormSection title="解决方案" onAdd={() => setField('solutions', [...node.solutions, { action: '', difficulty: 'medium', downtime_hours: 0 }])}>
          {node.solutions.map((item, index) => (
            <div key={index} className="grid grid-cols-[1fr_82px_82px_28px] gap-2">
              <input className="form-input" placeholder="处理动作" value={item.action} onChange={e => updateListItem('solutions', node.solutions, index, { ...item, action: e.target.value })} />
              <select className="form-input" value={item.difficulty} onChange={e => updateListItem('solutions', node.solutions, index, { ...item, difficulty: e.target.value })}>
                <option value="easy">简单</option>
                <option value="medium">中等</option>
                <option value="hard">困难</option>
              </select>
              <input className="form-input" type="number" min="0" placeholder="小时" value={item.downtime_hours} onChange={e => updateListItem('solutions', node.solutions, index, { ...item, downtime_hours: Number(e.target.value) || 0 })} />
              <RemoveButton onClick={() => removeListItem('solutions', node.solutions, index)} />
            </div>
          ))}
        </FormSection>

        <FormSection title="关联故障" onAdd={() => setField('related_faults', [...node.related_faults, { id: '', name: '', probability: 0 }])}>
          {node.related_faults.map((item, index) => (
            <div key={index} className="grid grid-cols-[1fr_82px_28px] gap-2">
              <input className="form-input" placeholder="故障名称" value={item.name} onChange={e => updateListItem('related_faults', node.related_faults, index, { ...item, name: e.target.value, id: e.target.value })} />
              <input className="form-input" type="number" min="0" max="1" step="0.1" placeholder="概率" value={item.probability} onChange={e => updateListItem('related_faults', node.related_faults, index, { ...item, probability: Number(e.target.value) || 0 })} />
              <RemoveButton onClick={() => removeListItem('related_faults', node.related_faults, index)} />
            </div>
          ))}
        </FormSection>

        <FormSection title="备件" onAdd={() => setField('spare_parts', [...node.spare_parts, { name: '', quantity: 1, est_cost: 0 }])}>
          {node.spare_parts.map((item, index) => (
            <div key={index} className="grid grid-cols-[1fr_64px_88px_28px] gap-2">
              <input className="form-input" placeholder="备件名称" value={item.name} onChange={e => updateListItem('spare_parts', node.spare_parts, index, { ...item, name: e.target.value })} />
              <input className="form-input" type="number" min="0" placeholder="数量" value={item.quantity} onChange={e => updateListItem('spare_parts', node.spare_parts, index, { ...item, quantity: Number(e.target.value) || 0 })} />
              <input className="form-input" type="number" min="0" placeholder="成本" value={item.est_cost} onChange={e => updateListItem('spare_parts', node.spare_parts, index, { ...item, est_cost: Number(e.target.value) || 0 })} />
              <RemoveButton onClick={() => removeListItem('spare_parts', node.spare_parts, index)} />
            </div>
          ))}
        </FormSection>

        <FormSection title="历史案例" onAdd={() => setField('cases', [...node.cases, { turbine: '', date: '', summary: '', resolution: '', total_cost: 0, downtime_days: 0 }])}>
          {node.cases.map((item, index) => (
            <div key={index} className="space-y-2 rounded border border-border-subtle bg-bg-deep p-3">
              <div className="grid grid-cols-[1fr_110px_28px] gap-2">
                <input className="form-input" placeholder="风机" value={item.turbine} onChange={e => updateListItem('cases', node.cases, index, { ...item, turbine: e.target.value })} />
                <input className="form-input" type="date" value={item.date} onChange={e => updateListItem('cases', node.cases, index, { ...item, date: e.target.value })} />
                <RemoveButton onClick={() => removeListItem('cases', node.cases, index)} />
              </div>
              <textarea className="form-input min-h-[64px]" placeholder="案例摘要" value={item.summary} onChange={e => updateListItem('cases', node.cases, index, { ...item, summary: e.target.value })} />
              <div className="grid grid-cols-[1fr_86px_86px] gap-2">
                <input className="form-input" placeholder="处理结果" value={item.resolution} onChange={e => updateListItem('cases', node.cases, index, { ...item, resolution: e.target.value })} />
                <input className="form-input" type="number" min="0" placeholder="成本" value={item.total_cost} onChange={e => updateListItem('cases', node.cases, index, { ...item, total_cost: Number(e.target.value) || 0 })} />
                <input className="form-input" type="number" min="0" placeholder="天数" value={item.downtime_days} onChange={e => updateListItem('cases', node.cases, index, { ...item, downtime_days: Number(e.target.value) || 0 })} />
              </div>
            </div>
          ))}
        </FormSection>
      </div>

      <div className="sticky bottom-0 flex gap-2 border-t border-border-subtle bg-bg-card/95 p-4 backdrop-blur-sm">
        <button onClick={onClose} disabled={saving} className="flex-1 rounded-lg border border-border-subtle py-2 text-sm text-text-secondary hover:border-border-active hover:text-text-primary disabled:opacity-60">取消</button>
        <button onClick={() => onSave(node)} disabled={saving} className="flex-1 rounded-lg border border-accent-blue/40 bg-accent-blue/20 py-2 text-sm font-medium text-accent-blue hover:bg-accent-blue/30 disabled:opacity-60">
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h3>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="rounded-lg border border-border-subtle bg-bg-deep px-3 py-2 text-xs text-text-muted">{text}</div>;
}

function FormInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-[10px] text-text-muted">{label}</span>
      <input className="form-input mt-1 w-full" value={value} onChange={e => onChange(e.target.value)} />
    </label>
  );
}

function FormSection({ title, onAdd, children }: { title: string; onAdd: () => void; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h3>
        <button onClick={onAdd} className="rounded border border-border-subtle bg-bg-deep px-2 py-1 text-[10px] text-accent-blue hover:border-accent-blue/50">添加</button>
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="h-9 rounded border border-border-subtle text-text-muted hover:border-accent-red/40 hover:text-accent-red">x</button>
  );
}

function SummaryTile({ label, value, tone, active, onClick }: { label: string; value: number; tone: 'blue' | 'red' | 'yellow' | 'cyan'; active?: boolean; onClick?: () => void }) {
  const toneClass = {
    blue: 'text-accent-blue border-accent-blue/20 bg-accent-blue/10',
    red: 'text-accent-red border-accent-red/20 bg-accent-red/10',
    yellow: 'text-accent-yellow border-accent-yellow/20 bg-accent-yellow/10',
    cyan: 'text-accent-cyan border-accent-cyan/20 bg-accent-cyan/10',
  }[tone];

  const content = (
    <>
      <span className="text-[10px] text-text-muted">{label}</span>
      <span className={`mt-1 text-lg font-bold ${toneClass.split(' ')[0]}`}>{value}</span>
    </>
  );

  if (onClick) {
    return (
      <button onClick={onClick} className={`flex flex-col rounded-lg border p-3 text-left transition-colors ${toneClass} ${active ? 'ring-1 ring-accent-yellow/40' : ''}`}>
        {content}
      </button>
    );
  }

  return <div className={`flex flex-col rounded-lg border p-3 ${toneClass}`}>{content}</div>;
}

function ReviewButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`px-3 py-2 transition-colors ${active ? 'bg-accent-blue/20 text-accent-blue' : 'bg-bg-card text-text-muted hover:text-text-primary'}`}>
      {label}
    </button>
  );
}

function StatBadge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-sm font-bold ${color}`}>{value}</span>
      <span className="text-[10px] text-text-muted">{label}</span>
    </div>
  );
}

function graphCategoryLabel(category: string) {
  return {
    turbine: '风机',
    fault_record: '故障事件',
    workorder: '工单',
    personnel: '人员',
    fault: '故障知识',
    symptom: '症状',
    root_cause: '根因',
    solution: '方案',
    spare_part: '备件',
    case_record: '案例',
  }[category] || category;
}
