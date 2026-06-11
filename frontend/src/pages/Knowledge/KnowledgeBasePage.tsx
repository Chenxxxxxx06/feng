import { useState, useMemo } from 'react';
import kbData from '../../data/fault-kb.json';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

interface FaultNode {
  id: string; fault_type: string; category: string; icon: string;
  severity: string; symptoms: { indicator: string; threshold: string; unit: string }[];
  root_causes: string[];
  solutions: { action: string; difficulty: string; downtime_hours: number }[];
  related_faults: { id: string; name: string; probability: number }[];
  spare_parts: { name: string; quantity: number; est_cost: number }[];
  cases: { turbine: string; date: string; summary: string; resolution: string; total_cost: number; downtime_days: number }[];
}

const SEVERITY: Record<string, string> = { low: '低', medium: '中', high: '高', critical: '紧急' };
const SEVERITY_COLOR: Record<string, string> = { low: 'bg-accent-green/20 text-accent-green', medium: 'bg-accent-yellow/20 text-accent-yellow', high: 'bg-accent-red/20 text-accent-red', critical: 'bg-red-600/30 text-red-400' };
const DIFFICULTY: Record<string, string> = { easy: '简单', medium: '中等', hard: '困难' };

const CATEGORIES = ['全部', ...Array.from(new Set((kbData.nodes as FaultNode[]).map(n => n.category)))];

