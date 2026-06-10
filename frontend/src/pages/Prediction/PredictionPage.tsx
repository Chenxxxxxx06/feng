import { useEffect, useState, useRef } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import type { RULPrediction, CostComparison, WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

function exportRULToCSV(predictions: RULPrediction[]) {
  const header = '风机名称,部件,剩余寿命(天),置信下限,置信上限,预测时间\n';
  const rows = predictions.map((p) =>
    `${p.turbine_name},${p.component},${p.remaining_life_days.toFixed(0)},${p.confidence_lower.toFixed(0)},${p.confidence_upper.toFixed(0)},${new Date(p.predicted_at).toLocaleDateString('zh-CN')}`
  ).join('\n');
  const blob = new Blob(['﻿' + header + rows], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `RUL预测_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

// ── Calendar Component ──
function MaintenanceCalendar() {
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [rulItems, setRulItems] = useState<RULPrediction[]>([]);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: Date; orders: WorkOrder[]; ruls: RULPrediction[] } | null>(null);

  useEffect(() => {
    api.get('/prediction/rul').then(({ data }) => setRulItems(data.predictions || []));
    api.get('/workorders/').then(({ data }) => setWorkOrders(data));
  }, []);

  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  // Map work orders to their date
  const getOrdersForDate = (d: Date) => workOrders.filter(wo => {
    const woDate = new Date(wo.created_at);
    return woDate.getFullYear() === d.getFullYear() && woDate.getMonth() === d.getMonth() && woDate.getDate() === d.getDate();
  });

  // Map RUL predictions to estimated maintenance date
  const getRulForDate = (d: Date) => rulItems.filter(p => {
    const estimatedDate = new Date(Date.now() + p.remaining_life_days * 86400000);
    return estimatedDate.getFullYear() === d.getFullYear() && estimatedDate.getMonth() === d.getMonth() && estimatedDate.getDate() === d.getDate();
  });

  const dayNames = ['一', '二', '三', '四', '五', '六', '日'];
  const startOffset = firstDay === 0 ? 6 : firstDay - 1; // Convert Sun=0 to Mon-first

  return (
    <div className="bg-bg-card border border-border-default rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">运维日历</h3>
        <div className="flex items-center gap-2 text-xs">
          <button onClick={() => setCurrentMonth(new Date(year, month - 1))} className="px-2 py-1 hover:text-accent-blue">◀</button>
          <span className="font-medium">{year}年{month + 1}月</span>
          <button onClick={() => setCurrentMonth(new Date(year, month + 1))} className="px-2 py-1 hover:text-accent-blue">▶</button>
          <button onClick={() => setCurrentMonth(new Date())} className="ml-2 px-2 py-1 border border-border-default rounded text-[10px] hover:border-accent-blue">今天</button>
        </div>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 text-center text-[10px] text-text-muted mb-1">
        {dayNames.map(d => <div key={d} className="py-1">{d}</div>)}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-px bg-border-default rounded overflow-hidden">
        {/* Empty cells before month start */}
        {Array.from({ length: startOffset }).map((_, i) => (
          <div key={`empty-${i}`} className="bg-bg-secondary p-1.5 min-h-[60px]" />
        ))}

        {/* Day cells */}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const date = new Date(year, month, i + 1);
          const orders = getOrdersForDate(date);
          const ruls = getRulForDate(date);
          const isToday = date.toDateString() === today.toDateString();
          const eventCount = orders.length + ruls.length;
          const urgentCount = ruls.filter(r => r.remaining_life_days < 30).length + orders.filter(o => o.status === 'pending').length;

          return (
            <div
              key={i}
              className={`bg-bg-secondary p-1.5 min-h-[60px] cursor-pointer transition-colors hover:bg-bg-hover relative ${isToday ? 'ring-1 ring-accent-blue' : ''}`}
              onMouseEnter={(e) => {
                if (eventCount > 0) {
                  const rect = (e.target as HTMLElement).getBoundingClientRect();
                  setTooltip({ x: rect.right + 8, y: rect.top, date, orders, ruls });
                }
              }}
              onMouseLeave={() => setTooltip(null)}
            >
              <span className={`text-[11px] ${isToday ? 'text-accent-blue font-bold' : 'text-text-secondary'}`}>{i + 1}</span>
              {eventCount > 0 && (
                <div className="flex gap-0.5 mt-0.5 flex-wrap">
                  {urgentCount > 0 && <span className="w-2 h-2 rounded-full bg-accent-red" title={`${urgentCount} 紧急`} />}
                  {orders.length > 0 && <span className="w-2 h-2 rounded-full bg-accent-blue" />}
                  {ruls.filter(r => r.remaining_life_days >= 90).length > 0 && <span className="w-2 h-2 rounded-full bg-accent-green" />}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex gap-4 mt-2 text-[9px] text-text-muted">
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-red mr-1" />紧急工单/DDL</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-blue mr-1" />工单</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-green mr-1" />计划维护(RUL)</span>
      </div>

      {/* Mouse-following Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-bg-card border border-border-default rounded-lg shadow-xl p-3 min-w-[260px] max-w-[340px]"
          style={{ left: tooltip.x, top: tooltip.y, pointerEvents: 'none' }}
        >
          <p className="text-xs font-medium mb-1.5 border-b border-border-default pb-1">
            {tooltip.date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}
          </p>
          {tooltip.orders.map(wo => (
            <div key={`wo-${wo.id}`} className="text-[10px] mb-1.5 pb-1 border-b border-border-default last:border-0">
              <div className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-accent-blue flex-shrink-0" />
                <span className="font-medium text-text-primary">WO-{String(wo.id).padStart(4, '0')} {wo.title}</span>
              </div>
              <p className="text-text-muted mt-0.5 ml-3">风机 #{wo.turbine_id} · {wo.assignee || '未指派'} · {wo.status === 'pending' ? '待处理' : wo.status}</p>
            </div>
          ))}
          {tooltip.ruls.filter(r => r.remaining_life_days < 30).map(r => (
            <div key={`rul-${r.turbine_id}-${r.component}`} className="text-[10px] mb-1 pb-1 border-b border-border-default last:border-0">
              <div className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-accent-red flex-shrink-0" />
                <span className="font-medium text-accent-red">{r.turbine_name} {r.component}</span>
              </div>
              <p className="text-text-muted mt-0.5 ml-3">RUL {r.remaining_life_days.toFixed(0)}天 · 紧急维护窗口</p>
            </div>
          ))}
          {tooltip.orders.length === 0 && tooltip.ruls.length === 0 && (
            <p className="text-[10px] text-text-muted">该日无工单</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Prediction Page ──
export default function PredictionPage() {
  const [predictions, setPredictions] = useState<RULPrediction[]>([]);
  const [costResult, setCostResult] = useState<CostComparison | null>(null);
  const [costTurbine, setCostTurbine] = useState('');
  const rulChartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get('/prediction/rul').then(({ data }) => setPredictions(data.predictions || []));
  }, []);

  useEffect(() => {
    if (!rulChartRef.current || !predictions.length) return;
    const chart = echarts.init(rulChartRef.current, 'dark');
    const data = predictions.slice(0, 20);
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { color: '#8b949e', fontSize: 11 } },
      grid: { top: 35, right: 30, bottom: 40, left: 60 },
      xAxis: { type: 'category', data: data.map(p => `${p.turbine_name}-${p.component}`), axisLabel: { color: '#5c6975', fontSize: 9, rotate: 30 } },
      yAxis: { type: 'value', name: '剩余天数', axisLabel: { color: '#5c6975' } },
      series: [{
        type: 'bar',
        data: data.map(p => ({ value: p.remaining_life_days, itemStyle: { color: p.remaining_life_days < 90 ? '#f85149' : p.remaining_life_days < 180 ? '#d29922' : '#3fb950', borderRadius: [3, 3, 0, 0] }})),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#f85149', type: 'dashed', width: 1 }, data: [{ yAxis: 90, label: { formatter: '告警线', color: '#f85149', fontSize: 9 } }] },
      }],
    });
    const hr = () => chart.resize();
    window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); chart.dispose(); };
  }, [predictions]);

  const handleCostCompare = async () => {
    if (!costTurbine) return;
    const { data } = await api.post('/prediction/cost-comparison', { turbine_id: Number(costTurbine), fault_type: 'bearing_wear' });
    setCostResult(data);
  };

  const highRisk = predictions.filter(p => p.remaining_life_days < 180).sort((a, b) => a.remaining_life_days - b.remaining_life_days);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto p-6 space-y-5">
        <h2 className="text-lg font-semibold">预测性维护决策</h2>

        {/* RUL Chart */}
        <div className="bg-bg-card border border-border-default rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">剩余寿命预测 (RUL)</h3>
            {predictions.length > 0 && (
              <button onClick={() => exportRULToCSV(predictions)} className="px-3 py-1 border border-border-default rounded text-xs text-text-secondary hover:text-accent-blue">⬇ 导出CSV</button>
            )}
          </div>
          <div ref={rulChartRef} style={{ height: 350 }} />
        </div>

        {/* Calendar + High Risk Table */}
        <div className="grid grid-cols-2 gap-4">
          <MaintenanceCalendar />
          {/* High Risk Table */}
          <div className="bg-bg-card border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-medium mb-3">高风险部件列表</h3>
            <div className="overflow-auto max-h-[280px]">
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted border-b border-border-default"><th className="text-left py-2">风机</th><th className="text-left py-2">部件</th><th className="text-right py-2">RUL</th><th className="text-right py-2">风险</th></tr></thead>
                <tbody>
                  {highRisk.slice(0, 12).map((p, i) => (
                    <tr key={i} className="border-b border-border-default hover:bg-bg-hover">
                      <td className="py-2">{p.turbine_name}</td><td className="py-2">{p.component}</td>
                      <td className="py-2 text-right font-mono">{p.remaining_life_days.toFixed(0)} 天</td>
                      <td className="py-2 text-right"><span className={`px-1.5 py-0.5 rounded text-[10px] ${p.remaining_life_days < 30 ? 'bg-accent-red/20 text-accent-red' : p.remaining_life_days < 90 ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-blue/20 text-accent-blue'}`}>{p.remaining_life_days < 30 ? '紧急' : p.remaining_life_days < 90 ? '近期' : '计划'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Cost Comparison */}
        <div className="bg-bg-card border border-border-default rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">维护成本对比</h3>
          <div className="flex gap-3 mb-4">
            <input type="number" placeholder="风机ID" value={costTurbine} onChange={(e) => setCostTurbine(e.target.value)}
              className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary w-28 focus:outline-none focus:border-accent-blue" />
            <button onClick={handleCostCompare} className="px-4 py-2 bg-accent-blue text-white rounded text-sm hover:opacity-90">计算对比</button>
          </div>
          {costResult && (
            <div>
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">立即检修</p><p className="text-xl font-mono font-bold text-accent-red">¥{costResult.immediate_repair_cost.toLocaleString()}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">延迟检修</p><p className="text-xl font-mono font-bold text-accent-yellow">¥{costResult.delayed_repair_cost.toLocaleString()}</p></div>
                <div className="bg-bg-hover rounded p-3 text-center"><p className="text-xs text-text-muted mb-1">每日停机损失</p><p className="text-xl font-mono font-bold text-text-primary">¥{costResult.downtime_loss_per_day.toLocaleString()}</p></div>
              </div>
              <div className="mt-3 p-3 bg-accent-green/10 border border-accent-green/30 rounded text-xs text-accent-green">{costResult.recommendation}</div>
            </div>
          )}
        </div>
      </div>
      <CopilotFAB />
    </div>
  );
}
