import { useCallback, useEffect, useState } from 'react';
import api from '../../../services/api';
import { getWhatIfAnalysis } from '../../../services/incidentService';

interface Props {
  incidentId: number;
}

interface DecisionPoint {
  point_id: string;
  seq: number;
  stage: string;
  timestamp: string;
  actual_choice: string;
  alternatives: string[];
}

interface Fork {
  decision_point_id: string;
  alternative_choice: string;
  estimated_cost: number;
  estimated_downtime_hours: number;
  estimated_risk: number;
  recovery_probability: number;
  total_score: number;
  cost_vs_actual: number;
  key_assumptions?: string[];
  data_quality?: string;
  is_catastrophic?: boolean;
}

function money(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
}

/**
 * What-if 分叉推演面板
 * GET  /api/incidents/{id}/what-if            — 决策点 + 全部分叉
 * POST /api/incidents/{id}/what-if/simulate   — 单点单方案重算
 */
export default function WhatIfPanel({ incidentId }: Props) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activePoint, setActivePoint] = useState<string | null>(null);
  const [simulating, setSimulating] = useState<string | null>(null);
  const [simResult, setSimResult] = useState<Fork | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getWhatIfAnalysis(incidentId);
      setData(result);
      setActivePoint(result?.decision_points?.[0]?.point_id || null);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : e?.message || 'What-if 推演加载失败');
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => { void load(); }, [load]);

  const runSingleFork = useCallback(async (pointId: string, alternative: string) => {
    setSimulating(`${pointId}:${alternative}`);
    setSimError(null);
    setSimResult(null);
    try {
      const { data: fork } = await api.post(`/incidents/${incidentId}/what-if/simulate`, null, {
        params: { decision_point_id: pointId, alternative },
      });
      setSimResult(fork);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setSimError(typeof detail === 'string' ? detail : e?.message || '单点推演失败');
    } finally {
      setSimulating(null);
    }
  }, [incidentId]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-20 w-full" />
        <div className="skeleton h-32 w-full" />
        <div className="skeleton h-32 w-full" />
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

  const decisionPoints: DecisionPoint[] = data?.decision_points || [];
  const forks: Fork[] = data?.forks || [];
  const actual = data?.actual_path || {};

  if (decisionPoints.length === 0) {
    return (
      <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-10 text-center">
        <div className="text-3xl">🔀</div>
        <p className="mt-2 text-sm text-text-secondary">暂无可推演的决策点</p>
        <p className="mt-1 text-xs text-text-muted">
          决策点从事件的 Agent 飞行记录与决策方案中提取，请先执行「自主调查」与「决策分析」。
        </p>
      </div>
    );
  }

  const activeForks = forks.filter((fork) => fork.decision_point_id === activePoint);

  return (
    <div className="space-y-4">
      {/* 实际路径 */}
      <div className="rounded-lg border border-accent-blue/30 bg-accent-blue/8 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-text-primary">🛣 实际走过的路径</span>
          <span className="rounded bg-bg-card px-2 py-0.5 text-[10px] text-text-muted">
            策略 {actual.chosen_strategy || '未知'}
          </span>
          <span className="ml-auto text-[10px] text-text-muted">
            算法 {data?.algorithm_version || '—'} · seed {data?.seed ?? '—'}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="最终阶段" value={actual.final_stage || '—'} />
          <Metric label="验证状态" value={actual.verification_status || '未验证'} />
          <Metric label="实际成本" value={money(actual.actual_cost)} />
          <Metric label="实际停机" value={actual.actual_downtime != null ? `${actual.actual_downtime} 天` : '—'} />
        </div>
      </div>

      {/* 决策点选择 */}
      <div className="flex flex-wrap gap-2">
        {decisionPoints.map((point) => (
          <button
            key={point.point_id}
            onClick={() => { setActivePoint(point.point_id); setSimResult(null); setSimError(null); }}
            className={`rounded-lg border px-3 py-2 text-left transition-colors ${
              activePoint === point.point_id
                ? 'border-accent-blue/50 bg-accent-blue/12'
                : 'border-border-default bg-bg-secondary/40 hover:border-border-active'
            }`}
          >
            <div className="text-[11px] font-semibold text-text-primary">
              #{point.seq} {point.stage}
            </div>
            <div className="text-[10px] text-text-muted">
              实选 {point.actual_choice} · {point.alternatives?.length || 0} 个替代
            </div>
          </button>
        ))}
      </div>

      {/* 分叉结果 */}
      {activeForks.length === 0 ? (
        <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-6 text-center text-sm text-text-muted">
          该决策点没有可比较的替代路径
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {activeForks.map((fork) => (
            <ForkCard
              key={`${fork.decision_point_id}-${fork.alternative_choice}`}
              fork={fork}
              busy={simulating === `${fork.decision_point_id}:${fork.alternative_choice}`}
              onSimulate={() => { void runSingleFork(fork.decision_point_id, fork.alternative_choice); }}
            />
          ))}
        </div>
      )}

      {simError && (
        <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-3 text-xs text-accent-red">
          ⚠ {simError}
        </div>
      )}

      {simResult && (
        <div className="rounded-lg border border-accent-cyan/35 bg-accent-cyan/8 p-4">
          <p className="text-sm font-semibold text-accent-cyan">
            ↻ 单点重算：{simResult.decision_point_id} → {simResult.alternative_choice}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="推演成本" value={money(simResult.estimated_cost)} />
            <Metric label="停机小时" value={`${(simResult.estimated_downtime_hours || 0).toFixed(1)}h`} />
            <Metric label="恢复概率" value={`${((simResult.recovery_probability || 0) * 100).toFixed(0)}%`} />
            <Metric label="综合得分" value={(simResult.total_score || 0).toFixed(1)} />
          </div>
          {simResult.key_assumptions && simResult.key_assumptions.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[11px] text-text-muted">
              {simResult.key_assumptions.map((item, index) => <li key={index}>· {item}</li>)}
            </ul>
          )}
        </div>
      )}

      <p className="rounded-lg border border-border-subtle bg-bg-secondary/30 p-3 text-[11px] leading-5 text-text-muted">
        推演使用与真实决策相同的评分模型、仅扰动输入，不是历史真值；`data_quality=partial` 表示部分输入缺失，
        结果仅供复盘参考。
      </p>
    </div>
  );
}

