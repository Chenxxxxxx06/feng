import { useCallback, useEffect, useMemo, useState } from 'react';
import StateBlock from '../../../components/Common/StateBlock';
import { Skeleton, SkeletonList } from '../../../components/Common/Skeleton';
import { toast } from '../../../components/Common/Toast';
import {
  DETECTION_META,
  describeAuditDemoError,
  detectionLabel,
  fetchAuditDemoCandidates,
  fetchAuditDemoStatus,
  runTamperCheck,
  scenarioShortName,
  shortHash,
  tamperFieldLabel,
  type AuditChainLink,
  type AuditChainReport,
  type AuditDemoCandidate,
  type AuditDemoStatus,
  type TamperCheckResponse,
  type TamperScenario,
} from '../../../services/auditDemoService';

/**
 * 审计链篡改检测演示面板。
 *
 * 讲一个三幕的故事：
 *   幕一 只改内容不重算哈希      → 内容哈希当场暴露
 *   幕二 改内容并重算该环哈希    → 下一环链接断裂
 *   幕三 重算整条下游链伪造自洽链 → **哈希全过、签名失败**
 *
 * 第三幕是全场最有说服力的一刻：攻击者能伪造出一条内部完全自洽的链，
 * 纯 SHA-256 校验一个错都挑不出来，但根哈希变了 —— 他没有 Ed25519 私钥，
 * 无法重新签名，于是在验签这一关被拦下。
 *
 * 全程只读：后端在 build_chain 产出的内存副本（deepcopy）上做篡改，
 * 响应里的 database_mutated 恒为 false，面板把这一点显式打在最醒目的位置。
 */

interface Props {
  incidentId: number;
}

const AUTO = 'auto';

// ── 小积木 ──

/** 通过 / 失败 的语义标记（颜色不是唯一表达，同时给出文字） */
function CheckChip({ ok, label, size = 'sm' }: { ok: boolean; label: string; size?: 'sm' | 'lg' }) {
  const color = ok ? 'var(--accent-green)' : 'var(--accent-red)';
  const tint = ok ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)';
  const border = ok ? 'rgba(16,185,129,0.30)' : 'rgba(239,68,68,0.32)';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: size === 'lg' ? '5px 11px' : '2px 7px',
        borderRadius: 999,
        background: tint,
        border: `1px solid ${border}`,
        color,
        fontSize: size === 'lg' ? 'var(--font-size-sm)' : 'var(--font-size-xs)',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      <span aria-hidden="true">{ok ? '✓' : '✗'}</span>
      {label}
    </span>
  );
}

/** 长哈希：等宽字体 + 截断，hover 显示完整值 */
function HashText({ value, head = 12, color }: { value?: string | null; head?: number; color?: string }) {
  return (
    <code
      className="num"
      title={value || '—'}
      style={{ fontSize: 'var(--font-size-xs)', color: color ?? 'var(--text-muted)', cursor: 'help' }}
    >
      {shortHash(value, head)}
    </code>
  );
}

// ── 链条可视化 ──

