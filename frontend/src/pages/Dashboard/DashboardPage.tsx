import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import TurbineMap from '../../components/Map/TurbineMap';
import FilterPanel from '../../components/Common/FilterPanel';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import AIPanel from '../../components/AIAssistant/AIPanel';
import type { TurbineSummary, TurbineDetail } from '../../types';

export default function DashboardPage() {
  const [summary, setSummary] = useState<TurbineSummary>({ turbines: [], total: 0, healthy: 0, warning: 0, faulty: 0 });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<TurbineDetail | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [mtbfHours, setMtbfHours] = useState<number | null>(null);
  const [mttrHours, setMttrHours] = useState<number | null>(null);
  const [mttrSource, setMttrSource] = useState<string>('');
  const [currentTime, setCurrentTime] = useState(new Date());

  const fetchData = async () => {
    setLoading(true);
    const params = new URLSearchParams(filters);
    const { data } = await api.get(`/turbines/?${params}`);
    setSummary(data);
    setLoading(false);
  };
  useEffect(() => { fetchData(); }, [filters]);
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    api.get(`/turbines/${selectedId}`).then(({ data }) => setDetail(data));
  }, [selectedId]);

  // ── MTBF from CARE event files, MTTR from prediction formula ──
  useEffect(() => {
    let cancelled = false;
    const fetchMetrics = async () => {
      try {
        const { data } = await api.get('/turbines/monitoring-metrics');
        if (cancelled) return;
        if (data?.mtbf_hours != null) setMtbfHours(data.mtbf_hours);
      } catch { /* MTBF unavailable */ }
      try {
        const { data } = await api.get('/prediction/summary');
        if (cancelled) return;
        if (data?.reliability?.mttr_hours != null) {
          setMttrHours(data.reliability.mttr_hours);
          setMttrSource(' (估)');
        }
      } catch { /* MTTR unavailable */ }
    };
    fetchMetrics();
    return () => { cancelled = true; };
  }, []);

  // ── Clock refresh ──
  useEffect(() => {
    const t = setInterval(() => setCurrentTime(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const healthy = summary.turbines.filter((t) => t.status === 'normal').length;
  const warning = summary.turbines.filter((t) => t.status === 'warning').length;
  const faulty = summary.turbines.filter((t) => t.status === 'fault').length;
  const avail = summary.total > 0 ? ((healthy + warning) / summary.total * 100).toFixed(1) : '--';

  const fmtMtbf = (h: number | null) => {
    if (h == null) return '--';
    if (h >= 8760) return `${(h / 8760).toFixed(1)} 年`;
    if (h >= 720) return `${(h / 720).toFixed(0)} 月`;
    if (h >= 24) return `${(h / 24).toFixed(0)} 天`;
    return h.toFixed(0);
  };
  const fmtMttr = (h: number | null) => (h != null ? h.toFixed(1) : '--');

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: 'radial-gradient(ellipse at 50% 30%, #0f1a2e 0%, #080c12 70%)' }}>
      {/* ── Top Bar ── */}
      <div className="flex-shrink-0 px-6 py-3 flex items-center justify-between border-b border-border-subtle">
        <div className="flex items-center gap-4">
          <h2 className="text-base font-bold tracking-wide">
            <span className="gradient-text">陕西省 · 风场监控</span>
          </h2>
          <span className="text-[10px] text-text-muted bg-bg-card border border-border-subtle rounded-full px-2.5 py-0.5">
            共 {summary.total} 台风机
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-[11px] text-accent-green">
            <span className="w-2 h-2 rounded-full status-dot-live" />
            系统运行正常
          </span>
          <span className="text-[10px] text-text-muted">本地时间 {currentTime.toLocaleString('zh-CN')}</span>
        </div>
      </div>

      {/* ── KPI Strip ── */}
      <div className="flex-shrink-0 px-6 py-3">
        <div className="grid grid-cols-6 gap-3">
          <KPICard label="风机可用率" value={avail} unit="%" color="#388bfd" />
          <KPICard label="正常运行" value={String(healthy)} unit="台" color="#3fb950" />
          <KPICard label="预警风机" value={String(warning)} unit="台" color="#d29922" />
          <KPICard label="故障风机" value={String(faulty)} unit="台" color="#f85149" trend={faulty > 0 ? 'up' : undefined} />
          <KPICard label="MTBF" value={mtbfHours != null ? Math.round(mtbfHours).toLocaleString() : '--'} unit="h" color="#39d2c0" />
          <KPICard label="MTTR" value={fmtMttr(mttrHours)} unit={`h${mttrSource}`} color="#a371f7" />
        </div>
      </div>

      {/* ── MAIN: Map + Slide Panel ── */}
      <div className="flex-1 relative mx-6 mb-3 rounded-xl overflow-hidden border border-border-subtle" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-bg-deep/60 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
              <span className="text-text-muted text-xs">加载中...</span>
            </div>
          </div>
        )}
        <div className="absolute inset-0 z-0">
          <TurbineMap turbines={summary.turbines} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <div className="relative z-[700]">
          <FilterPanel filters={filters} onChange={setFilters} />
        </div>

        {/* Slide-out Detail Panel */}
        <div className={`absolute top-0 right-0 h-full w-[370px] glass-panel shadow-2xl transform transition-transform duration-300 z-[800] flex flex-col border-l border-border-subtle ${
          detail ? 'translate-x-0' : 'translate-x-full'
        }`}>
          {detail && (
            <div className="slide-panel h-full flex flex-col">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-subtle">
                <div>
                  <h3 className="font-bold text-sm">{detail.name}</h3>
                  <p className="text-[10px] text-text-muted">{detail.region} · {detail.model}</p>
                </div>
                <button onClick={() => { setSelectedId(null); setDetail(null); }}
                  className="w-7 h-7 rounded-full flex items-center justify-center text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors">✕</button>
              </div>
              <div className="flex-1 overflow-auto p-5 space-y-4">
                {/* HI Gauge */}
                <div className="text-center py-3">
                  <div className="inline-flex items-center justify-center w-24 h-24 rounded-full border-4 relative" style={{
                    borderColor: detail.hi_value >= 80 ? '#3fb950' : detail.hi_value >= 60 ? '#d29922' : '#f85149',
                    boxShadow: `0 0 24px ${detail.hi_value >= 80 ? 'rgba(63,185,80,0.3)' : detail.hi_value >= 60 ? 'rgba(210,153,34,0.3)' : 'rgba(248,81,73,0.3)'}`,
                    borderRightColor: 'transparent', borderBottomColor: 'transparent', transform: 'rotate(-45deg)',
                  }}>
                    <div style={{ transform: 'rotate(45deg)' }}>
                      <p className="text-2xl font-mono font-bold" style={{ color: detail.hi_value >= 80 ? '#3fb950' : detail.hi_value >= 60 ? '#d29922' : '#f85149' }}>
                        {detail.hi_value.toFixed(0)}
                      </p>
                      <p className="text-[9px] text-text-muted">HI</p>
                    </div>
                  </div>
                  <p className={`text-xs font-medium mt-2 ${detail.status === 'normal' ? 'text-accent-green' : detail.status === 'warning' ? 'text-accent-yellow' : 'text-accent-red'}`}>
                    {detail.status === 'normal' ? '● 正常运行' : detail.status === 'warning' ? '● 预警状态' : '● 故障状态'}
                  </p>
                </div>

                {/* Info Grid */}
                <div className="grid grid-cols-2 gap-2.5">
                  {[
                    ['额定功率', `${detail.power_mw} MW`, '#58a6ff'],
                    ['上次维护', detail.last_maintenance ? new Date(detail.last_maintenance).toLocaleDateString('zh-CN') : '暂无维护记录', '#8b949e'],
                  ].map(([l, v, c]) => (
                    <div key={l as string} className="industrial-card rounded-lg p-3">
                      <p className="text-[10px] text-text-muted mb-0.5">{l}</p>
                      <p className="font-mono text-sm font-bold" style={{ color: c as string }}>{v}</p>
                    </div>
                  ))}
                </div>

                {/* Quick Actions */}
                <div className="space-y-2 pt-1">
                  <Link to={`/turbine/${detail.id}`}
                    className="block w-full text-center py-2.5 rounded-lg text-xs font-medium transition-all"
                    style={{ background: 'rgba(56,139,253,0.1)', border: '1px solid rgba(56,139,253,0.3)', color: '#388bfd' }}>
                    查看单机详情 →
                  </Link>
                  <Link to="/workorder"
                    className="block w-full text-center py-2.5 rounded-lg text-xs text-text-secondary transition-all"
                    style={{ border: '1px solid rgba(143,162,188,0.15)' }}>
                    + 创建维修工单
                  </Link>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom Charts ── */}
      <div className="flex-shrink-0 px-6 pb-4">
        <div className="grid grid-cols-4 gap-3" style={{ height: '180px' }}>
          <QuickList turbines={summary.turbines} selectedId={selectedId} onSelect={setSelectedId} />
          <HIChartPanel turbines={summary.turbines} />
          <HealthPiePanel healthy={healthy} warning={warning} faulty={faulty} />
          <div className="rounded-xl border border-border-default bg-bg-card overflow-hidden">
            <AIPanel pageType="dashboard" />
          </div>
        </div>
      </div>

      <CopilotFAB pageContext={{
        turbine_id: selectedId ?? undefined,
        turbine_name: detail?.name,
        total_turbines: summary.total,
        healthy, warning, faulty,
      }} />
    </div>
  );
}

