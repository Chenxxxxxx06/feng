import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import * as echarts from '../../services/echarts';
import api from '../../services/api';
import TurbineMap from '../../components/Map/TurbineMap';
import FilterPanel from '../../components/Common/FilterPanel';
import AIPanel from '../../components/AIAssistant/AIPanel';
import AnimatedNumber from '../../components/Common/AnimatedNumber';
import DataSourceNotice from '../../components/Common/DataSourceNotice';
import StateBlock from '../../components/Common/StateBlock';
import { Skeleton, SkeletonList, SkeletonChart } from '../../components/Common/Skeleton';
import { fetchUserPreferences, loadLocalPreferences, PREFERENCES_UPDATED_EVENT, type UserPreferences } from '../../services/preferences';
import type { DataProvenance } from '../../services/dataProvenance';
import type { TurbineSummary, TurbineDetail, WorkOrder, Fault } from '../../types';

const EMPTY_SUMMARY: TurbineSummary = { turbines: [], total: 0, healthy: 0, warning: 0, faulty: 0 };
const STATUS_COLORS = { normal: '#10B981', warning: '#F59E0B', fault: '#EF4444' } as const;

interface ThresholdAlertStatus {
  threshold: number;
  low_count: number;
  turbines: Array<{ id: number; name: string; region: string | null; status: string; hi_value: number; model: string | null }>;
  checked_at: string;
}

interface TrendPoint {
  time: string;
  value: number;
}

interface ComponentTempItem {
  label: string;
  temperature: number;
  maxTemp: number;
  unit?: string | null;
  status: 'normal' | 'warning' | 'fault';
}

/** GET /api/turbines/dashboard-aggregate —— 全部字段由真实 SCADA 记录聚合得到 */
interface DashboardAggregate extends DataProvenance {
  total_turbines: number;
  component_temps: ComponentTempItem[];
  scada_trends: { wind_speed_ms: TrendPoint[]; power_kw: TrendPoint[]; gearbox_temp_c: TrendPoint[] };
  total_power_kw: number;
  today_energy_kwh: number;
  data_available: boolean;
  data_window?: string | null;
  latest_data_ts?: string | null;
}

type LoadState = 'loading' | 'ready' | 'error';
type PanelStatus = 'loading' | 'error' | 'empty';