function ChainLinkRow({
  link,
  next,
  isLast,
  tamperedSeq,
}: {
  link: AuditChainLink;
  next?: AuditChainLink;
  isLast: boolean;
  tamperedSeq?: number;
}) {
  const broken = !link.valid;
  const tampered = tamperedSeq === link.seq;
  // 与下一环之间的连线：下一环链接不上即为断裂
  const connectorBroken = next ? !next.link_ok : false;
  const nodeColor = broken ? 'var(--accent-red)' : 'var(--accent-green)';
  const connectorColor = connectorBroken ? 'var(--accent-red)' : 'var(--accent-green)';

  return (
    <li style={{ display: 'flex', gap: 10, listStyle: 'none' }}>
      {/* 左侧链轨：节点 + 连线 */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, width: 26 }}>
        <span
          className="num"
          aria-hidden="true"
          style={{
            width: 24,
            height: 24,
            borderRadius: 999,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 'var(--font-size-xs)',
            fontWeight: 700,
            color: nodeColor,
            background: broken ? 'rgba(239,68,68,0.14)' : 'rgba(16,185,129,0.12)',
            border: `1.5px solid ${nodeColor}`,
            boxShadow: broken ? '0 0 10px rgba(239,68,68,0.35)' : undefined,
          }}
        >
          {link.seq}
        </span>
        {!isLast && (
          <span
            aria-hidden="true"
            style={{
              width: 2,
              flex: 1,
              minHeight: 16,
              marginTop: 2,
              marginBottom: 2,
              background: connectorBroken
                ? `repeating-linear-gradient(180deg, ${connectorColor} 0 4px, transparent 4px 8px)`
                : connectorColor,
              opacity: connectorBroken ? 1 : 0.45,
            }}
          />
        )}
      </div>

      {/* 右侧内容 */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          marginBottom: 8,
          padding: '9px 11px',
          borderRadius: 'var(--radius-md)',
          background: broken ? 'rgba(239,68,68,0.07)' : 'rgba(59,130,246,0.04)',
          border: `1px solid ${broken ? 'rgba(239,68,68,0.30)' : 'var(--border-subtle)'}`,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 7 }}>
          <span className="truncate-cell" style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-primary)', maxWidth: 220 }} title={link.action_type}>
            {link.action_type}
          </span>
          {link.agent && (
            <span className="badge badge-neutral" title={link.agent}>{link.agent}</span>
          )}
          {link.decision && <span className="badge badge-info">{link.decision}</span>}
          {tampered && <span className="badge badge-danger badge-pulse">篡改点</span>}
          <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 5, flexWrap: 'wrap' }}>
            <CheckChip ok={link.hash_ok} label="内容哈希" />
            <CheckChip ok={link.link_ok} label="前驱链接" />
          </span>
        </div>

        <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
          <span>prev</span>
          <HashText value={link.prev_hash} color={link.link_ok ? 'var(--text-secondary)' : 'var(--accent-red)'} />
          <span aria-hidden="true">→</span>
          <span>current</span>
          <HashText value={link.current_hash} color={link.hash_ok ? 'var(--accent-cyan)' : 'var(--accent-red)'} />
          {!link.hash_ok && (
            <>
              <span aria-hidden="true">·</span>
              <span>重算</span>
              <HashText value={link.recomputed_hash} color="var(--accent-yellow)" />
            </>
          )}
        </div>

        <p
          style={{
            marginTop: 5,
            fontSize: 'var(--font-size-xs)',
            lineHeight: 1.65,
            color: broken ? 'var(--accent-red)' : 'var(--text-muted)',
          }}
        >
          {link.reason}
        </p>
      </div>
    </li>
  );
}

