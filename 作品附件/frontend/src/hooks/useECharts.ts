import { useEffect, useRef, useCallback } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';

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

  useEffect(() => {
    if (!containerRef.current || !option) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current, theme);
    }
    chartRef.current.setOption({ backgroundColor: 'transparent', ...option });
    const handleResize = () => chartRef.current?.resize();
    window.addEventListener('resize', handleResize);
    return () => { window.removeEventListener('resize', handleResize); };
  }, deps);

  useEffect(() => {
    return () => { chartRef.current?.dispose(); chartRef.current = null; };
  }, []);

  const resize = useCallback(() => { chartRef.current?.resize(); }, []);
  return { containerRef, chartRef, resize, height };
}

export const CHART_COLORS = {
  red: '#EF4444',
  yellow: '#F59E0B',
  green: '#10B981',
  blue: '#3B82F6',
  purple: '#8B5CF6',
  muted: '#94A3B8',
  grid: '#0D2447',
  text: '#64748B',
} as const;

export function rulColor(days: number): string {
  if (days < 90) return CHART_COLORS.red;
  if (days < 180) return CHART_COLORS.yellow;
  return CHART_COLORS.green;
}

export function hiColor(value: number): string {
  if (value >= 80) return CHART_COLORS.green;
  if (value >= 60) return CHART_COLORS.yellow;
  return CHART_COLORS.red;
}
