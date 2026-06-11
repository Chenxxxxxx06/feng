import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

const STATUS_FLOW = ['pending', 'assigned', 'in_progress', 'review', 'completed', 'closed'];
const STATUS_LABEL: Record<string, string> = { pending: '待分配', assigned: '已分配', in_progress: '执行中', review: '待验收', completed: '已完成', closed: '已关闭', cancelled: '已取消' };
const STATUS_COLOR: Record<string, string> = { pending: 'bg-accent-red/20 text-accent-red', assigned: 'bg-accent-yellow/20 text-accent-yellow', in_progress: 'bg-accent-blue/20 text-accent-blue', review: 'bg-accent-yellow/20 text-accent-yellow', completed: 'bg-accent-green/20 text-accent-green', closed: 'bg-text-muted/20 text-text-muted', cancelled: 'bg-text-muted/20 text-text-muted' };
const PRIORITY_LABEL: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' };
const PRIORITY_COLOR: Record<string, string> = { low: 'text-accent-green', medium: 'text-accent-blue', high: 'text-accent-yellow', urgent: 'text-accent-red' };

interface Personnel { id: number; name: string; skills: string[]; region: string; load: number; email: string }
interface AIAnalysis { diagnosis: string; anomalies: { indicator: string; value: string; normal: string; deviation: string; level: string }[]; turbine_name: string; fault_type: string }

const emptyForm = {
  turbine_id: '',
  title: '',
  description: '',
  assignee: '',
  assignee_id: '',
  assignee_email: '',
  cost_estimate: '0',
  priority: 'medium',
  fault_type: '轴承磨损',
  due_date: '',
};

