import { useEffect, useState } from 'react';
import { getAuditChain, verifyAuditChain } from '../../../services/incidentService';
import StateBlock from '../../../components/Common/StateBlock';
import { Skeleton, SkeletonList } from '../../../components/Common/Skeleton';
import { toast, describeError } from '../../../components/Common/Toast';

interface Props {
  incidentId: number;
}

const DECISION_LABEL: Record<string, string> = {
  allowed: '允许',
  denied: '拒绝',
  requires_approval: '需审批',
};

export default function AuditChainPanel({ incidentId }: Props) {
  const [chain, setChain] = useState<any>(null);
  const [verification, setVerification] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true); setError(null);
    getAuditChain(incidentId)
      .then(setChain)
      .catch(e => setError(describeError(e, '审计链加载失败')))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setLoading(true); setError(null);
    getAuditChain(incidentId)
      .then(setChain)
      .catch(e => setError(describeError(e, '审计链加载失败')))
      .finally(() => setLoading(false));
  }, [incidentId]);

  const handleVerify = async () => {
    setVerifying(true); setError(null);
    try {
      const result = await verifyAuditChain(incidentId);
      setVerification(result);
      if (result?.chain_valid) toast.success('链完整性验证通过', `共校验 ${result.total_entries} 个区块`);
      else toast.error('链完整性验证失败', '检测到哈希链断裂，请查看下方详情');
    } catch (e: any) {
      const message = describeError(e, '审计链验证失败');
      setError(message);
      toast.error('审计链验证失败', message);
    } finally { setVerifying(false); }
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton className="skeleton-title" width={140} height={14} />
          <Skeleton width={110} height={26} radius={8} />
        </div>
        <SkeletonList rows={6} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="surface-card">
        <StateBlock kind="error" title="审计链加载失败" desc={error} onRetry={load} />
      </div>
    );
  }
  if (!chain) {
    return (
      <div className="surface-card">
        <StateBlock kind="empty" title="暂无审计链数据" desc="事件尚未产生受策略引擎管控的 Agent 操作。" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="section-title">审计链</h3>
            {verification?.chain_valid && <span className="badge badge-success">可检测篡改</span>}
          </div>
          <p className="mt-1 text-[10px] text-text-muted">
            <span className="num">{chain.total_entries}</span> 个区块 · 根哈希
            <code className="num ml-1 truncate-cell inline-block max-w-[280px] align-bottom" title={chain.root_hash}>{chain.root_hash}</code>
          </p>
        </div>
        <button onClick={handleVerify} disabled={verifying} className="btn btn-primary btn-sm">
          {verifying && <span className="btn-spinner" aria-hidden="true" />}
          {verifying ? '验证中…' : '验证完整链'}
        </button>
      </div>

      {/* Verification result */}
      {verification && (
        <div
          className="surface-card p-4"
          style={verification.chain_valid
            ? { background: 'rgba(16,185,129,0.08)', borderColor: 'rgba(16,185,129,0.28)' }
            : { background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.30)' }}
          role="status"
        >
          <p className="flex items-center gap-2 section-title">
            <span className={`dot ${verification.chain_valid ? 'dot-success' : 'dot-danger'}`} aria-hidden="true" />
            {verification.chain_valid ? '链完整性验证通过' : '链完整性验证失败'}
          </p>
          <p className="mt-1.5 text-[11px] text-text-secondary">
            总区块 <span className="num">{verification.total_entries}</span> · 签名验证{' '}
            {verification.key_available ? (verification.signature_valid ? '通过' : '未通过') : '密钥未配置'} · 根哈希{' '}
            <code className="num" title={verification.root_hash}>{String(verification.root_hash || '').slice(0, 24)}…</code>
          </p>
          {verification.tampered_entries?.length > 0 && (
            <p className="mt-2 text-[11px]" style={{ color: 'var(--accent-red)' }}>
              检测到篡改：区块 #{verification.tampered_entries.join(', #')}
              {verification.first_broken_at && `（首次断裂：#${verification.first_broken_at}）`}
            </p>
          )}
          {verification.error_message && (
            <p className="mt-2 text-[10px] text-text-muted">{verification.error_message}</p>
          )}
        </div>
      )}

      {/* Entry list */}
      {chain.entries?.length > 0 && (
        <div className="table-scroll max-h-96 space-y-px">
          {chain.entries.map((entry: any) => (
            <div
              key={entry.seq}
              className="flex items-center gap-3 rounded-md px-2.5 py-1.5 text-[10px] transition-colors hover:bg-bg-hover"
              style={{ background: 'rgba(59,130,246,0.03)' }}
            >
              <span className="num w-8 flex-shrink-0 text-right text-text-muted">#{entry.seq}</span>
              <span className="w-32 flex-shrink-0 truncate text-text-primary" title={entry.action_type}>{entry.action_type}</span>
              <span className="w-16 flex-shrink-0 truncate text-text-muted" title={entry.agent}>{entry.agent}</span>
              {entry.decision && (
                <span className={`badge ${entry.decision === 'denied' ? 'badge-danger' : entry.decision === 'allowed' ? 'badge-success' : 'badge-warning'}`}>
                  {DECISION_LABEL[entry.decision] || entry.decision}
                </span>
              )}
              <code className="num flex-1 truncate text-right text-text-muted" title={entry.current_hash}>
                {entry.current_hash?.substring(0, 16)}…
              </code>
            </div>
          ))}
        </div>
      )}

      {chain.entries?.length === 0 && (
        <div className="surface-card">
          <StateBlock
            kind="empty"
            title="暂无可审计的 Agent 操作记录"
            desc="启动「自主调查」后，每一次受管控的动作都会写入审计链。"
          />
        </div>
      )}

      {/* Signature status */}
      <p className="surface-inset p-3 text-[10px] leading-relaxed text-text-muted">
        <span className="font-semibold text-text-secondary">关于审计链：</span>
        SHA-256 哈希链提供<strong className="text-text-secondary">可检测篡改</strong>的证据。
        {chain.signed ? ' 根哈希已使用 Ed25519 签名。' : ' 签名密钥未配置，当前仅验证哈希链连续性。'}
        本机制不是区块链，不提供分布式共识。
      </p>
    </div>
  );
}
