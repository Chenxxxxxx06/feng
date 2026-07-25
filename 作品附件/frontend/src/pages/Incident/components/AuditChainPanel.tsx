import { useEffect, useState } from 'react';
import { getAuditChain, verifyAuditChain } from '../../../services/incidentService';

interface Props {
  incidentId: number;
}

export default function AuditChainPanel({ incidentId }: Props) {
  const [chain, setChain] = useState<any>(null);
  const [verification, setVerification] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true); setError(null);
    getAuditChain(incidentId)
      .then(setChain)
      .catch(e => setError(e?.response?.data?.detail || '加载失败'))
      .finally(() => setLoading(false));
  }, [incidentId]);

  const handleVerify = async () => {
    setVerifying(true); setError(null);
    try {
      const result = await verifyAuditChain(incidentId);
      setVerification(result);
    } catch (e: any) {
      setError(e?.response?.data?.detail || '验证失败');
    } finally { setVerifying(false); }
  };

  if (loading) return <div className="p-8 text-center text-slate-500">加载审计链...</div>;
  if (error) return <div className="p-4 text-red-400 bg-red-950/20 rounded-lg">⚠ {error}</div>;
  if (!chain) return <div className="p-8 text-center text-slate-500">暂无审计链数据</div>;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg">🔗</span>
            <span className="font-semibold text-white">审计链</span>
            {verification?.chain_valid && (
              <span className="text-xs px-2 py-0.5 bg-emerald-600 text-white rounded">✓ 可检测篡改</span>
            )}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {chain.total_entries} 个区块 · 根哈希: <code className="text-slate-400 text-xs">{chain.root_hash}</code>
          </div>
        </div>
        <button onClick={handleVerify} disabled={verifying}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded transition-colors">
          {verifying ? '验证中...' : '🔒 验证完整链'}
        </button>
      </div>

      {/* Verification result */}
      {verification && (
        <div className={`p-4 rounded-lg border ${
          verification.chain_valid
            ? 'bg-emerald-950/20 border-emerald-700/30'
            : 'bg-red-950/20 border-red-700/30'
        }`}>
          <div className="font-semibold text-white">
            {verification.chain_valid ? '✅ 链完整性验证通过' : '❌ 链完整性验证失败'}
          </div>
          <div className="text-sm text-slate-400 mt-1">
            总区块: {verification.total_entries} ·
            签名验证: {verification.key_available ? (verification.signature_valid ? '✅' : '❌') : '⚠ 密钥未配置'} ·
            根哈希: <code className="text-xs">{verification.root_hash}</code>
          </div>
          {verification.tampered_entries?.length > 0 && (
            <div className="text-sm text-red-400 mt-2">
              ⚠ 检测到篡改: 区块 #{verification.tampered_entries.join(', #')}
              {verification.first_broken_at && ` (首次断裂: #${verification.first_broken_at})`}
            </div>
          )}
          {verification.error_message && (
            <div className="text-xs text-slate-500 mt-2">{verification.error_message}</div>
          )}
        </div>
      )}

      {/* Entry list */}
      <div className="space-y-1 max-h-96 overflow-y-auto">
        {chain.entries?.map((entry: any) => (
          <div key={entry.seq} className="flex items-center gap-3 p-2 bg-slate-800/30 rounded hover:bg-slate-800/50 transition-colors text-xs">
            <span className="text-slate-600 w-8 text-right tabular-nums">#{entry.seq}</span>
            <span className="text-slate-300 w-32 truncate">{entry.action_type}</span>
            <span className="text-slate-500 w-16 truncate">{entry.agent}</span>
            {entry.decision && (
              <span className={`px-1.5 py-0.5 rounded text-xs ${
                entry.decision === 'denied' ? 'bg-red-600/30 text-red-300' :
                entry.decision === 'allowed' ? 'bg-emerald-600/30 text-emerald-300' :
                'bg-slate-600/30 text-slate-300'
              }`}>
                {entry.decision}
              </span>
            )}
            <code className="text-slate-600 text-xs flex-1 text-right truncate" title={entry.current_hash}>
              {entry.current_hash?.substring(0, 16)}...
            </code>
          </div>
        ))}
      </div>

      {chain.entries?.length === 0 && (
        <div className="p-8 text-center text-slate-500">
          <div className="text-3xl mb-2">📭</div>
          <div>暂无可审计的Agent操作记录</div>
          <div className="text-xs text-slate-600 mt-1">启动自主调查后自动生成审计链</div>
        </div>
      )}

      {/* Signature status */}
      <div className="text-xs text-slate-600 p-3 bg-slate-800/20 rounded border border-slate-700/30">
        <span className="font-semibold">关于审计链</span>:
        SHA-256哈希链提供<strong>可检测篡改</strong>证据。
        {chain.signed ? ' 根哈希已使用Ed25519签名。' : ' 签名密钥未配置，仅验证哈希链连续性。'}
        这不是区块链，不提供分布式共识。
      </div>
    </div>
  );
}
