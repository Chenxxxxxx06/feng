import { useEffect, useState, useRef } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import type { RULPrediction, CostComparison, WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

function exportRULToCSV(predictions: RULPrediction[]) {
  const h = 'TURBINE,COMPONENT,RUL_DAYS,CI_LOWER,CI_UPPER,PREDICTED\n';
  const rows = predictions.map(p => `${p.turbine_name},${p.component},${p.remaining_life_days.toFixed(0)},${p.confidence_lower.toFixed(0)},${p.confidence_upper.toFixed(0)},${new Date(p.predicted_at).toLocaleDateString('zh-CN')}`).join('\n');
  const b = new Blob(['﻿' + h + rows], { type: 'text/csv;charset=utf-8' });
  const u = URL.createObjectURL(b);
  const a = document.createElement('a'); a.href = u; a.download = `RUL_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(u);
}

function MaintenanceCalendar() {
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [rulItems, setRulItems] = useState<RULPrediction[]>([]);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: Date; orders: WorkOrder[]; ruls: RULPrediction[] } | null>(null);

  useEffect(() => {
    api.get('/prediction/rul').then(({ data }) => setRulItems(data.predictions || []));
    api.get('/workorders/').then(({ data }) => setWorkOrders(data));
  }, []);

  const yr = currentMonth.getFullYear(), mo = currentMonth.getMonth();
  const firstDay = new Date(yr, mo, 1).getDay();
  const daysIn = new Date(yr, mo + 1, 0).getDate();
  const today = new Date();
  const startOff = firstDay === 0 ? 6 : firstDay - 1;

  const getOrders = (d: Date) => workOrders.filter(wo => {
    const wd = new Date(wo.created_at);
    return wd.getFullYear() === d.getFullYear() && wd.getMonth() === d.getMonth() && wd.getDate() === d.getDate();
  });
  const getRUL = (d: Date) => rulItems.filter(p => {
    const ed = new Date(Date.now() + p.remaining_life_days * 86400000);
    return ed.getFullYear() === d.getFullYear() && ed.getMonth() === d.getMonth() && ed.getDate() === d.getDate();
  });

  return (
    <div className="hud-panel p-4" style={{ background: '#161922' }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-mono text-[10px] uppercase tracking-widest" style={{ color: '#00E5FF' }}>
          <span style={{ color: '#445566' }}>[CAL]</span> MAINT_CALENDAR
        </h3>
        <div className="flex items-center gap-2 font-mono text-[10px]">
          <button onClick={() => setCurrentMonth(new Date(yr, mo - 1))} className="btn-ghost text-[10px]">&#9664;</button>
          <span style={{ color: '#E8ECF1' }}>{yr}-{String(mo + 1).padStart(2, '0')}</span>
          <button onClick={() => setCurrentMonth(new Date(yr, mo + 1))} className="btn-ghost text-[10px]">&#9654;</button>
          <button onClick={() => setCurrentMonth(new Date())} className="chip text-[8px]">TODAY</button>
        </div>
      </div>
      <div className="grid grid-cols-7 text-center font-mono text-[9px] mb-1" style={{ color: '#445566' }}>
        {['MON','TUE','WED','THU','FRI','SAT','SUN'].map(d => <div key={d} className="py-1">{d}</div>)}
      </div>
      <div className="grid grid-cols-7 overflow-hidden" style={{ gap: '1px', background: 'rgba(255,255,255,0.04)' }}>
        {Array.from({ length: startOff }).map((_, i) => <div key={`e${i}`} className="p-1" style={{ minHeight: 52, background: 'rgba(255,255,255,0.01)' }} />)}
        {Array.from({ length: daysIn }).map((_, i) => {
          const dt = new Date(yr, mo, i + 1);
          const ords = getOrders(dt), ruls = getRUL(dt);
          const isTdy = dt.toDateString() === today.toDateString();
          const evCnt = ords.length + ruls.length;
          const urg = ruls.filter(r => r.remaining_life_days < 30).length + ords.filter(o => o.status === 'pending').length;
          return (
            <div key={i} className="p-1 cursor-pointer relative" style={{
              minHeight: 52, background: isTdy ? 'rgba(0,229,255,0.04)' : 'rgba(255,255,255,0.01)',
              border: isTdy ? '1px solid rgba(0,229,255,0.2)' : '1px solid transparent',
            }}
              onMouseEnter={(e) => { if (evCnt > 0) { const r = (e.target as HTMLElement).getBoundingClientRect(); setTooltip({ x: r.right + 8, y: r.top, date: dt, orders: ords, ruls }); }}}
              onMouseLeave={() => setTooltip(null)}>
              <span className="font-mono text-[10px]" style={{ color: isTdy ? '#00E5FF' : '#8899AA' }}>{i + 1}</span>
              {evCnt > 0 && <div className="flex gap-0.5 mt-0.5">{urg > 0 && <span className="w-2 h-2" style={{ background: '#FF1744', boxShadow: '0 0 4px #FF1744' }} />}{ords.length > 0 && <span className="w-2 h-2" style={{ background: '#2979FF' }} />}</div>}
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-2 font-mono text-[8px] tracking-wider" style={{ color: '#445566' }}>
        <span className="flex items-center gap-1"><span className="w-2 h-2" style={{ background: '#FF1744' }} />URGENT</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2" style={{ background: '#2979FF' }} />WO</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2" style={{ background: '#00E676' }} />PLANNED</span>
      </div>
      {tooltip && (
        <div className="fixed z-50 p-3 min-w-[260px]" style={{
          left: tooltip.x, top: tooltip.y, pointerEvents: 'none',
          background: '#11141C', border: '1px solid rgba(0,229,255,0.15)', borderRadius: '2px',
          boxShadow: '0 0 30px rgba(0,0,0,0.7)',
        }}>
          <p className="font-mono text-[10px] font-semibold mb-1.5 pb-1 tracking-wider" style={{ color: '#00E5FF', borderBottom: '1px solid rgba(0,229,255,0.12)' }}>
            {tooltip.date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}
          </p>
          {tooltip.orders.map(wo => (
            <div key={wo.id} className="text-[10px] mb-1 pb-1" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <div className="flex items-center gap-1"><span className="w-1.5 h-1.5" style={{ background: '#2979FF' }} /><span style={{ color: '#E8ECF1' }}>WO-{String(wo.id).padStart(4, '0')} {wo.title}</span></div>
              <p className="mt-0.5 ml-2.5 font-mono text-[9px]" style={{ color: '#445566' }}>T#{wo.turbine_id} {wo.assignee || 'UNASSIGNED'}</p>
            </div>
          ))}
          {tooltip.ords.length === 0 && tooltip.ruls.length === 0 && <p className="font-mono text-[9px]" style={{ color: '#445566' }}>NO_WORK_ORDERS</p>}
        </div>
      )}
    </div>
  );
}

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
    const c = echarts.init(rulChartRef.current, 'dark');
    const data = predictions.slice(0, 20);
    c.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { color: '#8899AA', fontSize: 11 } },
      grid: { top: 35, right: 30, bottom: 40, left: 60 },
      xAxis: { type: 'category', data: data.map(p => `${p.turbine_name}-${p.component}`), axisLabel: { color: '#445566', fontSize: 9, rotate: 30 } },
      yAxis: { type: 'value', name: 'DAYS', axisLabel: { color: '#445566' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
      series: [{
        type: 'bar',
        data: data.map(p => ({ value: p.remaining_life_days, itemStyle: { color: p.remaining_life_days < 90 ? '#FF1744' : p.remaining_life_days < 180 ? '#FF9100' : '#00E676', borderRadius: [1, 1, 0, 0] } })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#FF1744', type: 'dashed', width: 1 }, data: [{ yAxis: 90, label: { formatter: 'ALERT', color: '#FF1744', fontSize: 9 } }] },
      }],
    });
    const hr = () => c.resize();
    window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); c.dispose(); };
  }, [predictions]);

  const handleCostCompare = async () => {
    if (!costTurbine) return;
    const { data } = await api.post('/prediction/cost-comparison', { turbine_id: Number(costTurbine), fault_type: 'bearing_wear' });
    setCostResult(data);
  };

  const highRisk = predictions.filter(p => p.remaining_life_days < 180).sort((a, b) => a.remaining_life_days - b.remaining_life_days);

  return (
    <div className="h-full flex flex-col overflow-hidden relative" style={{ background: '#020204' }}>
      <div className="flex-shrink-0 px-5 py-3 relative z-10" style={{ borderBottom: '1px solid rgba(0,229,255,0.12)', background: '#0A0C10' }}>
        <div className="flex items-center gap-4">
          <span className="font-mono text-[10px] tracking-widest" style={{ color: '#00E5FF' }}>[03]</span>
          <h2 className="text-sm font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
            PREDICTIVE_MAINTENANCE :: DECISION
          </h2>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-5 space-y-4 relative z-10">
        {/* RUL Chart */}
        <div className="hud-panel p-4 slide-up" style={{ background: '#161922' }}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-mono text-[10px] uppercase tracking-widest" style={{ color: '#00E5FF' }}>
              <span style={{ color: '#445566' }}>[RUL]</span> REMAINING_USEFUL_LIFE
            </h3>
            {predictions.length > 0 && (
              <button onClick={() => exportRULToCSV(predictions)} className="btn-prime text-[10px]">
                EXPORT_CSV
              </button>
            )}
          </div>
          <div ref={rulChartRef} style={{ height: 350 }} />
        </div>

        {/* Calendar + High Risk */}
        <div className="grid grid-cols-2 gap-4 slide-up slide-up-d1">
          <MaintenanceCalendar />
          <div className="hud-panel p-4" style={{ background: '#161922' }}>
            <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3" style={{ color: '#00E5FF' }}>
              <span style={{ color: '#445566' }}>[RISK]</span> HIGH_RISK_COMPONENTS
            </h3>
            <div className="overflow-auto" style={{ maxHeight: 280 }}>
              <table className="table-hud">
                <thead><tr><th>TURBINE</th><th>COMPONENT</th><th style={{ textAlign: 'right' }}>RUL</th><th style={{ textAlign: 'right' }}>RISK</th></tr></thead>
                <tbody>
                  {highRisk.slice(0, 12).map((p, i) => (
                    <tr key={i}>
                      <td>{p.turbine_name}</td><td>{p.component}</td>
                      <td className="font-mono" style={{ textAlign: 'right' }}>{p.remaining_life_days.toFixed(0)} D</td>
                      <td style={{ textAlign: 'right' }}>
                        <span className={`chip text-[9px] ${p.remaining_life_days < 30 ? 'chip-red' : p.remaining_life_days < 90 ? 'chip-amber' : 'chip-cyan'}`}>
                          {p.remaining_life_days < 30 ? 'URGENT' : p.remaining_life_days < 90 ? 'SOON' : 'PLANNED'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Cost Comparison */}
        <div className="hud-panel p-4 slide-up slide-up-d2" style={{ background: '#161922' }}>
          <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3" style={{ color: '#00E5FF' }}>
            <span style={{ color: '#445566' }}>[COST]</span> COST_COMPARISON
          </h3>
          <div className="flex gap-3 mb-4">
            <input type="number" placeholder="TURBINE_ID" value={costTurbine} onChange={(e) => setCostTurbine(e.target.value)}
              className="input-hud w-28" />
            <button onClick={handleCostCompare} className="btn-prime-filled text-[11px]">CALCULATE</button>
          </div>
          {costResult && (
            <div>
              <div className="grid grid-cols-3 gap-4">
                {[
                  { l: 'IMMEDIATE_REPAIR', v: costResult.immediate_repair_cost, c: '#FF1744' },
                  { l: 'DELAYED_REPAIR', v: costResult.delayed_repair_cost, c: '#FF9100' },
                  { l: 'DOWNTIME_LOSS/DAY', v: costResult.downtime_loss_per_day, c: '#8899AA' },
                ].map(({ l, v, c }) => (
                  <div key={l} className="hud-panel p-3 text-center" style={{ background: '#11141C' }}>
                    <p className="font-mono text-[8px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{l}</p>
                    <p className="kpi-value-sm" style={{ color: c, fontSize: '1.5rem' }}>¥{v.toLocaleString()}</p>
                  </div>
                ))}
              </div>
              <div className="mt-3 p-3 font-mono text-[9px] tracking-wider" style={{
                background: 'rgba(0,230,118,0.03)', border: '1px solid rgba(0,230,118,0.12)', borderRadius: '2px', color: '#00E676',
              }}>
                {'>'} {costResult.recommendation}
              </div>
            </div>
          )}
        </div>
      </div>
      <CopilotFAB />
    </div>
  );
}
