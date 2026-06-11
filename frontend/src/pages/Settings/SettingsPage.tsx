import { useEffect, useState } from 'react';
import api from '../../services/api';
import { useAuthStore } from '../../services/authStore';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

interface PipelineSource { type: string; name: string; status: string; last_update: string | null; record_count: number; real_data_available: boolean; note: string }
interface PipelineStatus { sources: PipelineSource[]; overall_status: string; errors: string[] }

export default function SettingsPage() {
  const { user, fetchMe } = useAuthStore();
  const [hiThreshold, setHiThreshold] = useState('70');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('gpt-4');
  const [saved, setSaved] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);
  const [testResults, setTestResults] = useState<Record<string, string>>({});

  useEffect(() => {
    api.get('/settings/thresholds').then(({ data }) => { if (data.length > 0) setHiThreshold(String(data[0].hi_threshold)); });
    refreshPipeline();
  }, []);

  const refreshPipeline = async () => { const { data } = await api.get('/settings/pipeline-status'); setPipeline(data); };

  const saveThreshold = async () => {
    await api.put('/settings/thresholds', { hi_threshold: Number(hiThreshold) });
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const saveProfile = async () => {
    await api.put('/settings/profile', { api_key: apiKey || null, model_preference: model });
    fetchMe(); setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const testConnection = async (type: string) => {
    setTestResults((prev) => ({ ...prev, [type]: 'TESTING' }));
    try {
      const { data } = await api.post('/settings/data-sources/test', { source_type: type, connection_params: {} });
      setTestResults((prev) => ({ ...prev, [type]: data.status === 'success' ? 'OK' : 'FAIL' }));
    } catch { setTestResults((prev) => ({ ...prev, [type]: 'FAIL' })); }
    setTimeout(refreshPipeline, 500);
  };

  const statusStyle = (s: string) => {
    switch (s) {
      case 'connected': return { bg: 'rgba(0,230,118,0.06)', border: 'rgba(0,230,118,0.15)', text: '#00E676' };
      case 'partial': return { bg: 'rgba(255,145,0,0.06)', border: 'rgba(255,145,0,0.15)', text: '#FF9100' };
      case 'error': return { bg: 'rgba(255,23,68,0.06)', border: 'rgba(255,23,68,0.15)', text: '#FF1744' };
      default: return { bg: 'rgba(68,85,102,0.06)', border: 'rgba(68,85,102,0.12)', text: '#445566' };
    }
  };
  const statusLabel = (s: string) => {
    switch (s) { case 'connected': return 'CONNECTED'; case 'partial': return 'PARTIAL'; case 'disconnected': return 'OFFLINE'; case 'error': return 'ERROR'; default: return s.toUpperCase(); }
  };

  const sourceIcons: Record<string, string> = { scada: 'SCADA', vibration: 'VIB', image: 'IMG', weather: 'WX' };

  return (
    <div className="h-full overflow-auto p-5 space-y-4 relative" style={{ background: 'transparent' }}>
      <div className="relative z-10">
        <div className="flex items-center gap-4 mb-5 fade-in">
          <span className="font-mono text-[10px] tracking-widest" style={{ color: '#00E5FF' }}>[05]</span>
          <h2 className="text-sm font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
            SYSTEM_SETTINGS :: CONFIG
          </h2>
        </div>

        {/* Profile */}
        <div className="hud-panel p-5 space-y-4 mb-4 slide-up" style={{ background: '#161922' }}>
          <h3 className="font-mono text-[10px] uppercase tracking-widest flex items-center gap-2" style={{ color: '#00E5FF' }}>
            <span style={{ color: '#445566' }}>[CFG]</span> PROFILE
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="font-mono text-[8px] uppercase tracking-wider block mb-1.5" style={{ color: '#445566' }}>API_KEY</label>
              <input type="password" placeholder="sk-..." value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="input-hud w-full" />
            </div>
            <div>
              <label className="font-mono text-[8px] uppercase tracking-wider block mb-1.5" style={{ color: '#445566' }}>MODEL</label>
              <select value={model} onChange={(e) => setModel(e.target.value)} className="select-hud w-full">
                <option value="gpt-4">GPT-4</option>
                <option value="gpt-3.5-turbo">GPT-3.5 TURBO</option>
                <option value="deepseek-v3">DEEPSEEK V3</option>
                <option value="claude-4">CLAUDE 4</option>
              </select>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={saveProfile} className="btn-prime-filled text-xs">SAVE</button>
            {saved && <span className="font-mono text-[10px] tracking-wider" style={{ color: '#00E676' }}>[OK] SAVED</span>}
          </div>
        </div>

        {/* Pipeline */}
        <div className="hud-panel p-5 space-y-4 mb-4 slide-up slide-up-d1" style={{ background: '#161922' }}>
          <div className="flex items-center justify-between">
            <h3 className="font-mono text-[10px] uppercase tracking-widest flex items-center gap-2" style={{ color: '#00E5FF' }}>
              <span style={{ color: '#445566' }}>[PIPE]</span> DATA_PIPELINE
            </h3>
            <div className="flex items-center gap-2">
              {pipeline && <span className="w-2 h-2 rounded-full" style={{ background: pipeline.overall_status === 'healthy' ? '#00E676' : '#FF9100' }} />}
              <span className="font-mono text-[10px] tracking-wider" style={{ color: '#8899AA' }}>
                {pipeline?.overall_status === 'healthy' ? 'NOMINAL' : 'DEGRADED'}
              </span>
              <button onClick={refreshPipeline} className="btn-ghost text-[10px] font-mono">REFRESH</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {pipeline?.sources.map((s) => {
              const st = statusStyle(s.status);
              return (
                <div key={s.type} className="hud-panel p-3.5" style={{ background: '#11141C' }}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] tracking-wider" style={{ color: '#00E5FF' }}>{sourceIcons[s.type] || '???'}</span>
                      <p className="text-xs font-medium" style={{ color: '#E8ECF1' }}>{s.name}</p>
                    </div>
                    <span className="chip text-[8px]" style={{ background: st.bg, borderColor: st.border, color: st.text }}>
                      {statusLabel(s.status)}
                    </span>
                  </div>
                  <div className="font-mono text-[8px] tracking-wider space-y-0.5" style={{ color: '#445566' }}>
                    {s.last_update && <p>LAST: {new Date(s.last_update).toLocaleString('zh-CN')}</p>}
                    {s.record_count > 0 && <p>RECORDS: {s.record_count.toLocaleString()}</p>}
                    <p style={{ color: s.real_data_available ? '#00E676' : '#FF9100' }}>{s.note}</p>
                  </div>
                  <div className="flex items-center justify-between mt-2.5">
                    {testResults[s.type] && (
                      <span className="font-mono text-[9px] tracking-wider" style={{
                        color: testResults[s.type] === 'TESTING' ? '#00E5FF' : testResults[s.type] === 'OK' ? '#00E676' : '#FF1744',
                      }}>
                        {testResults[s.type] === 'TESTING' ? 'TESTING...' : testResults[s.type] === 'OK' ? 'CONN_OK' : 'CONN_FAIL'}
                      </span>
                    )}
                    <button onClick={() => testConnection(s.type)} className="btn-ghost text-[9px] font-mono">TEST</button>
                  </div>
                </div>
              );
            })}
          </div>
          {pipeline?.errors && pipeline.errors.length > 0 && (
            <div className="mt-3 p-3 font-mono text-[9px] tracking-wider" style={{ background: 'rgba(255,23,68,0.03)', border: '1px solid rgba(255,23,68,0.12)', borderRadius: '2px', color: '#FF1744' }}>
              <p className="mb-1">PIPE_ERRORS ({pipeline.errors.length})</p>
              {pipeline.errors.map((e, i) => <p key={i}>{'>'} {e}</p>)}
            </div>
          )}
        </div>

        {/* Threshold + Personnel */}
        <div className="grid grid-cols-2 gap-4 slide-up slide-up-d2">
          <div className="hud-panel p-5 space-y-4" style={{ background: '#161922' }}>
            <h3 className="font-mono text-[10px] uppercase tracking-widest flex items-center gap-2" style={{ color: '#00E5FF' }}>
              <span style={{ color: '#445566' }}>[ALERT]</span> THRESHOLDS
            </h3>
            <div className="flex items-center gap-4">
              <div>
                <label className="font-mono text-[8px] uppercase tracking-wider block mb-1.5" style={{ color: '#445566' }}>HI_ALERT_THRESHOLD</label>
                <input type="number" min="0" max="100" value={hiThreshold} onChange={(e) => setHiThreshold(e.target.value)} className="input-hud w-24" />
              </div>
              <span className="font-mono text-[9px] mt-5 tracking-wider" style={{ color: '#445566' }}>TRIGGER_WHEN_HI_BELOW</span>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2 font-mono text-[10px] tracking-wider cursor-pointer" style={{ color: '#8899AA' }}>
                <input type="checkbox" /> EMAIL_NOTIFY
              </label>
              <label className="flex items-center gap-2 font-mono text-[10px] tracking-wider cursor-pointer" style={{ color: '#8899AA' }}>
                <input type="checkbox" /> WECHAT_NOTIFY
              </label>
            </div>
            <button onClick={saveThreshold} className="btn-prime-filled text-xs">SAVE</button>
          </div>

          <PersonnelSection />
        </div>
      </div>
      <CopilotFAB />
    </div>
  );
}

