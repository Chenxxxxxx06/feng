import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import TurbineMap from '../../components/Map/TurbineMap';
import FilterPanel from '../../components/Common/FilterPanel';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import AIPanel from '../../components/AIAssistant/AIPanel';
import { fetchUserPreferences, loadLocalPreferences, PREFERENCES_UPDATED_EVENT, type UserPreferences } from '../../services/preferences';
import type { TurbineSummary, TurbineDetail } from '../../types';

const EMPTY_SUMMARY: TurbineSummary = { turbines: [], total: 0, healthy: 0, warning: 0, faulty: 0 };
const STATUS_COLORS = { normal: '#10B981', warning: '#F59E0B', fault: '#EF4444' } as const;

interface ThresholdAlertStatus {
  threshold: number;
  low_count: number;
  turbines: Array<{ id: number; name: string; region: string | null; status: string; hi_value: number; model: string | null }>;
  checked_at: string;
}

function hiColor(hiValue: number): string {
  if (hiValue >= 80) return '#10B981';
  if (hiValue >= 60) return '#F59E0B';
  return '#EF4444';
}

function hiLevel(hiValue: number): 'good' | 'fair' | 'poor' {
  if (hiValue >= 80) return 'good';
  if (hiValue >= 60) return 'fair';
  return 'poor';
}

function scopedStats(turbines: TurbineDetail[]) {
  const healthy = turbines.filter((t) => t.status === 'normal').length;
  const warning = turbines.filter((t) => t.status === 'warning').length;
  const faulty = turbines.filter((t) => t.status === 'fault').length;
  const total = turbines.length;
  return { healthy, warning, faulty, online: healthy + warning, availability: total > 0 ? (((healthy + warning) / total) * 100).toFixed(1) : '--' };
}

/* ── Premium KPI Card ── */
function KPICard({ label, value, unit, color, trend }: { label: string; value: string; unit: string; color: string; trend?: string }) {
  return (
    <div className="premium-card rounded-2xl px-5 py-4 flex items-center gap-4 transition-all duration-300 hover:scale-[1.01] cursor-default group" style={{ minHeight: '76px' }}>
      <div className="w-1 h-12 rounded-full flex-shrink-0 transition-all duration-300 group-hover:h-14" style={{ background: `linear-gradient(180deg, ${color} 0%, ${color}44 100%)`, boxShadow: `0 0 12px ${color}33` }} />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-medium text-text-muted mb-1 tracking-wide uppercase">{label}</p>
        <p className="text-[26px] font-bold tracking-tight leading-none" style={{ color, fontFamily: "'SF Mono', 'JetBrains Mono', monospace", fontVariantNumeric: 'tabular-nums' }}>
          {value}<span className="text-[13px] font-medium text-text-muted ml-1.5 align-baseline">{unit}</span>
        </p>
      </div>
      {trend && <span className="text-accent-red text-xs">↑</span>}
    </div>
  );
}

/* ── Health Score Ring ── */
function HealthRing({ value, size = 52, strokeWidth = 5, label }: { value: number; size?: number; strokeWidth?: number; label: string }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = hiColor(value);
  const gid = `hr-${label.replace(/\s/g, '')}`;
  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width={size} height={size} className="transform -rotate-90">
        <defs><linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stopColor={color} stopOpacity="0.3" /><stop offset="100%" stopColor={color} /></linearGradient></defs>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeOpacity="0.12" strokeWidth={strokeWidth} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={`url(#${gid})`} strokeWidth={strokeWidth} strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} className="health-ring-circle" style={{ filter: `drop-shadow(0 0 6px ${color}55)` }} />
      </svg>
      <span className="text-xs font-bold" style={{ color, fontFamily: "'SF Mono', 'JetBrains Mono', monospace" }}>{value.toFixed(0)}</span>
      <span className="text-[10px] text-text-muted leading-tight text-center">{label}</span>
    </div>
  );
}

