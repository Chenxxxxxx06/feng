import { useCallback, useEffect, useState } from 'react';
import api from '../../../services/api';
import { runRedTeamScenario } from '../../../services/incidentService';

interface Props {
  incidentId: number;
}

interface Scenario {
  key: string;
  name: string;
  description: string;
  category: string;
  expected_behaviors: string[];
  max_score: number;
}

interface SessionResult {
  session_id: string;
  scenario_key: string;
  score: number;
  max_score: number;
  passed: boolean;
  score_breakdown?: Record<string, any>;
  errors?: string[];
  restored?: boolean;
  injection_mode?: string;
}

const CATEGORY_LABEL: Record<string, string> = {
  data_quality: '数据质量',
  safety: '安全边界',
  adversarial: '对抗输入',
  availability: '可用性',
  policy: '策略合规',
};

/**
 * 红队演练面板
 * GET  /api/incidents/{id}/red-team          — 场景清单（assessment_only）
 * POST /api/incidents/{id}/red-team/run      — 单场景评分
 * POST /api/incidents/{id}/red-team/run-all  — 全场景评分报告
 */
export default function RedTeamPanel({ incidentId }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [injectionMode, setInjectionMode] = useState<string>('assessment_only');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, SessionResult>>({});
  const [report, setReport] = useState<any>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(`/incidents/${incidentId}/red-team`);
      setScenarios(Array.isArray(data?.scenarios) ? data.scenarios : []);
      setInjectionMode(data?.injection_mode || 'assessment_only');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : e?.message || '红队场景加载失败');
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    setResults({});
    setReport(null);
    setRunError(null);
    void load();
  }, [load]);

  const runOne = useCallback(async (key: string) => {
    setRunning(key);
    setRunError(null);
    try {
      const result = await runRedTeamScenario(incidentId, key);
      setResults((prev) => ({ ...prev, [key]: result }));
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setRunError(typeof detail === 'string' ? detail : e?.message || `场景 ${key} 执行失败`);
    } finally {
      setRunning(null);
    }
  }, [incidentId]);

  const runAll = useCallback(async () => {
    setRunning('__all__');
    setRunError(null);
    try {
      const { data } = await api.post(`/incidents/${incidentId}/red-team/run-all`, null, { timeout: 60000 });
      setReport(data);
      const merged: Record<string, SessionResult> = {};
      for (const session of data?.sessions || []) merged[session.scenario_key] = session;
      setResults((prev) => ({ ...prev, ...merged }));
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setRunError(typeof detail === 'string' ? detail : e?.message || '全场景演练失败');
    } finally {
      setRunning(null);
    }
  }, [incidentId]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-16 w-full" />
        {[0, 1, 2].map((index) => <div key={index} className="skeleton h-24 w-full" />)}
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

  if (scenarios.length === 0) {
    return (
      <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-10 text-center">
        <div className="text-3xl">🎯</div>
        <p className="mt-2 text-sm text-text-secondary">后端未注册任何红队场景</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-accent-orange/30 bg-accent-orange/8 p-4">
        <div>
          <p className="text-sm font-semibold text-text-primary">🎯 红队演练 · {scenarios.length} 个场景</p>
          <p className="mt-0.5 text-[11px] text-text-muted">
            注入模式 <code className="rounded bg-bg-card px-1 font-mono">{injectionMode}</code> —
            场景参数仅被记录用于评分，不会真的注入运行系统；得分来自事件真实的 trace / 证据 / 策略判定 / 告警。
          </p>
        </div>
        <button
          onClick={() => { void runAll(); }}
          disabled={running !== null}
          className="ml-auto rounded border border-accent-orange/40 bg-accent-orange/15 px-3 py-1.5 text-xs text-accent-orange transition-colors hover:bg-accent-orange/25 disabled:opacity-50"
        >
          {running === '__all__' ? '演练中…' : '⚔ 一键全量演练'}
        </button>
      </div>

      {runError && (
        <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-3 text-xs text-accent-red">⚠ {runError}</div>
      )}

      {report && (
        <div className={`rounded-lg border p-4 ${
          report.passed_scenarios === report.total_scenarios
            ? 'border-accent-green/35 bg-accent-green/8'
            : 'border-accent-yellow/35 bg-accent-yellow/8'
        }`}>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-semibold text-text-primary">演练报告 {report.report_id}</span>
            <span className="font-mono text-lg text-text-primary">
              {report.total_score} / {report.max_total_score}
            </span>
            <span className="text-xs text-text-muted">
              通过 {report.passed_scenarios}/{report.total_scenarios}
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded bg-bg-secondary/70">
            <div
              className="h-full rounded bg-accent-green"
              style={{ width: `${Math.min(100, (report.total_score / Math.max(report.max_total_score, 1)) * 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {scenarios.map((scenario) => {
          const result = results[scenario.key];
          const ratio = result ? result.score / Math.max(result.max_score || scenario.max_score, 1) : 0;
          return (
            <div
              key={scenario.key}
              className={`rounded-lg border p-3 ${
                !result ? 'border-border-default bg-bg-secondary/40'
                  : result.passed ? 'border-accent-green/35 bg-accent-green/8'
                    : 'border-accent-red/40 bg-accent-red/8'
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-text-primary">{scenario.name}</span>
                    <span className="shrink-0 rounded bg-bg-card px-1.5 py-0.5 text-[9px] text-text-muted">
                      {CATEGORY_LABEL[scenario.category] || scenario.category}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-text-muted">{scenario.description}</p>
                </div>
                {result && (
                  <span className={`shrink-0 font-mono text-lg ${result.passed ? 'text-accent-green' : 'text-accent-red'}`}>
                    {result.score}/{result.max_score}
                  </span>
                )}
              </div>

              {result && (
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-bg-secondary/70">
                  <div
                    className={`h-full rounded ${result.passed ? 'bg-accent-green' : 'bg-accent-red'}`}
                    style={{ width: `${Math.min(100, ratio * 100)}%` }}
                  />
                </div>
              )}

              {scenario.expected_behaviors?.length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {scenario.expected_behaviors.slice(0, 4).map((item, index) => (
                    <li key={index} className="flex gap-1 text-[10px] text-text-muted">
                      <span className="text-accent-cyan">▸</span>
                      <span className="min-w-0 flex-1">{item}</span>
                    </li>
                  ))}
                </ul>
              )}

              {result?.score_breakdown && Object.keys(result.score_breakdown).length > 0 && (
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded border border-border-subtle bg-bg-primary/40 p-2 text-[10px]">
                  {Object.entries(result.score_breakdown).slice(0, 8).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2">
                      <span className="truncate text-text-muted">{key}</span>
                      <span className="shrink-0 font-mono text-text-secondary">
                        {typeof value === 'object' ? JSON.stringify(value).slice(0, 18) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {result?.errors && result.errors.length > 0 && (
                <p className="mt-2 text-[10px] text-accent-red">失败项：{result.errors.join('；')}</p>
              )}

              <button
                onClick={() => { void runOne(scenario.key); }}
                disabled={running !== null}
                className="mt-2 rounded border border-border-default bg-bg-secondary/60 px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:border-accent-orange/40 hover:text-accent-orange disabled:opacity-50"
              >
                {running === scenario.key ? '演练中…' : result ? '重新演练' : '运行场景'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
