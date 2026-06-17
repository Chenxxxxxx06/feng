import { useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import type { WorkOrder } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

const STATUS_FLOW = ['pending', 'assigned', 'in_progress', 'review', 'completed', 'closed'];
const STATUS_FILTERS = [...STATUS_FLOW, 'cancelled'];
const STATUS_LABEL: Record<string, string> = {
  pending: '待分配',
  assigned: '已分配',
  in_progress: '执行中',
  review: '待验收',
  completed: '已完成',
  closed: '已关闭',
  cancelled: '已取消',
};
const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-accent-red/15 text-accent-red border-accent-red/25',
  assigned: 'bg-accent-yellow/15 text-accent-yellow border-accent-yellow/25',
  in_progress: 'bg-accent-blue/15 text-accent-blue border-accent-blue/25',
  review: 'bg-accent-yellow/15 text-accent-yellow border-accent-yellow/25',
  completed: 'bg-accent-green/15 text-accent-green border-accent-green/25',
  closed: 'bg-text-muted/15 text-text-muted border-text-muted/25',
  cancelled: 'bg-text-muted/15 text-text-muted border-text-muted/25',
};
const PRIORITY_LABEL: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' };
const PRIORITY_COLOR: Record<string, string> = {
  low: 'text-accent-green',
  medium: 'text-accent-blue',
  high: 'text-accent-yellow',
  urgent: 'text-accent-red',
};
const PRIORITY_BORDER: Record<string, string> = {
  low: 'border-l-accent-green',
  medium: 'border-l-accent-blue',
  high: 'border-l-accent-yellow',
  urgent: 'border-l-accent-red',
};

interface Personnel {
  id: number;
  name: string;
  skills: string[];
  region: string;
  load: number;
  email: string;
}

interface AIAnalysis {
  diagnosis: string;
  anomalies: { indicator: string; value: string; normal: string; deviation: string; level: string }[];
  turbine_name: string;
  fault_type: string;
}

const FAULT_TYPES = [
  '轴承磨损',
  '齿轮箱点蚀',
  '发电机过热',
  '叶片裂纹',
  '变桨系统故障',
  '冷却系统故障',
  '主轴不对中',
  '电气故障',
];

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

function isTerminal(status: string) {
  return ['completed', 'closed', 'cancelled'].includes(status);
}

function dateOnly(value?: string | null) {
  return value ? new Date(value).toLocaleDateString('zh-CN') : '未设置';
}

function isDueToday(value?: string | null) {
  if (!value) return false;
  const due = new Date(value);
  const now = new Date();
  return due.toDateString() === now.toDateString();
}

function isOverdue(wo: WorkOrder) {
  if (!wo.due_date || isTerminal(wo.status)) return false;
  const due = new Date(wo.due_date);
  due.setHours(23, 59, 59, 999);
  return due.getTime() < Date.now();
}

function dueTone(wo: WorkOrder) {
  if (isOverdue(wo)) return 'text-accent-red';
  if (isDueToday(wo.due_date)) return 'text-accent-yellow';
  return 'text-text-secondary';
}

