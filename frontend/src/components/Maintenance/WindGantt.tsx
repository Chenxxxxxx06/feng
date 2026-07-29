import { useMemo } from 'react';
import type { GanttResponse } from '../../services/productionService';

/**
 * 风窗甘特图：横轴时间，背景是风功率预测热力带（风大时段深色），
 * 工单色块叠在低风谷上。用 CSS 绝对定位实现，避免 ECharts custom series 的坐标换算风险。
 */

const ROW_HEIGHT = 36;
const GUTTER = 112;

const PRIORITY_COLOR: Record<string, string> = {
  urgent: '#EF4444',
  high: '#F97316',
  medium: '#3B82F6',
  low: '#10B981',
};

/** 风大 → 深蓝；低风窗口 → 浅绿（黄金检修时段）。 */
function windCellColor(cf: number, isLow: boolean): string {
  const a = Math.min(1, Math.max(0, cf));
  if (isLow) return `rgba(16,185,129,${(0.08 + a * 0.12).toFixed(3)})`;
  return `rgba(59,130,246,${(0.05 + a * 0.55).toFixed(3)})`;
}

function toMs(iso?: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : t;
}

function fmtDayLabel(ms: number): string {
  const d = new Date(ms);
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'short' });
}

function fmtHm(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function WindGantt({ data }: { data: GanttResponse | null }) {
  const model = useMemo(() => {
    if (!data) return null;
    const start = toMs(data.period_start);
    const end = toMs(data.period_end);
    if (start == null || end == null || end <= start) return null;
    const span = end - start;
    const pct = (ms: number) => ((ms - start) / span) * 100;

    const cells = (data.wind_band || [])
      .map((c) => {
        const t = toMs(c.time);
        if (t == null) return null;
        return {
          left: pct(t),
          width: (3600_000 / span) * 100,
          color: windCellColor(c.capacity_factor, c.is_low_wind),
          isLow: c.is_low_wind,
          key: c.time,
        };
      })
      .filter((c): c is NonNullable<typeof c> => c !== null);

    const bars = (data.bars || [])
      .map((b) => {
        const bs = toMs(b.start);
        const be = toMs(b.end);
        if (bs == null || be == null) return null;
        const left = Math.max(0, pct(bs));
        const right = Math.min(100, pct(be));
        return { ...b, left, width: Math.max(0.6, right - left) };
      })
      .filter((b): b is NonNullable<typeof b> => b !== null);

    // 泳道：按后端给的 row 分组，行标题取该行第一个工单的机组名
    const rowCount = bars.length > 0 ? Math.max(...bars.map((b) => b.row)) + 1 : 0;
    const rowLabels: string[] = [];
    for (let r = 0; r < rowCount; r += 1) {
      const first = bars.find((b) => b.row === r);
      rowLabels.push(first ? (first.turbine_name || `#${first.turbine_id}`) : `泳道${r + 1}`);
    }

    // 日分隔线
    const days: { left: number; label: string }[] = [];
    const cursor = new Date(start);
    cursor.setMinutes(0, 0, 0);
    cursor.setHours(0);
    let guard = 0;
    while (cursor.getTime() <= end && guard < 40) {
      const t = cursor.getTime();
      if (t >= start) days.push({ left: pct(t), label: fmtDayLabel(t) });
      cursor.setDate(cursor.getDate() + 1);
      guard += 1;
    }

    const windows = (data.low_wind_windows || [])
      .map((w) => {
        const ws = toMs(w.start);
        const we = toMs(w.end);
        if (ws == null || we == null) return null;
        const left = Math.max(0, pct(ws));
        const right = Math.min(100, pct(we));
        return { ...w, left, width: Math.max(0.4, right - left) };
      })
      .filter((w): w is NonNullable<typeof w> => w !== null);

    return { start, end, cells, bars, rowCount, rowLabels, days, windows };
  }, [data]);

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted">
        <span className="ops-status-dot text-accent-blue" />
        <p className="text-sm">暂无甘特图数据</p>
      </div>
    );
  }

  if (!model) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted">
        <span className="ops-status-dot text-accent-yellow" />
        <p className="text-sm">甘特图时间区间无效</p>
        <p className="text-xs">时间范围暂不可用</p>
      </div>
    );
  }

  const bodyHeight = Math.max(ROW_HEIGHT * Math.max(model.rowCount, 1), ROW_HEIGHT);

  return (
    <div className="w-full">
      {/* 时间轴 */}
      <div className="flex items-end">
        <div style={{ width: GUTTER }} className="pr-3 text-right text-xs text-text-muted">时间轴</div>
        <div className="relative h-6 flex-1">
          {model.days.map((d, i) => (
            <div key={i} className="absolute top-0 whitespace-nowrap text-xs text-text-muted" style={{ left: `${d.left}%` }}>
              <span className="ml-1">{d.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 低风窗口带 */}
      <div className="flex items-center">
        <div style={{ width: GUTTER }} className="pr-3 text-right text-xs text-accent-green">低风窗口</div>
        <div className="relative h-5 flex-1 rounded-sm border border-border-default bg-bg-deep/50">
          {model.windows.map((w, i) => (
            <div
              key={i}
              className="absolute inset-y-0 rounded-sm"
              style={{
                left: `${w.left}%`,
                width: `${w.width}%`,
                background: 'linear-gradient(180deg, rgba(16,185,129,0.45), rgba(16,185,129,0.20))',
              }}
              title={`${w.label || '低风窗口'}｜${w.hours}h｜平均出力 ${w.avg_power_kw.toFixed(0)}kW｜容量系数 ${(w.capacity_factor * 100).toFixed(0)}%`}
            />
          ))}
          {model.windows.length === 0 && (
            <span className="absolute left-2 top-0 text-xs leading-5 text-text-muted">未识别到低风窗口</span>
          )}
        </div>
      </div>

      {/* 主体：风功率热力带 + 工单块 */}
      <div className="mt-1 flex">
        <div style={{ width: GUTTER }} className="pr-2">
          {model.rowCount === 0 ? (
            <div className="text-right text-xs text-text-muted" style={{ height: ROW_HEIGHT, lineHeight: `${ROW_HEIGHT}px` }}>—</div>
          ) : (
            model.rowLabels.map((label, i) => (
              <div
                key={i}
                className="truncate pr-1 text-right text-xs text-text-secondary"
                style={{ height: ROW_HEIGHT, lineHeight: `${ROW_HEIGHT}px` }}
                title={label}
              >
                {label}
              </div>
            ))
          )}
        </div>

        <div
          className="relative flex-1 overflow-hidden rounded-md border border-border-default"
          style={{ height: bodyHeight, background: 'rgba(7,26,53,0.65)' }}
        >
          {/* 风功率热力带 */}
          {model.cells.map((c) => (
            <div
              key={c.key}
              className="absolute inset-y-0"
              style={{ left: `${c.left}%`, width: `${c.width}%`, background: c.color }}
            />
          ))}

          {/* 日分隔线 */}
          {model.days.map((d, i) => (
            <div
              key={`d-${i}`}
              className="absolute inset-y-0 w-px"
              style={{ left: `${d.left}%`, background: 'rgba(148,163,184,0.18)' }}
            />
          ))}

          {/* 泳道分隔线 */}
          {Array.from({ length: Math.max(0, model.rowCount - 1) }).map((_, i) => (
            <div
              key={`r-${i}`}
              className="absolute inset-x-0 h-px"
              style={{ top: (i + 1) * ROW_HEIGHT, background: 'rgba(59,130,246,0.10)' }}
            />
          ))}

          {/* 工单块 */}
          {model.bars.map((b) => {
            const color = PRIORITY_COLOR[b.priority] || '#3B82F6';
            return (
              <div
                key={`${b.work_order_id}-${b.row}`}
                className="absolute flex items-center overflow-hidden rounded px-1.5"
                style={{
                  left: `${b.left}%`,
                  width: `${b.width}%`,
                  top: b.row * ROW_HEIGHT + 4,
                  height: ROW_HEIGHT - 8,
                  background: `linear-gradient(180deg, ${color}E6, ${color}A6)`,
                  border: b.moved_by ? '1.5px dashed #8B5CF6' : `1px solid ${color}`,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
                }}
                title={[
                  `#${b.work_order_id} ${b.label}`,
                  `机组：${b.turbine_name}`,
                  `时段：${fmtHm(b.start)} → ${fmtHm(b.end)}`,
                  `损失电量：${b.est_lost_kwh.toFixed(0)} kWh`,
                  `相比基线省：${b.saving_kwh.toFixed(0)} kWh`,
                  b.moved_by ? `重排原因：${b.moved_by}` : '',
                  b.reason ? `排程理由：${b.reason}` : '',
                ].filter(Boolean).join('\n')}
              >
                <span className="truncate text-xs font-medium text-white">
                  #{b.work_order_id} {b.label || b.turbine_name}
                </span>
              </div>
            );
          })}

          {model.bars.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-xs text-text-muted">
              当前方案没有已排程的工单块
            </div>
          )}
        </div>
      </div>

      {/* 图例 */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border-default pt-3 text-xs text-text-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-8 rounded-sm" style={{ background: 'linear-gradient(90deg, rgba(59,130,246,0.06), rgba(59,130,246,0.60))' }} />
          风功率
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-6 rounded-sm" style={{ background: 'rgba(16,185,129,0.40)' }} />
          低风窗口
        </span>
        {(['urgent', 'high', 'medium', 'low'] as const).map((p) => (
          <span key={p} className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-3 rounded-sm" style={{ background: PRIORITY_COLOR[p] }} />
            {p === 'urgent' ? '紧急' : p === 'high' ? '高' : p === 'medium' ? '中' : '低'}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm border border-dashed" style={{ borderColor: '#8B5CF6' }} />
          事件重排
        </span>
        {data.legend?.max_work_wind_ms != null && (
          <span>作业风速上限 <span className="font-mono text-text-secondary">{String(data.legend.max_work_wind_ms)} m/s</span></span>
        )}
        {data.legend?.work_window_local && (
          <span>作业时段 <span className="font-mono text-text-secondary">{String(data.legend.work_window_local)}</span></span>
        )}
        <span>预测来源 <span className="font-mono text-text-secondary">{data.forecast_source || '—'}</span></span>
      </div>
    </div>
  );
}
