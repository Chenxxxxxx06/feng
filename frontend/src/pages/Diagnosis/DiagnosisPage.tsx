import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { Fault, FaultDetail } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

export default function DiagnosisPage() {
  const [faults, setFaults] = useState<Fault[]>([]);
  const [selected, setSelected] = useState<FaultDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/diagnosis/faults').then(({ data }) => { setFaults(data); setLoading(false); });
  }, []);

  const viewDetail = async (id: number) => {
    const { data } = await api.get(`/diagnosis/faults/${id}`);
    setSelected(data);
  };

  const openCount = faults.filter(f => f.status === 'open').length;
  const weekAgo = new Date(Date.now() - 7 * 86400000);
  const weekNew = faults.filter(f => new Date(f.detected_at) > weekAgo).length;
  const avgConfidence = faults.length > 0
    ? (faults.reduce((sum, f) => sum + f.confidence, 0) / faults.length * 100).toFixed(1) + '%'
    : '--';
  const closedCount = faults.filter(f => f.status === 'closed').length;
  const healthScore = faults.length > 0
    ? Math.min(100, Math.round((closedCount / faults.length) * 60 + (faults.length - weekNew) / Math.max(faults.length, 1) * 40))
    : 100;

  const cards = [
    { label: 'TOTAL_FAULTS', value: String(faults.length), unit: 'REC', color: '#00E5FF' },
    { label: 'PENDING', value: String(openCount), unit: 'REC', color: openCount > 0 ? '#FF1744' : '#00E676' },
    { label: 'WEEKLY_NEW', value: String(weekNew), unit: 'REC', color: weekNew > 0 ? '#FF9100' : '#8899AA' },
    { label: 'AVG_CONFIDENCE', value: avgConfidence, unit: '', color: '#2979FF' },
    { label: 'DIAG_HEALTH', value: String(healthScore), unit: 'PT', color: healthScore >= 80 ? '#00E676' : healthScore >= 60 ? '#FF9100' : '#FF1744' },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden relative" style={{ background: '#020204' }}>
      {/* Header */}
      <div className="flex-shrink-0 px-5 py-3 relative z-10" style={{ borderBottom: '1px solid rgba(0,229,255,0.12)', background: '#0A0C10' }}>
        <div className="flex items-center gap-4 mb-4">
          <span className="font-mono text-[10px] tracking-widest" style={{ color: '#00E5FF' }}>[02]</span>
          <h2 className="text-sm font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
            FAULT_DIAGNOSIS :: ANALYZER
          </h2>
        </div>
        <div className="grid grid-cols-5 gap-3">
          {cards.map((c) => (
            <div key={c.label} className="hud-panel px-3.5 py-3 fade-in" style={{ background: '#161922' }}>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.color, boxShadow: `0 0 4px ${c.color}` }} />
                <p className="font-mono text-[8px] uppercase tracking-widest" style={{ color: '#445566' }}>{c.label}</p>
              </div>
              <p className="kpi-value-sm" style={{ color: c.color }}>
                {c.value}
                <span className="kpi-unit">{c.unit}</span>
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Fault List + Root Cause */}
      <div className="flex-1 flex overflow-hidden relative z-10">
        <div className="flex-1 overflow-auto p-5">
          {loading ? (
            <p className="font-mono text-[11px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>SCANNING...</p>
          ) : (
            <div className="space-y-2">
              {faults.map((f) => (
                <div key={f.id} onClick={() => viewDetail(f.id)}
                  className="hud-panel p-4 cursor-pointer slide-up"
                  style={{
                    background: selected?.id === f.id ? 'rgba(0,229,255,0.03)' : '#161922',
                    borderColor: selected?.id === f.id ? 'rgba(0,229,255,0.3)' : undefined,
                  }}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="w-2 h-2 rounded-full" style={{
                        background: f.status === 'open' ? '#FF1744' : '#00E676',
                        boxShadow: `0 0 6px ${f.status === 'open' ? '#FF1744' : '#00E676'}`,
                      }} />
                      <span className="font-medium text-[13px]" style={{ color: '#E8ECF1' }}>{f.fault_type}</span>
                      <span className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
                        TURBINE#{f.turbine_id} {f.turbine_name || ''}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
                      <span>CONF <span style={{ color: '#FF9100' }}>{(f.confidence * 100).toFixed(0)}%</span></span>
                      <span>{new Date(f.detected_at).toLocaleDateString('zh-CN')}</span>
                      <span className={`chip text-[9px] ${f.status === 'open' ? 'chip-red' : 'chip-green'}`}>
                        {f.status === 'open' ? 'OPEN' : 'CLOSED'}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
              {faults.length === 0 && <p className="font-mono text-[11px] tracking-wider" style={{ color: '#445566' }}>NO_FAULT_RECORDS</p>}
            </div>
          )}

          {/* Root Cause */}
          {selected && (
            <div className="mt-4 hud-panel p-4 slide-up" style={{ background: '#161922' }}>
              <h3 className="font-mono text-[10px] uppercase tracking-widest mb-3 flex items-center gap-2" style={{ color: '#00E5FF' }}>
                <span style={{ color: '#FF9100' }}>[RCA]</span> ROOT_CAUSE :: {selected.fault_type}
                <span className="font-mono text-[9px] ml-2" style={{ color: '#445566' }}>T#{selected.turbine_id}</span>
              </h3>
              <div className="space-y-2">
                {selected.signals?.map((sig) => (
                  <div key={sig.id} className="flex items-center gap-3 px-3 py-2.5 text-[11px]"
                    style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '2px' }}>
                    <span className={`chip text-[9px] w-12 justify-center ${
                      sig.priority === 'high' ? 'chip-red' : sig.priority === 'medium' ? 'chip-amber' : ''
                    }`}>{sig.priority === 'high' ? 'HIGH' : sig.priority === 'medium' ? 'MED' : 'LOW'}</span>
                    <span className="flex-1" style={{ color: '#E8ECF1' }}>{sig.sensor_name}</span>
                    <div className="progress-hud w-32">
                      <div className="progress-hud-fill" style={{ width: `${(sig.contribution_score * 100).toFixed(0)}%`, background: '#00E5FF' }} />
                    </div>
                    <span className="w-14 text-right font-mono font-medium" style={{ color: '#8899AA' }}>
                      {(sig.contribution_score * 100).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
              {selected.details && (
                <div className="mt-3 p-3 font-mono text-[9px] tracking-wider" style={{
                  background: 'rgba(255,145,0,0.03)', border: '1px solid rgba(255,145,0,0.12)', borderRadius: '2px',
                  color: '#FF9100',
                }}>
                  {'>'} RECOMMENDATION: {JSON.stringify(selected.details)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <CopilotFAB />
    </div>
  );
}
