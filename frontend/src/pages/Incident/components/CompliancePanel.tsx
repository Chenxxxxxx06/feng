import { useCallback, useEffect, useState } from 'react';
import api from '../../../services/api';
import { getComplianceCheck } from '../../../services/incidentService';

interface Props {
  incidentId: number;
}

interface RuleMeta {
  rule_id: string;
  ref: string;
  category: string;
  description: string;
  severity: string;
  verification: string;
  remediation: string;
}

interface CheckResult {
  rule_id: string;
  passed: boolean;
  severity: string;
  details: string;
  remediation: string;
}

const ACTIONS: { key: string; label: string }[] = [
  { key: 'close_incident', label: '关闭事件' },
  { key: 'execute_repair', label: '执行维修' },
  { key: 'approve_plan', label: '审批方案' },
];

const SEVERITY_META: Record<string, { label: string; text: string; border: string; bg: string; order: number }> = {
  blocker: { label: 'Blocker', text: 'text-accent-red', border: 'border-accent-red/50', bg: 'bg-accent-red/12', order: 0 },
  critical: { label: 'Critical', text: 'text-accent-orange', border: 'border-accent-orange/45', bg: 'bg-accent-orange/10', order: 1 },
  warning: { label: 'Warning', text: 'text-accent-yellow', border: 'border-accent-yellow/40', bg: 'bg-accent-yellow/8', order: 2 },
  info: { label: 'Info', text: 'text-accent-blue', border: 'border-accent-blue/30', bg: 'bg-accent-blue/8', order: 3 },
};

function severityMeta(severity: string) {
  return SEVERITY_META[String(severity || '').toLowerCase()] || SEVERITY_META.info;
}

/**
 * 合规检查面板
 * GET  /api/incidents/{id}/compliance          — 规则库（含 GB/T 引用）
 * POST /api/incidents/{id}/compliance/check    — 针对某个动作跑合规巡检
 */