function PersonnelSection() {
  const [unlocked, setUnlocked] = useState(false);
  const [pwd, setPwd] = useState('');
  const [error, setError] = useState('');
  const [personnel, setPersonnel] = useState<any[]>([]);
  const [newPerson, setNewPerson] = useState({ name: '', skills: '', region: '陕北', email: '' });

  useEffect(() => { api.get('/personnel/').then(({ data }) => setPersonnel(data)).catch(() => {}); }, [unlocked]);

  const handleUnlock = async () => {
    try {
      const { data } = await api.post('/auth/login', { username: 'admin', password: pwd });
      if (data.access_token) { setUnlocked(true); setError(''); }
    } catch { setError('AUTH_FAILURE'); }
  };

  const addPerson = async () => {
    if (!newPerson.name) return;
    setPersonnel([...personnel, { id: personnel.length + 1, name: newPerson.name, skills: newPerson.skills.split(',').map((s: string) => s.trim()), region: newPerson.region, load: 0, email: newPerson.email }]);
    setNewPerson({ name: '', skills: '', region: '陕北', email: '' });
  };

  const removePerson = (id: number) => { setPersonnel(personnel.filter(p => p.id !== id)); };

  return (
    <div className="hud-panel p-5 space-y-4" style={{ background: '#161922' }}>
      <h3 className="font-mono text-[10px] uppercase tracking-widest flex items-center gap-2" style={{ color: '#00E5FF' }}>
        <span style={{ color: '#445566' }}>[CREW]</span> PERSONNEL
        <span className="font-mono text-[8px] ml-2" style={{ color: '#445566' }}>ADMIN_AUTH_REQUIRED</span>
      </h3>

      {!unlocked ? (
        <div className="flex items-center gap-3">
          <input type="password" placeholder="ADMIN_PASSWORD" value={pwd}
            onChange={(e) => setPwd(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
            className="input-hud w-44" />
          <button onClick={handleUnlock} className="btn-prime-filled text-xs">UNLOCK</button>
          {error && <span className="font-mono text-[9px] tracking-wider" style={{ color: '#FF1744' }}>{error}</span>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex gap-2">
            <input placeholder="NAME" value={newPerson.name} onChange={(e) => setNewPerson({ ...newPerson, name: e.target.value })} className="input-hud w-20" />
            <input placeholder="SKILLS" value={newPerson.skills} onChange={(e) => setNewPerson({ ...newPerson, skills: e.target.value })} className="input-hud flex-1" />
            <select value={newPerson.region} onChange={(e) => setNewPerson({ ...newPerson, region: e.target.value })} className="select-hud">
              <option>陕北</option><option>关中</option><option>陕南</option>
            </select>
            <input placeholder="EMAIL" value={newPerson.email} onChange={(e) => setNewPerson({ ...newPerson, email: e.target.value })} className="input-hud w-36" />
            <button onClick={addPerson} className="btn-prime-filled text-xs" style={{ borderColor: '#00E676', color: '#00E676' }}>+ ADD</button>
          </div>
          <div className="space-y-1 max-h-40 overflow-auto">
            {personnel.map((p) => (
              <div key={p.id} className="flex items-center gap-3 px-3 py-2 text-xs"
                style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '2px' }}>
                <span className="w-14 font-medium font-mono text-[10px] tracking-wider" style={{ color: '#E8ECF1' }}>{p.name}</span>
                <span className="flex gap-1">
                  {p.skills.map((s: string) => <span key={s} className="chip chip-cyan text-[8px]">{s}</span>)}
                </span>
                <span className="font-mono text-[9px]" style={{ color: '#445566' }}>{p.region}</span>
                <span className="font-mono text-[9px]" style={{ color: '#445566' }}>{p.email}</span>
                <span className="ml-auto font-mono text-[9px] tracking-wider" style={{
                  color: p.load >= 3 ? '#FF1744' : p.load >= 2 ? '#FF9100' : '#00E676',
                }}>LOAD:{p.load}/5</span>
                <button onClick={() => removePerson(p.id)}
                  className="w-5 h-5 flex items-center justify-center transition-colors ml-1"
                  style={{ color: '#445566' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = '#FF1744')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = '#445566')}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