function fmtDateTime(value?: string | null): string {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '--';
  return parsed.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function faultSeverity(priority?: string | null): 'critical' | 'warning' | 'info' {
  if (priority === 'urgent' || priority === 'high') return 'critical';
  if (priority === 'medium') return 'warning';
  return 'info';
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

/* ── Premium KPI Card（数字带计数动画） ── */
function KPICard({ label, value, numeric, decimals = 0, unit, color, trend, hint, className = '' }: {
  label: string;
  /** 非数值型 KPI 直接给字符串；数值型请用 numeric 以启用计数动画 */
  value?: string;
  numeric?: number | null;
  decimals?: number;
  unit: string;
  color: string;
  trend?: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div
      className={`premium-card surface-card-hover rounded-2xl px-4 py-3.5 flex items-center gap-3.5 cursor-default group ${className}`}
      style={{ minHeight: '72px' }}
      title={hint || `${label}${typeof numeric === 'number' ? `：${numeric.toFixed(decimals)}${unit}` : ''}`}
    >
      <div className="w-1 h-11 rounded-full flex-shrink-0 transition-all duration-300 group-hover:h-[52px]" style={{ background: `linear-gradient(180deg, ${color} 0%, ${color}44 100%)`, boxShadow: `0 0 12px ${color}33` }} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-semibold text-text-muted mb-1 tracking-[0.06em] uppercase truncate" title={label}>{label}</p>
        <p className="num text-[24px] font-bold tracking-tight leading-none" style={{ color }}>
          {typeof numeric === 'number' || numeric === null
            ? <AnimatedNumber value={numeric} decimals={decimals} />
            : value}
          {unit && <span className="text-[12px] font-medium text-text-muted ml-1.5 align-baseline" style={{ fontFamily: 'var(--font-sans)' }}>{unit}</span>}
        </p>
      </div>
      {trend && <span className="text-accent-red text-xs" aria-hidden="true">↑</span>}
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
    <div className="flex flex-col items-center gap-1.5" role="img" aria-label={`${label} ${value.toFixed(0)}%`} title={`${label}：${value.toFixed(1)}%`}>
      <svg width={size} height={size} className="transform -rotate-90" aria-hidden="true">
        <defs><linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stopColor={color} stopOpacity="0.3" /><stop offset="100%" stopColor={color} /></linearGradient></defs>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeOpacity="0.12" strokeWidth={strokeWidth} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={`url(#${gid})`} strokeWidth={strokeWidth} strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} className="health-ring-circle" style={{ filter: `drop-shadow(0 0 6px ${color}55)` }} />
      </svg>
      <span className="num text-xs font-bold" style={{ color }}><AnimatedNumber value={value} decimals={0} /></span>
      <span className="text-[10px] text-text-muted leading-tight text-center">{label}</span>
    </div>
  );
}

/* ── Panel Loading / Error / Empty State（加载态用骨架屏，形状贴近真实内容） ── */
function PanelState({ status, onRetry, emptyText = '暂无数据', emptyDesc, skeleton }: {
  status: PanelStatus;
  onRetry?: () => void;
  emptyText?: string;
  emptyDesc?: string;
  skeleton?: ReactNode;
}) {
  if (status === 'loading') {
    return <div className="flex-1 min-h-0 overflow-hidden">{skeleton ?? <SkeletonList rows={3} />}</div>;
  }
  if (status === 'error') {
    return (
      <div className="flex-1 flex items-center justify-center">
        <StateBlock kind="error" desc="接口未返回数据，请检查后端服务后重试。" onRetry={onRetry} compact />
      </div>
    );
  }
  return (
    <div className="flex-1 flex items-center justify-center">
      <StateBlock kind="empty" title={emptyText} desc={emptyDesc} compact />
    </div>
  );
}

/* ── Alarm Item ── */
function AlarmItem({ title, turbine, severity, time }: { title: string; turbine: string; severity: 'critical' | 'warning' | 'info'; time: string }) {
  const c = severity === 'critical'
    ? { bg: 'rgba(239,68,68,0.10)', border: '#EF4444', dot: '#EF4444', label: '严重', pulse: 'status-dot-danger' }
    : severity === 'warning'
      ? { bg: 'rgba(245,158,11,0.10)', border: '#F59E0B', dot: '#F59E0B', label: '预警', pulse: 'status-dot-warning' }
      : { bg: 'rgba(59,130,246,0.10)', border: '#3B82F6', dot: '#3B82F6', label: '提示', pulse: '' };
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2 rounded-xl transition-all duration-200 hover:bg-bg-hover"
      style={{ background: c.bg, borderLeft: `3px solid ${c.border}` }}
      title={`【${c.label}】${title} — ${turbine}`}
    >
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${c.pulse}`} style={{ background: c.dot, boxShadow: `0 0 6px ${c.dot}` }} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-medium text-text-primary truncate"><span className="sr-only">{c.label}：</span>{title}</p>
        <p className="text-[10px] text-text-muted truncate">{turbine}</p>
      </div>
      <span className="num text-[10px] text-text-muted flex-shrink-0">{time}</span>
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
  return <div className="flex flex-col"><div className="flex items-center justify-between mb-1"><p className="text-[11px] font-medium text-text-secondary">{title}</p><span className="text-[10px] text-text-muted">{unit}</span></div><div ref={ref} style={{ height }} role="img" aria-label={`${title}趋势图（单位 ${unit}）`} /></div>;
}

/* ── Work Order Preview ── */
function WorkOrderPreview({ id, title, status, priority, assignee }: { id: number; title: string; status: string; priority?: string | null; assignee: string | null }) {
  const sc: Record<string, { label: string; color: string }> = { pending: { label: '待分配', color: '#EF4444' }, assigned: { label: '已分配', color: '#F59E0B' }, in_progress: { label: '执行中', color: '#3B82F6' }, review: { label: '待验收', color: '#F59E0B' }, completed: { label: '已完成', color: '#10B981' }, closed: { label: '已关闭', color: '#64748B' }, cancelled: { label: '已取消', color: '#64748B' } };
  const s = sc[status] || { label: status, color: '#64748B' };
  const priorityLabel: Record<string, string> = { urgent: '紧急', high: '高', medium: '中', low: '低' };
  return (
    <Link to="/workorder" className="flex items-center gap-2.5 px-3 py-2 rounded-xl transition-all duration-200 hover:bg-bg-hover group" title={`WO-${String(id).padStart(4, '0')} ${title} · ${s.label}`}>
      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: s.color, boxShadow: `0 0 6px ${s.color}` }} aria-hidden="true" />
      <div className="flex-1 min-w-0"><p className="text-[12px] font-medium text-text-primary truncate group-hover:text-white transition-colors"><span className="num">WO-{String(id).padStart(4, '0')}</span> {title}</p><p className="text-[10px] text-text-muted truncate">{assignee || '待分配'} · {s.label}</p></div>
      <span className="badge flex-shrink-0" style={{ background: `${s.color}18`, borderColor: `${s.color}44`, color: s.color }}>{priorityLabel[priority || ''] || '--'}</span>
    </Link>
  );
}

/* ── Component Health Card ── */
function ComponentHealthCard({ label, temperature, maxTemp, unit, status }: ComponentTempItem) {
  const pct = maxTemp > 0 ? Math.min(100, Math.max(0, (temperature / maxTemp) * 100)) : 0;
  const color = status === 'normal' ? '#10B981' : status === 'warning' ? '#F59E0B' : '#EF4444';
  const statusLabel = status === 'normal' ? '正常' : status === 'warning' ? '预警' : '故障';
  return (
    <div
      className="px-3 py-2 rounded-xl transition-all duration-200 hover:bg-bg-hover/50"
      style={{ border: '1px solid rgba(59,130,246,0.08)' }}
      title={`${label}：${temperature.toFixed(1)}${unit || '°C'}（上限 ${maxTemp}${unit || '°C'}，状态${statusLabel}）`}
    >
      <div className="flex items-center justify-between gap-2 mb-1"><span className="text-[11px] text-text-secondary truncate">{label}</span><span className="w-1.5 h-1.5 flex-shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} aria-hidden="true" /></div>
      <p className="num text-[17px] font-bold leading-tight" style={{ color }}>{temperature.toFixed(1)}<span className="text-[11px] font-medium text-text-muted ml-0.5" style={{ fontFamily: 'var(--font-sans)' }}>{unit || '°C'}</span></p>
      <div className="mt-1.5 h-1 rounded-full" style={{ background: 'rgba(59,130,246,0.10)' }} role="presentation"><div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} /></div>
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
  const [thresholdState, setThresholdState] = useState<LoadState>('loading');
  const [aggregate, setAggregate] = useState<DashboardAggregate | null>(null);
  const [aggregateState, setAggregateState] = useState<LoadState>('loading');
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [workOrderState, setWorkOrderState] = useState<LoadState>('loading');
  const [faults, setFaults] = useState<Fault[]>([]);
  const [faultState, setFaultState] = useState<LoadState>('loading');
  const [riskFirst, setRiskFirst] = useState(() => loadLocalPreferences().riskFirst);

  // Request sequence guard: a slow stale response must not overwrite a newer one
  const fetchSeqRef = useRef(0);
  const fetchData = async () => { const seq = ++fetchSeqRef.current; setLoading(true); try { const params = new URLSearchParams(filters); const { data } = await api.get(`/turbines/?${params}`); if (seq === fetchSeqRef.current) setSummary(data); } catch { if (seq === fetchSeqRef.current) setSummary(EMPTY_SUMMARY); } finally { if (seq === fetchSeqRef.current) setLoading(false); } };
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

  const loadThresholdAlerts = useCallback(async () => {
    setThresholdState('loading');
    try {
      const { data } = await api.get<ThresholdAlertStatus>('/settings/threshold-alerts');
      setThresholdAlerts(data);
      setThresholdState('ready');
    } catch {
      setThresholdAlerts(null);
      setThresholdState('error');
    }
  }, []);

  useEffect(() => {
    loadThresholdAlerts();
    window.addEventListener('threshold-alerts-updated', loadThresholdAlerts);
    return () => window.removeEventListener('threshold-alerts-updated', loadThresholdAlerts);
  }, [loadThresholdAlerts]);

  // ── Real SCADA aggregate: component temps / 24h trends / power / energy ──
  const loadAggregate = useCallback(async () => {
    setAggregateState('loading');
    try {
      // Heavy server-side aggregation over the imported SCADA dataset (cached 60s)
      const { data } = await api.get<DashboardAggregate>('/turbines/dashboard-aggregate', { timeout: 60000 });
      setAggregate(data);
      setAggregateState('ready');
    } catch {
      setAggregate(null);
      setAggregateState('error');
    }
  }, []);
  useEffect(() => { loadAggregate(); }, [loadAggregate]);

  // ── Real work orders ──
  const loadWorkOrders = useCallback(async () => {
    setWorkOrderState('loading');
    try {
      const { data } = await api.get<WorkOrder[]>('/workorders/');
      setWorkOrders(Array.isArray(data) ? data : []);
      setWorkOrderState('ready');
    } catch {
      setWorkOrders([]);
      setWorkOrderState('error');
    }
  }, []);
  useEffect(() => { loadWorkOrders(); }, [loadWorkOrders]);

  // ── Real faults (diagnosis) ──
  const loadFaults = useCallback(async () => {
    setFaultState('loading');
    try {
      const { data } = await api.get<Fault[]>('/diagnosis/faults');
      setFaults(Array.isArray(data) ? data : []);
      setFaultState('ready');
    } catch {
      setFaults([]);
      setFaultState('error');
    }
  }, []);
  useEffect(() => { loadFaults(); }, [loadFaults]);

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

  // ── SCADA trends / component temps: 100% from GET /turbines/dashboard-aggregate ──
  const windSpeedData = aggregate?.scada_trends?.wind_speed_ms ?? [];
  const powerData = aggregate?.scada_trends?.power_kw ?? [];
  const tempData = aggregate?.scada_trends?.gearbox_temp_c ?? [];
  const componentTemps = aggregate?.component_temps ?? [];
  const scadaPanelStatus: PanelStatus | null =
    aggregateState === 'loading' ? 'loading'
      : aggregateState === 'error' ? 'error'
        : windSpeedData.length + powerData.length + tempData.length === 0 ? 'empty'
          : null;
  const componentPanelStatus: PanelStatus | null =
    aggregateState === 'loading' ? 'loading'
      : aggregateState === 'error' ? 'error'
        : componentTemps.length === 0 ? 'empty'
          : null;
  const scadaWindowLabel = aggregateState !== 'ready' || !aggregate?.data_available
    ? '--'
    : aggregate.data_window === 'recent_24h' ? '数据集近24小时' : '数据集最新样本';
  const scadaWindowHint = aggregate?.latest_data_ts ? `数据集最新时间 ${fmtDateTime(aggregate.latest_data_ts)}` : '';

  // ── Alarms: HI threshold alerts (/settings/threshold-alerts) + faults (/diagnosis/faults) ──
  const alarms = useMemo(() => {
    const thresholdTime = fmtDateTime(thresholdAlerts?.checked_at);
    const hiAlarms = (thresholdAlerts?.turbines || []).map((turbine) => ({
      id: `hi-${turbine.id}`,
      title: `HI低于阈值 ${thresholdAlerts?.threshold ?? '--'}`,
      turbine: `${turbine.name} · ${turbine.region || '-'} · HI ${turbine.hi_value.toFixed(1)}`,
      severity: 'critical' as const,
      time: thresholdTime,
    }));
    const faultAlarms = faults.map((fault) => ({
      id: `fault-${fault.id}`,
      title: `${fault.fault_type} · 置信度 ${(fault.confidence * 100).toFixed(0)}%`,
      turbine: `${fault.turbine_name || `风机 #${fault.turbine_id}`} · ${fault.turbine_region || '-'}`,
      severity: faultSeverity(fault.priority),
      time: fmtDateTime(fault.detected_at),
    }));
    const combined = [...hiAlarms, ...faultAlarms];
    if (!riskFirst) return combined;
    const severityRank = (severity: string) => (severity === 'critical' ? 0 : severity === 'warning' ? 1 : 2);
    return combined.sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
  }, [faults, riskFirst, thresholdAlerts]);
  const alarmPanelStatus: PanelStatus | null =
    thresholdState === 'loading' || faultState === 'loading' ? 'loading'
      : alarms.length === 0 ? (thresholdState === 'error' || faultState === 'error' ? 'error' : 'empty')
        : null;
  const reloadAlarms = useCallback(() => { loadThresholdAlerts(); loadFaults(); }, [loadFaults, loadThresholdAlerts]);

  // ── Work orders: GET /workorders/ (latest first, server-side ordered) ──
  const workOrderPreview = useMemo(() => workOrders.slice(0, 4), [workOrders]);
  const workOrderPanelStatus: PanelStatus | null =
    workOrderState === 'loading' ? 'loading'
      : workOrderState === 'error' ? 'error'
        : workOrderPreview.length === 0 ? 'empty'
          : null;

  const avgHealth = scopedTurbines.length > 0 ? scopedTurbines.reduce((s, t) => s + t.hi_value, 0) / scopedTurbines.length : 0;
  // Power / energy come from the SCADA aggregate only — null when the dataset has no records.
  const currentPowerMw = aggregate?.data_available ? Number((aggregate.total_power_kw / 1000).toFixed(2)) : null;
  const todayEnergyMwh = aggregate?.data_available ? Number((aggregate.today_energy_kwh / 1000).toFixed(1)) : null;

  const aiSummaryData = useMemo(() => ({
    total_turbines: summary.total,
    healthy_turbines: healthy,
    warning_turbines: warning,
    faulty_turbines: faulty,
    availability: avail,
    mtbf_hours: mtbfHours,
    avg_health: avgHealth,
    current_power_mw: currentPowerMw,
    today_energy_mwh: todayEnergyMwh,
    scada_data_window: aggregate?.data_window ?? null,
    scada_latest_ts: aggregate?.latest_data_ts ?? null,
    alarm_total: alarms.length,
    alarms: alarms.slice(0, 10),
    work_orders: workOrderPreview.map((wo) => ({
      id: wo.id,
      title: wo.title,
      status: wo.status,
      priority: wo.priority ?? null,
      assignee: wo.assignee,
      turbine_id: wo.turbine_id,
      created_at: wo.created_at,
    })),
    component_temperatures: componentTemps,
    data_sources: {
      turbines: 'GET /api/turbines/',
      reliability: 'GET /api/turbines/monitoring-metrics',
      scada_aggregate: 'GET /api/turbines/dashboard-aggregate',
      threshold_alerts: 'GET /api/settings/threshold-alerts',
      faults: 'GET /api/diagnosis/faults',
      work_orders: 'GET /api/workorders/',
    },
  }), [aggregate, alarms, avail, avgHealth, componentTemps, currentPowerMw, faulty, healthy, mtbfHours, summary.total, todayEnergyMwh, warning, workOrderPreview]);

  const closeDetail = useCallback(() => { setSelectedId(null); setDetail(null); }, []);

  return (
    <div className="page-enter h-full flex flex-col overflow-y-auto" style={{ background: 'radial-gradient(ellipse at 50% 20%, #0D2447 0%, #071A35 70%)' }}>
      {/* ═══ Top Header ═══ */}
      <header className="flex-shrink-0 px-4 py-2.5 flex items-center justify-between gap-4 flex-wrap border-b" style={{ borderColor: 'rgba(59,130,246,0.08)' }}>
        <div className="flex items-center gap-4 min-w-0">
          <div className="min-w-0">
            <h2 className="ops-title gradient-text mt-0">陕西省 · 风场监控中心</h2>
            <p className="text-[10px] text-text-muted mt-0.5">全场健康态势 · SCADA 为公开历史数据</p>
          </div>
          <span className="badge badge-info flex-shrink-0">共 <span className="num">{summary.total}</span> 台风机</span>
        </div>
        <div className="flex items-center gap-4">
          {(() => {
            const fleetColor = faulty > 0 ? '#EF4444' : warning > 0 ? '#F59E0B' : '#10B981';
            const fleetLabel = faulty > 0 ? `${faulty} 台风机故障` : warning > 0 ? `${warning} 台风机预警` : '无故障与预警风机';
            return (
              <span className="flex items-center gap-2 text-[12px] font-semibold" style={{ color: fleetColor }} role="status">
                <span className="relative flex h-2 w-2" aria-hidden="true"><span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: fleetColor }} /><span className="relative inline-flex rounded-full h-2 w-2" style={{ background: fleetColor }} /></span>{fleetLabel}
              </span>
            );
          })()}
          <span className="num text-[11px] text-text-muted" title="系统当前时间">{currentTime.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
        </div>
      </header>

      {aggregate && (
        <div className="flex-shrink-0 px-4 pt-2">
          <DataSourceNotice provenance={aggregate} />
        </div>
      )}

      {/* ═══ KPI Strip ═══ */}
      <section className="flex-shrink-0 px-4 pt-3 pb-2" aria-label="全场关键指标">
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          <KPICard className="stagger-1" label="风机可用率" numeric={summary.total > 0 ? ((healthy + warning) / summary.total) * 100 : null} decimals={1} unit="%" color="#3B82F6" hint={`在运（正常+预警）机组占比，当前 ${avail}%`} />
          <KPICard className="stagger-1" label="正常运行" numeric={healthy} unit="台" color="#10B981" hint="健康指数正常、无告警的机组数量" />
          <KPICard className="stagger-2" label="预警风机" numeric={warning} unit="台" color="#F59E0B" hint="健康指数下降、需关注的机组数量" />
          <KPICard className="stagger-2" label="故障风机" numeric={faulty} unit="台" color="#EF4444" trend={faulty > 0 ? 'up' : undefined} hint="已判定故障、需立即处置的机组数量" />
          <KPICard className="stagger-3" label="MTBF" value={mtbfHours != null ? fmtMtbf(mtbfHours) : '--'} unit="" color="#22D3EE" hint="平均无故障运行时间（Mean Time Between Failures）" />
        </div>
      </section>

      {/* ═══ Map ═══ */}
      <div className="flex-1 relative mx-2 my-3 rounded-2xl overflow-hidden stagger-4" style={{ border: '1px solid rgba(59,130,246,0.10)', boxShadow: 'inset 0 0 80px rgba(0,0,0,0.4), 0 4px 24px rgba(0,0,0,0.3)', minHeight: '320px' }}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center backdrop-blur-sm" style={{ background: 'rgba(7,26,53,0.7)' }} role="status" aria-live="polite">
            <div className="flex flex-col items-center gap-3"><span className="state-spinner" style={{ width: 32, height: 32 }} /><span className="text-text-muted text-xs font-medium">正在加载风机分布数据…</span></div>
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
                <div className="min-w-0"><h3 className="font-bold text-[15px] text-text-primary truncate" title={detail.name}>{detail.name}</h3><p className="text-[11px] text-text-muted mt-0.5 truncate" title={`${detail.region} · ${detail.model}`}>{detail.region} · {detail.model}</p></div>
                <button onClick={closeDetail} aria-label="关闭风机详情面板" title="关闭" className="w-8 h-8 flex-shrink-0 rounded-full flex items-center justify-center text-text-muted hover:text-white hover:bg-bg-hover transition-all" style={{ border: '1px solid rgba(59,130,246,0.12)' }}>
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
                      <p className="num text-3xl font-bold" style={{ color: hiColor(detail.hi_value) }}>
                        <AnimatedNumber value={detail.hi_value} decimals={0} />
                      </p>
                      <p className="text-[10px] text-text-muted font-medium">健康指数</p>
                    </div>
                  </div>
                  <p className={`text-xs font-semibold mt-3 ${detail.status === 'normal' ? 'text-accent-green' : detail.status === 'warning' ? 'text-accent-yellow' : 'text-accent-red'}`}>
                    {detail.status === 'normal' ? '● 正常运行' : detail.status === 'warning' ? '▲ 预警状态' : '■ 故障状态'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {[{ label: '额定功率', value: `${detail.power_mw} MW`, color: '#3B82F6' }, { label: '上次维护', value: detail.last_maintenance ? new Date(detail.last_maintenance).toLocaleDateString('zh-CN') : '--', color: '#94A3B8' }, { label: '机型', value: detail.model || '--', color: '#22D3EE' }, { label: '区域', value: detail.region, color: '#94A3B8' }].map((item) => (
                    <div key={item.label} className="premium-card rounded-xl p-3.5"><p className="field-label mb-1">{item.label}</p><p className="num truncate-cell text-sm font-bold" style={{ color: item.color }} title={item.value}>{item.value}</p></div>
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
        <div className="grid items-start gap-3 grid-cols-1 md:grid-cols-2 xl:gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(256px,300px)]">
          {/* Column 1: Health Monitoring */}
          <section className="premium-card stagger-5 h-[360px] rounded-2xl p-4 flex flex-col overflow-hidden" aria-label="风机健康监测">
            <div className="flex items-center justify-between gap-2 mb-3"><h3 className="section-title">风机健康监测</h3><span className="field-label"><span className="num">{scopedTurbines.length}</span> 台风机</span></div>
            <div className="flex justify-around mb-4">
              <HealthRing value={avgHealth} label="平均健康" />
              <HealthRing value={scopedTurbines.length > 0 ? (stats.healthy / scopedTurbines.length) * 100 : 0} label="正常率" />
              <HealthRing value={100 - (stats.faulty / Math.max(1, scopedTurbines.length)) * 100} label="无故障率" />
            </div>
            <div className="mt-auto flex flex-col min-h-0">
              <div className="flex items-center justify-between gap-2 mb-2"><p className="field-label uppercase">关键部件温度</p><span className="field-label truncate" title={scadaWindowHint || 'SCADA 最新记录均值'}>SCADA 最新记录均值</span></div>
              {componentPanelStatus
                ? <PanelState status={componentPanelStatus} onRetry={loadAggregate} emptyText="暂无部件温度数据" emptyDesc="SCADA 数据集尚未导入或该时间窗内无记录。" skeleton={<div className="grid grid-cols-2 gap-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={64} radius={12} />)}</div>} />
                : <div className="grid grid-cols-2 gap-2">{componentTemps.map((comp) => (<ComponentHealthCard key={comp.label} {...comp} />))}</div>}
            </div>
          </section>

          {/* Column 2: Alarms + Work Orders */}
          <div className="h-[360px] flex flex-col gap-3 overflow-hidden stagger-5">
            <section className="premium-card rounded-2xl p-4 flex-1 flex flex-col overflow-hidden" aria-label="告警中心">
              <div className="flex items-center justify-between gap-2 mb-3">
                <h3 className="section-title">告警中心</h3>
                {(() => {
                  const critical = alarms.filter((a) => a.severity === 'critical').length;
                  return <span className={`badge ${critical > 0 ? 'badge-danger badge-pulse' : 'badge-neutral'}`}><span className="num">{critical}</span> 严重</span>;
                })()}
              </div>
              {alarmPanelStatus
                ? <PanelState status={alarmPanelStatus} onRetry={reloadAlarms} emptyText="暂无告警" emptyDesc="全场机组健康指数均高于阈值，无未处理故障。" />
                : <div className="flex-1 space-y-1.5 overflow-auto">{alarms.map((a) => (<AlarmItem key={a.id} {...a} />))}</div>}
            </section>
            <section className="premium-card rounded-2xl p-4 flex-1 flex flex-col overflow-hidden" aria-label="维修工单">
              <div className="flex items-center justify-between gap-2 mb-3"><h3 className="section-title">维修工单</h3><Link to="/workorder" className="text-[10px] font-medium text-accent-blue hover:underline">查看全部 →</Link></div>
              {workOrderPanelStatus
                ? <PanelState status={workOrderPanelStatus} onRetry={loadWorkOrders} emptyText="暂无工单" emptyDesc="当前没有待处理的维修工单。" />
                : <div className="flex-1 space-y-0.5 overflow-auto">{workOrderPreview.map((wo) => (<WorkOrderPreview key={wo.id} id={wo.id} title={wo.title} status={wo.status} priority={wo.priority} assignee={wo.assignee} />))}</div>}
            </section>
          </div>

          {/* Column 3: SCADA Charts */}
          <section className="premium-card stagger-5 h-[360px] rounded-2xl p-4 flex flex-col overflow-hidden" aria-label="SCADA 数据趋势">
            <div className="flex items-center justify-between gap-2 mb-3"><h3 className="section-title">SCADA 数据趋势</h3><span className="field-label truncate" title={scadaWindowHint || scadaWindowLabel}>{scadaWindowLabel}</span></div>
            {scadaPanelStatus
              ? <PanelState status={scadaPanelStatus} onRetry={loadAggregate} emptyText="暂无 SCADA 数据" emptyDesc="未检测到可用的 SCADA 时序记录。" skeleton={<div className="grid grid-rows-3 gap-3 h-full">{Array.from({ length: 3 }).map((_, i) => <SkeletonChart key={i} height={72} bars={16} />)}</div>} />
              : (
                <div className="flex-1 grid grid-rows-3 gap-3" style={{ minHeight: 0 }}>
                  <ScadaTrendChart title="风速趋势" data={windSpeedData} color="#22D3EE" unit="m/s" height={72} />
                  <ScadaTrendChart title="发电功率" data={powerData} color="#3B82F6" unit="kW" height={72} />
                  <ScadaTrendChart title="齿轮箱温度" data={tempData} color="#F59E0B" unit="°C" height={72} />
                </div>
              )}
          </section>

          {/* Column 4: AI Summary */}
          <section className="premium-card stagger-5 h-[360px] rounded-2xl min-h-0 overflow-hidden" aria-label="AI 全场摘要">
            <AIPanel pageType="dashboard" pageData={aiSummaryData} />
          </section>
        </div>
      </div>
    </div>
  );
}