export default function WorkOrderPage() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [personnel, setPersonnel] = useState<Personnel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [previewWO, setPreviewWO] = useState<WorkOrder | null>(null);
  const [openActionId, setOpenActionId] = useState<number | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [emailResult, setEmailResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [editingWO, setEditingWO] = useState(false);
  const [editForm, setEditForm] = useState({
    title: '',
    description: '',
    status: 'pending',
    assignee: '',
    fault_type: '',
    cost_estimate: '0',
  });
  const [form, setForm] = useState(emptyForm);

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
      turbine_id: Number(form.turbine_id),
      title: form.title,
      description: form.description,
      assignee: form.assignee || null,
      assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
      assignee_email: form.assignee_email || null,
      priority: form.priority,
      fault_type: form.fault_type,
      due_date: form.due_date || null,
      cost_estimate: Number(form.cost_estimate),
    });
    setShowCreate(false);
    setForm(emptyForm);
    fetchOrders();
  };

  const advanceStatus = async (id: number, current: string) => {
    const idx = STATUS_FLOW.indexOf(current);
    if (idx < STATUS_FLOW.length - 1) {
      await api.put(`/workorders/${id}`, { status: STATUS_FLOW[idx + 1] });
      setOpenActionId(null);
      fetchOrders();
    }
  };

  const cancelOrder = async (id: number) => {
    await api.delete(`/workorders/${id}`);
    setOpenActionId(null);
    fetchOrders();
  };

  const startEdit = (wo: WorkOrder) => {
    setEditForm({
      title: wo.title,
      description: wo.description || '',
      status: wo.status,
      assignee: wo.assignee || '',
      fault_type: wo.fault_type || '',
      cost_estimate: String(wo.cost_estimate || 0),
    });
    setEditingWO(true);
  };

  const saveEdit = async () => {
    if (!previewWO) return;
    const assignee = personnel.find((p) => p.name === editForm.assignee);
    const { data } = await api.put(`/workorders/${previewWO.id}`, {
      title: editForm.title,
      description: editForm.description || null,
      status: editForm.status,
      assignee: editForm.assignee || null,
      assignee_id: assignee?.id || null,
      assignee_email: assignee?.email || null,
      fault_type: editForm.fault_type || null,
      cost_estimate: Number(editForm.cost_estimate),
    });
    setPreviewWO(data);
    setOrders((prev) => prev.map((o) => (o.id === data.id ? data : o)));
    setEditingWO(false);
  };

  const sendEmail = async (wo: WorkOrder) => {
    setSendingEmail(true);
    setEmailResult(null);
    try {
      const recipients = wo.assignee_email ? [wo.assignee_email] : [];
      const { data } = await api.post(`/workorders/${wo.id}/send-email`, {
        recipient_emails: recipients,
        subject: `[风调预顺] WO-${String(wo.id).padStart(4, '0')} ${wo.title}`,
        use_preview_template: true,
      });
      if ((data.sent || 0) === 0) {
        const failedLog = data.logs?.find((log: any) => log.status === 'failed');
        setEmailResult({ type: 'error', message: failedLog?.error_message || '未实际发送：未找到负责人邮箱或后端仍未重启' });
      } else {
        setEmailResult({ type: 'success', message: `邮件已成功发送给负责人，共 ${data.sent} 封。` });
      }
    } catch (err: any) {
      setEmailResult({ type: 'error', message: err.response?.data?.detail || '发送失败，请检查通知配置' });
    }
    setSendingEmail(false);
  };

  const runAIAnalysis = async (wo: WorkOrder) => {
    setPreviewWO(wo);
    setEditingWO(false);
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
  const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN') : '未设置';
  const priorityOf = (wo: WorkOrder) => wo.priority || 'medium';
  const nextStatusLabel = (status: string) => {
    const idx = STATUS_FLOW.indexOf(status);
    if (idx < 0 || idx >= STATUS_FLOW.length - 1) return '';
    return status === 'completed' ? '关闭工单' : `推进到${STATUS_LABEL[STATUS_FLOW[idx + 1]]}`;
  };

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
                  setForm({ ...form, assignee: e.target.value, assignee_id: p ? String(p.id) : '', assignee_email: p?.email || '' });
                }} className="w-full bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary">
                  <option value="">-- 选择责任人 --</option>
                  {personnel.map(p => (
                    <option key={p.id} value={p.name}>{p.name} ({p.skills.join(', ')} | {p.region} | 负载:{p.load})</option>
                  ))}
                </select>
              </div>
              <input placeholder="预估成本" type="number" value={form.cost_estimate} onChange={(e) => setForm({ ...form, cost_estimate: e.target.value })}
                className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue" />
              <label className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus-within:border-accent-blue">
                <span className="block text-[10px] text-text-muted mb-1">DDL截止日期</span>
                <input
                  type="date"
                  value={form.due_date || ''}
                  onClick={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                  onFocus={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                  onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                  className="w-full bg-transparent text-text-primary focus:outline-none [color-scheme:dark]"
                />
              </label>
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
                <div className="flex items-center gap-2 relative">
                  <button
                    onClick={() => runAIAnalysis(o)}
                    className="px-3 py-1.5 border border-accent-cyan/50 text-accent-cyan rounded text-xs hover:bg-accent-cyan/10 transition-colors"
                  >
                    📧 预览工单
                  </button>
                  <button
                    onClick={() => setOpenActionId(openActionId === o.id ? null : o.id)}
                    className="w-20 px-3 py-1.5 bg-accent-blue/10 text-accent-blue rounded text-xs hover:bg-accent-blue/20"
                  >
                    操作 ▾
                  </button>
                  {openActionId === o.id && (
                    <div className="absolute right-0 top-8 z-20 w-36 bg-bg-card border border-border-default rounded shadow-xl py-1 text-xs">
                      {o.status !== 'closed' && o.status !== 'cancelled' && (
                        <button
                          onClick={() => advanceStatus(o.id, o.status)}
                          className="block w-full text-left px-3 py-2 text-text-secondary hover:bg-bg-hover hover:text-accent-blue"
                        >
                          {nextStatusLabel(o.status)}
                        </button>
                      )}
                      {!['closed', 'completed', 'cancelled'].includes(o.status) && (
                        <button
                          onClick={() => cancelOrder(o.id)}
                          className="block w-full text-left px-3 py-2 text-accent-red hover:bg-accent-red/10"
                        >
                          取消工单
                        </button>
                      )}
                      {(o.status === 'closed' || o.status === 'cancelled') && (
                        <div className="px-3 py-2 text-text-muted">暂无操作</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-4 mt-2 text-[10px] text-text-muted">
                <span>风机 #{o.turbine_id}</span>
                <span className={PRIORITY_COLOR[priorityOf(o)]}>优先级: {PRIORITY_LABEL[priorityOf(o)]}</span>
                <span>故障: {o.fault_type || '未设置'}</span>
                <span>DDL: {formatDate(o.due_date)}</span>
                {o.assignee && <span>👤 {o.assignee}</span>}
                <span>¥{o.cost_estimate.toLocaleString()}</span>
                {o.notification_sent_at && <span className="text-accent-green">已通知</span>}
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
                <h3 className="font-medium text-sm">{editingWO ? '编辑工单' : '📧 邮件预览'} — WO-{String(previewWO.id).padStart(4, '0')}</h3>
                <p className="text-[10px] text-text-muted">Subject: [风调预顺] WO-{String(previewWO.id).padStart(4, '0')} {previewWO.title}</p>
              </div>
              <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }} className="text-text-muted hover:text-text-primary text-lg">✕</button>
            </div>

            {/* Email Body */}
            <div className="p-5 space-y-4 text-xs">
              {editingWO && (
                <div className="border border-border-default rounded-lg p-4 space-y-3 bg-bg-secondary">
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      value={editForm.title}
                      onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                      placeholder="工单标题"
                      className="col-span-2 bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                    />
                    <select
                      value={editForm.status}
                      onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                      className="bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary"
                    >
                      {[...STATUS_FLOW, 'cancelled'].map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
                    </select>
                    <input
                      type="number"
                      value={editForm.cost_estimate}
                      onChange={(e) => setEditForm({ ...editForm, cost_estimate: e.target.value })}
                      placeholder="预估成本（元）"
                      className="bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                    />
                    <select
                      value={editForm.assignee}
                      onChange={(e) => setEditForm({ ...editForm, assignee: e.target.value })}
                      className="col-span-2 bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary"
                    >
                      <option value="">待分配</option>
                      {personnel.map((p) => <option key={p.id} value={p.name}>{p.name} ({p.email})</option>)}
                    </select>
                    <select
                      value={editForm.fault_type}
                      onChange={(e) => setEditForm({ ...editForm, fault_type: e.target.value })}
                      className="col-span-2 bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary"
                    >
                      <option value="">未设置故障类型</option>
                      {FAULT_TYPES.map((ft) => <option key={ft} value={ft}>{ft}</option>)}
                    </select>
                    <textarea
                      value={editForm.description}
                      onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                      placeholder="工单描述"
                      rows={3}
                      className="col-span-2 bg-bg-card border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                    />
                  </div>
                </div>
              )}
              <div className="border-2 border-border-default rounded-lg p-4 space-y-3 font-mono bg-bg-secondary">
                <div className="text-center border-b border-border-default pb-2">
                  <p className="font-bold text-sm">工单通知 — {previewWO.title}</p>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div><span className="text-text-muted">工单编号:</span> WO-{String(previewWO.id).padStart(4, '0')}</div>
                  <div><span className="text-text-muted">优先级:</span> <span className={PRIORITY_COLOR[priorityOf(previewWO)]}>{PRIORITY_LABEL[priorityOf(previewWO)]}</span></div>
                  <div><span className="text-text-muted">创建时间:</span> {new Date(previewWO.created_at).toLocaleString('zh-CN')}</div>
                  <div><span className="text-text-muted">DDL截止:</span> <span className="text-accent-yellow">{formatDate(previewWO.due_date)}</span></div>
                  <div><span className="text-text-muted">故障类型:</span> {previewWO.fault_type || aiAnalysis?.fault_type || '未设置'}</div>
                  <div><span className="text-text-muted">通知状态:</span> {previewWO.notification_sent_at ? `已通知 ${formatDate(previewWO.notification_sent_at)}` : '未发送'}</div>
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
                  <div><span className="text-text-muted">收件邮箱:</span> {previewWO.assignee_email || '按责任人账号邮箱发送'}</div>
                  <div><span className="text-text-muted">责任人:</span> {previewWO.assignee || '待分配'}</div>
                </div>
              </div>
            </div>

            {/* Footer actions */}
            <div className="sticky bottom-0 bg-bg-secondary border-t border-border-default px-5 py-3 flex gap-2 justify-end">
              {editingWO ? (
                <>
                  <button onClick={() => setEditingWO(false)} className="px-4 py-2 border border-border-default rounded text-sm text-text-secondary">取消编辑</button>
                  <button onClick={saveEdit} className="px-4 py-2 bg-accent-blue text-white rounded text-sm hover:opacity-90">保存修改</button>
                </>
              ) : (
                <>
                  <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); setEditingWO(false); }} className="px-4 py-2 border border-border-default rounded text-sm text-text-secondary">关闭</button>
                  <button onClick={() => startEdit(previewWO)} className="px-4 py-2 border border-accent-blue/50 text-accent-blue rounded text-sm hover:bg-accent-blue/10">编辑工单</button>
                  <button disabled={sendingEmail} onClick={() => sendEmail(previewWO)} className="px-4 py-2 bg-accent-green text-white rounded text-sm hover:opacity-90 disabled:opacity-50">
                    {sendingEmail ? '发送中...' : '📧 发送邮件'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {emailResult && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={() => setEmailResult(null)}>
          <div className="w-[360px] bg-bg-card border border-border-default rounded-lg p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className={`text-sm font-medium mb-2 ${emailResult.type === 'success' ? 'text-accent-green' : 'text-accent-red'}`}>
              {emailResult.type === 'success' ? '发送成功' : '发送失败'}
            </h3>
            <p className="text-xs text-text-secondary leading-relaxed break-words">{emailResult.message}</p>
            <div className="flex justify-end mt-4">
              <button onClick={() => setEmailResult(null)} className="px-4 py-2 bg-accent-blue text-white rounded text-sm">
                知道了
              </button>
            </div>
          </div>
        </div>
      )}

      <CopilotFAB />
    </div>
  );
}