function ChainView({ report, tamperedSeq }: { report: AuditChainReport; tamperedSeq?: number }) {
  if (!report.links?.length) {
    return <StateBlock kind="empty" title="该链没有可展示的环" desc="后端未返回任何审计环。" compact />;
  }
  return (
    <div>
      <ol style={{ margin: 0, padding: 0, listStyle: 'none' }}>
        {report.links.map((link, index) => (
          <ChainLinkRow
            key={link.seq}
            link={link}
            next={report.links[index + 1]}
            isLast={index === report.links.length - 1}
            tamperedSeq={tamperedSeq}
          />
        ))}
      </ol>

      {/* 根哈希与根签名 */}
      <div
        className="surface-inset"
        style={{ marginTop: 6, padding: 10, borderRadius: 'var(--radius-md)', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}
      >
        <span className="field-label">根哈希</span>
        <HashText value={report.root_hash} head={20} color="var(--text-secondary)" />
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <CheckChip ok={report.chain_valid} label={report.chain_valid ? 'SHA-256 链校验通过' : 'SHA-256 链校验失败'} />
          {report.signature?.enabled ? (
            <CheckChip ok={report.signature.verified} label={report.signature.verified ? 'Ed25519 验签通过' : 'Ed25519 验签失败'} />
          ) : (
            <span className="badge badge-warning">未启用根签名</span>
          )}
        </span>
        {report.signature?.note && (
          <p style={{ width: '100%', fontSize: 'var(--font-size-xs)', lineHeight: 1.65, color: 'var(--text-muted)' }}>
            {report.signature.note}
          </p>
        )}
      </div>
    </div>
  );
}

// ── 场景三聚光灯：哈希全过 vs 签名失败 ──

function RechainSpotlight({ scenario, baselineRoot }: { scenario: TamperScenario; baselineRoot: string }) {
  const hashPassed = scenario.hash_only_check_passed ?? scenario.result.chain_valid;
  const sigOk = scenario.result.signature?.verified ?? false;
  const sigEnabled = scenario.result.signature?.enabled ?? false;

  return (
    <div
      className="surface-card"
      style={{
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        background: 'rgba(139,92,246,0.06)',
        borderColor: 'rgba(139,92,246,0.28)',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <h4 className="section-title" style={{ color: 'var(--accent-purple)' }}>
          最有说服力的一幕：攻击者伪造出「自洽」的链
        </h4>
        <span className="badge badge-purple">场景三</span>
      </div>
      <p style={{ fontSize: 'var(--font-size-sm)', lineHeight: 1.75, color: 'var(--text-secondary)' }}>
        {scenario.attacker_capability}
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
        {/* 左：哈希校验全过 */}
        <div
          style={{
            padding: 13,
            borderRadius: 'var(--radius-md)',
            background: 'rgba(16,185,129,0.08)',
            border: '1px solid rgba(16,185,129,0.30)',
          }}
        >
          <div className="field-label">纯 SHA-256 链校验</div>
          <div style={{ marginTop: 6, display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 'var(--font-size-3xl)', fontWeight: 800, color: 'var(--accent-green)', lineHeight: 1 }}>
              {hashPassed ? '✓' : '✗'}
            </span>
            <span style={{ fontSize: 'var(--font-size-base)', fontWeight: 700, color: 'var(--accent-green)' }}>
              {hashPassed ? '全部通过' : '未通过'}
            </span>
          </div>
          <p style={{ marginTop: 6, fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            <span className="num">{scenario.result.total_entries}</span> 环逐环重算内容哈希、逐环核对前驱链接，
            一个错都挑不出来 —— 如果系统只有哈希链，这次篡改就成功了。
          </p>
        </div>

        {/* 右：签名验签失败 */}
        <div
          style={{
            padding: 13,
            borderRadius: 'var(--radius-md)',
            background: 'rgba(239,68,68,0.09)',
            border: '1px solid rgba(239,68,68,0.34)',
          }}
        >
          <div className="field-label">Ed25519 根签名验签</div>
          <div style={{ marginTop: 6, display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 'var(--font-size-3xl)', fontWeight: 800, color: 'var(--accent-red)', lineHeight: 1 }}>
              {sigEnabled && !sigOk ? '✗' : sigOk ? '✓' : '—'}
            </span>
            <span style={{ fontSize: 'var(--font-size-base)', fontWeight: 700, color: 'var(--accent-red)' }}>
              {sigEnabled ? (sigOk ? '验签通过' : '验签失败') : '未启用签名'}
            </span>
          </div>
          <p style={{ marginTop: 6, fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            根哈希已改变，用原始签名验签必然失败 —— 攻击者<strong style={{ color: 'var(--accent-red)' }}>没有私钥</strong>，
            无法为伪造的链重新签名。
          </p>
        </div>
      </div>

      <div className="surface-inset" style={{ padding: 10, borderRadius: 'var(--radius-md)', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <span className="field-label">根哈希变化</span>
        <HashText value={baselineRoot} head={16} color="var(--text-secondary)" />
        <span aria-hidden="true" style={{ color: 'var(--accent-red)' }}>→</span>
        <HashText value={scenario.result.root_hash} head={16} color="var(--accent-red)" />
        {scenario.root_hash_changed && <span className="badge badge-danger">根哈希已变化</span>}
      </div>

      <p style={{ fontSize: 'var(--font-size-sm)', lineHeight: 1.75, color: 'var(--text-primary)', fontWeight: 500 }}>
        {scenario.conclusion}
      </p>
    </div>
  );
}

// ── 主面板 ──

export default function TamperCheckPanel({ incidentId }: Props) {
  const [status, setStatus] = useState<AuditDemoStatus | null>(null);
  const [candidates, setCandidates] = useState<AuditDemoCandidate[]>([]);
  const [metaLoading, setMetaLoading] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);

  const [target, setTarget] = useState<string>(String(incidentId));
  const [field, setField] = useState<string>('decision');

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [report, setReport] = useState<TamperCheckResponse | null>(null);
  const [view, setView] = useState<string>('baseline');

  const loadMeta = useCallback(async () => {
    setMetaLoading(true);
    setMetaError(null);
    try {
      const [statusData, candidateData] = await Promise.all([
        fetchAuditDemoStatus(),
        fetchAuditDemoCandidates(),
      ]);
      setStatus(statusData);
      setCandidates(candidateData.candidates ?? []);
      // 当前事件若在候选里就默认选它，否则交给后端自动挑审计环最多的事件
      const hit = (candidateData.candidates ?? []).some((c) => c.id === incidentId);
      setTarget(hit ? String(incidentId) : AUTO);
    } catch (err) {
      setMetaError(describeAuditDemoError(err));
    } finally {
      setMetaLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const result = await runTamperCheck({
        incident_id: target === AUTO ? null : Number(target),
        tamper_field: field,
        allow_synthetic: true,
      });
      setReport(result);
      setView('baseline');
      if (result.summary?.all_detected) {
        toast.success(
          '篡改检测演示完成',
          `${result.summary.scenarios_detected}/${result.summary.scenarios_total} 种攻击场景全部被检出`,
        );
      } else {
        toast.warning('篡改检测演示完成', result.summary?.headline || '部分场景未被检出');
      }
    } catch (err) {
      const message = describeAuditDemoError(err);
      setRunError(message);
      toast.error('篡改检测演示失败', message);
    } finally {
      setRunning(false);
    }
  }, [field, target]);

  const scenarios = report?.scenarios ?? [];
  const rechain = useMemo(() => scenarios.find((s) => s.id === 'full_rechain'), [scenarios]);
  const activeScenario = useMemo(
    () => (view === 'baseline' ? null : scenarios.find((s) => s.id === view) ?? null),
    [scenarios, view],
  );
  const activeReport: AuditChainReport | null = activeScenario ? activeScenario.result : report?.baseline ?? null;

  if (metaLoading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton className="skeleton-title" width={180} height={14} />
          <Skeleton width={130} height={26} radius={8} />
        </div>
        <Skeleton height={64} radius={10} />
        <SkeletonList rows={4} />
      </div>
    );
  }

  if (metaError) {
    return (
      <div className="surface-card">
        <StateBlock kind="error" title="篡改检测演示不可用" desc={metaError} onRetry={() => void loadMeta()} />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* ── 头部 + 签名状态 ── */}
      <div className="surface-card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
              <h3 className="section-title">审计链篡改检测演示</h3>
              <span className="badge badge-success" title="篡改只发生在内存副本（deepcopy）上，数据库全程只读">
                内存副本演示 · 不改数据库
              </span>
            </div>
            <p style={{ marginTop: 4, fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-muted)' }}>
              三种攻击场景逐环对比：只改内容 / 改内容并重算本环哈希 / 重写整条下游链。
            </p>
          </div>
          <span
            className="num"
            style={{
              flexShrink: 0,
              padding: '4px 10px',
              borderRadius: 999,
              background: 'rgba(16,185,129,0.12)',
              border: '1px solid rgba(16,185,129,0.30)',
              color: 'var(--accent-green)',
              fontSize: 'var(--font-size-xs)',
              fontWeight: 700,
            }}
          >
            database_mutated: {String(report?.database_mutated ?? false)}
          </span>
        </div>

        {/* 签名状态 */}
        <div
          className="surface-inset"
          style={{ padding: 11, borderRadius: 'var(--radius-md)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}
        >
          <div>
            <div className="field-label">签名能力</div>
            <div style={{ marginTop: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className={`dot ${status?.signing_enabled ? 'dot-success' : 'dot-warning'}`} aria-hidden="true" />
              <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
                {status?.signing_enabled ? '已启用' : '未启用'}
              </span>
            </div>
          </div>
          <div>
            <div className="field-label">签名算法</div>
            <div className="num" style={{ marginTop: 3, fontSize: 'var(--font-size-sm)', color: 'var(--accent-cyan)', fontWeight: 600 }}>
              {status?.algorithm || '—'}
            </div>
          </div>
          <div>
            <div className="field-label">哈希算法</div>
            <div className="num" style={{ marginTop: 3, fontSize: 'var(--font-size-sm)', color: 'var(--accent-cyan)', fontWeight: 600 }}>
              {status?.hash_algorithm || '—'}
            </div>
          </div>
          <div>
            <div className="field-label">密钥来源</div>
            <div className="num truncate-cell" style={{ marginTop: 3, fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }} title={status?.key_source}>
              {status?.key_source || '—'}
            </div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div className="field-label">公钥（可公开，用于第三方独立验签）</div>
            <div style={{ marginTop: 3 }}>
              <HashText value={status?.public_key} head={32} color="var(--text-secondary)" />
            </div>
          </div>
          {status?.note && (
            <p style={{ gridColumn: '1 / -1', fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-muted)' }}>
              {status.note}
            </p>
          )}
        </div>

        {/* 控制条 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 10 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 220, flex: 1 }}>
            <span className="field-label">演示对象</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)} disabled={running}>
              <option value={AUTO}>自动选取（审计环最多的事件）</option>
              {candidates.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.incident_id} · {c.title}（{c.audit_links} 环）
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 200 }}>
            <span className="field-label">篡改字段</span>
            <select value={field} onChange={(e) => setField(e.target.value)} disabled={running}>
              {(report?.tamperable_fields ?? ['decision', 'output_hash', 'input_hash', 'action_type', 'agent']).map((f) => (
                <option key={f} value={f}>
                  {tamperFieldLabel(f)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => void handleRun()} disabled={running} className="btn btn-primary btn-sm">
            {running && <span className="btn-spinner" aria-hidden="true" />}
            {running ? '演示进行中…' : '运行篡改检测演示'}
          </button>
        </div>

        {candidates.length === 0 && (
          <p style={{ fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--accent-yellow)' }}>
            库中暂无带 Agent 轨迹的事件，演示将使用**合成**审计链（结果会明确标注 synthetic）。
          </p>
        )}
      </div>

      {/* ── 运行错误 ── */}
      {runError && (
        <div className="surface-card">
          <StateBlock kind="error" title="篡改检测演示失败" desc={runError} onRetry={() => void handleRun()} />
        </div>
      )}

      {/* ── 未运行时的空态 ── */}
      {!report && !runError && (
        <div className="surface-card">
          <StateBlock
            kind="empty"
            title="尚未运行演示"
            desc="选择演示对象后点击「运行篡改检测演示」，系统会在内存副本上模拟三种攻击，并逐环展示检测结果。数据库不会被修改。"
          />
        </div>
      )}

      {report && (
        <>
          {/* 一句话结论 */}
          <div
            className="surface-card"
            style={{
              padding: 13,
              background: report.summary?.all_detected ? 'rgba(16,185,129,0.08)' : 'rgba(245,158,11,0.08)',
              borderColor: report.summary?.all_detected ? 'rgba(16,185,129,0.28)' : 'rgba(245,158,11,0.28)',
            }}
            role="status"
          >
            <p style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 'var(--font-size-base)', fontWeight: 700, color: 'var(--text-primary)' }}>
              <span className={`dot ${report.summary?.all_detected ? 'dot-success' : 'dot-warning'}`} aria-hidden="true" />
              {report.summary?.scenarios_detected}/{report.summary?.scenarios_total} 种攻击场景全部被检出
            </p>
            <p style={{ marginTop: 5, fontSize: 'var(--font-size-sm)', lineHeight: 1.75, color: 'var(--text-secondary)' }}>
              {report.summary?.headline}
            </p>
            <div style={{ marginTop: 7, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <span className={`badge ${report.data_source === 'real_incident' ? 'badge-info' : 'badge-warning'}`}>
                {report.data_source === 'real_incident' ? '真实事件轨迹' : '合成演示链'}
              </span>
              {report.incident_id && (
                <span className="num" style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
                  {report.incident_id} · {report.incident_title}
                </span>
              )}
            </div>
            <p style={{ marginTop: 5, fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-muted)' }}>
              {report.data_source_note}
            </p>
          </div>

          {/* 三场景对比 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(238px, 1fr))', gap: 10 }}>
            {scenarios.map((scenario) => {
              const on = view === scenario.id;
              const chainOk = scenario.result.chain_valid;
              const sigOk = scenario.result.signature?.verified ?? false;
              return (
                <button
                  key={scenario.id}
                  type="button"
                  onClick={() => setView(scenario.id)}
                  aria-pressed={on}
                  className="surface-card"
                  style={{
                    padding: 12,
                    textAlign: 'left',
                    cursor: 'pointer',
                    borderColor: on ? 'var(--accent-blue)' : undefined,
                    background: on ? 'rgba(59,130,246,0.08)' : undefined,
                  }}
                >
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 700, color: 'var(--text-primary)' }}>
                      {scenarioShortName(scenario.id, scenario.name)}
                    </span>
                    <span className={`badge ${scenario.detected ? 'badge-success' : 'badge-danger'}`}>
                      {scenario.detected ? '已检出' : '未检出'}
                    </span>
                  </div>
                  <div style={{ marginTop: 7, display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    <CheckChip ok={chainOk} label="哈希链" />
                    <CheckChip ok={sigOk} label="根签名" />
                  </div>
                  <div style={{ marginTop: 7, fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', lineHeight: 1.7 }}>
                    首个断裂环：
                    <span className="num" style={{ color: scenario.result.first_broken_at ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                      {scenario.result.first_broken_at ? `第 ${scenario.result.first_broken_at} 环` : '无（哈希全过）'}
                    </span>
                  </div>
                  <div style={{ marginTop: 5, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {scenario.detected_by.length > 0 ? (
                      scenario.detected_by.map((m) => (
                        <span key={m} className="badge badge-cyan" title={DETECTION_META[m]?.desc}>
                          {detectionLabel(m)}
                        </span>
                      ))
                    ) : (
                      <span className="badge badge-neutral">无检出手段</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* 场景三聚光灯 */}
          {rechain && <RechainSpotlight scenario={rechain} baselineRoot={report.baseline.root_hash} />}

          {/* 链条可视化 */}
          <div className="surface-card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
              <h4 className="section-title">逐环校验详情</h4>
              <div style={{ marginLeft: 'auto', display: 'flex', flexWrap: 'wrap', gap: 4 }} role="tablist" aria-label="选择要查看的链">
                <button
                  type="button"
                  role="tab"
                  aria-selected={view === 'baseline'}
                  onClick={() => setView('baseline')}
                  className={`btn btn-xs ${view === 'baseline' ? 'btn-primary' : 'btn-secondary'}`}
                >
                  篡改前（基线）
                </button>
                {scenarios.map((s, i) => (
                  <button
                    key={s.id}
                    type="button"
                    role="tab"
                    aria-selected={view === s.id}
                    onClick={() => setView(s.id)}
                    className={`btn btn-xs ${view === s.id ? 'btn-primary' : 'btn-secondary'}`}
                    title={s.name}
                  >
                    场景{['一', '二', '三'][i] ?? i + 1}
                  </button>
                ))}
              </div>
            </div>

            {activeScenario && (
              <div
                className="surface-inset"
                style={{ padding: 11, borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: 6 }}
              >
                <p style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {activeScenario.name}
                </p>
                <p style={{ fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-muted)' }}>
                  攻击者能力：{activeScenario.attacker_capability}
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)' }}>
                  <span className="badge badge-danger">第 {activeScenario.tamper.seq} 环</span>
                  <span className="num">{activeScenario.tamper.field}</span>
                  <span className="num truncate-cell" style={{ maxWidth: 180, color: 'var(--text-muted)' }} title={activeScenario.tamper.before}>
                    {activeScenario.tamper.before || '—'}
                  </span>
                  <span aria-hidden="true">→</span>
                  <span className="num truncate-cell" style={{ maxWidth: 220, color: 'var(--accent-red)' }} title={activeScenario.tamper.after}>
                    {activeScenario.tamper.after}
                  </span>
                  {activeScenario.tamper.recomputed_hash && <span className="badge badge-warning">重算本环哈希</span>}
                  {activeScenario.tamper.rechained_downstream && <span className="badge badge-warning">重写下游全链</span>}
                </div>
                <p style={{ fontSize: 'var(--font-size-sm)', lineHeight: 1.75, color: 'var(--text-secondary)' }}>
                  {activeScenario.conclusion}
                </p>
              </div>
            )}

            {!activeScenario && (
              <p style={{ fontSize: 'var(--font-size-sm)', lineHeight: 1.75, color: 'var(--text-secondary)' }}>
                篡改前的原始审计链：<span className="num">{report.baseline.total_entries}</span> 环全部通过前驱链接与内容哈希校验
                {report.baseline.signature?.verified ? '，且 Ed25519 根签名验签通过。' : '。'}
              </p>
            )}

            {activeReport ? (
              <ChainView report={activeReport} tamperedSeq={activeScenario?.tamper.seq} />
            ) : (
              <StateBlock kind="empty" title="暂无链数据" desc="后端未返回可展示的审计链。" compact />
            )}
          </div>

          {/* 安全边界声明 */}
          <div
            className="surface-inset"
            style={{
              padding: 11,
              borderRadius: 'var(--radius-md)',
              border: '1px solid rgba(16,185,129,0.28)',
              background: 'rgba(16,185,129,0.06)',
              display: 'flex',
              gap: 9,
            }}
          >
            <span aria-hidden="true" style={{ flexShrink: 0, color: 'var(--accent-green)', marginTop: 1 }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2l8 3.5v6c0 4.7-3.3 8.9-8 10.5-4.7-1.6-8-5.8-8-10.5v-6z" />
                <polyline points="9 12 11 14 15 10" />
              </svg>
            </span>
            <div style={{ minWidth: 0 }}>
              <p className="num" style={{ fontSize: 'var(--font-size-sm)', fontWeight: 700, color: 'var(--accent-green)' }}>
                database_mutated: {String(report.database_mutated)}
              </p>
              <p style={{ marginTop: 3, fontSize: 'var(--font-size-xs)', lineHeight: 1.7, color: 'var(--text-secondary)' }}>
                {report.safety_note}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
