import { useCallback, useMemo, useRef, useState } from 'react';
import {
  buildExecutionChain, cancelAgentAction, cancelAgentTaskPlan, confirmAgentAction,
  formatDuration, planAgentTask,
} from '../../services/agentTraceService';
import type {
  AgentTaskPlanResponse, ChainPhase, ExecutionChainStep,
} from '../../services/agentTraceService';
import StepCard from './StepCard';
import GuardConfirmCard from './GuardConfirmCard';

interface Props {
  pageType: string;
  pageContext?: Record<string, unknown>;
  /** 预置指令建议（不传用默认） */
  suggestions?: string[];
  className?: string;
}

const DEFAULT_SUGGESTIONS = [
  '查询1号风机健康指数',
  '给3号风机建一个齿轮箱检修工单',
  '统计当前待处理的高优先级工单',
];

function errorText(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (error?.response?.data?.error_message) return String(error.response.data.error_message);
  if (error?.code === 'ECONNABORTED') return 'Agent 规划超时，后端可能仍在处理，请稍后重试。';
  return error?.message || fallback;
}

/**
 * 实时执行链 —— 玻璃驾驶舱右栏。
 * 把后端 Agent 任务规划（/agent-tasks/plan）与两阶段确认（/agent-actions/{id}/confirm）
 * 的每一步渲染成可见的状态卡：理解 → 规划 → 六段步骤 → 守护 → 写入 → 验证。
 */
