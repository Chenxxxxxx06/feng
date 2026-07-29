import type { CSSProperties } from 'react';

/**
 * 骨架屏原语 —— 形状贴近真实内容轮廓，避免"加载中…"裸文字。
 * 全部基于 global.css 的 .skeleton 系列 class，无第三方依赖。
 */

interface SkeletonProps {
  className?: string;
  style?: CSSProperties;
  width?: number | string;
  height?: number | string;
  radius?: number | string;
}

export function Skeleton({ className = '', style, width, height, radius }: SkeletonProps) {
  return (
    <div
      className={`skeleton ${className}`}
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

/** KPI 卡片骨架：与 .surface-card 的 KPI 布局同高 */
export function SkeletonKpiRow({ count = 4, className = '' }: { count?: number; className?: string }) {
  return (
    <div className={`grid gap-3 ${className}`} style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="surface-card flex items-center gap-3 px-4 py-3" style={{ minHeight: 72 }}>
          <Skeleton width={4} height={40} radius={999} />
          <div className="flex-1 space-y-2">
            <Skeleton className="skeleton-text" width="52%" />
            <Skeleton height={20} width="68%" radius={5} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 表格骨架：列宽按真实表头比例铺开 */
export function SkeletonTable({ rows = 6, cols = 5, showHeader = true }: { rows?: number; cols?: number; showHeader?: boolean }) {
  const widths = ['34%', '52%', '44%', '60%', '38%', '46%', '56%'];
  return (
    <div className="w-full" aria-hidden="true">
      {showHeader && (
        <div className="grid gap-3 border-b px-2 py-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, borderColor: 'var(--border-default)' }}>
          {Array.from({ length: cols }).map((_, i) => (
            <Skeleton key={i} className="skeleton-text" width="60%" height={9} />
          ))}
        </div>
      )}
      <div className="space-y-px">
        {Array.from({ length: rows }).map((_, r) => (
          <div
            key={r}
            className="grid items-center gap-3 px-2"
            style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, height: 34, opacity: Math.max(0.35, 1 - r * 0.1) }}
          >
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={c} className="skeleton-text" width={widths[(r + c) % widths.length]} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 列表骨架：图标 + 两行文字 */
export function SkeletonList({ rows = 4, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-xl px-3 py-2.5" style={{ background: 'rgba(59,130,246,0.04)', opacity: Math.max(0.4, 1 - i * 0.12) }}>
          <Skeleton width={8} height={8} radius={999} />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="skeleton-text" width={`${58 + ((i * 11) % 26)}%`} height={11} />
            <Skeleton className="skeleton-text" width="34%" height={8} />
          </div>
          <Skeleton className="skeleton-pill" />
        </div>
      ))}
    </div>
  );
}

/** 图表骨架：坐标轴 + 起伏柱形，轮廓接近折线/柱状图 */
export function SkeletonChart({ height = 180, bars = 14, className = '' }: { height?: number; bars?: number; className?: string }) {
  const heights = [42, 66, 54, 78, 61, 88, 70, 52, 74, 63, 85, 58, 71, 47, 80, 55];
  return (
    <div className={`flex w-full flex-col justify-end gap-2 ${className}`} style={{ height }} aria-hidden="true">
      <div className="flex flex-1 items-end gap-[3px]">
        {Array.from({ length: bars }).map((_, i) => (
          <Skeleton key={i} className="flex-1" height={`${heights[i % heights.length]}%`} radius={3} />
        ))}
      </div>
      <Skeleton height={1} width="100%" radius={0} />
      <div className="flex justify-between">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} width={26} height={7} radius={3} />)}
      </div>
    </div>
  );
}

/** 卡片骨架：标题 + 若干正文行 */
export function SkeletonCard({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`surface-card space-y-3 p-4 ${className}`} aria-hidden="true">
      <Skeleton className="skeleton-title" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="skeleton-text" width={`${92 - i * 14}%`} />
      ))}
    </div>
  );
}

export default Skeleton;
