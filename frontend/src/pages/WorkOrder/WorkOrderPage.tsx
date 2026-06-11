import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

const FLOW = ['pending', 'assigned', 'in_progress', 'review', 'completed', 'closed'];
const LABEL: Record<string, string> = { pending: 'PENDING', assigned: 'ASSIGNED', in_progress: 'IN_PROGRESS', review: 'REVIEW', completed: 'DONE', closed: 'CLOSED' };
const CHIP: Record<string, string> = { pending: 'chip-red', assigned: 'chip-amber', in_progress: 'chip-cyan', review: 'chip-amber', completed: 'chip-green', closed: '' };

interface Personnel { id: number; name: string; skills: string[]; region: string; load: number; email: string }
interface AIAnalysis { diagnosis: string; anomalies: { indicator: string; value: string; normal: string; deviation: string; level: string }[]; turbine_name: string; fault_type: string }

export default function WorkOrderPage() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [personnel, setPersonnel] = useState<Personnel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [previewWO, setPreviewWO] = useState<WorkOrder | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [form, setForm] = useState({ turbine_id: '', title: '', description: '', assignee: '', assignee_email: '', cost_estimate: '0', priority: 'medium', fault_type: '轴承磨损', due_date: '' });

  const fetchOrders = async () => {
    setLoading(true);
    const p = statusFilter ? `?status=${statusFilter}` : '';
    const { data } = await api.get(`/workorders/${p}`);
    setOrders(data); setLoading(false);
  };

  useEffect(() => {
    fetchOrders();
    api.get('/personnel/').then(({ data }) => setPersonnel(data)).catch(() => {});
  }, [statusFilter]);

  const handleCreate = async () => {
    await api.post('/workorders/', { turbine_id: Number(form.turbine_id), title: form.title, description: form.description, assignee: form.assignee || null, cost_estimate: Number(form.cost_estimate) });
    setShowCreate(false);
    setForm({ turbine_id: '', title: '', description: '', assignee: '', assignee_email: '', cost_estimate: '0', priority: 'medium', fault_type: '轴承磨损', due_date: '' });
    fetchOrders();
  };

  const advanceStatus = async (id: number, current: string) => {
    const idx = FLOW.indexOf(current);
    if (idx < FLOW.length - 1) { await api.put(`/workorders/${id}`, { status: FLOW[idx + 1] }); fetchOrders(); }
  };

  const runAIAnalysis = async (wo: WorkOrder) => {
    setPreviewWO(wo); setAnalyzing(true);
    try {
      const { data } = await api.post('/ai/analyze-fault', { turbine_id: wo.turbine_id, fault_type: wo.title || 'UNKNOWN' });
      setAiAnalysis(data);
    } catch { setAiAnalysis(null); }
    setAnalyzing(false);
  };

  const FAULT_TYPES = ['轴承磨损', '齿轮箱点蚀', '发电机过热', '叶片裂纹', '变桨系统故障', '冷却系统故障', '主轴不对中', '电气故障'];

  return (
    <div className="h-full overflow-auto p-5 relative" style={{ background: '#020204' }}>
      <div className="relative z-10">
        <div className="flex items-center justify-between mb-4 fade-in">
          <div className="flex items-center gap-4">
            <span className="font-mono text-[10px] tracking-widest" style={{ color: '#00E5FF' }}>[04]</span>
            <h2 className="text-sm font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>
              WORK_ORDER :: MANAGEMENT
            </h2>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="select-hud text-[11px]">
              <option value="">ALL_STATUS</option>
              {FLOW.map(s => <option key={s} value={s}>{LABEL[s]}</option>)}
            </select>
          </div>
          <button onClick={() => setShowCreate(true)} className="btn-prime-filled text-xs">+ NEW_WO</button>
        </div>

        {/* Status Flow */}
        <div className="flex items-center gap-1 mb-4 flex-wrap">
          <span className="font-mono text-[9px] uppercase tracking-widest mr-2" style={{ color: '#445566' }}>
            // FLOW:
          </span>
          {FLOW.map((s, i) => (
            <span key={s} className="flex items-center gap-1">
              <span className={`chip text-[9px] ${CHIP[s] || ''}`} style={!CHIP[s] ? { color: '#445566' } : {}}>
                {LABEL[s]}
              </span>
              {i < FLOW.length - 1 && (
                <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="#445566" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
              )}
            </span>
          ))}
        </div>

        {/* Create Modal */}
        {showCreate && (
          <div className="modal-backdrop" onClick={() => setShowCreate(false)}>
            <div className="w-[540px] p-6 space-y-4 max-h-[90vh] overflow-auto" style={{
              background: '#11141C', border: '1px solid rgba(0,229,255,0.15)', borderRadius: '4px',
              boxShadow: '0 0 40px rgba(0,0,0,0.8)',
            }} onClick={e => e.stopPropagation()}>
              <h3 className="font-display text-sm font-semibold tracking-wider" style={{ color: '#E8ECF1' }}>CREATE_WORK_ORDER</h3>
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="TURBINE_ID *" value={form.turbine_id} onChange={(e) => setForm({ ...form, turbine_id: e.target.value })} className="input-hud" />
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} className="select-hud">
                  <option value="low">LOW</option><option value="medium">MEDIUM</option><option value="high">HIGH</option><option value="urgent">URGENT</option>
                </select>
                <input placeholder="TITLE *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="col-span-2 input-hud" />
                <select value={form.fault_type} onChange={(e) => setForm({ ...form, fault_type: e.target.value })} className="col-span-2 select-hud">
                  {FAULT_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
                </select>
                <textarea placeholder="DESCRIPTION" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="col-span-2 input-hud" />
                <div className="col-span-2">
                  <label className="font-mono text-[8px] uppercase tracking-wider block mb-1" style={{ color: '#445566' }}>ASSIGNEE</label>
                  <select value={form.assignee} onChange={(e) => { const p = personnel.find(pp => pp.name === e.target.value); setForm({ ...form, assignee: e.target.value, assignee_email: p?.email || '' }); }} className="select-hud w-full">
                    <option value="">-- SELECT --</option>
                    {personnel.map(p => <option key={p.id} value={p.name}>{p.name} ({p.skills.join(', ')} | {p.region} | LOAD:{p.load})</option>)}
                  </select>
                </div>
                <input placeholder="COST_ESTIMATE" type="number" value={form.cost_estimate} onChange={(e) => setForm({ ...form, cost_estimate: e.target.value })} className="input-hud" />
                <input placeholder="DEADLINE" type="date" value={form.due_date || ''} onChange={(e) => setForm({ ...form, due_date: e.target.value })} className="input-hud" />
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setShowCreate(false)} className="btn-prime text-xs">CANCEL</button>
                <button onClick={handleCreate} className="btn-prime-filled text-xs">CREATE</button>
              </div>
            </div>
          </div>
        )}

        {/* Orders List */}
        {loading ? (
          <p className="font-mono text-[11px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>LOADING...</p>
        ) : (
          <div className="space-y-2">
            {orders.map((o) => (
              <div key={o.id} className="hud-panel p-4 slide-up" style={{ background: '#161922' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
                      WO-{String(o.id).padStart(4, '0')}
                    </span>
                    <span className="text-[13px] font-medium" style={{ color: '#E8ECF1' }}>{o.title}</span>
                    <span className={`chip text-[9px] ${CHIP[o.status] || ''}`} style={!CHIP[o.status] ? { color: '#445566' } : {}}>
                      {LABEL[o.status] || o.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => runAIAnalysis(o)}
                      className="btn-prime text-[10px]" style={{ borderColor: 'rgba(0,229,255,0.2)', color: '#00E5FF' }}>
                      PREVIEW
                    </button>
                    {o.status !== 'closed' && (
                      <button onClick={() => advanceStatus(o.id, o.status)} className="btn-prime-filled text-[10px]">
                        {o.status === 'completed' ? 'CLOSE' : 'ADVANCE >'}
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex gap-4 mt-2.5 font-mono text-[9px] tracking-wider" style={{ color: '#445566' }}>
                  <span>T#{o.turbine_id}</span>
                  {o.assignee && <span>ASGN: {o.assignee}</span>}
                  <span>¥{o.cost_estimate.toLocaleString()}</span>
                  <span>{new Date(o.created_at).toLocaleDateString('zh-CN')}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Preview Modal */}
        {previewWO && (
          <div className="modal-backdrop" onClick={() => { setPreviewWO(null); setAiAnalysis(null); }}>
            <div className="w-[660px] max-h-[85vh] overflow-auto" style={{
              background: '#11141C', border: '1px solid rgba(0,229,255,0.15)', borderRadius: '4px',
              boxShadow: '0 0 40px rgba(0,0,0,0.8)',
            }} onClick={e => e.stopPropagation()}>
              <div className="sticky top-0 px-5 py-3.5 flex items-center justify-between z-10" style={{ background: '#0A0C10', borderBottom: '1px solid rgba(0,229,255,0.12)' }}>
                <div>
                  <h3 className="font-display text-sm font-semibold tracking-wider" style={{ color: '#E8ECF1' }}>
                    EMAIL_PREVIEW :: WO-{String(previewWO.id).padStart(4, '0')}
                  </h3>
                  <p className="font-mono text-[9px] mt-0.5 tracking-wider" style={{ color: '#445566' }}>
                    SUBJ: [FDTYS] WO-{String(previewWO.id).padStart(4, '0')} {previewWO.title}
                  </p>
                </div>
                <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }}
                  className="w-6 h-6 flex items-center justify-center" style={{ color: '#445566' }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <div className="p-5 space-y-4 text-xs">
                <div className="hud-panel p-4 space-y-3" style={{ background: '#161922' }}>
                  <div className="text-center pb-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <p className="font-display font-bold text-sm tracking-wider" style={{ color: '#E8ECF1' }}>WORK_ORDER_NOTICE — {previewWO.title}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 font-mono text-[10px]">
                    <div><span style={{ color: '#445566' }}>WO_ID:</span> <span style={{ color: '#E8ECF1' }}>WO-{String(previewWO.id).padStart(4, '0')}</span></div>
                    <div><span style={{ color: '#445566' }}>PRIORITY:</span> <span className="chip chip-red text-[8px]">URGENT</span></div>
                    <div><span style={{ color: '#445566' }}>CREATED:</span> <span style={{ color: '#8899AA' }}>{new Date(previewWO.created_at).toLocaleString('zh-CN')}</span></div>
                    <div><span style={{ color: '#445566' }}>DEADLINE:</span> <span style={{ color: '#FF9100' }}>{new Date(Date.now() + 7 * 86400000).toLocaleDateString('zh-CN')}</span></div>
                  </div>
                  <div className="pt-2" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    <p className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{'>'} TURBINE_INFO</p>
                    <div className="grid grid-cols-2 gap-1 font-mono text-[10px]" style={{ color: '#8899AA' }}>
                      <div>TURBINE: {previewWO.turbine_id}</div><div>REGION: SHANBEI</div>
                      <div>STATUS: WARNING</div><div>HI: 78.1</div>
                    </div>
                  </div>
                  <div className="pt-2" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    <p className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{'>'} AI_ANALYSIS</p>
                    {analyzing ? <p className="font-mono text-[10px] animate-pulse" style={{ color: '#00E5FF' }}>ANALYZING...</p>
                      : aiAnalysis ? (
                        <div className="space-y-2">
                          <p style={{ color: '#8899AA' }}>{aiAnalysis.diagnosis}</p>
                          <p className="font-mono text-[9px] tracking-wider" style={{ color: '#FF1744' }}>ANOMALIES:</p>
                          {aiAnalysis.anomalies.map((a, i) => (
                            <div key={i} className="flex items-center gap-2 py-1 font-mono text-[10px]" style={{ color: a.level === 'high' ? '#FF1744' : '#FF9100', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <span className="w-1.5 h-1.5 rounded-full" style={{ background: a.level === 'high' ? '#FF1744' : '#FF9100' }} />
                              <span className="w-20">{a.indicator}</span>
                              <span>CUR: <b>{a.value}</b></span>
                              <span style={{ color: '#445566' }}>REF: {a.normal}</span>
                              <b>{a.deviation}</b>
                            </div>
                          ))}
                        </div>
                      ) : <p className="font-mono text-[10px]" style={{ color: '#445566' }}>AI_OFFLINE</p>}
                  </div>
                  <div className="pt-2" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    <p className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: '#445566' }}>{'>'} STEPS</p>
                    <ol className="list-decimal list-inside space-y-0.5 font-mono text-[10px]" style={{ color: '#8899AA' }}>
                      <li>SHUTDOWN_INSPECT_TEMP</li><li>VIBRATION_RETEST</li>
                      <li>REPLACE_DAMAGED_PARTS</li><li>24H_MONITOR_POST_FIX</li>
                    </ol>
                  </div>
                  <div className="pt-2 grid grid-cols-2 gap-2 font-mono text-[10px]" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    <div><span style={{ color: '#445566' }}>EST_HOURS:</span> <span style={{ color: '#8899AA' }}>4h</span></div>
                    <div><span style={{ color: '#445566' }}>EST_COST:</span> <span style={{ color: '#8899AA' }}>¥{previewWO.cost_estimate.toLocaleString()}</span></div>
                    <div><span style={{ color: '#445566' }}>SPARE:</span> <span style={{ color: '#8899AA' }}>BEARING_KIT x1</span></div>
                    <div><span style={{ color: '#445566' }}>ASSIGNEE:</span> <span style={{ color: '#8899AA' }}>{previewWO.assignee || 'UNASSIGNED'}</span></div>
                  </div>
                </div>
              </div>
              <div className="sticky bottom-0 px-5 py-3 flex gap-2 justify-end" style={{ background: '#0A0C10', borderTop: '1px solid rgba(0,229,255,0.12)' }}>
                <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }} className="btn-prime text-xs">BACK</button>
                <button className="btn-prime-filled text-xs" style={{ borderColor: '#00E676', color: '#00E676' }}>SEND_EMAIL</button>
              </div>
            </div>
          </div>
        )}
      </div>
      <CopilotFAB />
    </div>
  );
}
