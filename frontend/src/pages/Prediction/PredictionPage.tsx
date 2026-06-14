import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import { predictionService } from '../../services/predictionService';
import { useECharts, rulColor, hiColor, CHART_COLORS } from '../../hooks/useECharts';
import type { RULPrediction, CostComparison, WorkOrder, Turbine } from '../../types';
import type { PredictionSummary } from '../../services/predictionService';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

// ── Types ──
interface MaintenanceTask {
  turbine_id: number; turbine_name: string; region: string; component: string;
  rul_days: number; hi_value: number; status: string; urgency_score: number;
  priority: 'urgent' | 'high' | 'medium' | 'low'; action: string;
  downtime_hours: number; crew_size: number; parts_needed: string[];
  cost_estimate: number; active_faults: { type: string; confidence: number }[];
  existing_work_orders: { id: number; title: string; status: string }[];
  confidence_interval: [number, number];
}
interface MaintenancePlanResponse {
  plan: MaintenanceTask[]; total: number; urgent_count: number;
  high_count: number; total_cost_estimate: number;
}
interface AIAnalysisResult { analysis: string; plan: MaintenanceTask[]; total_plan_items: number; }

const FAULT_TYPES = [
  { value: 'bearing_wear', label: '轴承磨损' }, { value: 'gearbox_failure', label: '齿轮箱故障' },
  { value: 'blade_damage', label: '叶片损伤' }, { value: 'generator_failure', label: '发电机故障' },
  { value: 'pitch_system_fault', label: '变桨系统故障' }, { value: 'main_shaft_misalignment', label: '主轴不对中' },
  { value: 'cooling_system_fault', label: '冷却系统故障' }, { value: 'electrical_connection', label: '电气连接松动' },
] as const;

type SortKey = 'rul_asc' | 'rul_desc' | 'name_asc';
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'rul_asc', label: '剩余寿命 ↑' }, { key: 'rul_desc', label: '剩余寿命 ↓' }, { key: 'name_asc', label: '风机名称' },
];

function sortPredictions(list: RULPrediction[], key: SortKey): RULPrediction[] {
  const copy = [...list];
  switch (key) {
    case 'rul_asc': return copy.sort((a, b) => a.remaining_life_days - b.remaining_life_days);
    case 'rul_desc': return copy.sort((a, b) => b.remaining_life_days - a.remaining_life_days);
    case 'name_asc': return copy.sort((a, b) => a.turbine_name.localeCompare(b.turbine_name, 'zh'));
    default: return copy;
  }
}

function exportRULToCSV(predictions: RULPrediction[]) {
  const header = '风机名称,部件,剩余寿命(天),置信下限,置信上限,预测时间\n';
  const rows = predictions.map(p =>
    `${p.turbine_name},${p.component},${p.remaining_life_days.toFixed(0)},${p.confidence_lower.toFixed(0)},${p.confidence_upper.toFixed(0)},${new Date(p.predicted_at).toLocaleDateString('zh-CN')}`).join('\n');
  const blob = new Blob(['﻿' + header + rows], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `RUL预测_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

function StatCard({ label, value, sub, color = 'text-text-primary' }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-bg-card border border-border-default rounded-lg p-4 flex flex-col justify-center">
      <p className="text-[11px] text-text-muted mb-1">{label}</p>
      <p className={`text-2xl font-mono font-bold ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-text-muted mt-1">{sub}</p>}
    </div>
  );
}

function RefreshRULButton({ onDone }: { onDone: () => void }) {
  const [spinning, setSpinning] = useState(false);
  const handleRefresh = async () => {
    setSpinning(true);
    try { const r = await predictionService.refreshRUL(); alert(`RUL 已刷新: ${r.refreshed} 台风机, ${r.predictions} 条预测`); onDone(); }
    catch (e: any) { alert(e?.response?.data?.detail || '刷新失败'); }
    finally { setSpinning(false); }
  };
  return <button onClick={handleRefresh} disabled={spinning} className="px-3 py-1 border border-border-default rounded text-xs text-text-secondary hover:text-accent-blue disabled:opacity-50">{spinning ? '⏳ 刷新中...' : '🔄 刷新 RUL'}</button>;
}

