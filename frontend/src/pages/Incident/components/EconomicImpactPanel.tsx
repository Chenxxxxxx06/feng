import { Skeleton } from '../../../components/Common/Skeleton';

interface Props {
  incidentId: number;
  data: any;
  refresh: number;  // bumped by parent to re-fetch economic data
}

const QUALITY_LABEL: Record<string, string> = {
  complete: '完整',
  partial: '部分缺失',
  missing: '缺失',
};

export default function EconomicImpactPanel({ incidentId, data, refresh }: Props) {
  if (!data) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="surface-card space-y-2 p-5 text-center">
              <Skeleton className="skeleton-text mx-auto" width="40%" />
              <Skeleton className="mx-auto" height={26} width="62%" radius={6} />
              <Skeleton className="skeleton-text mx-auto" width="34%" height={8} />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} height={78} radius={12} />)}
        </div>
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
  const qualityColor = data.data_quality === 'complete'
    ? 'var(--accent-green)'
    : data.data_quality === 'partial' ? 'var(--accent-yellow)' : 'var(--accent-red)';

  return (
    <div className="space-y-3">
      {/* Live timer + cumulative loss */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="surface-card p-5 text-center">
          <div className="field-label mb-1.5">事件已持续</div>
          <div className="num text-[24px] font-bold leading-none text-text-primary">{elapsedStr}</div>
          <div className="field-label mt-1.5">每 30 秒自动刷新</div>
        </div>
        <div className="surface-card p-5 text-center" style={{ background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.28)' }}>
          <div className="field-label mb-1.5" style={{ color: 'var(--accent-red)' }}>累计发电损失</div>
          <div className="num text-[24px] font-bold leading-none" style={{ color: 'var(--accent-red)' }}>
            ¥{loss.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
          <div className="num field-label mt-1.5" style={{ color: 'var(--accent-red)' }}>¥{hourlyRate.toFixed(0)} / 小时</div>
        </div>
      </div>

      {/* Details */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="功率缺口" value={`${(data.power_gap_kw || 0).toFixed(0)} kW`} sub={data.power_source?.replace(/_/g, ' ') || ''} />
        <StatTile
          label="失效概率"
          value={data.failure_probability != null ? `${(data.failure_probability * 100).toFixed(1)}%` : '无数据'}
          sub={data.failure_probability_source || ''}
        />
        <StatTile
          label="预计总损失"
          value={data.estimated_total_loss_cny != null ? `¥${data.estimated_total_loss_cny.toLocaleString()}` : '—'}
          sub={data.estimated_resolution_hours ? `预计 ${data.estimated_resolution_hours} 小时解决` : ''}
        />
      </div>

      {/* Risk exposure */}
      {data.risk_exposure_cny != null && (
        <div className="surface-card p-4" style={{ background: 'rgba(249,115,22,0.08)', borderColor: 'rgba(249,115,22,0.28)' }}>
          <p className="flex items-center gap-2 text-[12px] font-semibold" style={{ color: 'var(--accent-orange)' }}>
            <span className="dot" style={{ color: 'var(--accent-orange)' }} aria-hidden="true" />
            风险暴露：<span className="num">¥{data.risk_exposure_cny.toLocaleString()}</span>
          </p>
          <p className="mt-1 text-[10px]" style={{ color: 'var(--accent-orange)', opacity: 0.8 }}>
            风险暴露 = 预计总损失 × 失效概率
          </p>
        </div>
      )}

      {/* Assumptions */}
      {data.assumptions?.length > 0 && (
        <div className="surface-inset p-3">
          <p className="field-label mb-1">计算假设</p>
          {data.assumptions.map((a: string, i: number) => (
            <p key={i} className="text-[10px] leading-relaxed text-text-muted">· {a}</p>
          ))}
        </div>
      )}

      {/* Data quality */}
      <p className="text-[10px] text-text-muted">
        数据质量：<span style={{ color: qualityColor }}>{QUALITY_LABEL[data.data_quality] || data.data_quality}</span>
        {data.data_quality !== 'complete' && <span className="ml-2">部分数据缺失，以上结果为估算值。</span>}
      </p>
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="surface-card p-3.5" title={sub ? `${label}：${value}（${sub}）` : `${label}：${value}`}>
      <div className="field-label">{label}</div>
      <div className="num mt-1 text-[16px] font-semibold text-text-primary">{value}</div>
      {sub && <div className="truncate-cell mt-1 text-[10px] text-text-muted">{sub}</div>}
    </div>
  );
}
