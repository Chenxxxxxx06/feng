import { useEffect, useState } from 'react';
import { getEconomicImpact } from '../../../services/incidentService';

interface Props {
  incidentId: number;
  data: any;
  refresh: number;  // triggers re-render for local timer
}

export default function EconomicImpactPanel({ incidentId, data, refresh }: Props) {
  const [localSeconds, setLocalSeconds] = useState(0);

  // Local per-second timer
  useEffect(() => {
    const t = setInterval(() => setLocalSeconds(s => s + 1), 1000);
    return () => clearInterval(t);
  }, []);

  if (!data) {
    return (
      <div className="p-8 text-center text-slate-500 bg-slate-900/30 rounded-lg border border-slate-700/30">
        <div className="text-3xl mb-2">💰</div>
        <div>加载经济数据中...</div>
      </div>
    );
  }

  const elapsed = data.elapsed_hours || 0;
  const hours = Math.floor(elapsed);
  const minutes = Math.floor((elapsed - hours) * 60);
  const secs = Math.floor(((elapsed - hours) * 60 - minutes) * 60);
  const elapsedStr = `${hours}h ${String(minutes).padStart(2, '0')}m ${String(secs).padStart(2, '0')}s`;

  const loss = data.cumulative_loss_cny || 0;
  const hourlyRate = data.hourly_loss_rate_cny || 0;

  return (
    <div className="space-y-4">
      {/* Live timer + cumulative loss */}
      <div className="grid grid-cols-2 gap-4">
        <div className="p-5 bg-slate-800/40 rounded-lg border border-slate-700/30 text-center">
          <div className="text-xs text-slate-500 mb-1">⏱ 事件已持续</div>
          <div className="text-2xl font-mono font-bold text-white tabular-nums">
            {elapsedStr}
          </div>
          <div className="text-xs text-slate-500 mt-1">每秒实时更新</div>
        </div>
        <div className="p-5 bg-red-950/20 rounded-lg border border-red-800/30 text-center">
          <div className="text-xs text-red-400 mb-1">💰 累计发电损失</div>
          <div className="text-2xl font-mono font-bold text-red-300 tabular-nums">
            ¥{loss.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
          <div className="text-xs text-red-400/70 mt-1">¥{hourlyRate.toFixed(0)}/小时</div>
        </div>
      </div>

      {/* Details */}
      <div className="grid grid-cols-3 gap-4">
        <StatTile label="功率缺口" value={`${(data.power_gap_kw || 0).toFixed(0)} kW`} sub={data.power_source?.replace(/_/g, ' ') || ''} />
        <StatTile
          label="失效概率"
          value={data.failure_probability != null ? `${(data.failure_probability * 100).toFixed(1)}%` : '无数据'}
          sub={data.failure_probability_source || ''}
        />
        <StatTile
          label="预计总损失"
          value={data.estimated_total_loss_cny != null ? `¥${data.estimated_total_loss_cny.toLocaleString()}` : '—'}
          sub={data.estimated_resolution_hours ? `预计${data.estimated_resolution_hours}h解决` : ''}
        />
      </div>

      {/* Risk exposure */}
      {data.risk_exposure_cny != null && (
        <div className="p-4 bg-orange-950/20 rounded-lg border border-orange-700/30">
          <div className="text-sm text-orange-300">
            🔴 风险暴露: <span className="font-bold">¥{data.risk_exposure_cny.toLocaleString()}</span>
          </div>
          <div className="text-xs text-orange-400/70 mt-1">
            风险暴露 = 预计总损失 × 失效概率
          </div>
        </div>
      )}

      {/* Assumptions */}
      {data.assumptions?.length > 0 && (
        <div className="p-3 bg-slate-800/30 rounded border border-slate-700/30">
          <div className="text-xs font-semibold text-slate-400 mb-1">计算假设</div>
          {data.assumptions.map((a: string, i: number) => (
            <div key={i} className="text-xs text-slate-500">• {a}</div>
          ))}
        </div>
      )}

      {/* Data quality */}
      <div className="text-xs text-slate-600">
        数据质量: <span className={
          data.data_quality === 'complete' ? 'text-emerald-400' :
          data.data_quality === 'partial' ? 'text-yellow-400' : 'text-red-400'
        }>{data.data_quality}</span>
        {data.data_quality !== 'complete' && (
          <span className="ml-2">⚠ 部分数据缺失，结果为估算值</span>
        )}
      </div>
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="p-4 bg-slate-800/40 rounded-lg border border-slate-700/30">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-white mt-1 tabular-nums">{value}</div>
      <div className="text-xs text-slate-600 mt-1 truncate">{sub}</div>
    </div>
  );
}
