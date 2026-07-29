import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../../services/api';

interface Props {
  incidentId: number;
  turbineId: number;
}

type SubTab = 'conflict' | 'genotype' | 'causal';

interface Genotype {
  fault_type: string;
  category: string;
  description: string;
  features: Record<string, string>;
  discriminators: string[];
}

const EDGE_STYLE: Record<string, { label: string; text: string; border: string; bg: string }> = {
  supports: { label: '支持', text: 'text-accent-green', border: 'border-accent-green/35', bg: 'bg-accent-green/8' },
  contradicts: { label: '矛盾', text: 'text-accent-red', border: 'border-accent-red/40', bg: 'bg-accent-red/10' },
  requires_check: { label: '待验证', text: 'text-accent-yellow', border: 'border-accent-yellow/35', bg: 'bg-accent-yellow/8' },
};

const CAUSAL_SERIES: { key: string; field: string; label: string }[] = [
  { key: 'wind_speed', field: 'wind_speed_ms', label: '风速' },
  { key: 'power', field: 'power_kw', label: '功率' },
  { key: 'gearbox_temp', field: 'gearbox_temperature_c', label: '齿轮箱温度' },
  { key: 'gen_temp', field: 'gen_temperature_c', label: '发电机温度' },
  { key: 'bearing_temp', field: 'bearing_temperature_c', label: '轴承温度' },
  { key: 'rotor_rpm', field: 'rotor_rpm', label: '转速' },
];

function detailOf(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e?.response?.status === 403) return '当前账号权限不足（需 engineer 及以上）';
  return e?.message || fallback;
}

/**
 * 深度分析 —— 合并三项后端已实现但前端未接的能力：
 * POST /api/incidents/{id}/multimodal-conflict  多模态冲突分析（图像 vs SCADA vs 振动 vs 知识）
 * GET  /api/diagnosis/fault-genotypes           故障基因库
 * POST /api/diagnosis/fault-genotype            Gower 距离基因匹配
 * POST /api/diagnosis/causal-discovery          Granger 因果发现（输入取自该风机真实 SCADA）
 */
