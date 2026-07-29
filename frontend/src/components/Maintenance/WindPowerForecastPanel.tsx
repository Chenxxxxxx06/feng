import { useCallback, useEffect, useMemo, useState } from 'react';
import type { EChartsOption } from '../../services/echarts';
import { useECharts } from '../../hooks/useECharts';
import StateBlock from '../Common/StateBlock';
import {
  fetchPowerForecast,
  prodError,
  refreshPowerForecast,
  type PowerForecastResponse,
} from '../../services/productionService';

function fmtKwh(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '—';
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} kWh`;
}

export default function WindPowerForecastPanel() {
  const [forecast, setForecast] = useState<PowerForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setForecast(await fetchPowerForecast({ hours: 168 }));
    } catch (err) {
      setError(prodError(err, '风功率预测加载失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    setError('');
    try {
      setForecast(await refreshPowerForecast({ hours: 168, method: 'auto' }));
    } catch (err) {
      setError(prodError(err, '风功率预测刷新失败'));
    } finally {
      setRefreshing(false);
    }
  };

  const option = useMemo<EChartsOption | null>(() => {
    if (!forecast?.points.length) return null;
    const labels = forecast.points.map((point) => new Date(point.forecast_time).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
    }));
    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { color: '#94A3B8', fontSize: 12 }, data: ['预期出力', '风速'] },
      grid: { top: 36, right: 58, bottom: 38, left: 68 },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#94A3B8', fontSize: 11, interval: Math.max(1, Math.floor(labels.length / 12)) },
        axisLine: { lineStyle: { color: '#1E3A5F' } },
      },
      yAxis: [
        {
          type: 'value',
          name: '出力 kW',
          nameTextStyle: { color: '#94A3B8' },
          axisLabel: { color: '#94A3B8' },
          splitLine: { lineStyle: { color: '#153253' } },
        },
        {
          type: 'value',
          name: '风速 m/s',
          nameTextStyle: { color: '#94A3B8' },
          axisLabel: { color: '#94A3B8' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '预期出力',
          type: 'line',
          data: forecast.points.map((point) => point.expected_power_kw ?? null),
          symbol: 'none',
          smooth: true,
          lineStyle: { color: '#22D3EE', width: 2 },
          areaStyle: { color: 'rgba(34,211,238,0.08)' },
        },
        {
          name: '风速',
          type: 'line',
          yAxisIndex: 1,
          data: forecast.points.map((point) => point.wind_speed_ms ?? null),
          symbol: 'none',
          smooth: true,
          lineStyle: { color: '#F59E0B', width: 1.5 },
        },
      ],
    };
  }, [forecast]);

  const { containerRef } = useECharts({ option, deps: [option], height: 280 });

  return (
    <section className="ops-panel p-4" aria-label="未来七天风功率预测">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-text-primary">未来 7 天风功率预测</h3>
        <button onClick={() => void refresh()} disabled={loading || refreshing} className="ops-btn px-3 py-1.5 text-xs disabled:opacity-50">
          {refreshing ? '刷新中...' : '刷新预测'}
        </button>
      </div>
      {error ? (
        <StateBlock kind="error" title="风功率预测不可用" desc={error} onRetry={() => void load()} />
      ) : loading ? (
        <div className="flex h-[280px] items-center justify-center text-sm text-text-muted">加载风功率预测...</div>
      ) : forecast?.points.length ? (
        <>
          <div className="mb-3 grid gap-3 sm:grid-cols-3">
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">低风窗口</p><p className="mt-1 font-mono text-xl font-bold text-accent-green">{forecast.low_wind_windows.length}</p></div>
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">预测发电量</p><p className="mt-1 font-mono text-xl font-bold">{fmtKwh(forecast.total_expected_kwh)}</p></div>
            <div className="ops-list-card p-3"><p className="text-xs text-text-muted">平均容量系数</p><p className="mt-1 font-mono text-xl font-bold text-accent-cyan">{(forecast.avg_capacity_factor * 100).toFixed(1)}%</p></div>
          </div>
          <div ref={containerRef} style={{ height: 280 }} />
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-border-default pt-3 text-xs text-text-muted">
            <span>来源 <span className="font-mono text-text-secondary">{forecast.source}</span></span>
            <span>生成时间 <span className="font-mono text-text-secondary">{new Date(forecast.generated_at).toLocaleString('zh-CN')}</span></span>
            {forecast.degraded && <span className="text-accent-yellow">降级：{forecast.degraded_reason || '预测源不可用'}</span>}
          </div>
        </>
      ) : (
        <StateBlock kind="empty" title="暂无风功率预测" onRetry={() => void refresh()} retryLabel="生成预测" />
      )}
    </section>
  );
}