export default function CompliancePanel({ incidentId }: Props) {
  const [action, setAction] = useState('close_incident');
  const [report, setReport] = useState<any>(null);
  const [rules, setRules] = useState<RuleMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRules, setShowRules] = useState(false);

  const load = useCallback(async (targetAction: string) => {
    setLoading(true);
    setError(null);
    try {
      const [checkResult, ruleResult] = await Promise.all([
        getComplianceCheck(incidentId, targetAction),
        api.get(`/incidents/${incidentId}/compliance`).then((res) => res.data).catch(() => null),
      ]);
      setReport(checkResult);
      setRules(Array.isArray(ruleResult?.rules) ? ruleResult.rules : []);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : e?.message || '合规检查失败');
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => { void load(action); }, [load, action]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-24 w-full" />
        {[0, 1, 2, 3].map((index) => <div key={index} className="skeleton h-14 w-full" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-4 text-sm text-accent-red">
        ⚠ {error}
        <button onClick={() => { void load(action); }} className="ml-3 underline">重试</button>
      </div>
    );
  }

  const results: CheckResult[] = (report?.results || []).slice().sort(
    (a: CheckResult, b: CheckResult) => {
      if (a.passed !== b.passed) return a.passed ? 1 : -1;
      return severityMeta(a.severity).order - severityMeta(b.severity).order;
    },
  );

  const ruleMap = new Map(rules.map((rule) => [rule.rule_id, rule]));
  const grouped = ['blocker', 'critical', 'warning', 'info'].map((severity) => ({
    severity,
    items: results.filter((item) => String(item.severity).toLowerCase() === severity),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="space-y-4">
      {/* 动作切换 + 总览 */}
      <div className={`rounded-lg border p-4 ${
        report?.can_close ? 'border-accent-green/35 bg-accent-green/8' : 'border-accent-red/40 bg-accent-red/10'
      }`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-text-primary">
            {report?.can_close ? '✅ 合规检查通过，允许放行' : '⛔ 存在阻断项，禁止放行'}
          </span>
          <div className="ml-auto flex gap-1">
            {ACTIONS.map((item) => (
              <button
                key={item.key}
                onClick={() => setAction(item.key)}
                className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                  action === item.key
                    ? 'border-accent-blue/45 bg-accent-blue/15 text-accent-blue'
                    : 'border-border-default text-text-muted hover:text-text-secondary'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
          <Tile label="规则总数" value={String(report?.total_rules ?? 0)} />
          <Tile label="通过" value={String(report?.passed ?? 0)} tone="text-accent-green" />
          <Tile label="未通过" value={String(report?.failed ?? 0)} tone="text-accent-orange" />
          <Tile label="Blocker" value={String(report?.blocker_failed ?? 0)} tone="text-accent-red" />
          <Tile label="Critical" value={String(report?.critical_failed ?? 0)} tone="text-accent-orange" />
        </div>
      </div>

      {/* 分级结果 */}
      {grouped.length === 0 ? (
        <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-8 text-center text-sm text-text-muted">
          该动作没有适用的合规规则
        </div>
      ) : grouped.map((group) => {
        const meta = severityMeta(group.severity);
        return (
          <div key={group.severity}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className={`text-xs font-semibold ${meta.text}`}>{meta.label}</span>
              <span className="text-[10px] text-text-muted">
                {group.items.filter((item) => item.passed).length}/{group.items.length} 通过
              </span>
            </div>
            <div className="space-y-1.5">
              {group.items.map((item) => {
                const rule = ruleMap.get(item.rule_id);
                return (
                  <div
                    key={item.rule_id}
                    className={`rounded-lg border p-3 ${item.passed
                      ? 'border-border-default bg-bg-secondary/40'
                      : `${meta.border} ${meta.bg}`}`}
                  >
                    <div className="flex items-start gap-2">
                      <span className={item.passed ? 'text-accent-green' : meta.text}>
                        {item.passed ? '✓' : '✗'}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] text-text-primary">{item.rule_id}</span>
                          {rule?.ref && (
                            <span className="rounded bg-bg-card px-1.5 py-0.5 text-[9px] text-text-muted">{rule.ref}</span>
                          )}
                          {rule?.category && (
                            <span className="text-[9px] text-text-muted">{rule.category}</span>
                          )}
                          <span className={`ml-auto text-[9px] ${meta.text}`}>{meta.label}</span>
                        </div>
                        {rule?.description && (
                          <p className="mt-0.5 text-[11px] text-text-secondary">{rule.description}</p>
                        )}
                        {item.details && (
                          <p className="mt-0.5 text-[10px] text-text-muted">{item.details}</p>
                        )}
                        {!item.passed && (item.remediation || rule?.remediation) && (
                          <p className="mt-1 rounded border border-border-subtle bg-bg-primary/40 p-1.5 text-[10px] text-accent-cyan">
                            整改建议：{item.remediation || rule?.remediation}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* 规则库 */}
      {rules.length > 0 && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
          <button
            onClick={() => setShowRules((value) => !value)}
            className="text-xs text-text-secondary hover:text-text-primary"
          >
            {showRules ? '▾' : '▸'} 合规规则库（{rules.length} 条，含 GB/T 与赛事条款引用）
          </button>
          {showRules && (
            <div className="mt-2 max-h-64 space-y-1 overflow-y-auto pr-1">
              {rules.map((rule) => {
                const meta = severityMeta(rule.severity);
                return (
                  <div key={rule.rule_id} className="flex items-start gap-2 rounded bg-bg-primary/40 p-2 text-[10px]">
                    <span className={`shrink-0 font-mono ${meta.text}`}>{meta.label}</span>
                    <span className="w-28 shrink-0 truncate font-mono text-text-muted">{rule.rule_id}</span>
                    <span className="min-w-0 flex-1 text-text-secondary">{rule.description}</span>
                    <span className="shrink-0 text-text-muted">{rule.ref}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border-default bg-bg-secondary/50 p-2 text-center">
      <div className="text-[10px] text-text-muted">{label}</div>
      <div className={`mt-0.5 font-mono text-lg font-semibold ${tone || 'text-text-primary'}`}>{value}</div>
    </div>
  );
}