export default function KnowledgeBasePage() {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('全部');
  const [severityFilter, setSeverityFilter] = useState('');
  const [detail, setDetail] = useState<FaultNode | null>(null);
  const [copilotMsg, setCopilotMsg] = useState('');

  const nodes = kbData.nodes as FaultNode[];

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return nodes.filter(n => {
      if (category !== '全部' && n.category !== category) return false;
      if (severityFilter && n.severity !== severityFilter) return false;
      if (q) {
        return n.fault_type.includes(q) ||
          n.symptoms.some(s => s.indicator.includes(q)) ||
          n.root_causes.some(r => r.includes(q)) ||
          n.solutions.some(s => s.action.includes(q));
      }
      return true;
    });
  }, [search, category, severityFilter]);

  const stats = useMemo(() => ({
    total: nodes.length,
    categories: new Set(nodes.map(n => n.category)).size,
    high: nodes.filter(n => n.severity === 'high' || n.severity === 'critical').length,
  }), []);

  const handleAskAI = (node: FaultNode) => {
    setCopilotMsg(`请分析故障: ${node.fault_type}。症状: ${node.symptoms.map(s => s.indicator).join('、')}。严重度: ${SEVERITY[node.severity]}。请给出诊断建议。`);
  };

  return (
    <div className="flex h-full">
      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-bold">📚 故障百科</h1>
            <p className="text-xs text-text-muted mt-1">
              共 {stats.total} 种故障 · {stats.categories} 个分类 · {stats.high} 个高危
            </p>
          </div>
        </div>

        {/* Search + Filter */}
        <div className="flex gap-3 mb-5">
          <input
            className="flex-1 bg-bg-card border border-border-subtle rounded-lg px-4 py-2 text-sm placeholder-text-muted focus:outline-none focus:border-accent-blue"
            placeholder="搜索故障名称、症状、根因、解决方案..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <select
            className="bg-bg-card border border-border-subtle rounded-lg px-3 py-2 text-sm"
            value={category}
            onChange={e => setCategory(e.target.value)}
          >
            {CATEGORIES.map(c => <option key={c} value={c}>{c === '全部' ? '全部分类' : c}</option>)}
          </select>
          <select
            className="bg-bg-card border border-border-subtle rounded-lg px-3 py-2 text-sm"
            value={severityFilter}
            onChange={e => setSeverityFilter(e.target.value)}
          >
            <option value="">全部严重度</option>
            <option value="critical">紧急</option>
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </div>

        {/* Card Grid */}
        <div className="flex-1 overflow-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map(node => (
              <button
                key={node.id}
                className="bg-bg-card border border-border-subtle rounded-xl p-5 text-left hover:border-accent-blue/50 hover:shadow-lg transition-all duration-200 group cursor-pointer"
                onClick={() => setDetail(node)}
              >
                <div className="flex items-start justify-between mb-3">
                  <span className="text-3xl">{node.icon}</span>
                  <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${SEVERITY_COLOR[node.severity]}`}>
                    {SEVERITY[node.severity]}
                  </span>
                </div>
                <h3 className="font-semibold text-sm mb-1 group-hover:text-accent-blue transition-colors">
                  {node.fault_type}
                </h3>
                <p className="text-[11px] text-text-muted mb-3">{node.category}</p>
                <div className="flex flex-wrap gap-1.5">
                  {node.symptoms.slice(0, 3).map((s, i) => (
                    <span key={i} className="px-2 py-0.5 bg-bg-deep rounded text-[10px] text-text-secondary">
                      {s.indicator} {s.threshold}
                    </span>
                  ))}
                  {node.symptoms.length > 3 && (
                    <span className="px-2 py-0.5 text-[10px] text-text-muted">+{node.symptoms.length - 3}</span>
                  )}
                </div>
                <div className="mt-3 text-[10px] text-text-muted">
                  {node.cases.length} 个历史案例 · {node.solutions.length} 个方案
                </div>
              </button>
            ))}
          </div>
          {filtered.length === 0 && (
            <div className="text-center py-16 text-text-muted text-sm">未找到匹配的故障知识</div>
          )}
        </div>
      </div>

      {/* Detail Drawer */}
      {detail && (
        <div className="w-[420px] flex-shrink-0 border-l border-border-subtle bg-bg-card overflow-auto">
          <div className="sticky top-0 bg-bg-card/95 backdrop-blur-sm border-b border-border-subtle p-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{detail.icon}</span>
              <div>
                <h2 className="font-bold text-base">{detail.fault_type}</h2>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${SEVERITY_COLOR[detail.severity]}`}>
                  {SEVERITY[detail.severity]} · {detail.category}
                </span>
              </div>
            </div>
            <button onClick={() => setDetail(null)} className="text-text-muted hover:text-text-primary text-xl leading-none">&times;</button>
          </div>

          <div className="p-5 space-y-6">
            {/* Symptoms */}
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

            {/* Root Causes */}
            <section>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">🎯 根因分析</h3>
              <ol className="space-y-1.5">
                {detail.root_causes.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm bg-bg-deep rounded-lg px-3 py-2">
                    <span className="text-text-muted font-mono text-xs">{i + 1}.</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ol>
            </section>

            {/* Solutions */}
            <section>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">🔧 解决方案</h3>
              <div className="space-y-2">
                {detail.solutions.map((s, i) => (
                  <div key={i} className="bg-bg-deep rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium">{s.action}</span>
                      <span className="text-[10px] text-text-muted">{DIFFICULTY[s.difficulty]}</span>
                    </div>
                    <span className="text-[10px] text-text-muted">⏱ 预计停机 {s.downtime_hours}h</span>
                  </div>
                ))}
              </div>
            </section>

            {/* Related Faults */}
            {detail.related_faults.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">⚠️ 关联故障</h3>
                <div className="space-y-1.5">
                  {detail.related_faults.map((rf, i) => (
                    <div key={i} className="flex justify-between text-sm bg-bg-deep rounded-lg px-3 py-2">
                      <button
                        className="text-accent-blue hover:underline text-left"
                        onClick={() => { const n = nodes.find(x => x.id === rf.id); if (n) setDetail(n); }}
                      >
                        {rf.name}
                      </button>
                      <span className="text-text-muted text-xs">{Math.round(rf.probability * 100)}% 伴生</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Case History */}
            {detail.cases.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">📖 历史案例</h3>
                {detail.cases.map((c, i) => (
                  <div key={i} className="bg-bg-deep rounded-lg p-3 mb-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium">{c.turbine}</span>
                      <span className="text-[10px] text-text-muted">{c.date}</span>
                    </div>
                    <p className="text-xs text-text-secondary mb-2">{c.summary}</p>
                    <div className="flex gap-3 text-[10px] text-text-muted">
                      <span>🔧 {c.resolution}</span>
                      <span>💴 ¥{(c.total_cost / 10000).toFixed(1)}万</span>
                      <span>⏱ {c.downtime_days}天</span>
                    </div>
                  </div>
                ))}
              </section>
            )}

            {/* Spare Parts */}
            {detail.spare_parts.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">📦 关联备件</h3>
                <div className="space-y-1.5">
                  {detail.spare_parts.map((sp, i) => (
                    <div key={i} className="flex justify-between text-sm bg-bg-deep rounded-lg px-3 py-2">
                      <span>{sp.name}</span>
                      <span className="text-text-muted text-xs">x{sp.quantity} · ¥{sp.est_cost.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Ask AI */}
            <button
              onClick={() => handleAskAI(detail)}
              className="w-full py-3 rounded-xl text-sm font-medium transition-all duration-200"
              style={{ background: 'linear-gradient(135deg, rgba(56,139,253,0.15), rgba(57,210,192,0.1))' }}
            >
              🤖 AI 诊断此故障
            </button>
          </div>
        </div>
      )}

      {/* Copilot */}
      <CopilotFAB initialMessage={copilotMsg} />
    </div>
  );
}
