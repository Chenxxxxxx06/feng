import api from './api';

/**
 * 维护窗口规划 API 客户端。
 * 后端路由：backend/app/api/production.py，挂载前缀 /api/production。
 * 类型与 backend/app/schemas/production.py 对齐。
 */

const BASE = '/production';

export function prodError(e: unknown, fallback = '请求失败'): string {
  const err = e as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail != null) {
    try { return JSON.stringify(detail); } catch { /* ignore */ }
  }
  return err?.message || fallback;
}

// ── 风功率预测 ──

export interface PowerForecastPoint {
  forecast_time: string;
  horizon_hours: number;
  wind_speed_ms?: number | null;
  expected_power_kw?: number | null;
  confidence_low?: number | null;
  confidence_high?: number | null;
  source: string;
}

export interface LowWindWindow {
  start: string;
  end: string;
  hours: number;
  avg_power_kw: number;
  min_power_kw: number;
  avg_wind_ms: number;
  capacity_factor: number;
  label: string;
}

export interface PowerForecastResponse {
  turbine_id?: number | null;
  turbine_name?: string | null;
  hours: number;
  farm_rated_kw: number;
  source: string;
  method_note: string;
  generated_at: string;
  points: PowerForecastPoint[];
  low_wind_windows: LowWindWindow[];
  total_expected_kwh: number;
  avg_capacity_factor: number;
  degraded: boolean;
  degraded_reason?: string | null;
}

// ── 排产方案 ──

export interface ScheduleSlot {
  work_order_id: number;
  turbine_id: number;
  turbine_name: string;
  title: string;
  priority: string;
  slot_start?: string | null;
  slot_end?: string | null;
  duration_hours: number;
  crew_size: number;
  est_lost_kwh: number;
  worst_lost_kwh: number;
  baseline_lost_kwh: number;
  saving_kwh: number;
  saving_cny: number;
  avg_wind_ms?: number | null;
  safety_score: number;
  rul_days?: number | null;
  reason: string;
  moved_by?: string | null;
  parts_note?: string | null;
  constraints: string[];
  scheduled: boolean;
  unscheduled_reason?: string | null;
}

export interface ProductionPlanSummary {
  id: number;
  plan_no: string;
  period_start: string;
  period_end: string;
  status: string;
  strategy: string;
  total_lost_kwh: number;
  baseline_lost_kwh: number;
  improvement_pct: number;
  total_revenue_loss: number;
  scheduled_count: number;
  unscheduled_count: number;
  baseline_plan_id?: number | null;
  baseline_plan_no?: string | null;
  created_by_name?: string | null;
  note?: string | null;
  audit_hash?: string | null;
  created_at?: string | null;
  committed_at?: string | null;
}

export interface PlanComparison {
  baseline_lost_kwh?: number;
  optimized_lost_kwh?: number;
  saved_kwh?: number;
  saved_cny?: number;
  improvement_pct?: number;
  baseline_label?: string;
  optimized_label?: string;
  algorithm?: string;
  swap_improvements?: number;
  constraint_hits?: Record<string, number>;
  constraint_labels?: Record<string, string>;
  capacity?: Record<string, any>;
  low_wind_windows?: Record<string, any>[];
  forecast_source?: string;
}

export interface ProductionPlanDetail extends ProductionPlanSummary {
  objective: Record<string, any>;
  schedule: ScheduleSlot[];
  comparison: PlanComparison;
  moved_slots: ScheduleSlot[];
}

export interface CommitPlanResponse {
  plan_no: string;
  status: string;
  committed_at?: string | null;
  superseded_plan_nos: string[];
  audit_hash?: string | null;
  message: string;
}

// ── 甘特图 ──

export interface GanttBar {
  work_order_id: number;
  turbine_id: number;
  turbine_name: string;
  label: string;
  priority: string;
  start?: string | null;
  end?: string | null;
  est_lost_kwh: number;
  saving_kwh: number;
  moved_by?: string | null;
  reason: string;
  row: number;
}

export interface GanttWindCell {
  time: string;
  wind_speed_ms?: number | null;
  expected_power_kw?: number | null;
  capacity_factor: number;
  is_low_wind: boolean;
}

export interface GanttResponse {
  plan_no?: string | null;
  status?: string | null;
  period_start: string;
  period_end: string;
  bars: GanttBar[];
  wind_band: GanttWindCell[];
  low_wind_windows: LowWindWindow[];
  farm_rated_kw: number;
  forecast_source: string;
  legend: Record<string, any>;
}

// ── 域概览 ──

export interface ProductionSummary {
  active_plan_no?: string | null;
  active_plan_status?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  week_lost_kwh: number;
  week_revenue_loss_cny: number;
  baseline_lost_kwh: number;
  improvement_pct: number;
  saved_kwh: number;
  saved_cny: number;
  pending_work_orders: number;
  scheduled_work_orders: number;
  unscheduled_work_orders: number;
  low_wind_hours: number;
  forecast_source: string;
  forecast_points: number;
  plan_versions: number;
  electricity_price_cny_per_kwh: number;
  highlights: string[];
}

// ── 接口函数 ──

export async function fetchProductionSummary(): Promise<ProductionSummary> {
  const { data } = await api.get(`${BASE}/summary`);
  return data;
}

export async function fetchPowerForecast(params?: {
  hours?: number;
  turbine_id?: number;
}): Promise<PowerForecastResponse> {
  const { data } = await api.get(`${BASE}/power-forecast`, { params });
  return data;
}

export async function refreshPowerForecast(body: {
  hours?: number;
  turbine_id?: number;
  method?: string;
}): Promise<PowerForecastResponse> {
  const { data } = await api.post(`${BASE}/power-forecast/refresh`, body);
  return data;
}

export async function fetchPlans(params?: {
  limit?: number;
  status?: string;
}): Promise<ProductionPlanSummary[]> {
  const { data } = await api.get(`${BASE}/plans`, { params });
  return Array.isArray(data) ? data : [];
}

export async function fetchPlanDetail(planNo: string): Promise<ProductionPlanDetail> {
  const { data } = await api.get(`${BASE}/plans/${encodeURIComponent(planNo)}`);
  return data;
}

export async function optimizePlan(body?: {
  period_days?: number;
  work_order_ids?: number[];
  mode?: string;
  note?: string;
  with_baseline?: boolean;
}): Promise<ProductionPlanDetail> {
  const { data } = await api.post(`${BASE}/plans/optimize`, body ?? {});
  return data;
}

export async function commitPlan(planNo: string): Promise<CommitPlanResponse> {
  const { data } = await api.post(`${BASE}/plans/${encodeURIComponent(planNo)}/commit`);
  return data;
}

export async function replanPlan(
  planNo: string,
  body: {
    reason: string;
    affected_work_orders?: number[];
    delay_hours?: number;
    note?: string;
  },
): Promise<ProductionPlanDetail> {
  const { data } = await api.post(`${BASE}/plans/${encodeURIComponent(planNo)}/replan`, body);
  return data;
}

export async function fetchGantt(planNo?: string): Promise<GanttResponse> {
  const { data } = await api.get(`${BASE}/gantt`, {
    params: planNo ? { plan_no: planNo } : undefined,
  });
  return data;
}

// ── 展示常量 ──

export const PLAN_STATUS_LABEL: Record<string, string> = {
  draft: '草案',
  committed: '已提交',
  superseded: '已被替代',
};

export const PRIORITY_LABEL: Record<string, string> = {
  urgent: '紧急',
  high: '高',
  medium: '中',
  low: '低',
};