// ── Calendar ──
function MaintenanceCalendar({ workOrders, rulItems }: { workOrders: WorkOrder[]; rulItems: RULPrediction[] }) {
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: Date; orders: WorkOrder[]; ruls: RULPrediction[] } | null>(null);
  const year = currentMonth.getFullYear(); const month = currentMonth.getMonth();
  const firstDay = new Date(year, month, 1).getDay(); const daysInMonth = new Date(year, month + 1, 0).getDate(); const today = new Date();

  const rulDates = useMemo(() => { const now = Date.now(); return rulItems.map(p => ({ ...p, estimatedDate: new Date(now + p.remaining_life_days * 86400000) })); }, [rulItems]);
  const dateLookup = useMemo(() => {
    const map = new Map<string, { orders: WorkOrder[]; ruls: RULPrediction[] }>();
    const dk = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    for (const wo of workOrders) { const ref = wo.due_date ? new Date(wo.due_date) : new Date(wo.created_at); const k = dk(ref); const e = map.get(k) || { orders: [], ruls: [] }; e.orders.push(wo); map.set(k, e); }
    for (const p of rulDates) { const k = dk(p.estimatedDate); const e = map.get(k) || { orders: [], ruls: [] }; e.ruls.push(p); map.set(k, e); }
    return map;
  }, [workOrders, rulDates]);

  const getEvents = useCallback((date: Date) => { const k = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`; return dateLookup.get(k) || { orders: [] as WorkOrder[], ruls: [] as RULPrediction[] }; }, [dateLookup]);

  const dayNames = ['一','二','三','四','五','六','日']; const startOffset = firstDay === 0 ? 6 : firstDay - 1;

  return (
    <div className="bg-bg-card border border-border-default rounded-lg p-4">
      <div className="flex items-center justify-between mb-3"><h3 className="text-sm font-medium">运维日历</h3>
        <div className="flex items-center gap-2 text-xs">
          <button onClick={() => setCurrentMonth(new Date(year, month - 1))} className="px-2 py-1 hover:text-accent-blue">◀</button>
          <span className="font-medium">{year}年{month + 1}月</span>
          <button onClick={() => setCurrentMonth(new Date(year, month + 1))} className="px-2 py-1 hover:text-accent-blue">▶</button>
          <button onClick={() => setCurrentMonth(new Date())} className="ml-2 px-2 py-1 border border-border-default rounded text-[10px] hover:border-accent-blue">今天</button>
        </div>
      </div>
      <div className="grid grid-cols-7 text-center text-[10px] text-text-muted mb-1">{dayNames.map(d => <div key={d} className="py-1">{d}</div>)}</div>
      <div className="grid grid-cols-7 gap-px bg-border-default rounded overflow-hidden">
        {Array.from({ length: startOffset }).map((_, i) => <div key={`e${i}`} className="bg-bg-secondary p-1.5 min-h-[60px]"/>)}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const date = new Date(year, month, i + 1); const { orders, ruls } = getEvents(date);
          const isToday = date.toDateString() === today.toDateString(); const eventCount = orders.length + ruls.length;
          const urgentCount = ruls.filter(r => r.remaining_life_days < 30).length + orders.filter(o => o.status === 'pending').length;
          return (
            <div key={i} className={`bg-bg-secondary p-1.5 min-h-[60px] cursor-pointer transition-colors hover:bg-bg-hover relative ${isToday ? 'ring-1 ring-accent-blue' : ''}`}
              onMouseEnter={e => { if (eventCount > 0) { const rect = (e.target as HTMLElement).getBoundingClientRect(); setTooltip({ x: rect.right + 8, y: rect.top, date, orders, ruls }); }}}
              onMouseLeave={() => setTooltip(null)}>
              <span className={`text-[11px] ${isToday ? 'text-accent-blue font-bold' : 'text-text-secondary'}`}>{i + 1}</span>
              {eventCount > 0 && <div className="flex gap-0.5 mt-0.5 flex-wrap">{urgentCount > 0 && <span className="w-2 h-2 rounded-full bg-accent-red"/>}{orders.length > 0 && <span className="w-2 h-2 rounded-full bg-accent-blue"/>}{ruls.filter(r => r.remaining_life_days >= 90).length > 0 && <span className="w-2 h-2 rounded-full bg-accent-green"/>}</div>}
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-2 text-[9px] text-text-muted"><span><span className="inline-block w-2 h-2 rounded-full bg-accent-red mr-1"/>紧急</span><span><span className="inline-block w-2 h-2 rounded-full bg-accent-blue mr-1"/>工单</span><span><span className="inline-block w-2 h-2 rounded-full bg-accent-green mr-1"/>计划</span></div>
      {tooltip && (
        <div className="fixed z-50 bg-bg-card border border-border-default rounded-lg shadow-xl p-3 min-w-[260px] max-w-[340px]" style={{ left: tooltip.x, top: tooltip.y, pointerEvents: 'none' }}>
          <p className="text-xs font-medium mb-1.5 border-b border-border-default pb-1">{tooltip.date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</p>
          {tooltip.orders.map(wo => <div key={`wo-${wo.id}`} className="text-[10px] mb-1.5 pb-1 border-b border-border-default last:border-0"><div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-accent-blue flex-shrink-0"/><span className="font-medium">WO-{String(wo.id).padStart(4, '0')} {wo.title}</span></div><p className="text-text-muted mt-0.5 ml-3">风机 #{wo.turbine_id} · {wo.assignee || '未指派'} · {wo.status === 'pending' ? '待处理' : wo.status}{wo.due_date && ` · ${new Date(wo.due_date).toLocaleDateString('zh-CN')}到期`}</p></div>)}
          {tooltip.ruls.filter(r => r.remaining_life_days < 30).map(r => <div key={`rul-${r.turbine_id}-${r.component}`} className="text-[10px] mb-1 pb-1 border-b border-border-default last:border-0"><div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-accent-red flex-shrink-0"/><span className="font-medium text-accent-red">{r.turbine_name} {r.component}</span></div><p className="text-text-muted mt-0.5 ml-3">RUL {r.remaining_life_days.toFixed(0)}天 · 紧急维护窗口</p></div>)}
        </div>
      )}
    </div>
  );
}

// ── Main ──
export default function PredictionPage() {
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [turbines, setTurbines] = useState<Turbine[]>([]); const [predictions, setPredictions] = useState<RULPrediction[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]); const [summary, setSummary] = useState<PredictionSummary | null>(null);
  const [maintPlan, setMaintPlan] = useState<MaintenancePlanResponse | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysisResult | null>(null); const [aiLoading, setAiLoading] = useState(false);
  const [showFullPlan, setShowFullPlan] = useState(false);

  const [costTurbineId, setCostTurbineId] = useState<number | null>(null); const [costFaultType, setCostFaultType] = useState<string>('bearing_wear');
  const [costResult, setCostResult] = useState<CostComparison | null>(null); const [costLoading, setCostLoading] = useState(false);

  const [sortKey, setSortKey] = useState<SortKey>('rul_asc'); const [chartLimit, setChartLimit] = useState(20);
  const rulChartRef = useRef<HTMLDivElement>(null); const regionChartRef = useRef<HTMLDivElement>(null);

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [rulData, woRes, turbData, sumData, planRes] = await Promise.all([
        predictionService.getRUL(), api.get('/workorders/'), predictionService.getTurbines(),
        predictionService.getSummary(), api.get('/prediction/maintenance-plan', { params: { top_n: 50 } }),
      ]);
      setPredictions(rulData); const d = woRes.data; setWorkOrders(Array.isArray(d) ? d : d.workorders || []);
      setTurbines(turbData); setSummary(sumData); setMaintPlan(planRes.data);
      if (turbData.length > 0 && !costTurbineId) setCostTurbineId(turbData[0].id);
    } catch (err: any) { setError(err?.response?.data?.detail || err?.message || '加载失败'); }
    finally { setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const sortedPredictions = useMemo(() => sortPredictions(predictions, sortKey).slice(0, chartLimit), [predictions, sortKey, chartLimit]);

  useEffect(() => {
    if (!rulChartRef.current || !sortedPredictions.length) return;
    const chart = echarts.init(rulChartRef.current, 'dark');
    chart.setOption({ backgroundColor: 'transparent', tooltip: { trigger: 'axis' }, legend: { top: 0, textStyle: { color: '#8b949e', fontSize: 11 } }, grid: { top: 35, right: 30, bottom: 40, left: 60 },
      xAxis: { type: 'category', data: sortedPredictions.map(p => `${p.turbine_name}-${p.component}`), axisLabel: { color: '#5c6975', fontSize: 9, rotate: 30 } },
      yAxis: { type: 'value', name: '剩余天数', axisLabel: { color: '#5c6975' } },
      series: [{ type: 'bar', data: sortedPredictions.map(p => ({ value: p.remaining_life_days, itemStyle: { color: rulColor(p.remaining_life_days), borderRadius: [3, 3, 0, 0] } })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#f85149', type: 'dashed', width: 1 }, data: [{ yAxis: 90, label: { formatter: '告警线', color: '#f85149', fontSize: 9 } }] } }] });
    const hr = () => chart.resize(); window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); chart.dispose(); };
  }, [sortedPredictions]);

  useEffect(() => {
    if (!regionChartRef.current || !summary?.by_region) return;
    const chart = echarts.init(regionChartRef.current, 'dark');
    const regions = Object.entries(summary.by_region);
    chart.setOption({ backgroundColor: 'transparent', tooltip: { trigger: 'axis' }, grid: { top: 20, right: 60, bottom: 30, left: 60 },
      xAxis: { type: 'category', data: regions.map(([r]) => r), axisLabel: { color: '#5c6975', fontSize: 11 } },
      yAxis: [{ type: 'value', name: '平均RUL(天)', axisLabel: { color: '#5c6975' }, splitLine: { lineStyle: { color: '#21262d' } } }, { type: 'value', name: '预测数', axisLabel: { color: '#5c6975' }, splitLine: { show: false } }],
      series: [{ name: '平均RUL', type: 'bar', data: regions.map(([, v]) => ({ value: v.avg_rul, itemStyle: { color: rulColor(v.avg_rul), borderRadius: [3, 3, 0, 0] } })) },
        { name: '预测数', type: 'line', yAxisIndex: 1, data: regions.map(([, v]) => v.count), lineStyle: { color: '#58a6ff' }, itemStyle: { color: '#58a6ff' }, symbol: 'circle', symbolSize: 6 }] });
    const hr = () => chart.resize(); window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); chart.dispose(); };
  }, [summary]);

  const handleCostCompare = async () => { if (!costTurbineId) return; setCostLoading(true); try { setCostResult(await predictionService.compareCost(costTurbineId, costFaultType)); } catch (e: any) { setCostResult(null); alert(e?.response?.data?.detail || '计算失败'); } finally { setCostLoading(false); } };
  const handleAIAnalysis = async () => { setAiLoading(true); setAiAnalysis(null); try { const { data } = await api.post('/ai/analyze-maintenance-plan'); setAiAnalysis(data); } catch (e: any) { alert(e?.response?.data?.detail || 'AI分析失败'); } finally { setAiLoading(false); } };

  const selectedTurbine = useMemo(() => turbines.find(t => t.id === costTurbineId), [turbines, costTurbineId]);
  const highRisk = useMemo(() => predictions.filter(p => p.remaining_life_days < 180).sort((a, b) => a.remaining_life_days - b.remaining_life_days), [predictions]);
  const turbineHiMap = useMemo(() => { const m = new Map<number, number>(); turbines.forEach(t => m.set(t.id, t.hi_value)); return m; }, [turbines]);

  const riskLabel = (r: CostComparison) => r.risk_level === 'high' ? '高' : r.risk_level === 'medium' ? '中' : '低';
  const riskClass = (r: CostComparison) => r.risk_level === 'high' ? 'text-accent-red bg-accent-red/10 border-accent-red/30' : r.risk_level === 'medium' ? 'text-accent-yellow bg-accent-yellow/10 border-accent-yellow/30' : 'text-accent-green bg-accent-green/10 border-accent-green/30';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto p-6 space-y-5">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">预测性维护决策</h2><RefreshRULButton onDone={loadData}/></div>

        {loading && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3 text-text-muted"><svg className="animate-spin w-8 h-8 text-accent-blue" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg><span className="text-sm">加载预测数据...</span></div></div>}
        {error && !loading && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3"><span className="text-3xl">⚠️</span><p className="text-accent-red text-sm">{error}</p><button onClick={loadData} className="px-4 py-2 border border-border-default rounded text-xs hover:text-accent-blue">重试</button></div></div>}
        {!loading && !error && predictions.length === 0 && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3 text-text-muted"><span className="text-3xl">📊</span><p className="text-sm">暂无 RUL 预测数据</p><p className="text-xs">请点击「刷新 RUL」生成预测数据</p><RefreshRULButton onDone={loadData}/></div></div>}

        {!loading && !error && summary && (
          <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
            <StatCard label="全队健康指数" value={summary.fleet.avg_hi?.toFixed(1) ?? '--'} color={summary.fleet.avg_hi && summary.fleet.avg_hi >= 80 ? 'text-accent-green' : 'text-accent-yellow'} sub={`${summary.fleet.healthy}正常·${summary.fleet.warning}预警·${summary.fleet.fault}故障`}/>
            <StatCard label="RUL 预测总数" value={summary.rul.total_predictions} sub={`平均 ${summary.rul.avg_days?.toFixed(0) ?? '--'} 天`}/>
            <StatCard label="关键风险 (<90天)" value={summary.rul.critical_count} color={summary.rul.critical_count > 0 ? 'text-accent-yellow' : 'text-accent-green'} sub={`紧急 ${summary.rul.imminent_count} 个`}/>
            <StatCard label="最短 RUL" value={`${summary.rul.min_days?.toFixed(0) ?? '--'} 天`} color={summary.rul.min_days && summary.rul.min_days < 90 ? 'text-accent-red' : 'text-text-primary'}/>
            <StatCard label="MTBF" value={`${(summary.reliability.mtbf_hours / 24).toFixed(0)} 天`} sub="平均故障间隔"/>
            <StatCard label="MTTR" value={`${summary.reliability.mttr_hours.toFixed(1)} h`} sub="平均修复时间"/>
          </div>
        )}

        {!loading && !error && predictions.length > 0 && (<>
          {/* RUL Chart + Compact Maintenance Plan */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 bg-bg-card border border-border-default rounded-lg p-4">
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2"><h3 className="text-sm font-medium">剩余寿命预测 (RUL)</h3>
                <div className="flex items-center gap-2">
                  {SORT_OPTIONS.map(opt => <button key={opt.key} onClick={() => setSortKey(opt.key)} className={`px-2 py-1 rounded border text-[10px] transition-colors ${sortKey === opt.key ? 'border-accent-blue text-accent-blue bg-accent-blue/10' : 'border-border-default text-text-muted hover:text-text-secondary'}`}>{opt.label}</button>)}
                  <select value={chartLimit} onChange={e => setChartLimit(Number(e.target.value))} className="bg-bg-secondary border border-border-default rounded px-2 py-1 text-[10px] text-text-secondary focus:outline-none focus:border-accent-blue"><option value={10}>10条</option><option value={20}>20条</option><option value={40}>40条</option><option value={100}>全部</option></select>
                  <button onClick={() => exportRULToCSV(predictions)} className="px-3 py-1 border border-border-default rounded text-xs text-text-secondary hover:text-accent-blue">⬇ CSV</button>
                </div>
              </div>
              <div ref={rulChartRef} style={{ height: 300 }}/>
              {/* Regional summary below RUL chart */}
              {summary?.by_region && <div className="mt-2 flex gap-3 text-[10px] text-text-muted border-t border-border-default pt-2">{Object.entries(summary.by_region).map(([r, v]) => <span key={r}>{r} <span className="font-mono text-text-primary">{v.avg_rul.toFixed(0)}天</span> ({v.count}项)</span>)}</div>}
            </div>

            {/* Compact Maintenance Plan — top 8, minimal columns */}
            {maintPlan && maintPlan.plan.length > 0 && (
              <div className="bg-bg-card border border-border-default rounded-lg p-3 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-medium">🔧 维修计划</h3>
                  <span className="text-[9px] text-text-muted">{maintPlan.total}项 · <span className="text-accent-red">{maintPlan.urgent_count}急</span> <span className="text-accent-yellow">{maintPlan.high_count}高</span></span>
                </div>
                <div className="flex-1 overflow-auto text-[10px]">
                  <table className="w-full">
                    <thead><tr className="text-text-muted border-b border-border-default"><th className="text-left py-1">风机</th><th className="text-left py-1">部件</th><th className="text-right py-1">RUL</th><th className="text-right py-1">紧急度</th><th className="text-left py-1">措施</th></tr></thead>
                    <tbody>
                      {maintPlan.plan.slice(0, 8).map((t, i) => (
                        <tr key={`${t.turbine_id}-${t.component}`} className={`border-b border-border-default hover:bg-bg-hover ${t.priority === 'urgent' ? 'bg-accent-red/5' : t.priority === 'high' ? 'bg-accent-yellow/5' : ''}`}>
                          <td className="py-1">{t.turbine_name}<span className="text-[8px] text-text-muted ml-0.5">{t.region}</span></td>
                          <td className="py-1">{t.component}</td>
                          <td className="py-1 text-right"><span className="font-mono" style={{ color: rulColor(t.rul_days) }}>{t.rul_days.toFixed(0)}天</span></td>
                          <td className="py-1 text-right"><div className="flex items-center justify-end gap-1"><div className="w-6 h-1 bg-bg-hover rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${t.urgency_score}%`, backgroundColor: t.urgency_score >= 70 ? '#f85149' : t.urgency_score >= 45 ? '#d29922' : '#58a6ff' }}/></div><span className="font-mono text-[9px]">{t.urgency_score.toFixed(0)}</span></div></td>
                          <td className="py-1"><span className={`px-1 py-0.5 rounded text-[8px] ${t.priority === 'urgent' ? 'bg-accent-red/20 text-accent-red' : t.priority === 'high' ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-blue/20 text-accent-blue'}`}>{t.action.length > 6 ? t.action.slice(0, 5) + '…' : t.action}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-2 pt-2 border-t border-border-default flex items-center justify-between gap-2">
                  <span className="text-[9px] text-text-muted">预估 ¥{maintPlan.total_cost_estimate.toLocaleString()}</span>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setShowFullPlan(!showFullPlan)} className="px-2 py-0.5 border border-border-default rounded text-[9px] text-text-muted hover:text-accent-blue">{showFullPlan ? '收起完整' : `全部 ${maintPlan.total} 项`}</button>
                    <button onClick={handleAIAnalysis} disabled={aiLoading} className="px-2 py-0.5 bg-accent-purple/20 border border-accent-purple/40 rounded text-[9px] text-accent-purple hover:bg-accent-purple/30 disabled:opacity-50">{aiLoading ? '🤖...' : '🤖AI分析'}</button>
                  </div>
                </div>
                {aiAnalysis && (
                  <div className="mt-2 p-2 bg-accent-purple/5 border border-accent-purple/20 rounded text-[10px] text-text-secondary max-h-[200px] overflow-auto relative">
                    <button onClick={() => setAiAnalysis(null)} className="absolute top-1 right-1 w-4 h-4 flex items-center justify-center rounded text-[10px] text-text-muted hover:text-accent-red hover:bg-accent-red/10">✕</button>
                    <span className="text-accent-purple font-medium text-xs">🤖 AI 运维分析：</span>
                    <p className="mt-1 whitespace-pre-line leading-relaxed mr-4">{aiAnalysis.analysis}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Calendar + High Risk */}
          <div className="grid grid-cols-2 gap-4">
            <MaintenanceCalendar workOrders={workOrders} rulItems={predictions}/>
            <div className="bg-bg-card border border-border-default rounded-lg p-4"><h3 className="text-sm font-medium mb-3">高风险部件列表</h3>
              <div className="overflow-auto max-h-[280px]">{highRisk.length === 0 ? <p className="text-xs text-text-muted py-8 text-center">暂无高风险部件 ✅</p> : <table className="w-full text-xs"><thead><tr className="text-text-muted border-b border-border-default"><th className="text-left py-2">风机</th><th className="text-left py-2">部件</th><th className="text-right py-2">HI</th><th className="text-right py-2">RUL</th><th className="text-right py-2">置信区间</th><th className="text-right py-2">风险</th></tr></thead>
                <tbody>{highRisk.slice(0, 12).map((p, i) => { const hi = turbineHiMap.get(p.turbine_id); return <tr key={i} className="border-b border-border-default hover:bg-bg-hover"><td className="py-2">{p.turbine_name}</td><td className="py-2">{p.component}</td><td className="py-2 text-right"><span className="font-mono" style={{ color: hi ? hiColor(hi) : undefined }}>{hi?.toFixed(0) ?? '--'}</span></td><td className="py-2 text-right font-mono">{p.remaining_life_days.toFixed(0)} 天</td><td className="py-2 text-right font-mono text-text-muted">{p.confidence_lower.toFixed(0)}–{p.confidence_upper.toFixed(0)}</td><td className="py-2 text-right"><span className={`px-1.5 py-0.5 rounded text-[10px] ${p.remaining_life_days < 30 ? 'bg-accent-red/20 text-accent-red' : p.remaining_life_days < 90 ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-blue/20 text-accent-blue'}`}>{p.remaining_life_days < 30 ? '紧急' : p.remaining_life_days < 90 ? '近期' : '计划'}</span></td></tr>; })}</tbody></table>}
              </div>
            </div>
          </div>

          {/* Cost Comparison */}
          <div className="bg-bg-card border border-border-default rounded-lg p-4"><h3 className="text-sm font-medium mb-3">维护成本对比</h3>
            <div className="flex gap-3 mb-4 flex-wrap">
              <select value={costTurbineId ?? ''} onChange={e => setCostTurbineId(e.target.value ? Number(e.target.value) : null)} className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue min-w-[200px]"><option value="" disabled>选择风机</option>{turbines.map(t => <option key={t.id} value={t.id}>{t.name} — {t.model || '未知型号'} ({t.region})</option>)}</select>
              <select value={costFaultType} onChange={e => setCostFaultType(e.target.value)} className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue">{FAULT_TYPES.map(ft => <option key={ft.value} value={ft.value}>{ft.label}</option>)}</select>
              <button onClick={handleCostCompare} disabled={!costTurbineId || costLoading} className="px-4 py-2 bg-accent-blue text-white rounded text-sm hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed">{costLoading ? '计算中...' : '计算对比'}</button>
            </div>
            {selectedTurbine && <p className="text-[11px] text-text-muted -mt-2 mb-3">当前: {selectedTurbine.name} · {selectedTurbine.power_mw}MW · HI {selectedTurbine.hi_value}</p>}
            {costResult && <div>
              <div className="grid grid-cols-3 lg:grid-cols-6 gap-4">
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">立即检修</p><p className="text-xl font-mono font-bold text-accent-red">¥{costResult.immediate_repair_cost.toLocaleString()}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">延迟检修</p><p className="text-xl font-mono font-bold text-accent-yellow">¥{costResult.delayed_repair_cost.toLocaleString()}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">每日停机损失</p><p className="text-xl font-mono font-bold text-text-primary">¥{costResult.downtime_loss_per_day.toLocaleString()}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">故障概率</p><p className="text-xl font-mono font-bold text-text-primary">{(costResult.failure_probability * 100).toFixed(1)}%</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">风险等级</p><p className={`inline-flex items-center justify-center min-w-12 rounded border px-2 py-1 text-lg font-bold ${riskClass(costResult)}`}>{riskLabel(costResult)}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">预计节省</p><p className={`text-xl font-mono font-bold ${costResult.estimated_saving >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>¥{costResult.estimated_saving.toLocaleString()}</p></div>
              </div>
              <p className="mt-3 p-3 bg-accent-green/10 border border-accent-green/30 rounded text-xs text-accent-green">{costResult.recommendation}</p>
              <div className="mt-3 grid grid-cols-2 lg:grid-cols-5 gap-2">{costResult.cost_drivers.map(d => <div key={d} className="rounded border border-border-default bg-bg-secondary px-3 py-2 text-xs text-text-secondary">{d}</div>)}</div>
            </div>}
          </div>

        </>)}
      </div>
      <CopilotFAB />

      {/* Full Maintenance Plan Modal */}
      {showFullPlan && maintPlan && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60" onClick={() => setShowFullPlan(false)}>
          <div className="bg-bg-card border border-border-default rounded-xl shadow-2xl w-[90vw] max-w-5xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border-default flex-shrink-0">
              <div className="flex items-center gap-3">
                <h2 className="text-base font-semibold">🔧 完整维修计划</h2>
                <span className="text-xs text-text-muted">{maintPlan.total}项 · 紧急 {maintPlan.urgent_count} · 高优先 {maintPlan.high_count} · 总预估 ¥{maintPlan.total_cost_estimate.toLocaleString()}</span>
              </div>
              <button onClick={() => { setShowFullPlan(false); setAiAnalysis(null); }} className="w-7 h-7 flex items-center justify-center rounded hover:bg-bg-hover text-text-muted hover:text-accent-red text-lg">✕</button>
            </div>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted border-b border-border-default sticky top-0 bg-bg-card z-10"><th className="text-left py-2 w-8 pl-4">#</th><th className="text-left py-2">风机</th><th className="text-left py-2">部件</th><th className="text-right py-2">RUL</th><th className="text-right py-2">HI</th><th className="text-right py-2">紧急度</th><th className="text-left py-2">建议措施</th><th className="text-right py-2">停机</th><th className="text-right py-2">费用</th><th className="text-left py-2 pr-4">备件</th></tr></thead>
                <tbody>{maintPlan.plan.slice(0, 100).map((t, i) =>
                  <tr key={`modal-${t.turbine_id}-${t.component}`} className={`border-b border-border-default hover:bg-bg-hover ${t.priority === 'urgent' ? 'bg-accent-red/5' : t.priority === 'high' ? 'bg-accent-yellow/5' : ''}`}>
                    <td className="py-1.5 text-text-muted pl-4">{i + 1}</td>
                    <td className="py-1.5">{t.turbine_name}<span className="text-[9px] text-text-muted ml-1">{t.region}</span></td>
                    <td className="py-1.5">{t.component}</td>
                    <td className="py-1.5 text-right"><span className="font-mono" style={{ color: rulColor(t.rul_days) }}>{t.rul_days.toFixed(0)}天</span></td>
                    <td className="py-1.5 text-right"><span className="font-mono" style={{ color: hiColor(t.hi_value) }}>{t.hi_value.toFixed(0)}</span></td>
                    <td className="py-1.5 text-right"><div className="flex items-center justify-end gap-1.5"><div className="w-10 h-1.5 bg-bg-hover rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${t.urgency_score}%`, backgroundColor: t.urgency_score >= 70 ? '#f85149' : t.urgency_score >= 45 ? '#d29922' : '#58a6ff' }}/></div><span className="font-mono text-[10px]">{t.urgency_score.toFixed(0)}</span></div></td>
                    <td className="py-1.5"><span className={`px-1.5 py-0.5 rounded text-[10px] ${t.priority === 'urgent' ? 'bg-accent-red/20 text-accent-red' : t.priority === 'high' ? 'bg-accent-yellow/20 text-accent-yellow' : t.priority === 'medium' ? 'bg-accent-blue/20 text-accent-blue' : 'bg-accent-green/20 text-accent-green'}`}>{t.action}</span></td>
                    <td className="py-1.5 text-right font-mono text-text-muted">{t.downtime_hours}h</td>
                    <td className="py-1.5 text-right font-mono">¥{t.cost_estimate.toLocaleString()}</td>
                    <td className="py-1.5 pr-4"><div className="flex flex-wrap gap-0.5">{t.parts_needed.slice(0, 2).map(p => <span key={p} className="px-1 py-0.5 bg-bg-hover rounded text-[9px] text-text-muted">{p}</span>)}</div></td>
                  </tr>
                )}</tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
