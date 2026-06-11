import { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import type { TurbineDetail, SCADAPoint, Fault } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

export default function TurbineDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [turbine, setTurbine] = useState<TurbineDetail | null>(null);
  const [scada, setScada] = useState<SCADAPoint[]>([]);
  const [wind, setWind] = useState<Record<string, any> | null>(null);
  const [faults, setFaults] = useState<Fault[]>([]);
  const [vibration, setVibration] = useState<Record<string, any> | null>(null);
  const [bladeImages, setBladeImages] = useState<any[]>([]);
  const [diagnosisResult, setDiagnosisResult] = useState<any>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const vibChartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    api.get(`/turbines/${id}`).then(({ data }) => setTurbine(data));
    api.get(`/turbines/${id}/scada?hours=24`).then(({ data }) => setScada(data));
    api.get(`/turbines/${id}/wind`).then(({ data }) => setWind(data));
    api.get(`/diagnosis/faults?turbine_id=${id}`).then(({ data }) => setFaults(data));
    api.get(`/diagnosis/vibration?turbine_id=${id}`).then(({ data }) => setVibration(data));
    api.get(`/diagnosis/blade-images?turbine_id=${id}`).then(({ data }) => setBladeImages(data));
  }, [id]);

  // SCADA chart
  useEffect(() => {
    if (!chartRef.current || !scada.length) return;
    const c = echarts.init(chartRef.current, 'dark');
    const times = scada.map(s => new Date(s.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
    c.setOption({
      backgroundColor: 'transparent',
      grid: { top: 40, right: 60, bottom: 30, left: 50 },
      legend: { top: 5, textStyle: { color: '#8899AA', fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: times, axisLabel: { color: '#445566', fontSize: 10 } },
      yAxis: [
        { type: 'value', name: 'kW', axisLabel: { color: '#445566' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
        { type: 'value', name: '°C', axisLabel: { color: '#445566' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
      ],
      series: [
        { name: 'POWER', type: 'line', data: scada.map(s => s.power_kw), smooth: true, lineStyle: { color: '#00E5FF', width: 1.5 }, areaStyle: { color: 'rgba(0,229,255,0.05)' }, symbol: 'none' },
        { name: 'WIND', type: 'line', data: scada.map(s => s.wind_speed_ms), smooth: true, lineStyle: { color: '#2979FF', width: 1 }, symbol: 'none' },
        { name: 'GEN_TEMP', yAxisIndex: 1, type: 'line', data: scada.map(s => s.gen_temperature_c), smooth: true, lineStyle: { color: '#FF9100', width: 1 }, symbol: 'none' },
      ],
    });
    const hr = () => c.resize();
    window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); c.dispose(); };
  }, [scada]);

  // Vibration chart
  useEffect(() => {
    if (!vibChartRef.current || !vibration?.waveform) return;
    const c = echarts.init(vibChartRef.current, 'dark');
    c.setOption({
      backgroundColor: 'transparent',
      grid: { top: 30, right: 20, bottom: 30, left: 45 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: vibration.waveform.slice(0, 200).map((_: number, i: number) => (i * vibration.duration_seconds / vibration.waveform.length).toFixed(3) + 's'), axisLabel: { color: '#445566', fontSize: 9 } },
      yAxis: { type: 'value', name: 'mm/s²', axisLabel: { color: '#445566' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
      dataZoom: [{ type: 'inside', start: 0, end: 30 }],
      series: [{ name: 'VIB', type: 'line', data: vibration.waveform.slice(0, 2048), smooth: false, lineStyle: { color: '#00E5FF', width: 1 }, areaStyle: { color: 'rgba(0,229,255,0.04)' }, symbol: 'none' }],
    });
    const hr = () => c.resize();
    window.addEventListener('resize', hr);
    return () => { window.removeEventListener('resize', hr); c.dispose(); };
  }, [vibration]);

  const runBladeDiagnosis = async (imagePath: string) => {
    setDiagnosing(true);
    try {
      const { data } = await api.post('/diagnosis/blade-diagnosis', { turbine_id: Number(id), image_path: imagePath });
      setDiagnosisResult(data);
    } catch { setDiagnosisResult({ damage_type: 'ERROR', confidence: 0, damage_bbox: null, image_path: '' }); }
    setDiagnosing(false);
  };

  if (!turbine) return (
    <div className="flex items-center justify-center h-full" style={{ color: '#445566' }}>
      <span className="font-mono text-xs tracking-wider animate-pulse">LOADING...</span>
    </div>
  );

  return (
    <div className="h-full flex relative" style={{ background: '#020204' }}>
      <div className="flex-1 overflow-auto p-6 space-y-4 relative z-10">
        {/* Header */}
        <div className="flex items-center gap-3 fade-in">
          <Link to="/dashboard" className="btn-ghost text-xs font-mono tracking-wider">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
            BACK
          </Link>
          <h2 className="text-base font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
            {turbine.name}
          </h2>
          <span className={`chip ${turbine.status === 'normal' ? 'chip-green' : turbine.status === 'warning' ? 'chip-amber' : 'chip-red'}`}>
            {turbine.status === 'normal' ? 'NOMINAL' : turbine.status === 'warning' ? 'WARNING' : 'FAULT'}
          </span>
        </div>

        {/* Blade Diagnosis */}
        <div className="hud-panel p-4 slide-up" style={{ background: '#161922' }}>
          <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: '#00E5FF' }}>
            <span style={{ color: '#445566' }}>[DIAG]</span> BLADE_IMAGING
          </h3>
          <div className="flex gap-4">
            <div className="flex-1">
              <div className="grid grid-cols-3 gap-2 mb-3">
                {bladeImages.map((img, i) => (
                  <div key={i} onClick={() => runBladeDiagnosis(img.image_path)}
                    className="p-5 text-center cursor-pointer transition-all"
                    style={{
                      background: diagnosisResult?.image_path === img.image_path ? 'rgba(0,229,255,0.04)' : 'rgba(255,255,255,0.02)',
                      border: diagnosisResult?.image_path === img.image_path ? '1px solid rgba(0,229,255,0.25)' : '1px dashed rgba(255,255,255,0.08)',
                      borderRadius: '2px',
                    }}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={diagnosisResult?.image_path === img.image_path ? '#00E5FF' : '#445566'} strokeWidth="1.2" style={{ margin: '0 auto 6px' }}>
                      <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
                    </svg>
                    <p className="text-[10px] mb-0.5" style={{ color: '#8899AA' }}>{img.view || 'IMAGE'}</p>
                    <p className="font-mono text-[9px]" style={{ color: '#445566' }}>#{i + 1} {new Date(img.timestamp).toLocaleDateString('zh-CN')}</p>
                    {img.has_damage && <p className="font-mono text-[9px] mt-1.5" style={{ color: '#FF1744' }}>DAMAGE_DETECTED</p>}
                  </div>
                ))}
              </div>
              <p className="font-mono text-[9px] tracking-wider" style={{ color: '#445566' }}>CLICK_IMAGE_TO_RUN_AI_DIAGNOSIS</p>
            </div>

            <div className="w-64 hud-panel p-3 flex-shrink-0" style={{ background: '#161922' }}>
              <h4 className="font-mono text-[9px] uppercase tracking-widest mb-2" style={{ color: '#445566' }}>{'>'} AI_RESULT</h4>
              {diagnosing ? (
                <p className="font-mono text-[10px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>ANALYZING...</p>
              ) : diagnosisResult ? (
                <div className="space-y-2 text-[11px]">
                  <div className="flex justify-between"><span style={{ color: '#445566' }}>TYPE</span><span style={{ color: '#FF9100' }}>{diagnosisResult.damage_type}</span></div>
                  <div className="flex justify-between"><span style={{ color: '#445566' }}>CONFIDENCE</span><span className="font-mono" style={{ color: '#00E676' }}>{(diagnosisResult.confidence * 100).toFixed(1)}%</span></div>
                  {diagnosisResult.damage_bbox && (
                    <div className="flex justify-between"><span style={{ color: '#445566' }}>POSITION</span><span className="font-mono" style={{ color: '#8899AA' }}>x:{diagnosisResult.damage_bbox.x} y:{diagnosisResult.damage_bbox.y}</span></div>
                  )}
                  <div className="mt-2 p-2 font-mono text-[9px] tracking-wider" style={{ background: 'rgba(255,145,0,0.04)', border: '1px solid rgba(255,145,0,0.12)', borderRadius: '2px', color: '#FF9100' }}>
                    ACTION: 2WK_REINSPECTION. SPARE: LEADING_EDGE_FILM.
                  </div>
                </div>
              ) : (
                <p className="font-mono text-[10px]" style={{ color: '#445566' }}>SELECT_IMAGE_FIRST</p>
              )}
            </div>
          </div>
        </div>

        {/* SCADA */}
        <div className="hud-panel p-4 slide-up slide-up-d1" style={{ background: '#161922' }}>
          <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: '#00E5FF' }}>
            <span style={{ color: '#445566' }}>[SCADA]</span> REALTIME_CURVE :: 24H
          </h3>
          <div ref={chartRef} style={{ height: 300 }} />
        </div>

        {/* Wind + Vibration */}
        <div className="grid grid-cols-2 gap-4 slide-up slide-up-d2">
          {wind && (
            <div className="hud-panel p-4" style={{ background: '#161922' }}>
              <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: '#00E5FF' }}>
                <span style={{ color: '#445566' }}>[WX]</span> WEATHER :: {wind.note || 'ERA5'}
              </h3>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {[
                  ['WIND_SPD', wind.wind_speed_ms, 'm/s'], ['GUST', wind.wind_gust_ms, 'm/s'], ['DIR', wind.wind_direction_deg, '°'],
                  ['TURB', wind.turbulence_intensity, ''], ['TEMP', wind.air_temperature_c, '°C'], ['PRES', wind.air_pressure_hpa, 'hPa'],
                ].map(([l, v, u]) => (
                  <div key={l as string} className="hud-panel p-2.5 text-center" style={{ background: '#11141C' }}>
                    <p className="font-mono text-[8px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{l}</p>
                    <p className="font-mono font-semibold text-xs" style={{ color: '#00E5FF' }}>{v}{u}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="hud-panel p-4" style={{ background: '#161922' }}>
            <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: '#00E5FF' }}>
              <span style={{ color: '#445566' }}>[VIB]</span> WAVEFORM
              {vibration && <span className="font-mono text-[9px]" style={{ color: '#445566' }}>RMS: <span style={{ color: '#00E5FF' }}>{vibration.rms}</span></span>}
              {vibration?.fault_detected && <span className="chip chip-red text-[8px]">FAULT_SIG</span>}
            </h3>
            {vibration ? <div ref={vibChartRef} style={{ height: 180 }} /> : <p className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>LOADING...</p>}
          </div>
        </div>
      </div>

      {/* Right: Faults */}
      <div className="w-72 flex-shrink-0 flex flex-col relative z-10"
        style={{ borderLeft: '1px solid rgba(0,229,255,0.12)', background: '#0A0C10' }}>
        <div className="p-4 flex-1 overflow-auto">
          <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3" style={{ color: '#00E5FF' }}>
            <span style={{ color: '#445566' }}>[FLT]</span> FAULT_LOG
          </h3>
          {faults.length === 0 ? (
            <p className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>NO_FAULTS</p>
          ) : (
            <div className="space-y-2">
              {faults.map((f) => (
                <div key={f.id} className="hud-panel p-3 text-xs space-y-1.5" style={{ background: '#161922' }}>
                  <div className="flex justify-between items-center">
                    <span style={{ color: '#FF1744' }}>{f.fault_type}</span>
                    <span className="font-mono text-[9px]" style={{ color: '#445566' }}>{new Date(f.detected_at).toLocaleDateString('zh-CN')}</span>
                  </div>
                  <div className="flex justify-between font-mono text-[9px]" style={{ color: '#445566' }}>
                    <span>CONF: {(f.confidence * 100).toFixed(0)}%</span>
                    <span className="chip text-[8px]">{f.status === 'open' ? 'OPEN' : 'CLOSED'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <CopilotFAB />
    </div>
  );
}
