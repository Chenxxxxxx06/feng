import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { getTaskPackage } from '../../../services/incidentService';

interface Props {
  incidentId: number;
}

interface SafetyItem {
  id: string;
  description: string;
  required: boolean;
  completed: boolean;
}

interface ProcedureStep {
  seq: number;
  action: string;
  tool_required?: string | null;
  estimated_minutes?: number | null;
  safety_note?: string | null;
}

const RISK_STYLE: Record<string, string> = {
  low: 'bg-accent-green/15 text-accent-green border-accent-green/30',
  medium: 'bg-accent-yellow/15 text-accent-yellow border-accent-yellow/30',
  high: 'bg-accent-orange/15 text-accent-orange border-accent-orange/35',
  critical: 'bg-accent-red/15 text-accent-red border-accent-red/40',
};

const WORK_ORDER_LINK_LABEL: Record<string, string> = {
  explicit: '用户指定',
  fault_relation: '故障直接关联',
  fault_and_time: '同故障时间关联',
};

/**
 * 任务包面板 — Agent 交付的「可执行成果」
 * GET /api/incidents/{id}/task-package
 * 含：诊断证据 / 选定方案 / 人料工具 / 安全清单 / 工序步骤 / 验收标准 / 回滚与升级条件
 */
export default function TaskPackagePanel({ incidentId }: Props) {
  const [pkg, setPkg] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTaskPackage(incidentId);
      setPkg(result);
      const initial: Record<string, boolean> = {};
      for (const item of result?.safety_checklist || []) initial[item.id] = Boolean(item.completed);
      setChecked(initial);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : e?.message || '任务包生成失败');
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-24 w-full" />
        <div className="skeleton h-40 w-full" />
        <div className="skeleton h-40 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-4 text-sm text-accent-red">
        ⚠ {error}
        <button onClick={() => { void load(); }} className="ml-3 underline">重试</button>
      </div>
    );
  }

  if (!pkg) {
    return <div className="p-8 text-center text-sm text-text-muted">暂无任务包数据</div>;
  }

  const safety: SafetyItem[] = pkg.safety_checklist || [];
  const steps: ProcedureStep[] = pkg.procedure_steps || [];
  const requiredDone = safety.filter((item) => item.required && checked[item.id]).length;
  const requiredTotal = safety.filter((item) => item.required).length;
  const totalMinutes = steps.reduce((sum, step) => sum + (step.estimated_minutes || 0), 0);

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="rounded-lg border border-accent-cyan/30 bg-accent-cyan/8 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-text-primary">📦 {pkg.title || '维修任务包'}</span>
          <span className={`rounded border px-2 py-0.5 text-[10px] ${RISK_STYLE[pkg.risk_level] || RISK_STYLE.medium}`}>
            风险 {pkg.risk_level || '—'}
          </span>
          {pkg.work_order_id && (
            <span
              className="rounded bg-bg-card px-2 py-0.5 text-[10px] text-text-muted"
              title={`关联置信度 ${Math.round((pkg.work_order_link_confidence || 0) * 100)}%`}
            >
              工单 #{pkg.work_order_id} · {WORK_ORDER_LINK_LABEL[pkg.work_order_link_source] || '已关联'}
            </span>
          )}
          {!pkg.work_order_id && (
            <span className="text-[10px] text-accent-yellow">尚未绑定可验证工单</span>
          )}
          <span className="ml-auto text-[10px] text-text-muted">
            {pkg.includes_llm_content ? '⚠ 含 LLM 生成内容，需人工复核' : '全部由确定性规则生成'}
          </span>
        </div>
        {pkg.description && <p className="mt-1.5 text-xs leading-5 text-text-secondary">{pkg.description}</p>}
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="工序步骤" value={`${steps.length} 步`} sub={totalMinutes ? `约 ${totalMinutes} 分钟` : undefined} />
          <Tile label="安全项" value={`${requiredDone}/${requiredTotal}`} sub="必检项完成度" />
          <Tile label="备件" value={`${(pkg.required_parts || []).length} 项`} />
          <Tile label="工具" value={`${(pkg.required_tools || []).length} 项`} />
        </div>
      </div>

      {/* 选定方案 + 依据 */}
      {(pkg.selected_plan || pkg.selection_rationale) && (
        <Section title="🎯 选定方案与选型依据">
          {pkg.selected_plan && (
            <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
              {Object.entries(pkg.selected_plan).slice(0, 8).map(([key, value]) => (
                <div key={key} className="rounded border border-border-default bg-bg-secondary/50 p-2">
                  <div className="truncate text-[10px] text-text-muted">{key}</div>
                  <div className="mt-0.5 truncate font-mono text-text-primary">
                    {typeof value === 'object' ? JSON.stringify(value).slice(0, 24) : String(value ?? '—')}
                  </div>
                </div>
              ))}
            </div>
          )}
          {pkg.selection_rationale && (
            <p className="mt-2 text-[11px] leading-5 text-text-secondary">{pkg.selection_rationale}</p>
          )}
        </Section>
      )}

      {/* 安全清单 */}
      <Section title="🦺 作业前安全清单">
        {safety.length === 0 ? (
          <p className="text-xs text-text-muted">未生成安全项</p>
        ) : (
          <div className="space-y-1">
            {safety.map((item) => (
              <label
                key={item.id}
                className={`flex cursor-pointer items-start gap-2 rounded border p-2 transition-colors ${
                  checked[item.id]
                    ? 'border-accent-green/35 bg-accent-green/8'
                    : item.required
                      ? 'border-accent-yellow/30 bg-accent-yellow/6'
                      : 'border-border-default bg-bg-secondary/40'
                }`}
              >
                <input
                  type="checkbox"
                  checked={Boolean(checked[item.id])}
                  onChange={(event) => setChecked((prev) => ({ ...prev, [item.id]: event.target.checked }))}
                  className="mt-0.5"
                />
                <span className="min-w-0 flex-1 text-[11px] text-text-secondary">{item.description}</span>
                {item.required && (
                  <span className="shrink-0 rounded bg-accent-red/15 px-1.5 py-0.5 text-[9px] text-accent-red">必检</span>
                )}
              </label>
            ))}
          </div>
        )}
        <p className="mt-2 text-[10px] text-text-muted">
          勾选状态仅用于现场自查，不回写后端（后端 task-package 为只读生成接口）。
        </p>
      </Section>

      {/* 工序步骤 */}
      <Section title="🔧 标准作业工序">
        {steps.length === 0 ? (
          <p className="text-xs text-text-muted">未生成工序步骤</p>
        ) : (
          <div className="space-y-1.5">
            {steps.map((step) => (
              <div key={step.seq} className="flex gap-2 rounded border border-border-default bg-bg-secondary/40 p-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-blue/20 font-mono text-[10px] text-accent-blue">
                  {step.seq}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] text-text-primary">{step.action}</p>
                  <div className="mt-0.5 flex flex-wrap gap-3 text-[10px] text-text-muted">
                    {step.tool_required && <span>工具：{step.tool_required}</span>}
                    {step.estimated_minutes != null && <span>预计 {step.estimated_minutes} 分钟</span>}
                  </div>
                  {step.safety_note && (
                    <p className="mt-1 text-[10px] text-accent-orange">⚠ {step.safety_note}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* 资源 */}
      <div className="grid gap-3 md:grid-cols-3">
        <ListCard title="🧰 所需工具" items={pkg.required_tools} />
        <ListCard title="🔩 所需备件" items={pkg.required_parts} />
        <ListCard title="👷 技能 / 人员" items={[...(pkg.required_skills || []), ...(pkg.assigned_personnel || [])]} />
      </div>

      {/* 验收 / 回滚 / 升级 */}
      <div className="grid gap-3 md:grid-cols-3">
        <ListCard title="✅ 验收标准" items={pkg.acceptance_criteria} tone="text-accent-green" />
        <ListCard title="↩ 回滚条件" items={pkg.rollback_conditions} tone="text-accent-yellow" />
        <ListCard title="⬆ 升级条件" items={pkg.escalation_conditions} tone="text-accent-red" />
      </div>

      {pkg.recovery_verification_metrics && (
        <Section title="📈 恢复验证指标">
          <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
            {Object.entries(pkg.recovery_verification_metrics).map(([key, value]) => (
              <div key={key} className="rounded border border-border-default bg-bg-secondary/50 p-2">
                <div className="truncate text-[10px] text-text-muted">{key}</div>
                <div className="mt-0.5 truncate font-mono text-text-primary">
                  {typeof value === 'object' ? JSON.stringify(value).slice(0, 24) : String(value ?? '—')}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 诊断证据 */}
      {Array.isArray(pkg.diagnostic_evidence) && pkg.diagnostic_evidence.length > 0 && (
        <Section title="🔗 携带的诊断证据">
          <div className="space-y-1">
            {pkg.diagnostic_evidence.slice(0, 12).map((item: any, index: number) => (
              <div key={index} className="flex items-center gap-2 rounded bg-bg-primary/40 p-2 text-[10px]">
                <span className="shrink-0 text-accent-cyan">{item.node_type || item.type || 'evidence'}</span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">
                  {item.label || item.description || JSON.stringify(item).slice(0, 60)}
                </span>
                {item.confidence != null && (
                  <span className="shrink-0 font-mono text-text-muted">
                    {(Number(item.confidence) * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      <p className="text-[10px] text-text-muted">生成时间 {pkg.generated_at || '—'}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
      <h4 className="mb-2 text-xs font-semibold text-text-primary">{title}</h4>
      {children}
    </div>
  );
}

function ListCard({ title, items, tone }: { title: string; items?: any[]; tone?: string }) {
  const list = (items || []).filter(Boolean);
  return (
    <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
      <h4 className="mb-1.5 text-xs font-semibold text-text-primary">{title}</h4>
      {list.length === 0 ? (
        <p className="text-[10px] text-text-muted">无</p>
      ) : (
        <ul className="space-y-0.5">
          {list.map((item, index) => (
            <li key={index} className={`flex gap-1 text-[10px] ${tone || 'text-text-secondary'}`}>
              <span>▸</span>
              <span className="min-w-0 flex-1">
                {typeof item === 'object' ? JSON.stringify(item).slice(0, 80) : String(item)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-border-default bg-bg-secondary/50 p-2">
      <div className="text-[10px] text-text-muted">{label}</div>
      <div className="mt-0.5 font-mono text-base font-semibold text-text-primary">{value}</div>
      {sub && <div className="text-[10px] text-text-muted">{sub}</div>}
    </div>
  );
}