export default function ExecutionChainPanel({
  pageType, pageContext, suggestions, className,
}: Props) {
  const [input, setInput] = useState('');
  const [plan, setPlan] = useState<AgentTaskPlanResponse | null>(null);
  const [phase, setPhase] = useState<ChainPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [resultSummary, setResultSummary] = useState<string>('');
  const lastMessageRef = useRef<string>('');

  const busy = phase === 'planning' || phase === 'executing';

  const runPlan = useCallback(async (message: string, planId?: string | null) => {
    const text = message.trim();
    if (!text) return;
    lastMessageRef.current = text;
    setPhase('planning');
    setError(null);
    setResultSummary('');
    if (!planId) setPlan(null);
    const startedAt = Date.now();
    try {
      const response = await planAgentTask({
        message: text,
        page_context: { page: pageType, ...(pageContext || {}) },
        plan_id: planId || undefined,
      });
      setElapsedMs(Date.now() - startedAt);
      setPlan(response);
      if (response.status === 'error' || response.status === 'unsupported') setPhase('failed');
      else setPhase('planned');
    } catch (e: any) {
      setElapsedMs(Date.now() - startedAt);
      setError(errorText(e, 'Agent 任务规划失败，请检查后端服务与登录状态。'));
      setPhase('failed');
    }
  }, [pageContext, pageType]);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    // 需要澄清时，把补充信息挂回同一个 plan_id
    void runPlan(text, plan?.status === 'needs_clarification' ? plan?.plan_id : null);
  }, [busy, input, plan, runPlan]);

  const handleConfirm = useCallback(async () => {
    if (!plan?.request_id) return;
    setPhase('executing');
    setError(null);
    try {
      const response = await confirmAgentAction(plan.request_id);
      if (response.status === 'success') {
        const entity = response.display?.open_entity as { type?: string; id?: number } | undefined;
        setResultSummary(
          entity?.type
            ? `${entity.type} #${entity.id ?? '-'} 已写入，后端回读校验通过`
            : `${response.action || '动作'} 已执行并落库`,
        );
        setPhase('executed');
      } else {
        setError(response.error_message || `执行失败（${response.error_code || 'execution_failed'}）`);
        setPhase('failed');
      }
    } catch (e: any) {
      setError(errorText(e, 'Agent 动作确认失败。'));
      setPhase('failed');
    }
  }, [plan]);

  const handleCancel = useCallback(async () => {
    if (!plan) return;
    setPhase('cancelled');
    try {
      if (plan.request_id) await cancelAgentAction(plan.request_id);
      else if (plan.plan_id) await cancelAgentTaskPlan(plan.plan_id);
    } catch {
      // 服务端待确认动作会自然过期，本地状态已回滚
    }
  }, [plan]);

  const handleReset = useCallback(() => {
    setPlan(null);
    setPhase('idle');
    setError(null);
    setResultSummary('');
    setElapsedMs(0);
  }, []);

  const chain: ExecutionChainStep[] = useMemo(
    () => buildExecutionChain(plan, phase, { elapsedMs, resultSummary }),
    [plan, phase, elapsedMs, resultSummary],
  );

  const guardVisible = Boolean(
    plan?.confirmation && plan?.request_id && (phase === 'planned' || phase === 'executing'),
  );

  const chips = suggestions?.length ? suggestions : DEFAULT_SUGGESTIONS;

  return (
    <div className={`flex h-full min-h-0 flex-col ${className || ''}`}>
      <div className="mb-2 flex shrink-0 items-center gap-1.5">
        <span className="text-accent-green text-xs">🛰</span>
        <h4 className="text-xs font-medium text-text-secondary">实时执行链</h4>
        {phase !== 'idle' && (
          <button
            onClick={handleReset}
            className="ml-auto rounded border border-border-default px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
          >
            清空
          </button>
        )}
      </div>

      {/* 指令输入 */}
      <div className="mb-2 shrink-0">
        <div className="flex gap-1.5">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') handleSubmit(); }}
            placeholder={plan?.status === 'needs_clarification' ? '补充澄清信息…' : '输入 Agent 任务指令…'}
            className="min-w-0 flex-1 rounded border border-border-default bg-bg-secondary px-2 py-1 text-[10px] text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
          />
          <button
            onClick={handleSubmit}
            disabled={busy || !input.trim()}
            className="shrink-0 rounded border border-accent-green/40 bg-accent-green/10 px-2 py-1 text-[10px] text-accent-green transition-colors hover:bg-accent-green/20 disabled:opacity-40"
          >
            {busy ? '…' : '执行'}
          </button>
        </div>
        {phase === 'idle' && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {chips.map((chip) => (
              <button
                key={chip}
                onClick={() => { setInput(''); void runPlan(chip); }}
                className="rounded-full border border-border-default bg-bg-secondary/60 px-2 py-0.5 text-[9px] text-text-muted transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan"
              >
                {chip}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 链路主体 */}
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
        {phase === 'planning' && chain.length <= 1 && (
          <div className="space-y-1.5">
            {[0, 1, 2].map((index) => (
              <div key={index} className="skeleton h-11 w-full rounded-lg" />
            ))}
          </div>
        )}

        {phase === 'idle' && chain.length === 0 && !error && (
          <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-3 text-center">
            <div className="text-lg">🛰</div>
            <p className="mt-1 text-[10px] leading-4 text-text-muted">
              输入一条指令，逐步观察 Agent 的
              <span className="text-accent-cyan"> 理解 → 规划 → 工具 → 守护 → 写入 → 验证 </span>
              全过程。写操作会在守护步骤被拦截，需要你点击确认后才落库。
            </p>
          </div>
        )}

        {chain.map((step, index) => (
          <StepCard key={step.key} step={step} isLast={index === chain.length - 1 && !guardVisible} />
        ))}

        {guardVisible && plan?.confirmation && plan?.request_id && (
          <GuardConfirmCard
            confirmation={plan.confirmation}
            requestId={plan.request_id}
            action={plan.action}
            busy={phase === 'executing'}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        )}

        {plan?.status === 'needs_clarification' && (
          <div className="rounded-lg border border-accent-blue/35 bg-accent-blue/8 p-2 text-[10px] text-text-secondary">
            <span className="font-semibold text-accent-blue">需要澄清：</span>
            {plan.clarification_question || `请补充 ${(plan.missing_slots || []).join('、')}`}
          </div>
        )}

        {phase === 'executed' && (
          <div className="rounded-lg border border-accent-green/35 bg-accent-green/8 p-2 text-[10px] text-accent-green">
            ✓ 闭环完成 · 已写入并通过回读验证 {elapsedMs ? `· 规划耗时 ${formatDuration(elapsedMs)}` : ''}
          </div>
        )}

        {phase === 'cancelled' && (
          <div className="rounded-lg border border-border-default bg-bg-secondary/50 p-2 text-[10px] text-text-muted">
            已取消本次 Agent 动作，未写入任何数据。
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-2">
            <p className="text-[10px] leading-4 text-accent-red">⚠ {error}</p>
            <button
              onClick={() => { void runPlan(lastMessageRef.current); }}
              disabled={!lastMessageRef.current || busy}
              className="mt-1.5 rounded border border-accent-red/40 px-2 py-0.5 text-[9px] text-accent-red hover:bg-accent-red/15 disabled:opacity-40"
            >
              重试
            </button>
          </div>
        )}

        {plan?.candidates && plan.candidates.length > 1 && (
          <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-2">
            <p className="text-[9px] uppercase tracking-wide text-text-muted">候选剧本</p>
            <div className="mt-1 space-y-0.5">
              {plan.candidates.slice(0, 4).map((candidate) => (
                <div key={candidate.id} className="flex items-center gap-1.5 text-[9px]">
                  <span className={`truncate ${candidate.id === plan.playbook_id ? 'text-accent-cyan' : 'text-text-muted'}`}>
                    {candidate.name || candidate.id}
                  </span>
                  <span className="ml-auto shrink-0 font-mono text-text-muted">
                    {candidate.score ?? '-'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