/* ── Alarm Item ── */
function AlarmItem({ title, turbine, severity, time }: { title: string; turbine: string; severity: 'critical' | 'warning' | 'info'; time: string }) {
  const c = severity === 'critical' ? { bg: 'rgba(239,68,68,0.10)', border: '#EF4444', dot: '#EF4444' } : severity === 'warning' ? { bg: 'rgba(245,158,11,0.10)', border: '#F59E0B', dot: '#F59E0B' } : { bg: 'rgba(59,130,246,0.10)', border: '#3B82F6', dot: '#3B82F6' };
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 hover:bg-bg-hover cursor-pointer" style={{ background: c.bg, borderLeft: `3px solid ${c.border}` }}>
      <span className="w-2 h-2 rounded-full flex-shrink-0 status-dot-danger" style={{ background: c.dot, boxShadow: `0 0 6px ${c.dot}` }} />
      <div className="flex-1 min-w-0"><p className="text-[12px] font-medium text-text-primary truncate">{title}</p><p className="text-[10px] text-text-muted">{turbine}</p></div>
      <span className="text-[10px] text-text-muted flex-shrink-0">{time}</span>
    </div>
  );
}

/* ── SCADA Trend Chart ── */
function ScadaTrendChart({ title, data, color, unit, height = 76 }: { title: string; data: { time: string; value: number }[]; color: string; unit: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !data.length) return;
    const chart = echarts.init(ref.current, 'dark');
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 6, right: 12, bottom: 18, left: 44 },
      tooltip: {
        trigger: 'axis', confine: false, extraCssText: 'z-index:1000;pointer-events:auto;',
        backgroundColor: 'rgba(10,31,63,0.97)', borderColor: 'rgba(59,130,246,0.35)', borderWidth: 1,
        textStyle: { color: '#F1F5F9', fontSize: 11 },
        formatter: (params: any) => { const p = Array.isArray(params) ? params[0] : params; return `<div style="min-width:120px">${p.axisValue}<br/><span style="color:${color}">●</span> ${p.seriesName}: <b>${p.value} ${unit}</b></div>`; },
      },
      xAxis: { type: 'category', data: data.map((d) => d.time), axisLabel: { color: '#64748B', fontSize: 8, interval: 3 }, axisLine: { lineStyle: { color: 'rgba(59,130,246,0.10)' } }, axisTick: { show: false } },
      yAxis: { type: 'value', axisLabel: { color: '#64748B', fontSize: 8, margin: 6 }, splitLine: { lineStyle: { color: 'rgba(59,130,246,0.06)' } }, splitNumber: 2 },
      series: [{ name: title, type: 'line', data: data.map((d) => d.value), symbol: 'none', smooth: true, lineStyle: { color, width: 2 }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: `${color}33` }, { offset: 1, color: `${color}00` }]) } }],
    });
    const r = () => chart.resize(); window.addEventListener('resize', r);
    return () => { window.removeEventListener('resize', r); chart.dispose(); };
  }, [data, color, title, unit]);
  return <div className="flex flex-col"><div className="flex items-center justify-between mb-1"><p className="text-[11px] font-medium text-text-secondary">{title}</p><span className="text-[10px] text-text-muted">{unit}</span></div><div ref={ref} style={{ height }} /></div>;
}

/* ── Work Order Preview ── */
function WorkOrderPreview({ id, title, status, priority, assignee }: { id: number; title: string; status: string; priority: string; assignee: string | null }) {
  const sc: Record<string, { label: string; color: string }> = { pending: { label: '待分配', color: '#EF4444' }, assigned: { label: '已分配', color: '#F59E0B' }, in_progress: { label: '执行中', color: '#3B82F6' }, review: { label: '待验收', color: '#F59E0B' }, completed: { label: '已完成', color: '#10B981' }, closed: { label: '已关闭', color: '#64748B' } };
  const s = sc[status] || { label: status, color: '#64748B' };
  return (
    <Link to="/workorder" className="flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 hover:bg-bg-hover group">
      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: s.color, boxShadow: `0 0 6px ${s.color}` }} />
      <div className="flex-1 min-w-0"><p className="text-[12px] font-medium text-text-primary truncate group-hover:text-white transition-colors">WO-{String(id).padStart(4, '0')} {title}</p><p className="text-[10px] text-text-muted">{assignee || '待分配'} · {s.label}</p></div>
      <span className="text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0" style={{ background: `${s.color}18`, color: s.color }}>{priority === 'urgent' ? '紧急' : priority === 'high' ? '高' : priority === 'medium' ? '中' : '低'}</span>
    </Link>
  );
}

