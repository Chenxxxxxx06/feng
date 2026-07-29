import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../../services/api';
import type { WorkOrder, Turbine } from '../../types';
import StateBlock from '../../components/Common/StateBlock';
import { Skeleton } from '../../components/Common/Skeleton';
import { toast, describeError } from '../../components/Common/Toast';
import WorkOrderSchedulePanel from '../../components/Maintenance/WorkOrderSchedulePanel';
import { useHasMinimumRole, READ_ONLY_PERMISSION_TITLE } from '../../services/permissions';

const STATUS_FLOW = ['pending', 'assigned', 'in_progress', 'review', 'completed', 'closed'];
const STATUS_FILTERS = [...STATUS_FLOW, 'cancelled'];
// 与后端 workorders.py 的 WORKORDER_TRANSITIONS 状态机保持一致
const STATUS_TRANSITIONS: Record<string, string[]> = {
  pending: ['assigned', 'in_progress', 'cancelled'],
  assigned: ['in_progress', 'cancelled'],
  in_progress: ['review', 'completed', 'cancelled'],
  review: ['in_progress', 'completed', 'cancelled'],
  completed: ['closed'],
  closed: [],
  cancelled: [],
};
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
  const canManage = useHasMinimumRole('operator');
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [personnel, setPersonnel] = useState<Personnel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [previewWO, setPreviewWO] = useState<WorkOrder | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<WorkOrder | null>(null);
  const [deletingOrder, setDeletingOrder] = useState(false);
  const [verifyTarget, setVerifyTarget] = useState<WorkOrder | null>(null);
  const [verifyNote, setVerifyNote] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState('');
  const [actionError, setActionError] = useState('');
  const [openActionId, setOpenActionId] = useState<number | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [aiError, setAiError] = useState<string>('');
  const [analyzing, setAnalyzing] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [emailResult, setEmailResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [createResult, setCreateResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [creating, setCreating] = useState(false);
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
  const contextIncidentId = Number(searchParams.get('incident_id') || 0);
  const contextTurbineId = Number(searchParams.get('turbine_id') || 0);
  const contextIncidentRef = searchParams.get('incident_ref')?.trim() || '';
  const contextTurbineName = searchParams.get('turbine_name')?.trim() || '';
  const contextIncidentTitle = searchParams.get('incident_title')?.trim() || '';

  useEffect(() => {
    if (!canManage || contextIncidentId <= 0 || contextTurbineId <= 0) return;

    setForm((current) => ({
      ...current,
      turbine_id: String(contextTurbineId),
      title: current.title || `${contextTurbineName || `#${contextTurbineId}`} 事件维修处置`,
      description:
        current.description ||
        `关联事件：${contextIncidentRef || `#${contextIncidentId}`}${
          contextIncidentTitle ? `\n事件标题：${contextIncidentTitle}` : ''
        }`,
      priority: current.priority === 'medium' ? 'high' : current.priority,
    }));
    setShowCreate(true);
  }, [
    contextIncidentId,
    contextIncidentRef,
    contextIncidentTitle,
    contextTurbineId,
    contextTurbineName,
    canManage,
  ]);

  const clearIncidentContext = () => {
    setSearchParams({}, { replace: true });
  };

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
    api.get<{ turbines: Turbine[] }>('/turbines/').then(({ data }) => setTurbines(data.turbines || [])).catch(() => {});
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
    if (!canManage) return;
    setCreateResult(null);
    const turbineId = Number(form.turbine_id);
    if (!turbineId || turbineId <= 0) {
      setCreateResult({ type: 'error', message: '请输入有效的风机 ID（正整数）' });
      return;
    }
    if (!form.title.trim()) {
      setCreateResult({ type: 'error', message: '请输入工单标题' });
      return;
    }
    setCreating(true);
    try {
      await api.post('/workorders/', {
        turbine_id: turbineId,
        incident_id: contextIncidentId > 0 ? contextIncidentId : null,
        title: form.title.trim(),
        description: form.description || null,
        assignee: form.assignee || null,
        assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
        assignee_email: form.assignee_email || null,
        priority: form.priority,
        fault_type: form.fault_type,
        due_date: form.due_date || null,
        cost_estimate: Number(form.cost_estimate) || 0,
      });
      setShowCreate(false);
      setForm(emptyForm);
      clearIncidentContext();
      setCreateResult(null);
      toast.success('工单已创建', form.title.trim());
      fetchOrders();
    } catch (err: any) {
      const message = describeError(err, '工单创建失败，请检查必填字段');
      setCreateResult({ type: 'error', message });
      toast.error('工单创建失败', message);
    } finally {
      setCreating(false);
    }
  };

  const advanceStatus = async (id: number, current: string) => {
    if (!canManage) return;
    const idx = STATUS_FLOW.indexOf(current);
    if (idx < STATUS_FLOW.length - 1) {
      try {
        await api.put(`/workorders/${id}`, { status: STATUS_FLOW[idx + 1] });
        setOpenActionId(null);
        toast.success('工单状态已推进', `WO-${String(id).padStart(4, '0')} → ${STATUS_LABEL[STATUS_FLOW[idx + 1]]}`);
        fetchOrders();
      } catch (err: any) {
        const message = describeError(err, '工单状态推进失败，请稍后重试');
        setActionError(message);
        toast.error('工单状态推进失败', message);
      }
    }
  };

  const cancelOrder = async (id: number) => {
    if (!canManage) return;
    try {
      const { data } = await api.put(`/workorders/${id}`, { status: 'cancelled' });
      setOrders((prev) => prev.map((o) => (o.id === id ? data : o)));
      setOpenActionId(null);
      toast.success('工单已取消', `WO-${String(id).padStart(4, '0')}`);
      fetchOrders();
    } catch (err: any) {
      const message = describeError(err, '取消工单失败，请稍后重试');
      setActionError(message);
      toast.error('取消工单失败', message);
    }
  };

  const requestDeleteOrder = (wo: WorkOrder) => {
    if (!canManage) return;
    setDeleteTarget(wo);
    setOpenActionId(null);
  };

  const confirmDeleteOrder = async () => {
    if (!deleteTarget) return;
    setDeletingOrder(true);
    try {
      await api.delete(`/workorders/${deleteTarget.id}`);
      setOrders((prev) => prev.filter((o) => o.id !== deleteTarget.id));
      if (previewWO?.id === deleteTarget.id) {
        setPreviewWO(null);
        setAiAnalysis(null);
        setAiError('');
        setEditingWO(false);
      }
      toast.success('工单已删除', deleteTarget.title);
      setDeleteTarget(null);
    } catch (err: any) {
      const message = describeError(err, '工单删除失败，请稍后重试');
      setActionError(message);
      toast.error('工单删除失败', message);
    } finally {
      setDeletingOrder(false);
    }
  };

  const requestVerifyClose = (wo: WorkOrder) => {
    if (!canManage) return;
    setVerifyTarget(wo);
    setVerifyNote('');
    setVerifyError('');
    setOpenActionId(null);
  };

  const confirmVerifyClose = async () => {
    if (!verifyTarget) return;
    setVerifying(true);
    setVerifyError('');
    try {
      // 后端 P0-12：completed→closed 前必须存在 action_type='verified' 的维修记录
      await api.post(`/workorders/${verifyTarget.id}/records`, {
        action_type: 'verified',
        content: verifyNote.trim() || '验收通过',
      });
      const { data } = await api.put(`/workorders/${verifyTarget.id}`, { status: 'closed' });
      setOrders((prev) => prev.map((o) => (o.id === data.id ? data : o)));
      if (previewWO?.id === data.id) setPreviewWO(data);
      toast.success('工单已验收关闭', verifyTarget.title);
      setVerifyTarget(null);
      setVerifyNote('');
      fetchOrders();
    } catch (err: any) {
      const message = describeError(err, '验收关闭失败，请稍后重试');
      setVerifyError(message);
      toast.error('验收关闭失败', message);
    } finally {
      setVerifying(false);
    }
  };

  const startEdit = (wo: WorkOrder) => {
    if (!canManage) return;
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

  // 后端 P0-11/P0-12 的状态校验返回英文 detail，这里转为可读中文
  const translateStatusError = (httpStatus?: number, detail?: string): string => {
    if (httpStatus === 409 && detail?.includes('without verification')) {
      return '工单未通过验收，不能直接关闭。请使用「验收并关闭」按钮填写验收结论后再关闭。';
    }
    if (httpStatus === 409 && detail?.startsWith('Cannot transition')) {
      return '当前状态不允许流转到所选状态，请刷新页面确认最新状态后重试。';
    }
    if (httpStatus === 400 && detail === 'Invalid work order status') {
      return '工单状态取值无效，请重新选择。';
    }
    return detail || '工单保存失败，请检查填写内容';
  };

  const saveEdit = async () => {
    if (!canManage || !previewWO) return;
    const assignee = personnel.find((p) => p.name === editForm.assignee);
    try {
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
    } catch (err: any) {
      setActionError(translateStatusError(err.response?.status, err.response?.data?.detail));
    }
  };

  const translateEmailError = (detail: string): string => {
    const map: Record<string, string> = {
      'Email notification is disabled in settings': '邮件通知未开启，请前往「设置 → 告警规则」开启邮件通知',
      'No recipient email found for work order assignee': '该工单未指定责任人邮箱，请先为工单分配责任人',
      'WorkOrder not found': '工单不存在，请刷新页面后重试',
    };
    if (map[detail]) return map[detail];
    if (detail.startsWith('Missing SMTP settings')) return 'SMTP 邮件配置不完整，请联系管理员检查 .env 文件';
    if (detail) return `邮件发送失败：${detail}`;
    return '发送失败，请确认后端服务已启动且通知配置正确';
  };

  const sendEmail = async (wo: WorkOrder) => {
    if (!canManage) return;
    setSendingEmail(true);
    setEmailResult(null);
    try {
      const recipients = wo.assignee_email ? [wo.assignee_email] : [];
      const { data } = await api.post(`/workorders/${wo.id}/send-email`, {
        recipient_emails: recipients,
        subject: `[风调预顺] WO-${String(wo.id).padStart(4, '0')} ${wo.title}`,
        use_preview_template: true,
      }, { timeout: 60000 });
      if ((data.sent || 0) === 0) {
        const failedLog = data.logs?.find((log: any) => log.status === 'failed');
        if (failedLog?.error_message) {
          setEmailResult({ type: 'error', message: `邮件发送失败：${failedLog.error_message}` });
        } else {
          setEmailResult({ type: 'error', message: '未找到有效收件人，请为该工单分配责任人并确保其账号已绑定邮箱' });
        }
      } else {
        setEmailResult({ type: 'success', message: `邮件已发送给责任人，共 ${data.sent} 封。` });
      }
    } catch (err: any) {
      const detail: string | undefined = err.response?.data?.detail;
      setEmailResult({ type: 'error', message: translateEmailError(detail || '') });
    }
    setSendingEmail(false);
  };

  const runAIAnalysis = async (wo: WorkOrder) => {
    setPreviewWO(wo);
    setEditingWO(false);
    setAnalyzing(true);
    setAiError('');
    setAiAnalysis(null);
    try {
      const { data } = await api.post('/ai/analyze-fault', {
        turbine_id: wo.turbine_id,
        fault_type: wo.fault_type || wo.title || '未知故障',
      }, { timeout: 60000 });
      setAiAnalysis(data);
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || '';
      const axiosCode = err?.code || '';
      if (status === 404) {
        setAiError(`风机 #${wo.turbine_id} 不存在或已删除，无法获取SCADA数据进行AI分析。`);
      } else if (status === 503) {
        setAiError('AI诊断服务当前不可用，请检查系统AI配置或稍后重试。');
      } else if (status === 401 || status === 403) {
        setAiError('AI服务鉴权失败，请在系统设置中配置有效的API KEY。');
      } else if (status === 500) {
        setAiError(detail ? `服务器内部错误：${detail}` : '服务器内部错误，请查看后端日志。');
      } else if (status) {
        setAiError(detail || `请求失败 (HTTP ${status})，请检查后端服务。`);
      } else if (axiosCode === 'ECONNABORTED') {
        setAiError('AI分析请求超时（>60秒），AI供应商响应过慢或网络不稳，请稍后重试。');
      } else if (axiosCode === 'ERR_NETWORK' || axiosCode === 'ERR_CONNECTION_REFUSED') {
        setAiError('无法连接后端服务（端口 8000），请确认后端已启动：双击 启动风调预顺.bat，或 cd backend && python launcher.py');
      } else {
        setAiError(`请求失败 (${axiosCode || '未知错误'})：${err?.message || ''}。请检查后端服务是否运行、AI配置是否正确。`);
      }
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
    <div className="h-full overflow-auto ops-page page-enter">
      <div className="ops-content mx-auto max-w-[1480px] space-y-4">
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
            onClick={() => canManage && setShowCreate(true)}
            disabled={!canManage}
            title={canManage ? '创建维修工单' : READ_ONLY_PERMISSION_TITLE}
            className="btn btn-primary btn-lg flex-shrink-0"
          >
            创建工单
          </button>
        </section>

        <section className="grid gap-3 md:grid-cols-4" aria-label="工单概览指标">
          {stats.map((item, i) => (
            <div key={item.label} className={`ops-panel surface-card-hover p-3.5 stagger-${Math.min(4, i + 1)}`} title={`${item.label}：${item.value}（${item.hint}）`}>
              <div className="flex items-center justify-between gap-2">
                <span className="field-label truncate">{item.label}</span>
                <span className="field-label flex-shrink-0">{item.hint}</span>
              </div>
              <p className={`num mt-2 text-[26px] font-bold leading-none ${item.tone}`}>{item.value}</p>
            </div>
          ))}
        </section>

        <WorkOrderSchedulePanel />

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
                    <select
                      value={form.turbine_id}
                      onChange={(e) => setForm({ ...form, turbine_id: e.target.value })}
                      disabled={contextIncidentId > 0}
                      aria-label="选择风机"
                      className="form-input px-3 py-2 text-sm text-text-primary">
                      <option value="">选择风机 *</option>
                      {turbines.map((t) => (
                        <option key={t.id} value={String(t.id)}>{t.name} · {t.region}</option>
                      ))}
                    </select>
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
                  {contextIncidentId > 0 && (
                    <div
                      className="mt-3 rounded border border-accent-blue/40 bg-accent-blue/10 px-3 py-2 text-xs text-accent-blue"
                      data-testid="incident-workorder-context"
                    >
                      已关联事件：
                      <span className="ml-1 font-mono">
                        {contextIncidentRef || `#${contextIncidentId}`}
                      </span>
                      <span className="ml-2 text-text-secondary">
                        · {contextTurbineName || `风机 #${contextTurbineId}`}
                      </span>
                    </div>
                  )}
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

                {createResult && (
                  <div className={`rounded border px-3 py-2 text-xs ${createResult.type === 'success' ? 'border-accent-green/40 bg-accent-green/10 text-accent-green' : 'border-accent-red/40 bg-accent-red/10 text-accent-red'}`}>
                    {createResult.message}
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-2 border-t border-border-default px-6 py-4">
                <button
                  onClick={() => {
                    setShowCreate(false);
                    setCreateResult(null);
                    setForm(emptyForm);
                    clearIncidentContext();
                  }}
                  className="btn btn-secondary"
                >
                  取消
                </button>
                <button disabled={creating} onClick={handleCreate} className="btn btn-primary">
                  {creating && <span className="btn-spinner" aria-hidden="true" />}
                  {creating ? '创建中…' : '创建'}
                </button>
              </div>
            </div>
          </div>
        )}

        {loading ? (
          <div className="space-y-3" role="status" aria-label="工单列表加载中">
            {[1, 2, 3, 4].map((item) => (
              <div key={item} className="premium-card flex gap-4 rounded-2xl p-4" style={{ opacity: Math.max(0.4, 1 - item * 0.12) }}>
                <Skeleton width={4} height={64} radius={999} />
                <div className="flex-1 space-y-2.5">
                  <div className="flex items-center gap-2">
                    <Skeleton className="skeleton-pill" />
                    <Skeleton className="skeleton-text" width="34%" height={12} />
                  </div>
                  <Skeleton className="skeleton-text" width="62%" />
                  <Skeleton className="skeleton-text" width="44%" height={9} />
                </div>
                <Skeleton width={92} height={28} radius={8} />
              </div>
            ))}
          </div>
        ) : loadError ? (
          <div className="premium-card rounded-2xl">
            <StateBlock kind="error" title="工单列表加载失败" desc={loadError} onRetry={() => { void fetchOrders(); }} />
          </div>
        ) : orders.length === 0 ? (
          <div className="premium-card rounded-2xl">
            <StateBlock
              kind="empty"
              title="暂无符合条件的维修工单"
              desc="可以调整上方筛选条件，或直接创建一条新的维修任务。"
              action={
                <button
                  onClick={() => canManage && setShowCreate(true)}
                  disabled={!canManage}
                  title={canManage ? '创建维修工单' : READ_ONLY_PERMISSION_TITLE}
                  className="btn btn-primary btn-sm"
                >
                  创建工单
                </button>
              }
            />
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
                        {o.incident_id && (
                          <span className="rounded border border-accent-blue/30 bg-accent-blue/10 px-2 py-0.5 font-mono text-[10px] text-accent-blue">
                            INC #{o.incident_id}
                          </span>
                        )}
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
                          disabled={!canManage}
                          title={canManage ? nextStatusLabel(o.status) : READ_ONLY_PERMISSION_TITLE}
                          className="ops-btn h-8 px-3 text-xs"
                        >
                          {nextStatusLabel(o.status)}
                        </button>
                      )}
                      {o.status === 'completed' && (
                        <button
                          onClick={() => requestVerifyClose(o)}
                          disabled={!canManage}
                          title={canManage ? '填写验收记录并关闭工单' : READ_ONLY_PERMISSION_TITLE}
                          className="h-8 rounded border border-accent-green/50 px-3 text-xs text-accent-green hover:bg-accent-green/10"
                        >
                          验收并关闭
                        </button>
                      )}
                      {canManage && <div className="relative">
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
                      </div>}
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
          <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={() => { setPreviewWO(null); setAiAnalysis(null); setAiError(''); }}>
            <div className="ops-drawer h-full w-full max-w-[720px] overflow-auto" onClick={e => e.stopPropagation()}>
              <div className="sticky top-0 z-10 border-b border-border-default bg-bg-panel/95 px-6 py-4 backdrop-blur">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="font-mono text-xs text-text-muted">WO-{String(previewWO.id).padStart(4, '0')}</p>
                    <h3 className="mt-1 text-lg font-semibold">{editingWO ? '编辑工单' : previewWO.title}</h3>
                    <p className="mt-1 text-xs text-text-muted">状态：{STATUS_LABEL[previewWO.status] || previewWO.status}</p>
                  </div>
                  <button onClick={() => { setPreviewWO(null); setAiAnalysis(null); setAiError(''); }} className="ops-btn px-3 py-1.5 text-sm">关闭</button>
                </div>
              </div>

              <div className="space-y-5 p-6 text-sm">
                {editingWO && (
                  <div className="premium-card rounded-2xl p-4">
                    <p className="mb-3 text-xs font-medium text-text-secondary">编辑信息</p>
                    <div className="grid grid-cols-2 gap-3">
                      <input value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} placeholder="工单标题"
                        className="col-span-2 form-input px-3 py-2 text-sm focus:border-accent-blue focus:outline-none" />
                      <div>
                        <select value={editForm.status} onChange={(e) => setEditForm({ ...editForm, status: e.target.value })} className="form-input w-full px-3 py-2 text-sm">
                          {[previewWO.status, ...(STATUS_TRANSITIONS[previewWO.status] || [])]
                            // completed→closed 必须先有验收记录，改由「验收并关闭」按钮完成
                            .filter((s) => !(previewWO.status === 'completed' && s === 'closed'))
                            .map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
                        </select>
                        {previewWO.status === 'completed' && (
                          <p className="mt-1 text-[11px] text-text-muted">关闭工单需先验收，请在工单列表使用「验收并关闭」按钮。</p>
                        )}
                      </div>
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
                  ) : aiError ? (
                    <div className="rounded-xl border border-accent-red/30 bg-accent-red/5 px-3 py-2">
                      <p className="text-xs text-accent-red leading-5">{aiError}</p>
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
                  <button
                    onClick={() => startEdit(previewWO)}
                    disabled={!canManage}
                    title={canManage ? '编辑工单' : READ_ONLY_PERMISSION_TITLE}
                    className="ops-btn px-4 py-2 text-sm"
                  >
                    编辑工单
                  </button>
                  <button
                    disabled={sendingEmail || !canManage}
                    title={canManage ? '发送工单通知' : READ_ONLY_PERMISSION_TITLE}
                    onClick={() => sendEmail(previewWO)}
                    className="rounded border border-accent-green/40 bg-accent-green/20 px-4 py-2 text-sm font-semibold text-accent-green hover:bg-accent-green/30 disabled:opacity-50"
                  >
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

        {actionError && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={() => setActionError('')}>
            <div className="w-[380px] premium-card rounded-2xl p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
              <h3 className="mb-2 text-sm font-medium text-accent-red">操作失败</h3>
              <p className="break-words text-xs leading-6 text-text-secondary">{actionError}</p>
              <div className="mt-4 flex justify-end">
                <button onClick={() => setActionError('')} className="rounded bg-accent-blue px-4 py-2 text-sm text-white">知道了</button>
              </div>
            </div>
          </div>
        )}

        {verifyTarget && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 p-4" onClick={() => !verifying && setVerifyTarget(null)}>
            <div
              className="w-full max-w-[420px] rounded-lg border border-accent-green/25 bg-bg-card shadow-2xl shadow-black/40"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="border-b border-border-default bg-bg-secondary px-5 py-4">
                <p className="text-xs font-medium text-accent-green">验收并关闭</p>
                <h3 className="mt-1 truncate text-base font-semibold text-text-primary">{verifyTarget.title}</h3>
              </div>
              <div className="space-y-3 px-5 py-4">
                <p className="text-xs leading-5 text-text-muted">
                  将为工单 WO-{String(verifyTarget.id).padStart(4, '0')} 创建验收记录，并把状态推进到「已关闭」。
                </p>
                <textarea
                  value={verifyNote}
                  onChange={(e) => setVerifyNote(e.target.value)}
                  placeholder="验收说明（可选，默认为“验收通过”）"
                  rows={3}
                  className="w-full form-input px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none"
                />
                {verifyError && (
                  <div className="rounded border border-accent-red/40 bg-accent-red/10 px-3 py-2 text-xs text-accent-red">
                    {verifyError}
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-2 border-t border-border-default bg-bg-secondary px-5 py-4">
                <button
                  disabled={verifying}
                  onClick={() => setVerifyTarget(null)}
                  className="rounded border border-border-default px-4 py-2 text-sm text-text-secondary hover:border-border-active hover:text-text-primary disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  disabled={verifying}
                  onClick={confirmVerifyClose}
                  className="rounded bg-accent-green px-4 py-2 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50"
                >
                  {verifying ? '处理中...' : '确认验收并关闭'}
                </button>
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

      </div>
    </div>
  );
}
