import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

const STATUS_FLOW = ['pending', 'assigned', 'in_progress', 'review', 'completed', 'closed'];
const STATUS_LABEL: Record<string, string> = { pending: '待分配', assigned: '已分配', in_progress: '执行中', review: '待验收', completed: '已完成', closed: '已关闭' };
const STATUS_COLOR: Record<string, string> = { pending: 'bg-accent-red/20 text-accent-red', assigned: 'bg-accent-yellow/20 text-accent-yellow', in_progress: 'bg-accent-blue/20 text-accent-blue', review: 'bg-accent-yellow/20 text-accent-yellow', completed: 'bg-accent-green/20 text-accent-green', closed: 'bg-text-muted/20 text-text-muted' };

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
    const params = statusFilter ? `?status=${statusFilter}` : '';
    const { data } = await api.get(`/workorders/${params}`);
    setOrders(data);
    setLoading(false);
  };

  useEffect(() => {
    fetchOrders();
    api.get('/personnel/').then(({ data }) => setPersonnel(data)).catch(() => {});
  }, [statusFilter]);

  const handleCreate = async () => {
    await api.post('/workorders/', {
      turbine_id: Number(form.turbine_id), title: form.title,
      description: form.description, assignee: form.assignee || null,
      cost_estimate: Number(form.cost_estimate),
    });
    setShowCreate(false);
    setForm({ turbine_id: '', title: '', description: '', assignee: '', assignee_email: '', cost_estimate: '0', priority: 'medium', fault_type: '轴承磨损', due_date: '' });
    fetchOrders();
  };

  const advanceStatus = async (id: number, current: string) => {
    const idx = STATUS_FLOW.indexOf(current);
    if (idx < STATUS_FLOW.length - 1) {
      await api.put(`/workorders/${id}`, { status: STATUS_FLOW[idx + 1] });
      fetchOrders();
    }
  };

  const runAIAnalysis = async (wo: WorkOrder) => {
    setPreviewWO(wo);
    setAnalyzing(true);
    try {
      const { data } = await api.post('/ai/analyze-fault', {
        turbine_id: wo.turbine_id,
        fault_type: wo.title || '未知故障',
      });
      setAiAnalysis(data);
    } catch { setAiAnalysis(null); }
    setAnalyzing(false);
  };

  const FAULT_TYPES = ['轴承磨损', '齿轮箱点蚀', '发电机过热', '叶片裂纹', '变桨系统故障', '冷却系统故障', '主轴不对中', '电气故障'];

  return (
    <div className="h-full overflow-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">维修工单管理</h2>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-bg-secondary border border-border-default rounded px-2 py-1 text-xs text-text-primary">
            <option value="">全部状态</option>
            {STATUS_FLOW.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-accent-blue text-white rounded text-sm hover:opacity-90">+ 创建工单</button>
      </div>

      {/* Status flow */}
      <div className="flex items-center gap-1 mb-4 text-[10px]">
        <span className="text-text-muted mr-2">流转:</span>
        {STATUS_FLOW.map((s, i) => (
          <span key={s} className="flex items-center gap-1">
            <span className={`px-1.5 py-0.5 rounded ${STATUS_COLOR[s]}`}>{STATUS_LABEL[s]}</span>
            {i < STATUS_FLOW.length - 1 && <span className="text-text-muted">→</span>}
          </span>
        ))}
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-bg-card border border-border-default rounded-lg w-[520px] p-6 space-y-4 max-h-[90vh] overflow-auto">
            <h3 className="font-medium">创建新工单</h3>
            <div className="grid grid-cols-2 gap-3">
              <input placeholder="风机ID *" value={form.turbine_id} onChange={(e) => setForm({ ...form, turbine_id: e.target.value })}
                className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
              <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}
                className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary">
                <option value="low">低优先级</option><option value="medium">中优先级</option><option value="high">高优先级</option><option value="urgent">紧急</option>
              </select>
              <input placeholder="工单标题 *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="col-span-2 bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
              <select value={form.fault_type} onChange={(e) => setForm({ ...form, fault_type: e.target.value })}
                className="col-span-2 bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary">
                {FAULT_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
              </select>
              <textarea placeholder="工单描述" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3}
                className="col-span-2 bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
              {/* Personnel selector */}
              <div className="col-span-2">
                <label className="text-[10px] text-text-muted block mb-1">选择责任人</label>
                <select value={form.assignee} onChange={(e) => {
                  const p = personnel.find(pp => pp.name === e.target.value);
                  setForm({ ...form, assignee: e.target.value, assignee_email: p?.email || '' });
                }} className="w-full bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary">
                  <option value="">-- 选择责任人 --</option>
                  {personnel.map(p => (
                    <option key={p.id} value={p.name}>{p.name} ({p.skills.join(', ')} | {p.region} | 负载:{p.load})</option>
                  ))}
                </select>
              </div>
              <input placeholder="预估成本" type="number" value={form.cost_estimate} onChange={(e) => setForm({ ...form, cost_estimate: e.target.value })}
                className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
              <input placeholder="DDL截止日期" type="date" value={form.due_date || ''} onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border border-border-default rounded text-sm text-text-secondary">取消</button>
              <button onClick={handleCreate} className="px-4 py-2 bg-accent-blue text-white rounded text-sm">创建</button>
            </div>
          </div>
        </div>
      )}

      {/* Orders List */}
      {loading ? <p className="text-text-muted text-sm">加载中...</p> : (
        <div className="space-y-2">
          {orders.map((o) => (
            <div key={o.id} className="bg-bg-card border border-border-default rounded-lg p-4 hover:border-border-active transition-colors">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-text-muted font-mono">WO-{String(o.id).padStart(4, '0')}</span>
                  <span className="text-sm font-medium">{o.title}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${STATUS_COLOR[o.status] || ''}`}>{STATUS_LABEL[o.status] || o.status}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => runAIAnalysis(o)}
                    className="px-3 py-1.5 border border-accent-cyan/50 text-accent-cyan rounded text-xs hover:bg-accent-cyan/10 transition-colors"
                  >
                    📧 预览工单
                  </button>
                  {o.status !== 'closed' && (
                    <button onClick={() => advanceStatus(o.id, o.status)}
                      className="px-3 py-1.5 bg-accent-blue/10 text-accent-blue rounded text-xs hover:bg-accent-blue/20">
                      {o.status === 'completed' ? '关闭' : '推进 →'}
                    </button>
                  )}
                </div>
              </div>
              <div className="flex gap-4 mt-2 text-[10px] text-text-muted">
                <span>风机 #{o.turbine_id}</span>
                {o.assignee && <span>👤 {o.assignee}</span>}
                <span>¥{o.cost_estimate.toLocaleString()}</span>
                <span>{new Date(o.created_at).toLocaleDateString('zh-CN')}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Preview Modal — email template + AI analysis */}
      {previewWO && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => { setPreviewWO(null); setAiAnalysis(null); }}>
          <div className="bg-bg-card border border-border-default rounded-lg w-[640px] max-h-[85vh] overflow-auto shadow-2xl" onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div className="sticky top-0 bg-bg-secondary border-b border-border-default px-5 py-3 flex items-center justify-between z-10">
              <div>
                <h3 className="font-medium text-sm">📧 邮件预览 — WO-{String(previewWO.id).padStart(4, '0')}</h3>
                <p className="text-[10px] text-text-muted">Subject: [风调预顺] WO-{String(previewWO.id).padStart(4, '0')} {previewWO.title}</p>
              </div>
              <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }} className="text-text-muted hover:text-text-primary text-lg">✕</button>
            </div>

            {/* Email Body */}
            <div className="p-5 space-y-4 text-xs">
              <div className="border-2 border-border-default rounded-lg p-4 space-y-3 font-mono bg-bg-secondary">
                <div className="text-center border-b border-border-default pb-2">
                  <p className="font-bold text-sm">工单通知 — {previewWO.title}</p>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div><span className="text-text-muted">工单编号:</span> WO-{String(previewWO.id).padStart(4, '0')}</div>
                  <div><span className="text-text-muted">优先级:</span> <span className="text-accent-red">🔴 紧急</span></div>
                  <div><span className="text-text-muted">创建时间:</span> {new Date(previewWO.created_at).toLocaleString('zh-CN')}</div>
                  <div><span className="text-text-muted">DDL截止:</span> <span className="text-accent-yellow">{new Date(Date.now() + 7*86400000).toLocaleDateString('zh-CN')}</span></div>
                </div>

                <div className="border-t border-border-default pt-2">
                  <p className="font-medium mb-1">📊 风机信息</p>
                  <div className="grid grid-cols-2 gap-1 text-text-secondary">
                    <div>风机: {previewWO.turbine_id}</div>
                    <div>区域: 陕北</div>
                    <div>当前状态: 预警</div>
                    <div>HI值: 78.1</div>
                  </div>
                </div>

                {/* AI Analysis section */}
                <div className="border-t border-border-default pt-2">
                  <p className="font-medium mb-1">🤖 AI分析报告</p>
                  {analyzing ? (
                    <p className="text-text-muted animate-pulse">AI分析中, 正在获取风机数据...</p>
                  ) : aiAnalysis ? (
                    <div className="space-y-2">
                      <p className="text-text-secondary">{aiAnalysis.diagnosis}</p>
                      <div className="mt-2">
                        <p className="text-accent-red font-medium mb-1">⚠️ 异常指标 (超出置信范围):</p>
                        {aiAnalysis.anomalies.map((a, i) => (
                          <div key={i} className={`flex items-center gap-2 py-1 border-b border-border-default last:border-0 ${a.level === 'high' ? 'text-accent-red' : 'text-accent-yellow'}`}>
                            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: a.level === 'high' ? '#f85149' : '#d29922' }} />
                            <span className="font-medium w-20">{a.indicator}</span>
                            <span>当前: <b>{a.value}</b></span>
                            <span className="text-text-muted">正常: {a.normal}</span>
                            <span className="font-bold">{a.deviation}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <p className="text-text-muted">AI分析加载失败</p>
                  )}
                </div>

                <div className="border-t border-border-default pt-2">
                  <p className="font-medium mb-1">🔧 操作步骤</p>
                  <ol className="list-decimal list-inside text-text-secondary space-y-0.5">
                    <li>停机检查相关部件温度</li>
                    <li>安排振动复测确认故障程度</li>
                    <li>根据检查结果更换受损部件</li>
                    <li>修复后运行24h监测确认</li>
                  </ol>
                </div>

                <div className="border-t border-border-default pt-2 grid grid-cols-2 gap-2">
                  <div><span className="text-text-muted">预估工时:</span> 4h</div>
                  <div><span className="text-text-muted">预估成本:</span> ¥{previewWO.cost_estimate.toLocaleString()}</div>
                  <div><span className="text-text-muted">备件需求:</span> 轴承套件×1</div>
                  <div><span className="text-text-muted">责任人:</span> {previewWO.assignee || '待分配'}</div>
                </div>
              </div>
            </div>

            {/* Footer actions */}
            <div className="sticky bottom-0 bg-bg-secondary border-t border-border-default px-5 py-3 flex gap-2 justify-end">
              <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }} className="px-4 py-2 border border-border-default rounded text-sm text-text-secondary">返回编辑</button>
              <button className="px-4 py-2 bg-accent-green text-white rounded text-sm hover:opacity-90">📧 发送邮件</button>
            </div>
          </div>
        </div>
      )}

      <CopilotFAB />
    </div>
  );
}