/* ── Component Health Card ── */
function ComponentHealthCard({ label, temperature, maxTemp, status }: { label: string; temperature: number; maxTemp: number; status: 'normal' | 'warning' | 'fault' }) {
  const pct = Math.min(100, (temperature / maxTemp) * 100);
  const color = status === 'normal' ? '#10B981' : status === 'warning' ? '#F59E0B' : '#EF4444';
  return (
    <div className="px-3 py-2.5 rounded-xl transition-all duration-200 hover:bg-bg-hover/50" style={{ border: '1px solid rgba(59,130,246,0.08)' }}>
      <div className="flex items-center justify-between mb-1.5"><span className="text-[11px] text-text-secondary">{label}</span><span className="w-1.5 h-1.5 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} /></div>
      <p className="text-lg font-bold" style={{ color, fontFamily: "'SF Mono', 'JetBrains Mono', monospace" }}>{temperature.toFixed(1)}°C</p>
      <div className="mt-1.5 h-1 rounded-full" style={{ background: 'rgba(59,130,246,0.10)' }}><div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} /></div>
    </div>
  );
}

/* ═══════════════════════════════ Main Dashboard ═══════════════════════════════ */
export default function DashboardPage() {
  const [summary, setSummary] = useState<TurbineSummary>(EMPTY_SUMMARY);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<TurbineDetail | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [mtbfHours, setMtbfHours] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [thresholdAlerts, setThresholdAlerts] = useState<ThresholdAlertStatus | null>(null);
  const [riskFirst, setRiskFirst] = useState(() => loadLocalPreferences().riskFirst);

  const fetchData = async () => { setLoading(true); try { const params = new URLSearchParams(filters); const { data } = await api.get(`/turbines/?${params}`); setSummary(data); } catch { setSummary(EMPTY_SUMMARY); } finally { setLoading(false); } };
  useEffect(() => { fetchData(); }, [filters]);
  useEffect(() => { if (!selectedId) { setDetail(null); return; } api.get(`/turbines/${selectedId}`).then(({ data }) => setDetail(data)).catch(() => setDetail(null)); }, [selectedId]);

  useEffect(() => {
    let c = false;
    (async () => { try { const { data } = await api.get('/turbines/monitoring-metrics'); if (!c && data?.mtbf_hours != null) setMtbfHours(data.mtbf_hours); } catch {}; })();
    return () => { c = true; };
  }, []);

  useEffect(() => { const t = setInterval(() => setCurrentTime(new Date()), 30_000); return () => clearInterval(t); }, []);

  useEffect(() => {
    const applyPrefs = (prefs: UserPreferences) => setRiskFirst(prefs.riskFirst);
    applyPrefs(loadLocalPreferences());
    fetchUserPreferences().then(applyPrefs).catch(() => undefined);
    const handlePreferences = (event: Event) => {
      applyPrefs((event as CustomEvent<UserPreferences>).detail || loadLocalPreferences());
    };
    window.addEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
    return () => window.removeEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadThresholdAlerts = async () => {
      try {
        const { data } = await api.get<ThresholdAlertStatus>('/settings/threshold-alerts');
        if (!cancelled) setThresholdAlerts(data);
      } catch {
        if (!cancelled) setThresholdAlerts(null);
      }
    };
    loadThresholdAlerts();
    window.addEventListener('threshold-alerts-updated', loadThresholdAlerts);
    return () => {
      cancelled = true;
      window.removeEventListener('threshold-alerts-updated', loadThresholdAlerts);
    };
  }, []);

  const healthy = summary.turbines.filter((t) => t.status === 'normal').length;
  const warning = summary.turbines.filter((t) => t.status === 'warning').length;
  const faulty = summary.turbines.filter((t) => t.status === 'fault').length;
  const avail = summary.total > 0 ? ((healthy + warning) / summary.total * 100).toFixed(1) : '--';
  const scopedTurbines = useMemo(() => {
    if (!riskFirst) return summary.turbines;
    const statusRank = (status: string) => (status === 'fault' ? 0 : status === 'warning' ? 1 : 2);
    return [...summary.turbines].sort((a, b) => (
      statusRank(a.status) - statusRank(b.status)
      || a.hi_value - b.hi_value
      || a.name.localeCompare(b.name, 'zh-CN')
    ));
  }, [riskFirst, summary.turbines]);
  const stats = useMemo(() => scopedStats(scopedTurbines), [scopedTurbines]);

  const fmtMtbf = (h: number | null) => { if (h == null) return '--'; if (h >= 24) return `${(h / 24).toFixed(0)} 天`; return `${h.toFixed(0)} 小时`; };

  const windSpeedData = useMemo(() => Array.from({ length: 24 }, (_, i) => ({ time: `${i}:00`, value: 4 + Math.sin(i / 4) * 3 + Math.random() * 4 })), []);
  const powerData = useMemo(() => Array.from({ length: 24 }, (_, i) => ({ time: `${i}:00`, value: 800 + Math.sin(i / 4) * 600 + Math.random() * 400 })), []);
  const tempData = useMemo(() => Array.from({ length: 24 }, (_, i) => ({ time: `${i}:00`, value: 45 + Math.sin(i / 5) * 8 + Math.random() * 4 })), []);

  const baseAlarms = useMemo(() => [
    { id: 1, title: '主轴承温度异常升高', turbine: '#03 风机 · 榆林靖边A区', severity: 'critical' as const, time: '14:32' },
    { id: 2, title: '齿轮箱振动幅值超阈值', turbine: '#07 风机 · 榆林定边B区', severity: 'warning' as const, time: '13:15' },
    { id: 3, title: '变桨系统响应延迟', turbine: '#12 风机 · 榆林横山C区', severity: 'warning' as const, time: '11:48' },
    { id: 4, title: '发电机绕组温度偏高', turbine: '#05 风机 · 榆林靖边A区', severity: 'info' as const, time: '10:22' },
    { id: 5, title: '维护周期即将到期提醒', turbine: '#09 风机 · 榆林定边B区', severity: 'info' as const, time: '08:56' },
  ], []);
  const alarms = useMemo(() => {
    const thresholdTime = thresholdAlerts?.checked_at
      ? new Date(thresholdAlerts.checked_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : '刚刚';
    const hiAlarms = (thresholdAlerts?.turbines || []).map((turbine) => ({
      id: `hi-${turbine.id}`,
      title: `HI低于阈值 ${thresholdAlerts?.threshold ?? 70}`,
      turbine: `${turbine.name} · ${turbine.region || '-'} · HI ${turbine.hi_value.toFixed(1)}`,
      severity: 'critical' as const,
      time: thresholdTime,
    }));
    const combined = [...hiAlarms, ...baseAlarms];
    if (!riskFirst) return combined;
    const severityRank = (severity: string) => (severity === 'critical' ? 0 : severity === 'warning' ? 1 : 2);
    return combined.sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
  }, [baseAlarms, riskFirst, thresholdAlerts]);

  const workOrders = useMemo(() => [
    { id: 42, title: '更换齿轮箱高速轴轴承', status: 'in_progress', priority: 'urgent', assignee: '张工' },
    { id: 41, title: '叶片前缘腐蚀修复', status: 'assigned', priority: 'high', assignee: '李工' },
    { id: 40, title: '发电机冷却系统清洗', status: 'pending', priority: 'medium', assignee: null },
    { id: 39, title: '变桨电机定期保养', status: 'completed', priority: 'low', assignee: '王工' },
  ], []);

  const componentTemps = useMemo(() => [
    { label: '主轴承', temperature: 62.3, maxTemp: 85, status: 'normal' as const },
    { label: '齿轮箱', temperature: 78.5, maxTemp: 90, status: 'warning' as const },
    { label: '发电机', temperature: 55.1, maxTemp: 80, status: 'normal' as const },
    { label: '变桨系统', temperature: 41.8, maxTemp: 65, status: 'normal' as const },
  ], []);

  const avgHealth = scopedTurbines.length > 0 ? scopedTurbines.reduce((s, t) => s + t.hi_value, 0) / scopedTurbines.length : 0;
  const todayEnergy = useMemo(() => (scopedTurbines.length * 3.3 * 0.32 * 24).toFixed(0), [scopedTurbines.length]);
  const currentPower = useMemo(() => (scopedTurbines.length * 3.3 * 0.35).toFixed(0), [scopedTurbines.length]);
  const aiSummaryData = useMemo(() => ({
    total_turbines: summary.total,
    healthy_turbines: healthy,
    warning_turbines: warning,
    faulty_turbines: faulty,
    availability: avail,
    mtbf_hours: mtbfHours,
    avg_health: avgHealth,
    current_power_mw: currentPower,
    today_energy_mwh: todayEnergy,
    alarms,
    work_orders: workOrders,
    component_temperatures: componentTemps,
  }), [alarms, avail, avgHealth, componentTemps, currentPower, faulty, healthy, mtbfHours, summary.total, todayEnergy, warning, workOrders]);

  const closeDetail = useCallback(() => { setSelectedId(null); setDetail(null); }, []);

  return (
    <div className="h-full flex flex-col overflow-y-auto" style={{ background: 'radial-gradient(ellipse at 50% 20%, #0D2447 0%, #071A35 70%)' }}>
      {/* ═══ Top Header ═══ */}
      <div className="flex-shrink-0 px-4 py-3 flex items-center justify-between border-b" style={{ borderColor: 'rgba(59,130,246,0.08)' }}>
        <div className="flex items-center gap-5">
          <div><h2 className="text-[15px] font-bold tracking-wide gradient-text">陕西省 · 风场监控中心</h2><p className="text-[10px] text-text-muted mt-0.5">实时数据更新</p></div>
          <span className="text-[10px] text-text-muted px-2.5 py-1 rounded-full" style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.12)' }}>共 {summary.total} 台风机</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-2 text-[12px] font-medium" style={{ color: '#10B981' }}>
            <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: '#10B981' }} /><span className="relative inline-flex rounded-full h-2 w-2" style={{ background: '#10B981' }} /></span>系统运行正常
          </span>
          <span className="text-[11px] text-text-muted font-mono">{currentTime.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
        </div>
      </div>

      {/* ═══ KPI Strip ═══ */}
      <div className="flex-shrink-0 px-4 pt-4 pb-2">
        <div className="grid grid-cols-5 gap-3">
          <KPICard label="风机可用率" value={avail} unit="%" color="#3B82F6" />
          <KPICard label="正常运行" value={String(healthy)} unit="台" color="#10B981" />
          <KPICard label="预警风机" value={String(warning)} unit="台" color="#F59E0B" />
          <KPICard label="故障风机" value={String(faulty)} unit="台" color="#EF4444" trend={faulty > 0 ? 'up' : undefined} />
          <KPICard label="MTBF" value={mtbfHours != null ? fmtMtbf(mtbfHours) : '--'} unit="" color="#22D3EE" />
        </div>
      </div>

      {/* ═══ Map ═══ */}
      <div className="flex-1 relative mx-2 my-3 rounded-2xl overflow-hidden" style={{ border: '1px solid rgba(59,130,246,0.10)', boxShadow: 'inset 0 0 80px rgba(0,0,0,0.4), 0 4px 24px rgba(0,0,0,0.3)', minHeight: '360px' }}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center backdrop-blur-sm" style={{ background: 'rgba(7,26,53,0.7)' }}>
            <div className="flex flex-col items-center gap-3"><div className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: 'rgba(59,130,246,0.3)', borderTopColor: '#3B82F6' }} /><span className="text-text-muted text-xs font-medium">加载风机数据...</span></div>
          </div>
        )}
        <div className="absolute inset-0 z-0"><TurbineMap turbines={scopedTurbines} selectedId={selectedId} onSelect={setSelectedId} /></div>
        <div className="relative z-[700]"><FilterPanel filters={filters} onChange={setFilters} /></div>

        {/* Slide-out Detail */}
        <div className={`absolute top-0 right-0 h-full w-[350px] transform transition-transform duration-300 z-[800] flex flex-col ${detail ? 'translate-x-0' : 'translate-x-full'}`}
          style={{ background: 'rgba(10,31,63,0.92)', backdropFilter: 'blur(20px)', borderLeft: '1px solid rgba(59,130,246,0.15)', boxShadow: '-8px 0 40px rgba(0,0,0,0.4)' }}>
          {detail && (
            <div className="slide-panel h-full flex flex-col">
              <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: 'rgba(59,130,246,0.10)' }}>
                <div><h3 className="font-bold text-[15px] text-text-primary">{detail.name}</h3><p className="text-[11px] text-text-muted mt-0.5">{detail.region} · {detail.model}</p></div>
                <button onClick={closeDetail} className="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-white hover:bg-bg-hover transition-all" style={{ border: '1px solid rgba(59,130,246,0.12)' }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                </button>
              </div>
              <div className="flex-1 overflow-auto p-5 space-y-5">
                <div className="flex flex-col items-center py-2">
                  <div className="relative flex items-center justify-center" style={{ width: 120, height: 120 }}>
                    <svg width="120" height="120" className="transform -rotate-90">
                      <circle cx="60" cy="60" r="52" fill="none" stroke={hiColor(detail.hi_value)} strokeOpacity="0.15" strokeWidth="8" />
                      <circle cx="60" cy="60" r="52" fill="none" stroke={hiColor(detail.hi_value)} strokeWidth="8" strokeLinecap="round" strokeDasharray={2 * Math.PI * 52} strokeDashoffset={2 * Math.PI * 52 * (1 - detail.hi_value / 100)} style={{ filter: `drop-shadow(0 0 12px ${hiColor(detail.hi_value)}66)`, transition: 'stroke-dashoffset 1s cubic-bezier(0.16, 1, 0.3, 1)' }} />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <p className="text-3xl font-bold" style={{ color: hiColor(detail.hi_value), fontFamily: "'SF Mono', 'JetBrains Mono', monospace" }}>{detail.hi_value.toFixed(0)}</p>
                      <p className="text-[10px] text-text-muted font-medium">健康指数</p>
                    </div>
                  </div>
                  <p className={`text-xs font-semibold mt-3 ${detail.status === 'normal' ? 'text-accent-green' : detail.status === 'warning' ? 'text-accent-yellow' : 'text-accent-red'}`}>
                    {detail.status === 'normal' ? '● 正常运行' : detail.status === 'warning' ? '▲ 预警状态' : '■ 故障状态'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {[{ label: '额定功率', value: `${detail.power_mw} MW`, color: '#3B82F6' }, { label: '上次维护', value: detail.last_maintenance ? new Date(detail.last_maintenance).toLocaleDateString('zh-CN') : '--', color: '#94A3B8' }, { label: '机型', value: detail.model || '--', color: '#22D3EE' }, { label: '区域', value: detail.region, color: '#94A3B8' }].map((item) => (
                    <div key={item.label} className="premium-card rounded-xl p-3.5"><p className="text-[10px] text-text-muted mb-1">{item.label}</p><p className="text-sm font-bold" style={{ color: item.color, fontFamily: "'SF Mono', 'JetBrains Mono', monospace" }}>{item.value}</p></div>
                  ))}
                </div>
                <div className="space-y-2.5 pt-1">
                  <Link to={`/turbine/${detail.id}`} className="flex items-center justify-center gap-2 w-full py-3 rounded-xl text-[13px] font-semibold transition-all duration-200 hover:brightness-110" style={{ background: 'linear-gradient(135deg, #3B82F6, #2563EB)', color: '#fff', boxShadow: '0 4px 16px rgba(59,130,246,0.3)' }}>查看单机详情<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12h14M12 5l7 7-7 7" /></svg></Link>
                  <Link to="/workorder" className="flex items-center justify-center w-full py-3 rounded-xl text-[13px] font-medium text-text-secondary transition-all duration-200 hover:text-white" style={{ border: '1px solid rgba(59,130,246,0.15)', background: 'rgba(59,130,246,0.04)' }}>+ 创建维修工单</Link>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══ Bottom Dashboard Grid ═══ */}
      <div className="flex-shrink-0 px-4 pb-5">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_300px] gap-4" style={{ height: '280px' }}>
          {/* Column 1: Health Monitoring */}
          <div className="premium-card rounded-2xl p-4 flex flex-col overflow-hidden">
            <div className="flex items-center justify-between mb-3"><h3 className="text-[13px] font-semibold text-text-primary">风机健康监测</h3><span className="text-[10px] text-text-muted">{scopedTurbines.length} 台风机</span></div>
            <div className="flex justify-around mb-4">
              <HealthRing value={avgHealth} label="平均健康" />
              <HealthRing value={scopedTurbines.length > 0 ? (stats.healthy / scopedTurbines.length) * 100 : 0} label="正常率" />
              <HealthRing value={100 - (stats.faulty / Math.max(1, scopedTurbines.length)) * 100} label="无故障率" />
            </div>
            <div className="mt-auto"><p className="text-[10px] text-text-muted mb-2 uppercase tracking-wide">关键部件温度</p>
              <div className="grid grid-cols-2 gap-2">{componentTemps.map((comp) => (<ComponentHealthCard key={comp.label} {...comp} />))}</div>
            </div>
          </div>

          {/* Column 2: Alarms + Work Orders */}
          <div className="flex flex-col gap-3 overflow-hidden">
            <div className="premium-card rounded-2xl p-4 flex-1 flex flex-col overflow-hidden">
              <div className="flex items-center justify-between mb-3"><h3 className="text-[13px] font-semibold text-text-primary">实时告警中心</h3><span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: 'rgba(239,68,68,0.12)', color: '#EF4444' }}>{alarms.filter((a) => a.severity === 'critical').length} 严重</span></div>
              <div className="flex-1 space-y-1.5 overflow-auto">{alarms.map((a) => (<AlarmItem key={a.id} {...a} />))}</div>
            </div>
            <div className="premium-card rounded-2xl p-4 flex-1 flex flex-col overflow-hidden">
              <div className="flex items-center justify-between mb-3"><h3 className="text-[13px] font-semibold text-text-primary">维修工单</h3><Link to="/workorder" className="text-[10px] text-accent-blue hover:underline">查看全部 →</Link></div>
              <div className="flex-1 space-y-0.5 overflow-auto">{workOrders.map((wo) => (<WorkOrderPreview key={wo.id} {...wo} />))}</div>
            </div>
          </div>

          {/* Column 3: SCADA Charts */}
          <div className="premium-card rounded-2xl p-4 flex flex-col overflow-visible">
            <div className="flex items-center justify-between mb-3"><h3 className="text-[13px] font-semibold text-text-primary">SCADA 数据趋势</h3><span className="text-[10px] text-text-muted">近24小时</span></div>
            <div className="flex-1 grid grid-rows-3 gap-3" style={{ minHeight: 0 }}>
              <ScadaTrendChart title="风速趋势" data={windSpeedData} color="#22D3EE" unit="m/s" height={76} />
              <ScadaTrendChart title="发电功率" data={powerData} color="#3B82F6" unit="kW" height={76} />
              <ScadaTrendChart title="齿轮箱温度" data={tempData} color="#F59E0B" unit="°C" height={76} />
            </div>
          </div>

          {/* Column 4: AI Summary */}
          <div className="premium-card rounded-2xl min-h-0 overflow-hidden">
            <AIPanel pageType="dashboard" pageData={aiSummaryData} />
          </div>
        </div>
      </div>

      <CopilotFAB />
    </div>
  );
}