function ForkCard({ fork, busy, onSimulate }: { fork: Fork; busy: boolean; onSimulate: () => void }) {
  const better = fork.cost_vs_actual < 0;
  return (
    <div className={`rounded-lg border p-3 ${
      fork.is_catastrophic
        ? 'border-accent-red/45 bg-accent-red/10'
        : better
          ? 'border-accent-green/35 bg-accent-green/8'
          : 'border-border-default bg-bg-secondary/40'
    }`}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-text-primary">{fork.alternative_choice}</span>
        {fork.is_catastrophic && (
          <span className="rounded bg-accent-red/25 px-1.5 py-0.5 text-[9px] text-accent-red">灾难性分支</span>
        )}
        <span className={`ml-auto font-mono text-sm ${better ? 'text-accent-green' : 'text-accent-orange'}`}>
          {fork.cost_vs_actual >= 0 ? '+' : ''}{money(fork.cost_vs_actual)}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
        <Line label="推演成本" value={money(fork.estimated_cost)} />
        <Line label="停机" value={`${(fork.estimated_downtime_hours || 0).toFixed(1)}h`} />
        <Line label="风险" value={`${((fork.estimated_risk || 0) * 100).toFixed(0)}%`} />
        <Line label="恢复概率" value={`${((fork.recovery_probability || 0) * 100).toFixed(0)}%`} />
        <Line label="综合得分" value={(fork.total_score || 0).toFixed(1)} />
        <Line label="数据质量" value={fork.data_quality || '—'} />
      </div>
      {fork.key_assumptions && fork.key_assumptions.length > 0 && (
        <p className="mt-2 text-[10px] leading-4 text-text-muted">
          假设：{fork.key_assumptions.slice(0, 2).join('；')}
        </p>
      )}
      <button
        onClick={onSimulate}
        disabled={busy}
        className="mt-2 rounded border border-accent-cyan/35 bg-accent-cyan/10 px-2.5 py-1 text-[11px] text-accent-cyan transition-colors hover:bg-accent-cyan/20 disabled:opacity-50"
      >
        {busy ? '推演中…' : '↻ 单独重算'}
      </button>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-default bg-bg-secondary/50 p-2">
      <div className="text-[10px] text-text-muted">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm text-text-primary">{value}</div>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-text-muted">{label}</span>
      <span className="truncate font-mono text-text-secondary">{value}</span>
    </div>
  );
}
