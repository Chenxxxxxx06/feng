import { useEffect, useRef, useCallback } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';

/**
 * Reusable ECharts hook — eliminates boilerplate:
 * - chart init / dispose lifecycle
 * - dark theme
 * - auto-resize on window resize
 * - responsive height
 *
 * Usage:
 *   const { chartRef } = useECharts({ option, deps: [data] });
 *   return <div ref={chartRef} style={{ height: 350 }} />;
 */
export function useECharts({
  option,
  deps = [],
  height = 350,
  theme = 'dark',
}: {
  option: EChartsOption | null;
  deps?: unknown[];
  height?: number;
  theme?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // Init + update chart
  useEffect(() => {
    if (!containerRef.current || !option) return;

    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current, theme);
    }

    chartRef.current.setOption({ backgroundColor: 'transparent', ...option });

    const handleResize = () => chartRef.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Dispose on unmount
  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  // Manually resize helper
  const resize = useCallback(() => {
    chartRef.current?.resize();
  }, []);

  return { containerRef, chartRef, resize, height };
}

/** Shared chart color helpers */
export const CHART_COLORS = {
  red: '#f85149',
  yellow: '#d29922',
  green: '#3fb950',
  blue: '#58a6ff',
  purple: '#bc8cff',
  muted: '#8b949e',
  grid: '#21262d',
  text: '#5c6975',
} as const;

/** Color by RUL threshold */
export function rulColor(days: number): string {
  if (days < 90) return CHART_COLORS.red;
  if (days < 180) return CHART_COLORS.yellow;
  return CHART_COLORS.green;
}

/** Color by HI threshold */
export function hiColor(value: number): string {
  if (value >= 80) return CHART_COLORS.green;
  if (value >= 60) return CHART_COLORS.yellow;
  return CHART_COLORS.red;
}
