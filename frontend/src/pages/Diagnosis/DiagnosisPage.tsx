import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { Fault, FaultDetail } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

export default function DiagnosisPage() {
  const [faults, setFaults] = useState<Fault[]>([]);
  const [selected, setSelected] = useState<FaultDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/diagnosis/faults').then(({ data }) => { setFaults(data); setLoading(false); });
  }, []);

  const viewDetail = async (id: number) => {
    const { data } = await api.get(`/diagnosis/faults/${id}`);
    setSelected(data);
  };

  // Compute summary stats
  const openCount = faults.filter(f => f.status === 'open').length;
  const weekAgo = new Date(Date.now() - 7 * 86400000);
  const weekNew = faults.filter(f => new Date(f.detected_at) > weekAgo).length;
  const avgConfidence = faults.length > 0
    ? (faults.reduce((sum, f) => sum + f.confidence, 0) / faults.length * 100).toFixed(1) + '%'
    : '--';
  const closedCount = faults.filter(f => f.status === 'closed').length;
  const healthScore = faults.length > 0
    ? Math.min(100, Math.round((closedCount / faults.length) * 60 + (faults.length - weekNew) / Math.max(faults.length, 1) * 40))
    : 100;

  const cards = [
    { label: '总故障数', value: String(faults.length), unit: '条', color: 'text-accent-blue', icon: '📋' },
    { label: '待处理', value: String(openCount), unit: '条', color: openCount > 0 ? 'text-accent-red' : 'text-accent-green', icon: '🔴' },
    { label: '本周新增', value: String(weekNew), unit: '条', color: weekNew > 0 ? 'text-accent-yellow' : 'text-text-secondary', icon: '📈' },
    { label: '平均置信度', value: avgConfidence, unit: '', color: 'text-accent-cyan', icon: '🎯' },
    { label: '诊断健康度', value: String(healthScore), unit: '分', color: healthScore >= 80 ? 'text-accent-green' : healthScore >= 60 ? 'text-accent-yellow' : 'text-accent-red', icon: '💚' },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header + Summary Cards */}
      <div className="flex-shrink-0 border-b border-border-default bg-bg-secondary px-6 py-4">
        <h2 className="text-sm font-semibold mb-3">故障诊断中心</h2>
        <div className="grid grid-cols-5 gap-3">
          {cards.map((c) => (
            <div key={c.label} className="bg-bg-card border border-border-default rounded-lg px-3 py-2.5 flex items-center gap-3">
              <span className="text-xl">{c.icon}</span>
              <div>
                <p className="text-[10px] text-text-muted">{c.label}</p>
                <p className={`text-lg font-mono font-bold ${c.color}`}>{c.value}<span className="text-[10px] font-normal text-text-muted ml-0.5">{c.unit}</span></p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main Content: Fault List + Root Cause */}
      <div className="flex-1 flex overflow-hidden">
        {/* Fault List */}
        <div className="flex-1 overflow-auto p-6">
          {loading ? (
            <p className="text-text-muted text-sm">加载中...</p>
          ) : (
            <div className="space-y-2">
              {faults.map((f) => (
                <div
                  key={f.id}
                  onClick={() => viewDetail(f.id)}
                  className={`bg-bg-card border rounded-lg p-3.5 cursor-pointer transition-colors ${
                    selected?.id === f.id ? 'border-accent-blue ring-1 ring-accent-blue/30' : 'border-border-default hover:border-border-active'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={`w-2 h-2 rounded-full ${f.status === 'open' ? 'bg-accent-red' : 'bg-accent-green'}`} />
                      <span className="font-medium text-sm">{f.fault_type}</span>
                      <span className="text-xs text-text-muted">风机 #{f.turbine_id} {f.turbine_name || ''}</span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-text-muted">
                      <span>置信度: <span className="text-accent-yellow font-mono">{(f.confidence * 100).toFixed(0)}%</span></span>
                      <span>{new Date(f.detected_at).toLocaleDateString('zh-CN')}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] ${f.status === 'open' ? 'bg-accent-red/20 text-accent-red' : 'bg-accent-green/20 text-accent-green'}`}>
                        {f.status === 'open' ? '待处理' : '已关闭'}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
              {faults.length === 0 && <p className="text-text-muted text-sm">暂无故障记录</p>}
            </div>
          )}

          {/* Root Cause */}
          {selected && (
            <div className="mt-4 bg-bg-card border border-border-default rounded-lg p-4">
              <h3 className="text-sm font-medium mb-4">
                故障根因分析 — {selected.fault_type}
                <span className="ml-2 text-xs text-text-muted">风机 #{selected.turbine_id}</span>
              </h3>
              <div className="space-y-1.5">
                {selected.signals?.map((sig) => (
                  <div key={sig.id} className="flex items-center gap-3 bg-bg-hover rounded px-3 py-2 text-xs">
                    <span className={`w-14 px-1.5 py-0.5 rounded text-center text-[10px] font-mono ${
                      sig.priority === 'high' ? 'bg-accent-red/20 text-accent-red' :
                      sig.priority === 'medium' ? 'bg-accent-yellow/20 text-accent-yellow' :
                      'bg-text-muted/20 text-text-muted'
                    }`}>
                      {sig.priority === 'high' ? '高' : sig.priority === 'medium' ? '中' : '低'}
                    </span>
                    <span className="flex-1 text-text-primary">{sig.sensor_name}</span>
                    {/* Progress bar for contribution */}
                    <div className="w-32 bg-bg-secondary rounded-full h-1.5 mr-2">
                      <div className="h-full rounded-full bg-accent-blue" style={{ width: `${(sig.contribution_score * 100).toFixed(0)}%` }} />
                    </div>
                    <span className="text-text-muted font-mono w-14 text-right">{(sig.contribution_score * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
              {selected.details && (
                <div className="mt-3 p-3 bg-accent-yellow/5 border border-accent-yellow/20 rounded text-xs">
                  <p className="text-accent-yellow font-medium mb-1">💡 排查建议：</p>
                  <p className="text-text-secondary">{JSON.stringify(selected.details)}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <CopilotFAB />
    </div>
  );
}
