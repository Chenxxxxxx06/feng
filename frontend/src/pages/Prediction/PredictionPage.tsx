import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import { predictionService } from '../../services/predictionService';
import { useECharts, rulColor, hiColor, CHART_COLORS } from '../../hooks/useECharts';
import type { RULPrediction, CostComparison, WorkOrder, Turbine } from '../../types';
import type { PredictionSummary } from '../../services/predictionService';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import MaintenanceCalendar from './MaintenanceCalendar';

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
    <div className="premium-card rounded-2xl p-4 flex flex-col justify-center">
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
  return <button onClick={handleRefresh} disabled={spinning} className="ops-btn px-3 py-1 text-xs disabled:opacity-50">{spinning ? '刷新中...' : '刷新 RUL'}</button>;
}

// ── Calendar ──
// ── Main ──
export default function PredictionPage() {
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [turbines, setTurbines] = useState<Turbine[]>([]); const [predictions, setPredictions] = useState<RULPrediction[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]); const [summary, setSummary] = useState<PredictionSummary | null>(null);
  const [maintPlan, setMaintPlan] = useState<MaintenancePlanResponse | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysisResult | null>(null); const [aiLoading, setAiLoading] = useState(false);
  const [showFullPlan, setShowFullPlan] = useState(false);
  const [scheduledTasks, setScheduledTasks] = useState<any[]>([]);
  const [overflowTasks, setOverflowTasks] = useState<any[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [scheduling, setScheduling] = useState(false);
  const [schedulePreview, setSchedulePreview] = useState<any[] | null>(null); // null = no preview, array = show modal

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
    chart.setOption({ backgroundColor: 'transparent', tooltip: { trigger: 'axis' }, legend: { top: 0, textStyle: { color: '#94A3B8', fontSize: 11 } }, grid: { top: 35, right: 30, bottom: 40, left: 60 },
      xAxis: { type: 'category', data: sortedPredictions.map(p => `${p.turbine_name}-${p.component}`), axisLabel: { color: '#64748B', fontSize: 9, rotate: 30 } },
      yAxis: { type: 'value', name: '剩余天数', axisLabel: { color: '#64748B' } },
      series: [{ type: 'bar', data: sortedPredictions.map(p => ({ value: p.remaining_life_days, itemStyle: { color: rulColor(p.remaining_life_days), borderRadius: [3, 3, 0, 0] } })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#EF4444', type: 'dashed', width: 1 }, data: [{ yAxis: 90, label: { formatter: '告警线', color: '#EF4444', fontSize: 9 } }] } }] });
    const hr = () => chart.resize(); window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); chart.dispose(); };
  }, [sortedPredictions]);

  useEffect(() => {
    if (!regionChartRef.current || !summary?.by_region) return;
    const chart = echarts.init(regionChartRef.current, 'dark');
    const regions = Object.entries(summary.by_region);
    chart.setOption({ backgroundColor: 'transparent', tooltip: { trigger: 'axis' }, grid: { top: 20, right: 60, bottom: 30, left: 60 },
      xAxis: { type: 'category', data: regions.map(([r]) => r), axisLabel: { color: '#64748B', fontSize: 11 } },
      yAxis: [{ type: 'value', name: '平均RUL(天)', axisLabel: { color: '#64748B' }, splitLine: { lineStyle: { color: '#0D2447' } } }, { type: 'value', name: '预测数', axisLabel: { color: '#64748B' }, splitLine: { show: false } }],
      series: [{ name: '平均RUL', type: 'bar', data: regions.map(([, v]) => ({ value: v.avg_rul, itemStyle: { color: rulColor(v.avg_rul), borderRadius: [3, 3, 0, 0] } })) },
        { name: '预测数', type: 'line', yAxisIndex: 1, data: regions.map(([, v]) => v.count), lineStyle: { color: '#3B82F6' }, itemStyle: { color: '#3B82F6' }, symbol: 'circle', symbolSize: 6 }] });
    const hr = () => chart.resize(); window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); chart.dispose(); };
  }, [summary]);

  // ── Schedule handlers ──
  const handleAutoSchedule = async () => {
    setScheduling(true);
    try {
      const { data } = await api.post('/prediction/schedule', {}, { params: { top_n: 30 } });
      if (!data.scheduled || data.scheduled.length === 0) {
        alert('排程结果为空，请先刷新 RUL 预测数据');
        return;
      }
      setSchedulePreview(data.scheduled || []); // show preview, don't apply yet
      setOverflowTasks(data.overflow || []);
      setConflicts(data.conflicts || []);
    } catch (e: any) { alert(e?.response?.data?.detail || '排程失败'); }
    finally { setScheduling(false); }
  };
  const confirmSchedule = (selected: any[]) => {
    setScheduledTasks(selected);
    setSchedulePreview(null);
  };
  const handleScheduleItem = (task: any, date: Date) => {
    const dated = { ...task, scheduled_date: date.toISOString().slice(0, 10), time_slot: '08:00-12:00' };
    setScheduledTasks(prev => [...prev.filter(t => !(t.turbine_id === task.turbine_id && t.component === task.component)), dated]);
  };

  const handleCostCompare = async () => { if (!costTurbineId) return; setCostLoading(true); try { setCostResult(await predictionService.compareCost(costTurbineId, costFaultType)); } catch (e: any) { setCostResult(null); alert(e?.response?.data?.detail || '计算失败'); } finally { setCostLoading(false); } };
  const handleAIAnalysis = async () => { setAiLoading(true); setAiAnalysis(null); try { const { data } = await api.post('/ai/analyze-maintenance-plan'); setAiAnalysis(data); } catch (e: any) { alert(e?.response?.data?.detail || 'AI分析失败'); } finally { setAiLoading(false); } };

  const selectedTurbine = useMemo(() => turbines.find(t => t.id === costTurbineId), [turbines, costTurbineId]);
  const highRisk = useMemo(() => predictions.filter(p => p.remaining_life_days < 180).sort((a, b) => a.remaining_life_days - b.remaining_life_days), [predictions]);
  const turbineHiMap = useMemo(() => { const m = new Map<number, number>(); turbines.forEach(t => m.set(t.id, t.hi_value)); return m; }, [turbines]);

  const riskLabel = (r: CostComparison) => r.risk_level === 'high' ? '高' : r.risk_level === 'medium' ? '中' : '低';
  const riskClass = (r: CostComparison) => r.risk_level === 'high' ? 'text-accent-red bg-accent-red/10 border-accent-red/30' : r.risk_level === 'medium' ? 'text-accent-yellow bg-accent-yellow/10 border-accent-yellow/30' : 'text-accent-green bg-accent-green/10 border-accent-green/30';

  return (
    <div className="h-full flex flex-col overflow-hidden ops-page">
      <div className="flex-1 overflow-auto p-6 space-y-5">
        <div className="ops-header flex items-center justify-between">
          <div>
            <p className="ops-eyebrow">预测决策与维护排程</p>
            <h2 className="ops-title gradient-text">预测性维护决策</h2>
            <p className="ops-subtitle">汇总剩余寿命、维修计划、成本对比和排程结果，帮助优先处理高风险任务。</p>
          </div>
          <RefreshRULButton onDone={loadData}/>
        </div>

        {loading && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3 text-text-muted"><svg className="animate-spin w-8 h-8 text-accent-blue" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg><span className="text-sm">加载预测数据...</span></div></div>}
        {error && !loading && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3"><span className="ops-status-dot text-accent-red" /><p className="text-accent-red text-sm">{error}</p><button onClick={loadData} className="ops-btn px-4 py-2 text-xs">重试</button></div></div>}
        {!loading && !error && predictions.length === 0 && <div className="flex items-center justify-center py-20"><div className="flex flex-col items-center gap-3 text-text-muted"><span className="ops-status-dot text-accent-blue" /><p className="text-sm">暂无 RUL 预测数据</p><p className="text-xs">请点击「刷新 RUL」生成预测数据</p><RefreshRULButton onDone={loadData}/></div></div>}

        {!loading && !error && summary && (
          <div className="grid grid-cols-3 lg:grid-cols-5 gap-3">
            <StatCard label="全队健康指数" value={summary.fleet.avg_hi?.toFixed(1) ?? '--'} color={summary.fleet.avg_hi && summary.fleet.avg_hi >= 80 ? 'text-accent-green' : 'text-accent-yellow'} sub={`${summary.fleet.healthy}正常·${summary.fleet.warning}预警·${summary.fleet.fault}故障`}/>
            <StatCard label="RUL 预测总数" value={summary.rul.total_predictions} sub={`平均 ${summary.rul.avg_days?.toFixed(0) ?? '--'} 天`}/>
            <StatCard label="关键风险 (<90天)" value={summary.rul.critical_count} color={summary.rul.critical_count > 0 ? 'text-accent-yellow' : 'text-accent-green'} sub={`紧急 ${summary.rul.imminent_count} 个`}/>
            <StatCard label="最短 RUL" value={`${summary.rul.min_days?.toFixed(0) ?? '--'} 天`} color={summary.rul.min_days && summary.rul.min_days < 90 ? 'text-accent-red' : 'text-text-primary'}/>
            <StatCard label="MTBF" value={`${(summary.reliability.mtbf_hours / 24).toFixed(0)} 天`} sub="平均故障间隔"/>
          </div>
        )}

        {!loading && !error && predictions.length > 0 && (<>
          {/* RUL Chart + Compact Maintenance Plan */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 ops-panel p-4">
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2"><h3 className="text-sm font-medium">剩余寿命预测 (RUL)</h3>
                <div className="flex items-center gap-2">
                  {SORT_OPTIONS.map(opt => <button key={opt.key} onClick={() => setSortKey(opt.key)} className={`ops-btn px-2 py-1 text-[10px] ${sortKey === opt.key ? 'ops-btn-primary' : ''}`}>{opt.label}</button>)}
                  <select value={chartLimit} onChange={e => setChartLimit(Number(e.target.value))} className="px-2 py-1 text-[10px] text-text-secondary"><option value={10}>10条</option><option value={20}>20条</option><option value={40}>40条</option><option value={100}>全部</option></select>
                  <button onClick={() => exportRULToCSV(predictions)} className="ops-btn px-3 py-1 text-xs">导出 CSV</button>
                </div>
              </div>
              <div ref={rulChartRef} style={{ height: 300 }}/>
              {/* Regional summary below RUL chart */}
              {summary?.by_region && <div className="mt-2 flex gap-3 text-[10px] text-text-muted border-t border-border-default pt-2">{Object.entries(summary.by_region).map(([r, v]) => <span key={r}>{r} <span className="font-mono text-text-primary">{v.avg_rul.toFixed(0)}天</span> ({v.count}项)</span>)}</div>}
            </div>

            {/* Compact Maintenance Plan — top 8, minimal columns */}
            {maintPlan && maintPlan.plan.length > 0 && (
              <div className="ops-panel p-3 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-medium">维修计划</h3>
                  <span className="text-[9px] text-text-muted">{maintPlan.total}项 · <span className="text-accent-red">{maintPlan.urgent_count}急</span> <span className="text-accent-yellow">{maintPlan.high_count}高</span></span>
                </div>
                <div className="flex-1 overflow-auto text-[10px]">
                  <table className="w-full">
                    <thead><tr className="text-text-muted border-b border-border-default"><th className="text-left py-1">风机</th><th className="text-left py-1">部件</th><th className="text-right py-1">RUL</th><th className="text-right py-1">紧急度</th><th className="text-left py-1">措施</th></tr></thead>
                    <tbody>
                      {maintPlan.plan.slice(0, 8).map((t, i) => (
                        <tr key={`${t.turbine_id}-${t.component}`} onClick={() => handleScheduleItem(t, new Date())}
                          className={`border-b border-border-default hover:bg-bg-hover cursor-pointer ${t.priority === 'urgent' ? 'bg-accent-red/5' : t.priority === 'high' ? 'bg-accent-yellow/5' : ''}`}
                          title="点击排入今天">
                          <td className="py-1">{t.turbine_name}<span className="text-[8px] text-text-muted ml-0.5">{t.region}</span></td>
                          <td className="py-1">{t.component}</td>
                          <td className="py-1 text-right"><span className="font-mono" style={{ color: rulColor(t.rul_days) }}>{t.rul_days.toFixed(0)}天</span></td>
                          <td className="py-1 text-right"><div className="flex items-center justify-end gap-1"><div className="w-6 h-1 bg-bg-hover rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${t.urgency_score}%`, backgroundColor: t.urgency_score >= 70 ? '#EF4444' : t.urgency_score >= 45 ? '#F59E0B' : '#3B82F6' }}/></div><span className="font-mono text-[9px]">{t.urgency_score.toFixed(0)}</span></div></td>
                          <td className="py-1"><span className={`px-1 py-0.5 rounded text-[8px] ${t.priority === 'urgent' ? 'bg-accent-red/20 text-accent-red' : t.priority === 'high' ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-blue/20 text-accent-blue'}`}>{t.action.length > 6 ? t.action.slice(0, 5) + '…' : t.action}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-2 pt-2 border-t border-border-default flex items-center justify-between gap-2">
                  <span className="text-[9px] text-text-muted">预估 ¥{maintPlan.total_cost_estimate.toLocaleString()}</span>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setShowFullPlan(!showFullPlan)} className="ops-btn px-2 py-0.5 text-[9px]">{showFullPlan ? '收起完整' : `全部 ${maintPlan.total} 项`}</button>
                    <button onClick={handleAIAnalysis} disabled={aiLoading} className="rounded border border-accent-purple/40 bg-accent-purple/15 px-2 py-0.5 text-[9px] font-semibold text-accent-purple hover:bg-accent-purple/25 disabled:opacity-50">AI 分析</button>
                  </div>
                </div>
                {aiAnalysis && (
                  <div className="mt-2 rounded border border-accent-purple/20 bg-accent-purple/5 p-2 text-[10px] text-text-secondary max-h-[200px] overflow-auto relative">
                    <button onClick={() => setAiAnalysis(null)} className="absolute top-1 right-1 h-4 w-4 flex items-center justify-center rounded text-[10px] text-text-muted hover:text-accent-red hover:bg-accent-red/10">×</button>
                    <span className="text-accent-purple font-medium text-xs">AI 运维分析：</span>
                    <p className="mt-1 whitespace-pre-line leading-relaxed mr-4">{aiAnalysis.analysis}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Calendar + High Risk */}
          <div className="grid grid-cols-2 gap-4">
            <MaintenanceCalendar workOrders={workOrders} rulItems={predictions} turbines={turbines}
              scheduledTasks={scheduledTasks} conflicts={conflicts}
              onAutoSchedule={handleAutoSchedule} onScheduleItem={handleScheduleItem} scheduling={scheduling}/>
            <div className="ops-panel p-4"><h3 className="text-sm font-medium mb-3">高风险部件列表</h3>
              <div className="overflow-auto max-h-[280px]">{highRisk.length === 0 ? <p className="text-xs text-text-muted py-8 text-center">暂无高风险部件</p> : <table className="w-full text-xs"><thead><tr className="text-text-muted border-b border-border-default"><th className="text-left py-2">风机</th><th className="text-left py-2">部件</th><th className="text-right py-2">HI</th><th className="text-right py-2">RUL</th><th className="text-right py-2">置信区间</th><th className="text-right py-2">风险</th></tr></thead>
                <tbody>{highRisk.slice(0, 12).map((p, i) => { const hi = turbineHiMap.get(p.turbine_id); return <tr key={i} className="border-b border-border-default hover:bg-bg-hover"><td className="py-2">{p.turbine_name}</td><td className="py-2">{p.component}</td><td className="py-2 text-right"><span className="font-mono" style={{ color: hi ? hiColor(hi) : undefined }}>{hi?.toFixed(0) ?? '--'}</span></td><td className="py-2 text-right font-mono">{p.remaining_life_days.toFixed(0)} 天</td><td className="py-2 text-right font-mono text-text-muted">{p.confidence_lower.toFixed(0)}–{p.confidence_upper.toFixed(0)}</td><td className="py-2 text-right"><span className={`px-1.5 py-0.5 rounded text-[10px] ${p.remaining_life_days < 30 ? 'bg-accent-red/20 text-accent-red' : p.remaining_life_days < 90 ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-blue/20 text-accent-blue'}`}>{p.remaining_life_days < 30 ? '紧急' : p.remaining_life_days < 90 ? '近期' : '计划'}</span></td></tr>; })}</tbody></table>}
              </div>
            </div>
          </div>

          {/* Cost Comparison */}
          <div className="ops-panel p-4"><h3 className="text-sm font-medium mb-3">维护成本对比</h3>
            <div className="flex gap-3 mb-4 flex-wrap">
              <select value={costTurbineId ?? ''} onChange={e => setCostTurbineId(e.target.value ? Number(e.target.value) : null)} className="min-w-[200px] px-3 py-2 text-sm text-text-primary"><option value="" disabled>选择风机</option>{turbines.map(t => <option key={t.id} value={t.id}>{t.name} — {t.model || '未知型号'} ({t.region})</option>)}</select>
              <select value={costFaultType} onChange={e => setCostFaultType(e.target.value)} className="px-3 py-2 text-sm text-text-primary">{FAULT_TYPES.map(ft => <option key={ft.value} value={ft.value}>{ft.label}</option>)}</select>
              <button onClick={handleCostCompare} disabled={!costTurbineId || costLoading} className="ops-btn ops-btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">{costLoading ? '计算中...' : '计算对比'}</button>
            </div>
            {selectedTurbine && <p className="text-[11px] text-text-muted -mt-2 mb-3">当前: {selectedTurbine.name} · {selectedTurbine.power_mw}MW · HI {selectedTurbine.hi_value}</p>}
            {costResult && <div>
              <div className="grid grid-cols-3 lg:grid-cols-6 gap-4">
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">立即检修</p><p className="text-xl font-mono font-bold text-accent-red">¥{costResult.immediate_repair_cost.toLocaleString()}</p></div>
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">延迟检修</p><p className="text-xl font-mono font-bold text-accent-yellow">¥{costResult.delayed_repair_cost.toLocaleString()}</p></div>
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">每日停机损失</p><p className="text-xl font-mono font-bold text-text-primary">¥{costResult.downtime_loss_per_day.toLocaleString()}</p></div>
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">故障概率</p><p className="text-xl font-mono font-bold text-text-primary">{(costResult.failure_probability * 100).toFixed(1)}%</p></div>
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">风险等级</p><p className={`inline-flex items-center justify-center min-w-12 rounded border px-2 py-1 text-lg font-bold ${riskClass(costResult)}`}>{riskLabel(costResult)}</p></div>
                <div className="ops-panel rounded-2xl p-3 text-center"><p className="text-xs text-text-muted mb-1">预计节省</p><p className={`text-xl font-mono font-bold ${costResult.estimated_saving >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>¥{costResult.estimated_saving.toLocaleString()}</p></div>
              </div>
              <p className="mt-3 p-3 bg-accent-green/10 border border-accent-green/30 rounded text-xs text-accent-green">{costResult.recommendation}</p>
              <div className="mt-3 grid grid-cols-2 lg:grid-cols-5 gap-2">{costResult.cost_drivers.map(d => <div key={d} className="form-input px-3 py-2 text-xs text-text-secondary">{d}</div>)}</div>
            </div>}
          </div>

        </>)}
      </div>
      <CopilotFAB />

      {/* Schedule Preview Modal */}
      {schedulePreview !== null && (
        <SchedulePreviewModal
          items={schedulePreview}
          conflicts={conflicts}
          overflow={overflowTasks}
          onConfirm={confirmSchedule}
          onCancel={() => setSchedulePreview(null)}
        />
      )}

      {/* Full Maintenance Plan Modal */}
      {showFullPlan && maintPlan && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60" onClick={() => setShowFullPlan(false)}>
          <div className="premium-card rounded-2xl shadow-2xl w-[90vw] max-w-5xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border-default flex-shrink-0">
              <div className="flex items-center gap-3">
                <h2 className="text-base font-semibold">完整维修计划</h2>
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
                    <td className="py-1.5 text-right"><div className="flex items-center justify-end gap-1.5"><div className="w-10 h-1.5 bg-bg-hover rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${t.urgency_score}%`, backgroundColor: t.urgency_score >= 70 ? '#EF4444' : t.urgency_score >= 45 ? '#F59E0B' : '#3B82F6' }}/></div><span className="font-mono text-[10px]">{t.urgency_score.toFixed(0)}</span></div></td>
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

// ── Schedule Preview Modal ──
function SchedulePreviewModal({ items, conflicts, overflow, onConfirm, onCancel }: {
  items: any[]; conflicts: any[]; overflow: any[]; onConfirm: (selected: any[]) => void; onCancel: () => void;
}) {
  const [checked, setChecked] = useState<boolean[]>(() => items.map(() => true));

  const toggle = (i: number) => { const n = [...checked]; n[i] = !n[i]; setChecked(n); };
  const toggleAll = () => { const allOn = checked.every(Boolean); setChecked(items.map(() => !allOn)); };
  const count = checked.filter(Boolean).length;

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div className="premium-card rounded-2xl shadow-2xl w-[95vw] max-w-5xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-default flex-shrink-0">
          <div><h2 className="text-base font-semibold">排程预览</h2><p className="text-[10px] text-text-muted mt-0.5">已选 {count}/{items.length} 项 · 溢出 {overflow.length}</p></div>
          <div className="flex items-center gap-2">
            <button onClick={toggleAll} className="ops-btn px-3 py-1 text-xs">{count === items.length ? '取消全选' : '全选'}</button>
            <button onClick={onCancel} className="ops-btn px-3 py-1 text-xs">取消</button>
            <button onClick={() => onConfirm(items.filter((_, i) => checked[i]))} disabled={count === 0} className="ops-btn ops-btn-primary px-4 py-1.5 text-xs disabled:opacity-50">确认排程 ({count}项)</button>
          </div>
        </div>
        {overflow.length > 0 && <div className="mx-4 my-2 p-2 bg-accent-red/5 border border-accent-red/20 rounded text-[9px] text-accent-red">{overflow.length} 项无法安排：{overflow.slice(0, 5).map((t: any) => `${t.turbine_name} ${t.component}`).join('、')}{overflow.length > 5 ? '等' : ''}</div>}
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 z-10 bg-bg-card/95 backdrop-blur">
            <tr className="text-text-muted border-b border-border-default">
              <th className="text-left py-2 pl-4 w-10"><input type="checkbox" checked={count === items.length && items.length > 0} onChange={toggleAll} className="w-3 h-3"/></th>
              <th className="text-left py-2">日期</th><th className="text-left py-2">风机</th><th className="text-left py-2">部件</th><th className="text-right py-2">RUL</th><th className="text-right py-2">工时</th><th className="text-left py-2">措施</th><th className="text-right py-2 pr-4">费用</th>
            </tr></thead>
            <tbody>{items.map((t, i) => (
              <tr key={i} className={`border-b border-border-default ${checked[i] ? '' : 'opacity-30'}`}>
                <td className="py-1.5 pl-4"><input type="checkbox" checked={checked[i]} onChange={() => toggle(i)} className="w-3 h-3"/></td>
                <td className="py-1 font-mono text-[9px]">{t.scheduled_date}</td>
                <td className="py-1">{t.turbine_name}<span className="text-[8px] text-text-muted ml-0.5">{t.region}</span></td>
                <td className="py-1">{t.component}</td>
                <td className="py-1 text-right font-mono">{t.rul_days?.toFixed(0)}天</td>
                <td className="py-1 text-right font-mono text-text-muted">{t.downtime_hours}h</td>
                <td className="py-1"><span className="px-1 py-0.5 rounded text-[8px] bg-accent-blue/20 text-accent-blue">{t.action}</span></td>
                <td className="py-1 pr-4 text-right font-mono">¥{t.cost_estimate?.toLocaleString()}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