function WorkOrderStepper({ status }: { status: string }) {
  const activeIndex = STATUS_FLOW.indexOf(status);
  if (status === 'cancelled') {
    return <span className="text-[11px] text-accent-red">工单已取消</span>;
  }

  return (
    <div className="flex items-center gap-1.5">
      {STATUS_FLOW.map((s, idx) => {
        const done = activeIndex >= idx;
        const current = activeIndex === idx;
        return (
          <span key={s} className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-8 rounded-full transition-colors ${
                done ? (current ? 'bg-accent-blue' : 'bg-accent-green/70') : 'bg-border-default'
              }`}
              title={STATUS_LABEL[s]}
            />
          </span>
        );
      })}
    </div>
  );
}

export default function WorkOrderPage() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [personnel, setPersonnel] = useState<Personnel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [previewWO, setPreviewWO] = useState<WorkOrder | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<WorkOrder | null>(null);
  const [deletingOrder, setDeletingOrder] = useState(false);
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
    priority: 'medium',
    assignee: '',
    fault_type: '',
    due_date: '',
    cost_estimate: '0',
  });
  const [form, setForm] = useState(emptyForm);

  const fetchOrders = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (priorityFilter) params.set('priority', priorityFilter);
      const query = params.toString();
      const { data } = await api.get(`/workorders/${query ? `?${query}` : ''}`);
      setOrders(data);
    } catch (err: any) {
      setLoadError(err.response?.data?.detail || '工单加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
    api.get('/personnel/').then(({ data }) => setPersonnel(data)).catch(() => {});
  }, [statusFilter, priorityFilter]);

  const stats = useMemo(() => {
    const active = orders.filter((o) => !isTerminal(o.status));
    return [
      { label: '待处理', value: active.length, tone: 'text-accent-blue', hint: '未关闭工单' },
      { label: '执行中', value: orders.filter((o) => o.status === 'in_progress').length, tone: 'text-accent-cyan', hint: '现场处理中' },
      { label: '今日到期', value: orders.filter((o) => isDueToday(o.due_date) && !isTerminal(o.status)).length, tone: 'text-accent-yellow', hint: '需要关注' },
      { label: '紧急工单', value: orders.filter((o) => o.priority === 'urgent' && !isTerminal(o.status)).length, tone: 'text-accent-red', hint: '高风险优先' },
    ];
  }, [orders]);

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
    const { data } = await api.put(`/workorders/${id}`, { status: 'cancelled' });
    setOrders((prev) => prev.map((o) => (o.id === id ? data : o)));
    setOpenActionId(null);
    fetchOrders();
  };

  const requestDeleteOrder = (wo: WorkOrder) => {
    setDeleteTarget(wo);
    setOpenActionId(null);
  };

  const confirmDeleteOrder = async () => {
    if (!deleteTarget) return;
    setDeletingOrder(true);
    await api.delete(`/workorders/${deleteTarget.id}`);
    setOrders((prev) => prev.filter((o) => o.id !== deleteTarget.id));
    if (previewWO?.id === deleteTarget.id) {
      setPreviewWO(null);
      setAiAnalysis(null);
      setEditingWO(false);
    }
    setDeleteTarget(null);
    setDeletingOrder(false);
  };

  const startEdit = (wo: WorkOrder) => {
    setEditForm({
      title: wo.title,
      description: wo.description || '',
      status: wo.status,
      priority: wo.priority || 'medium',
      assignee: wo.assignee || '',
      fault_type: wo.fault_type || '',
      due_date: wo.due_date ? wo.due_date.slice(0, 10) : '',
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
      priority: editForm.priority,
      fault_type: editForm.fault_type || null,
      due_date: editForm.due_date || null,
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
        setEmailResult({ type: 'error', message: failedLog?.error_message || '未实际发送：未找到责任人邮箱或后端未完成通知配置' });
      } else {
        setEmailResult({ type: 'success', message: `邮件已发送给责任人，共 ${data.sent} 封。` });
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
        fault_type: wo.fault_type || wo.title || '未知故障',
      });
      setAiAnalysis(data);
    } catch {
      setAiAnalysis(null);
    }
    setAnalyzing(false);
  };

  const priorityOf = (wo: WorkOrder) => wo.priority || 'medium';
  const nextStatusLabel = (status: string) => {
    const idx = STATUS_FLOW.indexOf(status);
    if (idx < 0 || idx >= STATUS_FLOW.length - 1) return '';
    return status === 'completed' ? '关闭工单' : `推进到${STATUS_LABEL[STATUS_FLOW[idx + 1]]}`;
  };

  return (
    <div className="h-full overflow-auto ops-page">
      <div className="mx-auto max-w-[1480px] space-y-5 p-6">
        <section className="ops-header flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="ops-eyebrow">维修记录与通知管理</p>
            <h2 className="ops-title gradient-text">维修工单工作台</h2>
            <p className="ops-subtitle">
              汇总派工、进度、截止日期和通知状态，帮助运维人员优先处理高风险任务。
            </p>
          </div>
          <button
            data-action="create-workorder"
            onClick={() => setShowCreate(true)}
            className="ops-btn ops-btn-primary h-10 px-4 text-sm"
          >
            创建工单
          </button>
        </section>

        <section className="grid gap-3 md:grid-cols-4">
          {stats.map((item) => (
            <div key={item.label} className="ops-panel p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-text-muted">{item.label}</span>
                <span className="text-[10px] text-text-muted">{item.hint}</span>
              </div>
              <p className={`mt-3 font-mono text-3xl font-semibold ${item.tone}`}>{item.value}</p>
            </div>
          ))}
        </section>

        <section className="ops-panel p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <select
                data-action="filter-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="h-9 px-3 text-sm text-text-primary"
              >
                <option value="">全部状态</option>
                {STATUS_FILTERS.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              </select>
              <select
                value={priorityFilter}
                onChange={(e) => setPriorityFilter(e.target.value)}
                className="h-9 px-3 text-sm text-text-primary"
              >
                <option value="">全部优先级</option>
                <option value="low">低</option>
                <option value="medium">中</option>
                <option value="high">高</option>
                <option value="urgent">紧急</option>
              </select>
              {(statusFilter || priorityFilter) && (
                <button
                  onClick={() => { setStatusFilter(''); setPriorityFilter(''); }}
                  className="ops-btn h-9 px-3 text-xs"
                >
                  清空筛选
                </button>
              )}
            </div>
            <div className="text-xs text-text-muted">
              当前显示 <span className="font-mono text-text-primary">{orders.length}</span> 条工单
            </div>
          </div>
        </section>

        {showCreate && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="w-full max-w-[620px] ops-panel shadow-2xl">
              <div className="border-b border-border-default px-6 py-4">
                <h3 className="text-base font-medium">创建新工单</h3>
                <p className="mt-1 text-xs text-text-muted">填写故障、派工和截止日期信息。</p>
              </div>
              <div className="max-h-[72vh] space-y-5 overflow-auto p-6">
                <div>
                  <p className="mb-3 text-xs font-medium text-text-secondary">基础信息</p>
                  <div className="grid grid-cols-2 gap-3">
                    <input placeholder="风机 ID *" value={form.turbine_id} onChange={(e) => setForm({ ...form, turbine_id: e.target.value })}
                      className="form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none" />
                    <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}
                      className="form-input px-3 py-2 text-sm text-text-primary">
                      <option value="low">低优先级</option><option value="medium">中优先级</option><option value="high">高优先级</option><option value="urgent">紧急</option>
                    </select>
                    <input placeholder="工单标题 *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                      className="col-span-2 form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none" />
                    <select value={form.fault_type} onChange={(e) => setForm({ ...form, fault_type: e.target.value })}
                      className="col-span-2 form-input px-3 py-2 text-sm text-text-primary">
                      {FAULT_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
                    </select>
                  </div>
                </div>

                <div>
                  <p className="mb-3 text-xs font-medium text-text-secondary">派工信息</p>
                  <div className="grid grid-cols-2 gap-3">
                    <select value={form.assignee} onChange={(e) => {
                      const p = personnel.find(pp => pp.name === e.target.value);
                      setForm({ ...form, assignee: e.target.value, assignee_id: p ? String(p.id) : '', assignee_email: p?.email || '' });
                    }} className="col-span-2 form-input px-3 py-2 text-sm text-text-primary">
                      <option value="">选择责任人</option>
                      {personnel.map(p => (
                        <option key={p.id} value={p.name}>{p.name} | {p.email} | {p.region} | 负载:{p.load}</option>
                      ))}
                    </select>
                    <div className="col-span-2 rounded border border-border-default bg-bg-secondary/70 px-3 py-2 text-xs text-text-secondary">
                      责任人邮箱：
                      <span className="ml-1 font-mono text-text-primary">
                        {form.assignee_email || '选择责任人后自动显示'}
                      </span>
                    </div>
                    <input placeholder="预估成本" type="number" value={form.cost_estimate} onChange={(e) => setForm({ ...form, cost_estimate: e.target.value })}
                      className="form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none" />
                    <input
                      type="date"
                      value={form.due_date || ''}
                      onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                      className="form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none [color-scheme:dark]"
                    />
                  </div>
                </div>

                <textarea placeholder="工单描述" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={4}
                  className="w-full form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none" />
              </div>
              <div className="flex justify-end gap-2 border-t border-border-default px-6 py-4">
                <button onClick={() => setShowCreate(false)} className="ops-btn px-4 py-2 text-sm">取消</button>
                <button onClick={handleCreate} className="ops-btn ops-btn-primary px-4 py-2 text-sm">创建</button>
              </div>
            </div>
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((item) => (
              <div key={item} className="h-28 animate-pulse premium-card rounded-2xl" />
            ))}
          </div>
        ) : loadError ? (
          <div className="rounded-lg border border-accent-red/30 bg-accent-red/10 p-6 text-sm text-accent-red">
            {loadError}
          </div>
        ) : orders.length === 0 ? (
          <div className="premium-card rounded-2xl p-12 text-center border-dashed">
            <p className="text-base font-medium text-text-primary">暂无符合条件的维修工单</p>
            <p className="mt-2 text-sm text-text-muted">可以调整筛选条件，或创建一条新的维修任务。</p>
            <button onClick={() => setShowCreate(true)} className="mt-5 rounded bg-accent-blue px-4 py-2 text-sm text-white">创建工单</button>
          </div>
        ) : (
          <div className="space-y-3">
            {orders.map((o) => {
              const priority = priorityOf(o);
              return (
                <article
                  key={o.id}
                  data-wo-id={o.id}
                  data-wo-assignee={o.assignee || ''}
                  data-wo-title={o.title}
                  className={`ops-list-card border-l-4 ${PRIORITY_BORDER[priority]} p-4`}
                >
                  <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[11px] text-text-muted">WO-{String(o.id).padStart(4, '0')}</span>
                        <span className={`rounded border px-2 py-0.5 text-[11px] ${STATUS_COLOR[o.status] || STATUS_COLOR.pending}`}>
                          {STATUS_LABEL[o.status] || o.status}
                        </span>
                        <span className={`text-[11px] font-medium ${PRIORITY_COLOR[priority]}`}>{PRIORITY_LABEL[priority]}优先级</span>
                        {isOverdue(o) && <span className="rounded bg-accent-red/15 px-2 py-0.5 text-[11px] text-accent-red">已超期</span>}
                      </div>
                      <h3 className="mt-3 truncate text-base font-semibold text-text-primary">{o.title}</h3>
                      <p className="mt-2 line-clamp-2 max-w-3xl text-sm leading-6 text-text-secondary">{o.description || '暂无工单描述'}</p>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                      <button
                        onClick={() => runAIAnalysis(o)}
                        className="h-8 rounded border border-accent-cyan/50 px-3 text-xs text-accent-cyan hover:bg-accent-cyan/10"
                      >
                        预览
                      </button>
                      {!isTerminal(o.status) && (
                        <button
                          onClick={() => advanceStatus(o.id, o.status)}
                          className="ops-btn h-8 px-3 text-xs"
                        >
                          {nextStatusLabel(o.status)}
                        </button>
                      )}
                      <div className="relative">
                        <button
                          onClick={() => setOpenActionId(openActionId === o.id ? null : o.id)}
                          className="ops-btn h-8 px-3 text-xs"
                        >
                          更多
                        </button>
                        {openActionId === o.id && (
                          <div className="absolute right-0 top-9 z-20 w-32 rounded border border-border-default bg-bg-card py-1 text-xs shadow-xl">
                            {!isTerminal(o.status) && (
                              <button onClick={() => cancelOrder(o.id)} className="block w-full px-3 py-2 text-left text-accent-red hover:bg-accent-red/10">
                                取消工单
                              </button>
                            )}
                            <button onClick={() => { setPreviewWO(o); startEdit(o); setOpenActionId(null); }} className="block w-full px-3 py-2 text-left text-text-secondary hover:bg-bg-hover hover:text-text-primary">
                              编辑
                            </button>
                            <button onClick={() => requestDeleteOrder(o)} className="block w-full px-3 py-2 text-left text-accent-red hover:bg-accent-red/10">
                              删除
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 border-t border-border-default pt-4 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
                    <div>
                      <p className="mb-2 text-[11px] text-text-muted">流程进度</p>
                      <WorkOrderStepper status={o.status} />
                    </div>
                    <div className="text-xs">
                      <p className="text-text-muted">风机与故障</p>
                      <p className="mt-1 text-text-primary">#{o.turbine_id} · {o.fault_type || '未设置'}</p>
                    </div>
                    <div className="text-xs">
                      <p className="text-text-muted">责任人与截止</p>
                      <p className="mt-1 text-text-primary">{o.assignee || '待分配'} · <span className={dueTone(o)}>{dateOnly(o.due_date)}</span></p>
                      {o.assignee_email && <p className="mt-1 truncate font-mono text-[11px] text-text-muted">{o.assignee_email}</p>}
                    </div>
                    <div className="text-xs">
                      <p className="text-text-muted">成本与通知</p>
                      <p className="mt-1 text-text-primary">¥{o.cost_estimate.toLocaleString()} · {o.notification_sent_at ? '已通知' : '未通知'}</p>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        {previewWO && (
          <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={() => { setPreviewWO(null); setAiAnalysis(null); }}>
            <div className="ops-drawer h-full w-full max-w-[720px] overflow-auto" onClick={e => e.stopPropagation()}>
              <div className="sticky top-0 z-10 border-b border-border-default bg-bg-panel/95 px-6 py-4 backdrop-blur">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="font-mono text-xs text-text-muted">WO-{String(previewWO.id).padStart(4, '0')}</p>
                    <h3 className="mt-1 text-lg font-semibold">{editingWO ? '编辑工单' : previewWO.title}</h3>
                    <p className="mt-1 text-xs text-text-muted">状态：{STATUS_LABEL[previewWO.status] || previewWO.status}</p>
                  </div>
                  <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); }} className="ops-btn px-3 py-1.5 text-sm">关闭</button>
                </div>
              </div>

              <div className="space-y-5 p-6 text-sm">
                {editingWO && (
                  <div className="premium-card rounded-2xl p-4">
                    <p className="mb-3 text-xs font-medium text-text-secondary">编辑信息</p>
                    <div className="grid grid-cols-2 gap-3">
                      <input value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} placeholder="工单标题"
                        className="col-span-2 form-input px-3 py-2 text-sm focus:border-accent-blue focus:outline-none" />
                      <select value={editForm.status} onChange={(e) => setEditForm({ ...editForm, status: e.target.value })} className="form-input px-3 py-2 text-sm">
                        {[...STATUS_FLOW, 'cancelled'].map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
                      </select>
                      <select value={editForm.priority} onChange={(e) => setEditForm({ ...editForm, priority: e.target.value })} className="form-input px-3 py-2 text-sm">
                        <option value="low">低优先级</option>
                        <option value="medium">中优先级</option>
                        <option value="high">高优先级</option>
                        <option value="urgent">紧急</option>
                      </select>
                      <input type="number" value={editForm.cost_estimate} onChange={(e) => setEditForm({ ...editForm, cost_estimate: e.target.value })} placeholder="预估成本"
                        className="form-input px-3 py-2 text-sm focus:border-accent-blue focus:outline-none" />
                      <input type="date" value={editForm.due_date} onChange={(e) => setEditForm({ ...editForm, due_date: e.target.value })}
                        className="form-input px-3 py-2 text-sm focus:border-accent-blue focus:outline-none [color-scheme:dark]" />
                      <select value={editForm.assignee} onChange={(e) => setEditForm({ ...editForm, assignee: e.target.value })} className="col-span-2 form-input px-3 py-2 text-sm">
                        <option value="">待分配</option>
                        {personnel.map((p) => <option key={p.id} value={p.name}>{p.name} | {p.email}</option>)}
                      </select>
                      <div className="col-span-2 premium-card rounded-2xl px-3 py-2 text-xs text-text-secondary">
                        责任人邮箱：
                        <span className="ml-1 font-mono text-text-primary">
                          {personnel.find((p) => p.name === editForm.assignee)?.email || previewWO.assignee_email || '待分配'}
                        </span>
                      </div>
                      <select value={editForm.fault_type} onChange={(e) => setEditForm({ ...editForm, fault_type: e.target.value })} className="col-span-2 form-input px-3 py-2 text-sm">
                        <option value="">未设置故障类型</option>
                        {FAULT_TYPES.map((ft) => <option key={ft} value={ft}>{ft}</option>)}
                      </select>
                      <textarea value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} placeholder="工单描述" rows={3}
                        className="col-span-2 form-input px-3 py-2 text-sm focus:border-accent-blue focus:outline-none" />
                    </div>
                  </div>
                )}

                <div className="premium-card rounded-2xl p-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <p className="text-xs text-text-muted">优先级</p>
                      <p className={`mt-1 font-medium ${PRIORITY_COLOR[priorityOf(previewWO)]}`}>{PRIORITY_LABEL[priorityOf(previewWO)]}</p>
                    </div>
                    <div>
                      <p className="text-xs text-text-muted">截止日期</p>
                      <p className={`mt-1 font-medium ${dueTone(previewWO)}`}>{dateOnly(previewWO.due_date)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-text-muted">故障类型</p>
                      <p className="mt-1 text-text-primary">{previewWO.fault_type || aiAnalysis?.fault_type || '未设置'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-text-muted">责任人</p>
                      <p className="mt-1 text-text-primary">{previewWO.assignee || '待分配'}</p>
                    </div>
                  </div>
                </div>

                <div className="premium-card rounded-2xl p-4">
                  <p className="mb-3 text-xs font-medium text-text-secondary">流程进度</p>
                  <WorkOrderStepper status={previewWO.status} />
                </div>

                <div className="premium-card rounded-2xl p-4">
                  <p className="mb-2 text-xs font-medium text-text-secondary">AI 分析报告</p>
                  {analyzing ? (
                    <p className="animate-pulse text-text-muted">正在获取风机数据并生成分析...</p>
                  ) : aiAnalysis ? (
                    <div className="space-y-3">
                      <p className="leading-6 text-text-secondary">{aiAnalysis.diagnosis}</p>
                      {aiAnalysis.anomalies.map((a, i) => (
                        <div key={i} className={`premium-card rounded-2xl px-3 py-2 ${a.level === 'high' ? 'text-accent-red' : 'text-accent-yellow'}`}>
                          <span className="font-medium">{a.indicator}</span>
                          <span className="ml-3 text-text-secondary">当前 {a.value} / 正常 {a.normal}</span>
                          <span className="ml-3">{a.deviation}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-text-muted">暂无分析结果。</p>
                  )}
                </div>

                <div className="premium-card rounded-2xl p-4">
                  <p className="mb-2 text-xs font-medium text-text-secondary">通知信息</p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <p className="text-text-secondary">收件邮箱：<span className="text-text-primary">{previewWO.assignee_email || '按责任人账号邮箱发送'}</span></p>
                    <p className="text-text-secondary">通知状态：<span className="text-text-primary">{previewWO.notification_sent_at ? `已通知 ${dateOnly(previewWO.notification_sent_at)}` : '未发送'}</span></p>
                    <p className="text-text-secondary">预估成本：<span className="text-text-primary">¥{previewWO.cost_estimate.toLocaleString()}</span></p>
                    <p className="text-text-secondary">风机编号：<span className="text-text-primary">#{previewWO.turbine_id}</span></p>
                  </div>
                </div>
              </div>

              <div className="sticky bottom-0 flex justify-end gap-2 border-t border-border-default bg-bg-secondary px-6 py-4">
                {editingWO ? (
                  <>
                    <button onClick={() => setEditingWO(false)} className="ops-btn px-4 py-2 text-sm">取消编辑</button>
                    <button onClick={saveEdit} className="ops-btn ops-btn-primary px-4 py-2 text-sm">保存修改</button>
                  </>
                ) : (
                  <>
                    <button onClick={() => startEdit(previewWO)} className="ops-btn px-4 py-2 text-sm">编辑工单</button>
                    <button disabled={sendingEmail} onClick={() => sendEmail(previewWO)} className="rounded border border-accent-green/40 bg-accent-green/20 px-4 py-2 text-sm font-semibold text-accent-green hover:bg-accent-green/30 disabled:opacity-50">
                      {sendingEmail ? '发送中...' : '发送邮件'}
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {emailResult && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={() => setEmailResult(null)}>
            <div className="w-[380px] premium-card rounded-2xl p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
              <h3 className={`mb-2 text-sm font-medium ${emailResult.type === 'success' ? 'text-accent-green' : 'text-accent-red'}`}>
                {emailResult.type === 'success' ? '发送成功' : '发送失败'}
              </h3>
              <p className="break-words text-xs leading-6 text-text-secondary">{emailResult.message}</p>
              <div className="mt-4 flex justify-end">
                <button onClick={() => setEmailResult(null)} className="rounded bg-accent-blue px-4 py-2 text-sm text-white">知道了</button>
              </div>
            </div>
          </div>
        )}

        {deleteTarget && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 p-4" onClick={() => !deletingOrder && setDeleteTarget(null)}>
            <div
              className="w-full max-w-[420px] rounded-lg border border-accent-red/25 bg-bg-card shadow-2xl shadow-black/40"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="border-b border-border-default bg-bg-secondary px-5 py-4">
                <p className="text-xs font-medium text-accent-red">删除确认</p>
                <h3 className="mt-1 truncate text-base font-semibold text-text-primary">{deleteTarget.title}</h3>
              </div>
              <div className="space-y-3 px-5 py-4">
                <div className="rounded border border-accent-red/20 bg-accent-red/10 px-3 py-2">
                  <p className="text-sm leading-6 text-text-primary">删除后，这条工单将从默认列表、人员负载、诊断关联和知识图谱中隐藏。</p>
                </div>
                <p className="text-xs leading-5 text-text-muted">
                  工单编号 WO-{String(deleteTarget.id).padStart(4, '0')} 的维护记录和通知日志会继续保留，便于后续审计。
                </p>
              </div>
              <div className="flex justify-end gap-2 border-t border-border-default bg-bg-secondary px-5 py-4">
                <button
                  disabled={deletingOrder}
                  onClick={() => setDeleteTarget(null)}
                  className="rounded border border-border-default px-4 py-2 text-sm text-text-secondary hover:border-border-active hover:text-text-primary disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  disabled={deletingOrder}
                  onClick={confirmDeleteOrder}
                  className="rounded bg-accent-red px-4 py-2 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50"
                >
                  {deletingOrder ? '删除中...' : '确认删除'}
                </button>
              </div>
            </div>
          </div>
        )}

        <CopilotFAB />
      </div>
    </div>
  );
}