export default function DeepAnalysisPanel({ incidentId, turbineId }: Props) {
  const [tab, setTab] = useState<SubTab>('conflict');
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1">
        {([['conflict', '🧩 多模态冲突'], ['genotype', '🧬 故障基因'], ['causal', '🔗 因果发现']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`rounded border px-3 py-1.5 text-[11px] transition-colors ${
              tab === key
                ? 'border-accent-blue/45 bg-accent-blue/15 text-accent-blue'
                : 'border-border-default text-text-muted hover:text-text-secondary'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'conflict' && <ConflictSection incidentId={incidentId} />}
      {tab === 'genotype' && <GenotypeSection />}
      {tab === 'causal' && <CausalSection turbineId={turbineId} />}
    </div>
  );
}

// ── 多模态冲突 ──

function ConflictSection({ incidentId }: { incidentId: number }) {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setReport(null); setError(null); }, [incidentId]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.post(`/incidents/${incidentId}/multimodal-conflict`, null, { timeout: 60000 });
      setReport(data);
    } catch (e: any) {
      setError(detailOf(e, '多模态冲突分析失败'));
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border-default bg-bg-secondary/40 p-3">
        <p className="min-w-0 flex-1 text-[11px] leading-5 text-text-muted">
          跨模态比对图像 / SCADA / 振动 / 告警 / 知识五类证据，生成 supports、contradicts、requires_check 三类
          带类型的证据边。<span className="text-accent-cyan">矛盾会被暴露而不是被掩盖。</span>
        </p>
        <button
          onClick={() => { void run(); }}
          disabled={loading}
          className="shrink-0 rounded border border-accent-cyan/40 bg-accent-cyan/10 px-3 py-1.5 text-xs text-accent-cyan transition-colors hover:bg-accent-cyan/20 disabled:opacity-50"
        >
          {loading ? '分析中…' : '运行冲突分析'}
        </button>
      </div>

      {loading && <div className="skeleton h-32 w-full" />}

      {error && (
        <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-3 text-xs text-accent-red">
          ⚠ {error}
          <button onClick={() => { void run(); }} className="ml-3 underline">重试</button>
        </div>
      )}

      {report && (
        <>
          <div className={`rounded-lg border p-4 ${
            report.evidence_sufficient ? 'border-accent-green/35 bg-accent-green/8' : 'border-accent-yellow/35 bg-accent-yellow/8'
          }`}>
            <p className="text-sm font-semibold text-text-primary">
              {report.evidence_sufficient ? '✅ 证据自洽，可支撑结论' : '⚠ 证据不足或存在矛盾'}
            </p>
            <p className="mt-1 text-[11px] leading-5 text-text-secondary">{report.overall_assessment}</p>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <Tile label="支持" value={String(report.supports_count ?? 0)} tone="text-accent-green" />
              <Tile label="矛盾" value={String(report.contradicts_count ?? 0)} tone="text-accent-red" />
              <Tile label="待验证" value={String(report.requires_check_count ?? 0)} tone="text-accent-yellow" />
            </div>
          </div>

          <div className="space-y-2">
            {(report.checks || []).map((check: any, index: number) => {
              const style = EDGE_STYLE[check.edge_type] || EDGE_STYLE.requires_check;
              return (
                <div key={index} className={`rounded-lg border p-3 ${style.border} ${style.bg}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-text-primary">
                      {check.source_type} → {check.target_type}
                    </span>
                    <span className={`rounded px-1.5 py-0.5 text-[9px] ${style.text}`}>{style.label}</span>
                    <span className="text-[10px] text-text-muted">严重度 {check.severity}</span>
                    <span className="ml-auto font-mono text-[10px] text-text-muted">
                      置信 {((check.confidence || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-text-primary">{check.finding}</p>
                  {check.explanation && <p className="mt-0.5 text-[10px] text-text-muted">{check.explanation}</p>}
                  {check.recommendation && (
                    <p className="mt-1 text-[10px] text-accent-cyan">建议：{check.recommendation}</p>
                  )}
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-text-muted">
            已生成 {report.generated_edges ?? 0} 条证据边并写入证据图 · {report.generated_at}
          </p>
        </>
      )}

      {!report && !loading && !error && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-8 text-center text-sm text-text-muted">
          点击「运行冲突分析」比对该事件的多模态证据
        </div>
      )}
    </div>
  );
}

// ── 故障基因 ──

function GenotypeSection() {
  const [genotypes, setGenotypes] = useState<Genotype[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [symptoms, setSymptoms] = useState<Record<string, string>>({});
  const [matching, setMatching] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/diagnosis/fault-genotypes');
      setGenotypes(Array.isArray(data?.genotypes) ? data.genotypes : []);
    } catch (e: any) {
      setError(detailOf(e, '故障基因库加载失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const featureOptions = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const genotype of genotypes) {
      for (const [key, value] of Object.entries(genotype.features || {})) {
        if (!map.has(key)) map.set(key, new Set());
        map.get(key)!.add(String(value));
      }
    }
    return Array.from(map.entries()).map(([key, values]) => ({ key, values: Array.from(values) }));
  }, [genotypes]);

  const runMatch = useCallback(async () => {
    const payload = Object.fromEntries(Object.entries(symptoms).filter(([, value]) => value));
    if (Object.keys(payload).length === 0) {
      setMatchError('请先至少选择一个观测特征');
      return;
    }
    setMatching(true);
    setMatchError(null);
    try {
      const { data } = await api.post('/diagnosis/fault-genotype', payload, { timeout: 30000 });
      setResult(data);
    } catch (e: any) {
      setMatchError(detailOf(e, '基因匹配失败'));
    } finally {
      setMatching(false);
    }
  }, [symptoms]);

  if (loading) return <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-20 w-full" />)}</div>;

  if (error) {
    return (
      <div className="rounded-lg border border-accent-red/35 bg-accent-red/10 p-3 text-xs text-accent-red">
        ⚠ {error}
        <button onClick={() => { void load(); }} className="ml-3 underline">重试</button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-text-primary">观测特征（Gower 距离混合类型匹配）</span>
          <div className="ml-auto flex flex-wrap gap-1">
            {genotypes.slice(0, 6).map((genotype) => (
              <button
                key={genotype.fault_type}
                onClick={() => setSymptoms({ ...genotype.features })}
                className="rounded-full border border-border-default px-2 py-0.5 text-[9px] text-text-muted transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan"
              >
                以 {genotype.fault_type} 填充
              </button>
            ))}
            <button
              onClick={() => { setSymptoms({}); setResult(null); }}
              className="rounded-full border border-border-default px-2 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
            >
              清空
            </button>
          </div>
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          {featureOptions.map(({ key, values }) => (
            <label key={key} className="flex items-center gap-2">
              <span className="w-32 shrink-0 truncate text-[10px] text-text-muted" title={key}>{key}</span>
              <select
                value={symptoms[key] || ''}
                onChange={(event) => setSymptoms((prev) => ({ ...prev, [key]: event.target.value }))}
                className="min-w-0 flex-1 rounded border border-border-default bg-bg-secondary px-1.5 py-1 text-[10px] text-text-primary focus:border-accent-cyan focus:outline-none"
              >
                <option value="">未观测</option>
                {values.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          ))}
        </div>

        <button
          onClick={() => { void runMatch(); }}
          disabled={matching}
          className="mt-3 rounded border border-accent-purple/40 bg-accent-purple/12 px-3 py-1.5 text-xs text-accent-purple transition-colors hover:bg-accent-purple/20 disabled:opacity-50"
        >
          {matching ? '匹配中…' : '🧬 运行基因匹配'}
        </button>
        {matchError && <p className="mt-2 text-[11px] text-accent-red">⚠ {matchError}</p>}
      </div>

      {result && (
        <div className="space-y-2">
          {(result.matches || []).map((match: any, index: number) => (
            <div
              key={match.fault_type}
              className={`rounded-lg border p-3 ${index === 0 ? 'border-accent-purple/45 bg-accent-purple/10' : 'border-border-default bg-bg-secondary/40'}`}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-text-primary">{match.fault_type}</span>
                {index === 0 && <span className="rounded bg-accent-purple/25 px-1.5 py-0.5 text-[9px] text-accent-purple">最相似</span>}
                <span className="ml-auto font-mono text-sm text-accent-purple">
                  {(match.similarity * 100).toFixed(1)}%
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded bg-bg-secondary/70">
                <div className="h-full rounded bg-accent-purple" style={{ width: `${Math.min(100, match.similarity * 100)}%` }} />
              </div>
              {match.discriminators?.length > 0 && (
                <p className="mt-1.5 text-[10px] text-text-muted">
                  鉴别特征：{match.discriminators.join('、')}
                </p>
              )}
              {match.feature_contributions && Object.keys(match.feature_contributions).length > 0 && (
                <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 md:grid-cols-3">
                  {Object.entries(match.feature_contributions).slice(0, 9).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2 text-[9px]">
                      <span className="truncate text-text-muted">{key}</span>
                      <span className="shrink-0 font-mono text-text-secondary">{String(value)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {result.differential_diagnosis && (
            <div className="rounded-lg border border-accent-cyan/30 bg-accent-cyan/8 p-3 text-[11px] leading-5 text-text-secondary">
              <span className="font-semibold text-accent-cyan">鉴别诊断：</span>{result.differential_diagnosis}
            </div>
          )}
          {(result.recommendations || []).length > 0 && (
            <ul className="space-y-0.5">
              {result.recommendations.map((item: string, index: number) => (
                <li key={index} className="flex gap-1 text-[11px] text-accent-yellow"><span>▸</span>{item}</li>
              ))}
            </ul>
          )}
          {result.evaluation && (
            <p className="text-[10px] text-text-muted">
              留一交叉验证：{JSON.stringify(result.evaluation)}
            </p>
          )}
        </div>
      )}

      {/* 基因库 */}
      <div className="rounded-lg border border-border-default bg-bg-secondary/30 p-3">
        <h4 className="mb-2 text-xs font-semibold text-text-primary">基因库（{genotypes.length} 类）</h4>
        <div className="grid gap-2 md:grid-cols-2">
          {genotypes.map((genotype) => (
            <div key={genotype.fault_type} className="rounded border border-border-default bg-bg-primary/40 p-2">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-text-primary">{genotype.fault_type}</span>
                <span className="rounded bg-bg-card px-1.5 py-0.5 text-[9px] text-text-muted">{genotype.category}</span>
              </div>
              <p className="mt-0.5 text-[10px] leading-4 text-text-muted">{genotype.description}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── 因果发现 ──

function CausalSection({ turbineId }: { turbineId: number }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [sampleInfo, setSampleInfo] = useState<{ points: number; series: string[] } | null>(null);

  useEffect(() => { setResult(null); setError(null); setSampleInfo(null); }, [turbineId]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: scada } = await api.get(`/turbines/${turbineId}/scada`, { params: { hours: 168 } });
      const records: any[] = Array.isArray(scada) ? scada : [];
      if (records.length < 30) {
        setError(`该风机可用 SCADA 样本仅 ${records.length} 条，不足以做 Granger 检验（至少 30 条）。`);
        setLoading(false);
        return;
      }
      const timeSeries: Record<string, number[]> = {};
      for (const item of CAUSAL_SERIES) {
        const values = records
          .map((row) => Number(row[item.field]))
          .filter((value) => Number.isFinite(value));
        if (values.length === records.length && values.length >= 30) timeSeries[item.key] = values;
      }
      const keys = Object.keys(timeSeries);
      if (keys.length < 2) {
        setError('可用的完整变量少于 2 个，无法做因果检验（SCADA 字段存在缺失）。');
        setLoading(false);
        return;
      }
      setSampleInfo({ points: records.length, series: keys });
      const { data } = await api.post('/diagnosis/causal-discovery', { time_series: timeSeries }, { timeout: 90000 });
      setResult(data);
    } catch (e: any) {
      setError(detailOf(e, '因果发现失败'));
    } finally {
      setLoading(false);
    }
  }, [turbineId]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border-default bg-bg-secondary/40 p-3">
        <p className="min-w-0 flex-1 text-[11px] leading-5 text-text-muted">
          取该风机最近 168 小时真实 SCADA 序列，做平稳性检验 + Granger 因果检验 + 多重比较校正 + Bootstrap 稳定性，
          并与物理规则交叉验证。<span className="text-accent-yellow">所有结论仅标注为「候选因果」。</span>
        </p>
        <button
          onClick={() => { void run(); }}
          disabled={loading}
          className="shrink-0 rounded border border-accent-blue/40 bg-accent-blue/12 px-3 py-1.5 text-xs text-accent-blue transition-colors hover:bg-accent-blue/20 disabled:opacity-50"
        >
          {loading ? '计算中…' : '🔗 运行因果发现'}
        </button>
      </div>

      {loading && <div className="skeleton h-32 w-full" />}

      {error && (
        <div className="rounded-lg border border-accent-yellow/35 bg-accent-yellow/8 p-3 text-xs text-accent-yellow">
          ⚠ {error}
          <button onClick={() => { void run(); }} className="ml-3 underline">重试</button>
        </div>
      )}

      {sampleInfo && (
        <p className="text-[10px] text-text-muted">
          样本 {sampleInfo.points} 点 · 变量 {sampleInfo.series.join('、')}
        </p>
      )}

      {result && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Tile label="检验总数" value={String(result.total_tests ?? 0)} />
            <Tile label="显著链接" value={String((result.significant_links || []).length)} tone="text-accent-green" />
            <Tile label="校正方法" value={String(result.correction_method || '—')} />
          </div>

          {(result.significant_links || []).length === 0 ? (
            <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-6 text-center text-xs text-text-muted">
              未发现统计显著的候选因果链接（这本身也是有效结论）
            </div>
          ) : (
            <div className="space-y-2">
              {result.significant_links.map((link: any, index: number) => (
                <div key={index} className={`rounded-lg border p-3 ${
                  link.physical_plausibility ? 'border-accent-green/35 bg-accent-green/8' : 'border-accent-yellow/35 bg-accent-yellow/8'
                }`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-text-primary">
                      {link.source} → {link.target}
                    </span>
                    <span className="rounded bg-bg-card px-1.5 py-0.5 text-[9px] text-text-muted">lag {link.lag}</span>
                    {link.stable && <span className="rounded bg-accent-green/20 px-1.5 py-0.5 text-[9px] text-accent-green">稳定</span>}
                    {link.physical_plausibility
                      ? <span className="rounded bg-accent-cyan/15 px-1.5 py-0.5 text-[9px] text-accent-cyan">符合物理规则</span>
                      : <span className="rounded bg-accent-yellow/20 px-1.5 py-0.5 text-[9px] text-accent-yellow">缺物理支撑</span>}
                    <span className="ml-auto font-mono text-[10px] text-text-muted">
                      p={Number(link.p_value_corrected).toExponential(2)} · 稳定性 {link.bootstrap_stability}
                    </span>
                  </div>
                  {link.interpretation && <p className="mt-1 text-[11px] text-text-secondary">{link.interpretation}</p>}
                  {link.physical_rule && <p className="mt-0.5 text-[10px] text-text-muted">物理规则：{link.physical_rule}</p>}
                  {link.caveat && <p className="mt-0.5 text-[10px] text-accent-orange">⚠ {link.caveat}</p>}
                </div>
              ))}
            </div>
          )}

          {result.caveat && (
            <p className="rounded-lg border border-border-subtle bg-bg-secondary/30 p-3 text-[10px] leading-5 text-text-muted">
              {result.caveat}
            </p>
          )}
        </>
      )}

      {!result && !loading && !error && (
        <div className="rounded-lg border border-border-default bg-bg-secondary/40 p-8 text-center text-sm text-text-muted">
          点击「运行因果发现」，从真实 SCADA 序列中挖掘候选因果链
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border-default bg-bg-secondary/50 p-2 text-center">
      <div className="text-[10px] text-text-muted">{label}</div>
      <div className={`mt-0.5 truncate font-mono text-base font-semibold ${tone || 'text-text-primary'}`}>{value}</div>
    </div>
  );
}
