import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import TurbineMap from '../../components/Map/TurbineMap';
import FilterPanel from '../../components/Common/FilterPanel';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import type { TurbineSummary, TurbineDetail } from '../../types';

const echartsDark = 'dark';

export default function DashboardPage() {
  const [summary, setSummary] = useState<TurbineSummary>({ turbines: [], total: 0, healthy: 0, warning: 0, faulty: 0 });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<TurbineDetail | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    const params = new URLSearchParams(filters);
    const { data } = await api.get(`/turbines/?${params}`);
    setSummary(data); setLoading(false);
  };
  useEffect(() => { fetchData(); }, [filters]);
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    api.get(`/turbines/${selectedId}`).then(({ data }) => setDetail(data));
  }, [selectedId]);

  const healthy = summary.turbines.filter(t => t.status === 'normal').length;
  const warning = summary.turbines.filter(t => t.status === 'warning').length;
  const faulty = summary.turbines.filter(t => t.status === 'fault').length;
  const avail = summary.total > 0 ? ((healthy + warning) / summary.total * 100).toFixed(1) : '--';

  return (
    <div className="h-full flex flex-col overflow-hidden relative" style={{ background: '#020204' }}>
      {/* ── Command Bar ── */}
      <div className="flex-shrink-0 px-5 py-3 flex items-center justify-between relative z-10"
        style={{ borderBottom: '1px solid rgba(0,229,255,0.12)', background: '#0A0C10' }}>
        <div className="flex items-center gap-4">
          <span className="font-mono text-[10px] tracking-widest" style={{ color: '#00E5FF' }}>[01]</span>
          <h2 className="text-sm font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
            SHANXI_WIND_FARM :: MONITOR
          </h2>
          <span className="chip">{summary.total} TURBINES</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ background: '#00E676', boxShadow: '0 0 6px rgba(0,230,118,0.5)' }} />
            <span className="font-mono text-[10px] tracking-wider" style={{ color: '#00E676' }}>SYS::NOMINAL</span>
          </div>
          <span className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
            {new Date().toISOString().replace('T', ' ').slice(0, 19)} UTC
          </span>
        </div>
      </div>

      {/* ── KPI Strip ── */}
      <div className="flex-shrink-0 px-5 py-3 relative z-10">
        <div className="grid grid-cols-6 gap-3">
          <KPICard label="AVAILABILITY" value={avail} unit="%" accent="cyan" />
          <KPICard label="NOMINAL" value={String(healthy)} unit="UNIT" accent="green" />
          <KPICard label="WARNING" value={String(warning)} unit="UNIT" accent="amber" />
          <KPICard label="FAULT" value={String(faulty)} unit="UNIT" accent="red" />
          <KPICard label="MTBF" value="2,340" unit="H" accent="blue" />
          <KPICard label="MTTR" value="4.2" unit="H" accent="blue" />
        </div>
      </div>

      {/* ── Map Area + Slide-out ── */}
      <div className="flex-1 relative mx-5 mb-3 overflow-hidden relative z-10"
        style={{ border: '1px solid rgba(0,229,255,0.12)', borderRadius: '2px' }}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center"
            style={{ background: 'rgba(2,2,4,0.7)', backdropFilter: 'blur(4px)' }}>
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
                style={{ borderColor: 'rgba(0,229,255,0.15)', borderTopColor: '#00E5FF' }} />
              <span className="font-mono text-[10px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>
                LOADING_TELEMETRY...
              </span>
            </div>
          </div>
        )}
        <TurbineMap turbines={summary.turbines} selectedId={selectedId} onSelect={setSelectedId} />
        <FilterPanel filters={filters} onChange={setFilters} />

        {/* Slide Detail Panel */}
        <div className={`absolute top-0 right-0 h-full w-[380px] transform transition-transform z-10 flex flex-col ${
          detail ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{
          background: 'rgba(17,20,28,0.94)',
          backdropFilter: 'blur(12px)',
          borderLeft: '1px solid rgba(0,229,255,0.15)',
          boxShadow: '0 0 40px rgba(0,0,0,0.7)',
        }}>
          {detail && (
            <div className="slide-right h-full flex flex-col">
              {/* Panel header */}
              <div className="flex items-center justify-between px-5 py-3.5 flex-shrink-0"
                style={{ borderBottom: '1px solid rgba(0,229,255,0.12)' }}>
                <div>
                  <h3 className="font-semibold text-sm font-display tracking-wider" style={{ color: '#E8ECF1' }}>
                    {detail.name}
                  </h3>
                  <p className="font-mono text-[9px] tracking-wider mt-0.5" style={{ color: '#445566' }}>
                    {detail.region} :: {detail.model}
                  </p>
                </div>
                <button onClick={() => { setSelectedId(null); setDetail(null); }}
                  className="w-6 h-6 flex items-center justify-center transition-colors"
                  style={{ color: '#445566' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = '#E8ECF1')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = '#445566')}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>

              <div className="flex-1 overflow-auto p-5 space-y-5">
                {/* HI Ring */}
                <div className="text-center py-2">
                  <div className="inline-flex items-center justify-center w-28 h-28 rounded-full relative"
                    style={{
                      border: `3px solid ${detail.hi_value >= 80 ? '#00E676' : detail.hi_value >= 60 ? '#FF9100' : '#FF1744'}`,
                      boxShadow: `0 0 30px ${detail.hi_value >= 80 ? 'rgba(0,230,118,0.2)' : detail.hi_value >= 60 ? 'rgba(255,145,0,0.2)' : 'rgba(255,23,68,0.2)'}`,
                    }}>
                    <div>
                      <p className="kpi-value" style={{
                        color: detail.hi_value >= 80 ? '#00E676' : detail.hi_value >= 60 ? '#FF9100' : '#FF1744',
                      }}>
                        {detail.hi_value.toFixed(0)}
                      </p>
                      <p className="font-mono text-[8px] uppercase tracking-widest mt-1" style={{ color: '#445566' }}>
                        HEALTH_IDX
                      </p>
                    </div>
                  </div>
                  <p className="font-mono text-[10px] font-medium mt-3 tracking-wider" style={{
                    color: detail.status === 'normal' ? '#00E676' : detail.status === 'warning' ? '#FF9100' : '#FF1744',
                  }}>
                    {detail.status === 'normal' ? 'STATUS::NOMINAL' : detail.status === 'warning' ? 'STATUS::WARNING' : 'STATUS::FAULT'}
                  </p>
                </div>

                {/* Info */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { l: 'POWER', v: `${detail.power_mw} MW`, c: '#00E5FF' },
                    { l: 'LAST_MAINT', v: detail.last_maintenance ? new Date(detail.last_maintenance).toLocaleDateString('zh-CN') : '--', c: '#8899AA' },
                  ].map(({ l, v, c }) => (
                    <div key={l} className="hud-panel p-3">
                      <p className="font-mono text-[8px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{l}</p>
                      <p className="font-mono text-[13px] font-semibold" style={{ color: c }}>{v}</p>
                    </div>
                  ))}
                </div>

                <div className="space-y-2 pt-1">
                  <Link to={`/turbine/${detail.id}`}
                    className="btn-prime-filled w-full text-xs justify-center py-2.5">
                    VIEW_DETAIL &gt;
                  </Link>
                  <Link to="/workorder"
                    className="btn-prime w-full text-xs justify-center py-2.5">
                    + CREATE_WORK_ORDER
                  </Link>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom Data Panels ── */}
      <div className="flex-shrink-0 px-5 pb-4 relative z-10">
        <div className="grid grid-cols-3 gap-3" style={{ height: 180 }}>
          <QuickList turbines={summary.turbines} selectedId={selectedId} onSelect={setSelectedId} />
          <HIChartPanel turbines={summary.turbines} />
          <HealthPiePanel healthy={healthy} warning={warning} faulty={faulty} />
        </div>
      </div>

      <CopilotFAB />
    </div>
  );
}

/* ── KPI CARD ── */
function KPICard({ label, value, unit, accent }: { label: string; value: string; unit: string; accent: string }) {
  const colors: Record<string, string> = {
    cyan: '#00E5FF', green: '#00E676', amber: '#FF9100', red: '#FF1744', blue: '#2979FF',
  };
  const c = colors[accent] || '#00E5FF';
  return (
    <div className="hud-panel px-4 py-3 flex flex-col justify-center slide-up" style={{ background: '#161922' }}>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: c, boxShadow: `0 0 6px ${c}` }} />
        <span className="font-mono text-[8px] uppercase tracking-widest" style={{ color: '#445566' }}>{label}</span>
      </div>
      <p className="kpi-value-sm" style={{ color: c }}>
        {value}
        <span className="kpi-unit">{unit}</span>
      </p>
      <div className="mt-1.5 w-8 h-px" style={{ background: c, opacity: 0.4 }} />
    </div>
  );
}

/* ── Quick List ── */
function QuickList({ turbines, selectedId, onSelect }: { turbines: TurbineDetail[]; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <div className="hud-panel p-3 flex flex-col overflow-hidden" style={{ background: '#161922' }}>
      <p className="font-mono text-[9px] uppercase tracking-widest mb-2" style={{ color: '#445566' }}>
        {'>'} QUICK_SCAN
      </p>
      <div className="flex-1 overflow-auto space-y-px">
        {turbines.slice(0, 8).map((t) => (
          <div key={t.id} onClick={() => onSelect(t.id)}
            className="flex items-center gap-2.5 px-2 py-1.5 cursor-pointer text-[11px] transition-all"
            style={{
              background: selectedId === t.id ? 'rgba(0,229,255,0.04)' : 'transparent',
              borderLeft: selectedId === t.id ? '2px solid #00E5FF' : '2px solid transparent',
              color: selectedId === t.id ? '#E8ECF1' : '#8899AA',
            }}>
            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{
              background: t.status === 'normal' ? '#00E676' : t.status === 'warning' ? '#FF9100' : '#FF1744',
              boxShadow: `0 0 4px ${t.status === 'normal' ? '#00E676' : t.status === 'warning' ? '#FF9100' : '#FF1744'}`,
            }} />
            <span className="w-14 font-medium truncate">{t.name}</span>
            <span className="flex-1 truncate text-[10px] font-mono" style={{ color: '#445566' }}>{t.model}</span>
            <span className="font-mono font-semibold text-xs" style={{
              color: t.hi_value >= 80 ? '#00E676' : t.hi_value >= 60 ? '#FF9100' : '#FF1744',
            }}>{t.hi_value.toFixed(0)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── HI Chart ── */
function HIChartPanel({ turbines }: { turbines: TurbineDetail[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !turbines.length) return;
    const c = echarts.init(ref.current, echartsDark);
    const data = turbines.slice(0, 12).sort((a, b) => b.hi_value - a.hi_value);
    c.setOption({
      backgroundColor: 'transparent',
      grid: { top: 14, right: 8, bottom: 20, left: 36 },
      xAxis: { type: 'category', data: data.map(t => t.name), axisLabel: { color: '#445566', fontSize: 8, rotate: 30 }, axisLine: { lineStyle: { color: 'rgba(0,229,255,0.12)' } } },
      yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }, axisLabel: { color: '#445566', fontSize: 8 } },
      series: [{
        type: 'bar', barWidth: 12,
        data: data.map(t => ({
          value: t.hi_value,
          itemStyle: { color: t.hi_value >= 80 ? '#00E676' : t.hi_value >= 60 ? '#FF9100' : '#FF1744', borderRadius: [1, 1, 0, 0] },
        })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#FF1744', type: 'dashed', width: 1 }, label: { color: '#FF1744', fontSize: 8, formatter: 'ALERT' }, data: [{ yAxis: 60 }] },
      }],
    });
    return () => c.dispose();
  }, [turbines]);
  return (
    <div className="hud-panel p-3 flex flex-col overflow-hidden" style={{ background: '#161922' }}>
      <p className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: '#445566' }}>{'>'} HI_INDEX</p>
      <div ref={ref} className="flex-1" />
    </div>
  );
}

/* ── Health Pie ── */
function HealthPiePanel({ healthy, warning, faulty }: { healthy: number; warning: number; faulty: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, echartsDark);
    c.setOption({
      backgroundColor: 'transparent',
      series: [{
        type: 'pie', radius: ['52%', '74%'], center: ['50%', '53%'],
        itemStyle: { borderColor: '#020204', borderWidth: 2 },
        label: { show: false },
        data: [
          { value: healthy, name: 'NOMINAL', itemStyle: { color: '#00E676' } },
          { value: warning, name: 'WARNING', itemStyle: { color: '#FF9100' } },
          { value: faulty, name: 'FAULT', itemStyle: { color: '#FF1744' } },
        ],
      }],
    });
    return () => c.dispose();
  }, [healthy, warning, faulty]);
  return (
    <div className="hud-panel p-3 flex flex-col overflow-hidden" style={{ background: '#161922' }}>
      <p className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: '#445566' }}>{'>'} DISTRIBUTION</p>
      <div ref={ref} className="flex-1" />
      <div className="flex justify-center gap-5 font-mono text-[8px] tracking-wider" style={{ color: '#8899AA' }}>
        <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5" style={{ background: '#00E676' }} />{healthy} NML</span>
        <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5" style={{ background: '#FF9100' }} />{warning} WRN</span>
        <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5" style={{ background: '#FF1744' }} />{faulty} FLT</span>
      </div>
    </div>
  );
}
