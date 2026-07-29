import { useCallback, useEffect, useState } from 'react';
import StateBlock from '../Common/StateBlock';
import { toast } from '../Common/Toast';
import WindGantt from './WindGantt';
import {
  commitPlan,
  fetchGantt,
  fetchPlanDetail,
  fetchPlans,
  fetchProductionSummary,
  optimizePlan,
  PLAN_STATUS_LABEL,
  prodError,
  type GanttResponse,
  type ProductionPlanDetail,
  type ProductionPlanSummary,
  type ProductionSummary,
} from '../../services/productionService';

type ViewMode = 'window' | 'plans';

function fmtKwh(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '—';
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} kWh`;
}

function fmtDateTime(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function WorkOrderSchedulePanel() {
  const [summary, setSummary] = useState<ProductionSummary | null>(null);
  const [plans, setPlans] = useState<ProductionPlanSummary[]>([]);
  const [gantt, setGantt] = useState<GanttResponse | null>(null);
  const [detail, setDetail] = useState<ProductionPlanDetail | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const [periodDays, setPeriodDays] = useState(7);
  const [view, setView] = useState<ViewMode>('window');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [nextSummary, nextPlans, nextGantt] = await Promise.all([
        fetchProductionSummary(),
        fetchPlans({ limit: 30 }),
        fetchGantt(),
      ]);
      setSummary(nextSummary);
      setPlans(nextPlans);
      setGantt(nextGantt);
      const active = nextGantt.plan_no
        || nextSummary.active_plan_no
        || nextPlans[0]?.plan_no
        || null;
      setSelectedPlan(active);
      setDetail(active ? await fetchPlanDetail(active) : null);
    } catch (err) {
      setError(prodError(err, '维护方案加载失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectPlan = async (planNo: string) => {
    setSelectedPlan(planNo);
    setError('');
    try {
      const [nextDetail, nextGantt] = await Promise.all([
        fetchPlanDetail(planNo),
        fetchGantt(planNo),
      ]);
      setDetail(nextDetail);
      setGantt(nextGantt);
    } catch (err) {
      setError(prodError(err, '方案详情加载失败'));
    }
  };

  const generatePlan = async () => {
    setBusy(true);
    setError('');
    try {
      const nextDetail = await optimizePlan({
        period_days: periodDays,
        mode: 'optimized',
        with_baseline: true,
      });
      setDetail(nextDetail);
      setSelectedPlan(nextDetail.plan_no);
      const [nextSummary, nextPlans, nextGantt] = await Promise.all([
        fetchProductionSummary(),
        fetchPlans({ limit: 30 }),
        fetchGantt(nextDetail.plan_no),
      ]);
      setSummary(nextSummary);
      setPlans(nextPlans);
      setGantt(nextGantt);
      toast.success('维护方案已生成', `${nextDetail.plan_no} · 改善 ${nextDetail.improvement_pct.toFixed(1)}%`);
    } catch (err) {
      const message = prodError(err, '维护方案生成失败');
      setError(message);
      toast.error('生成失败', message);
    } finally {
      setBusy(false);
    }
  };

  const submitPlan = async (planNo: string) => {
    setBusy(true);
    setError('');
    try {
      const result = await commitPlan(planNo);
      toast.success('方案已提交', result.message);
      await load();
    } catch (err) {
      const message = prodError(err, '方案提交失败');
      setError(message);
      toast.error('提交失败', message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ops-panel overflow-hidden" aria-label="维护窗口与方案">
      <div className="flex flex-col gap-3 border-b border-border-default p-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h3 className="text-base font-semibold text-text-primary">维护窗口与方案</h3>
          <p className="mt-1 text-sm text-text-secondary">
            {summary
              ? `${summary.pending_work_orders} 张待安排 · ${summary.low_wind_hours} 个低风小时 · ${summary.active_plan_no || '暂无生效方案'}`
              : '正在加载'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded border border-border-default bg-bg-deep p-0.5">
            <button
              onClick={() => setView('window')}
              className={`rounded px-3 py-1.5 text-xs ${view === 'window' ? 'bg-accent-blue text-white' : 'text-text-secondary'}`}
            >
              窗口与工单
            </button>
            <button
              onClick={() => setView('plans')}
              className={`rounded px-3 py-1.5 text-xs ${view === 'plans' ? 'bg-accent-blue text-white' : 'text-text-secondary'}`}
            >
              方案记录
            </button>
          </div>
          <select
            value={periodDays}
            onChange={(event) => setPeriodDays(Number(event.target.value))}
            className="h-9 px-3 text-sm text-text-primary"
            aria-label="规划周期"
          >
            <option value={3}>3 天</option>
            <option value={7}>7 天</option>
            <option value={14}>14 天</option>
          </select>
          <button onClick={() => void load()} disabled={loading || busy} className="ops-btn h-9 px-3 text-sm disabled:opacity-50">
            刷新
          </button>
          <button onClick={() => void generatePlan()} disabled={loading || busy} className="btn btn-primary h-9 px-4 text-sm disabled:opacity-50">
            {busy ? '处理中...' : '生成推荐方案'}
          </button>
        </div>
      </div>

      {error && (
        <div className="border-b border-border-default p-3">
          <StateBlock kind="error" title="维护方案不可用" desc={error} onRetry={() => void load()} />
        </div>
      )}

      {loading ? (
        <div className="p-8 text-center text-sm text-text-muted">加载维护窗口...</div>
      ) : view === 'window' ? (
        <div className="space-y-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">待安排</p><p className="mt-1 font-mono text-xl font-bold">{summary?.pending_work_orders ?? 0}</p></div>
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">低风窗口</p><p className="mt-1 font-mono text-xl font-bold text-accent-cyan">{summary?.low_wind_hours ?? 0} h</p></div>
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">预计损失</p><p className="mt-1 font-mono text-xl font-bold text-accent-orange">{fmtKwh(summary?.week_lost_kwh)}</p></div>
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">相比基线节省</p><p className="mt-1 font-mono text-xl font-bold text-accent-green">{fmtKwh(summary?.saved_kwh)}</p></div>
          </div>
          <WindGantt data={gantt} />
          {detail && (
            <div className="overflow-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 text-left">工单</th>
                    <th className="py-2 text-left">机组</th>
                    <th className="py-2 text-left">安排时段</th>
                    <th className="py-2 text-right">时长</th>
                    <th className="py-2 text-right">预计损失</th>
                    <th className="py-2 text-right">节省</th>
                    <th className="py-2 text-left">审核项</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.schedule.map((slot) => (
                    <tr key={slot.work_order_id} className="border-b border-border-default hover:bg-bg-hover">
                      <td className="py-2.5 text-accent-blue">#{slot.work_order_id} {slot.title}</td>
                      <td className="py-2.5">{slot.turbine_name}</td>
                      <td className="py-2.5 font-mono">{slot.scheduled ? `${fmtDateTime(slot.slot_start)} - ${fmtDateTime(slot.slot_end)}` : '待安排'}</td>
                      <td className="py-2.5 text-right font-mono">{slot.duration_hours.toFixed(1)} h</td>
                      <td className="py-2.5 text-right font-mono">{fmtKwh(slot.est_lost_kwh)}</td>
                      <td className="py-2.5 text-right font-mono text-accent-green">{fmtKwh(slot.saving_kwh)}</td>
                      <td className="max-w-[260px] truncate py-2.5 text-text-muted" title={slot.parts_note || slot.reason}>{slot.parts_note || '人员、工具与安全条件待审核'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {detail.schedule.length === 0 && <p className="py-8 text-center text-sm text-text-muted">当前方案没有工单安排</p>}
            </div>
          )}
        </div>
      ) : (
        <div className="overflow-auto p-4">
          <table className="w-full min-w-[760px] text-xs">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 text-left">方案号</th>
                <th className="py-2 text-left">状态</th>
                <th className="py-2 text-left">周期</th>
                <th className="py-2 text-right">已排/未排</th>
                <th className="py-2 text-right">损失电量</th>
                <th className="py-2 text-right">改善</th>
                <th className="py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((plan) => (
                <tr
                  key={plan.plan_no}
                  onClick={() => void selectPlan(plan.plan_no)}
                  className={`cursor-pointer border-b border-border-default hover:bg-bg-hover ${selectedPlan === plan.plan_no ? 'bg-accent-blue/10' : ''}`}
                >
                  <td className="py-2.5 font-mono text-accent-blue">{plan.plan_no}</td>
                  <td className="py-2.5">{PLAN_STATUS_LABEL[plan.status] || plan.status}</td>
                  <td className="py-2.5 text-text-secondary">{fmtDateTime(plan.period_start)} - {fmtDateTime(plan.period_end)}</td>
                  <td className="py-2.5 text-right font-mono">{plan.scheduled_count}/{plan.unscheduled_count}</td>
                  <td className="py-2.5 text-right font-mono">{fmtKwh(plan.total_lost_kwh)}</td>
                  <td className="py-2.5 text-right font-mono text-accent-green">{plan.improvement_pct.toFixed(1)}%</td>
                  <td className="py-2.5 text-right">
                    {plan.status === 'draft' && (
                      <button
                        onClick={(event) => { event.stopPropagation(); void submitPlan(plan.plan_no); }}
                        disabled={busy}
                        className="ops-btn px-3 py-1 text-xs disabled:opacity-50"
                      >
                        提交审核
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {plans.length === 0 && <p className="py-8 text-center text-sm text-text-muted">暂无方案记录</p>}
        </div>
      )}
    </section>
  );
}