/* ── KPI Card ── */
function KPICard({ label, value, unit, color, trend }: { label: string; value: string; unit: string; color: string; trend?: string }) {
  return (
    <div className="industrial-card rounded-xl px-4 py-3 flex items-center gap-3.5 transition-all duration-300 hover:scale-[1.02]">
      <div className="w-1 h-10 rounded-full flex-shrink-0" style={{ background: `linear-gradient(180deg, ${color}, transparent)` }} />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-text-muted mb-0.5">{label}</p>
        <p className="kpi-value text-xl font-mono font-bold tracking-tight" style={{ color }}>
          {value}
          <span className="text-[11px] font-normal text-text-muted ml-1">{unit}</span>
        </p>
      </div>
      {trend && <span className="text-accent-red text-xs">↑</span>}
    </div>
  );
}

/* ── Quick Turbine List ── */
function QuickList({ turbines, selectedId, onSelect }: { turbines: TurbineDetail[]; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <div className="industrial-card rounded-xl p-3 flex flex-col overflow-hidden">
      <p className="text-[11px] font-medium text-text-secondary mb-2">风机快查</p>
      <div className="flex-1 overflow-auto space-y-0.5">
        {turbines.slice(0, 8).map((t) => (
          <div key={t.id} onClick={() => onSelect(t.id)}
            className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-[11px] transition-all ${
              selectedId === t.id ? 'bg-bg-hover' : 'hover:bg-bg-hover/50'
            }`}>
            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: t.status === 'normal' ? '#3fb950' : t.status === 'warning' ? '#d29922' : '#f85149' }} />
            <span className="w-14 font-medium truncate">{t.name}</span>
            <span className="text-text-muted flex-1 truncate text-[10px]">{t.model}</span>
            <span className="font-mono font-bold text-[12px]" style={{ color: t.hi_value >= 80 ? '#3fb950' : t.hi_value >= 60 ? '#d29922' : '#f85149' }}>
              {t.hi_value.toFixed(0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── HI Bar Chart ── */
function HIChartPanel({ turbines }: { turbines: TurbineDetail[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !turbines.length) return;
    const chart = echarts.init(ref.current, 'dark');
    const data = turbines.slice(0, 12).sort((a, b) => b.hi_value - a.hi_value);
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 18, right: 8, bottom: 22, left: 32 },
      xAxis: { type: 'category', data: data.map((t) => t.name), axisLabel: { color: '#54657e', fontSize: 8, rotate: 30 }, axisLine: { lineStyle: { color: 'rgba(56,139,253,0.15)' } } },
      yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: 'rgba(56,139,253,0.08)' } }, axisLabel: { color: '#54657e', fontSize: 9 } },
      series: [{
        type: 'bar', barWidth: 14,
        data: data.map((t) => ({ value: t.hi_value, itemStyle: { color: t.hi_value >= 80 ? '#3fb950' : t.hi_value >= 60 ? '#d29922' : '#f85149', borderRadius: [3, 3, 0, 0] } })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#f85149', type: 'dashed', width: 1 }, label: { color: '#f85149', fontSize: 8 }, data: [{ yAxis: 60, label: { formatter: '告警线' } }] },
      }],
    });
    return () => chart.dispose();
  }, [turbines]);
  return (
    <div className="industrial-card rounded-xl p-3 flex flex-col overflow-hidden">
      <p className="text-[11px] font-medium text-text-secondary mb-1">HI 健康指数</p>
      <div ref={ref} className="flex-1" />
    </div>
  );
}

/* ── Health Pie ── */
function HealthPiePanel({ healthy, warning, faulty }: { healthy: number; warning: number; faulty: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, 'dark');
    chart.setOption({
      backgroundColor: 'transparent',
      series: [{
        type: 'pie', radius: ['55%', '78%'], center: ['50%', '55%'],
        itemStyle: { borderRadius: 4, borderColor: '#080c12', borderWidth: 3 },
        label: { show: false },
        data: [
          { value: healthy, name: '正常', itemStyle: { color: '#3fb950' } },
          { value: warning, name: '预警', itemStyle: { color: '#d29922' } },
          { value: faulty, name: '故障', itemStyle: { color: '#f85149' } },
        ],
      }],
    });
    return () => chart.dispose();
  }, [healthy, warning, faulty]);
  return (
    <div className="industrial-card rounded-xl p-3 flex flex-col overflow-hidden">
      <p className="text-[11px] font-medium text-text-secondary mb-1">健康分布</p>
      <div ref={ref} className="flex-1" />
      <div className="flex justify-center gap-5 text-[9px] text-text-muted">
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-green" />{healthy} 正常</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-yellow" />{warning} 预警</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-red" />{faulty} 故障</span>
      </div>
    </div>
  );
}
