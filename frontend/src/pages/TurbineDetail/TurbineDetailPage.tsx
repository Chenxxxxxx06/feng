import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import type { Fault, SCADAPoint, TurbineDetail } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

function rounded(value: number | null | undefined, digits: number) {
  return value == null ? null : Number(value.toFixed(digits));
}

function displayValue(value: unknown, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--';
}

function statusText(status: string) {
  if (status === 'normal') return '正常运行';
  if (status === 'warning') return '预警';
  return '故障';
}

export default function TurbineDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [turbine, setTurbine] = useState<TurbineDetail | null>(null);
  const [scada, setScada] = useState<SCADAPoint[]>([]);
  const [scadaMissing, setScadaMissing] = useState(false);
  const [wind, setWind] = useState<Record<string, any> | null>(null);
  const [windMissing, setWindMissing] = useState(false);
  const [faults, setFaults] = useState<Fault[]>([]);
  const [vibration, setVibration] = useState<Record<string, any> | null>(null);
  const [vibrationMissing, setVibrationMissing] = useState(false);
  const [bladeImages, setBladeImages] = useState<any[]>([]);
  const [diagnosisResult, setDiagnosisResult] = useState<any>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const vibChartRef = useRef<HTMLDivElement>(null);
  const scadaHistorical = scada.some((item) => item.dataset_window === 'historical_latest');
  const scadaSourceDataset = scada.find((item) => item.source_dataset)?.source_dataset;

  useEffect(() => {
    if (!id) return;
    api.get(`/turbines/${id}`).then(({ data }) => setTurbine(data));
    api.get(`/turbines/${id}/scada?hours=24`)
      .then(({ data }) => {
        setScada(data);
        setScadaMissing(data.length === 0);
      })
      .catch(() => {
        setScada([]);
        setScadaMissing(true);
      });
    api.get(`/turbines/${id}/wind`)
      .then(({ data }) => {
        setWind(data);
        setWindMissing(false);
      })
      .catch(() => {
        setWind(null);
        setWindMissing(true);
      });
    api.get(`/diagnosis/faults?turbine_id=${id}`).then(({ data }) => setFaults(data));
    api.get(`/diagnosis/vibration?turbine_id=${id}&component=`)
      .then(({ data }) => {
        setVibration(data);
        setVibrationMissing(false);
      })
      .catch(() => {
        setVibration(null);
        setVibrationMissing(true);
      });
    api.get(`/diagnosis/blade-images?turbine_id=${id}`).then(({ data }) => setBladeImages(data));
  }, [id]);

  useEffect(() => {
    if (!chartRef.current || !scada.length) return;
    const chart = echarts.init(chartRef.current, 'dark');
    const times = scada.map((item) => new Date(item.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 40, right: 60, bottom: 30, left: 50 },
      legend: { top: 5, textStyle: { color: '#8b949e', fontSize: 11 } },
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => displayValue(value, 1) },
      xAxis: { type: 'category', data: times, axisLabel: { color: '#5c6975', fontSize: 10 } },
      yAxis: [
        { type: 'value', name: 'kW', axisLabel: { color: '#5c6975', formatter: (value: number) => value.toFixed(0) } },
        { type: 'value', name: '°C', axisLabel: { color: '#5c6975', formatter: (value: number) => value.toFixed(1) } },
      ],
      series: [
        {
          name: '功率',
          type: 'line',
          data: scada.map((item) => rounded(item.power_kw, 1)),
          smooth: true,
          lineStyle: { color: '#58a6ff', width: 1.5 },
          areaStyle: { color: 'rgba(88,166,255,0.08)' },
          symbol: 'none',
        },
        {
          name: '风速',
          type: 'line',
          data: scada.map((item) => rounded(item.wind_speed_ms, 2)),
          smooth: true,
          lineStyle: { color: '#39d2c0', width: 1 },
          symbol: 'none',
        },
        {
          name: '发电机温度',
          yAxisIndex: 1,
          type: 'line',
          data: scada.map((item) => rounded(item.gen_temperature_c, 1)),
          smooth: true,
          lineStyle: { color: '#d29922', width: 1 },
          symbol: 'none',
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [scada]);

  useEffect(() => {
    if (!vibChartRef.current || !vibration?.waveform) return;
    const chart = echarts.init(vibChartRef.current, 'dark');
    const waveform = vibration.waveform.slice(0, 2048);
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 30, right: 20, bottom: 30, left: 45 },
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => displayValue(value, 3) },
      xAxis: {
        type: 'category',
        data: waveform.slice(0, 200).map((_: number, index: number) => `${((index * vibration.duration_seconds) / vibration.waveform.length).toFixed(3)}s`),
        axisLabel: { color: '#5c6975', fontSize: 9 },
      },
      yAxis: { type: 'value', name: 'mm/s²', axisLabel: { color: '#5c6975' } },
      dataZoom: [{ type: 'inside', start: 0, end: 30 }],
      series: [{
        name: '振动',
        type: 'line',
        data: waveform.map((value: number) => rounded(value, 3)),
        smooth: false,
        lineStyle: { color: '#39d2c0', width: 1 },
        areaStyle: { color: 'rgba(57,210,192,0.06)' },
        symbol: 'none',
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [vibration]);

  const runBladeDiagnosis = async (imagePath: string) => {
    setDiagnosing(true);
    try {
      const { data } = await api.post('/diagnosis/blade-diagnosis', { turbine_id: Number(id), image_path: imagePath });
      setDiagnosisResult(data);
    } catch {
      setDiagnosisResult({ damage_type: '数据集记录未找到', confidence: null, damage_bbox: null, image_path: '' });
    }
    setDiagnosing(false);
  };

  if (!turbine) return <div className="p-8 text-text-muted text-sm">加载中...</div>;

  return (
    <div className="h-full flex">
      <div className="flex-1 overflow-auto p-6 space-y-5">
        <div className="flex items-center gap-3">
          <Link to="/dashboard" data-action="back" className="text-text-muted hover:text-text-primary text-sm">返回</Link>
          <h2 className="text-lg font-semibold">{turbine.name}</h2>
          <span className={`px-2 py-0.5 rounded text-xs ${turbine.status === 'normal' ? 'bg-accent-green/20 text-accent-green' : turbine.status === 'warning' ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-red/20 text-accent-red'}`}>
            {statusText(turbine.status)}
          </span>
        </div>

        <div className="bg-bg-card border border-border-default rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">叶片图像诊断</h3>
          <div className="flex gap-4">
            <div className="flex-1">
              <div className="grid grid-cols-3 gap-2 mb-3">
                {bladeImages.map((img, index) => (
                  <button
                    type="button"
                    key={`${img.image_path}-${index}`}
                    onClick={() => runBladeDiagnosis(img.image_path)}
                    className={`border-2 rounded-lg overflow-hidden text-left cursor-pointer transition-all hover:scale-[1.02] ${
                      diagnosisResult?.image_path === img.image_path ? 'border-accent-blue bg-accent-blue/5' : 'border-border-default hover:border-accent-blue/50'
                    }`}
                  >
                    {img.image_url ? (
                      <img src={img.image_url} alt={img.damage_label || '叶片巡检图像'} className="h-24 w-full object-cover bg-bg-secondary" />
                    ) : (
                      <div className="h-24 bg-bg-secondary flex items-center justify-center text-[10px] text-text-muted">无图像文件</div>
                    )}
                    <div className="p-2">
                      <p className="text-[10px] text-text-secondary">{img.view || '叶片图像'}</p>
                      <p className="text-[10px] text-text-muted">#{index + 1} · {new Date(img.timestamp).toLocaleDateString('zh-CN')}</p>
                      {img.has_damage && <p className="text-[10px] text-accent-red mt-1">检测到损伤</p>}
                    </div>
                  </button>
                ))}
                {bladeImages.length === 0 && (
                  <div className="col-span-3 rounded-lg border border-border-default bg-bg-secondary p-4 text-xs text-text-muted">
                    未导入真实叶片图像数据集。
                  </div>
                )}
              </div>
            </div>

            <div className="w-64 border border-border-default rounded-lg p-3 bg-bg-secondary">
              <h4 className="text-xs font-medium mb-2">数据集标注诊断</h4>
              {diagnosing ? (
                <p className="text-xs text-text-muted animate-pulse">分析中...</p>
              ) : diagnosisResult ? (
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-text-muted">损伤类型</span>
                    <span className="text-accent-yellow font-medium">{diagnosisResult.damage_type}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">置信度</span>
                    <span className="font-mono text-accent-green">
                      {diagnosisResult.confidence == null ? '无' : `${(diagnosisResult.confidence * 100).toFixed(1)}%`}
                    </span>
                  </div>
                  {diagnosisResult.damage_bbox && (
                    <div className="flex justify-between">
                      <span className="text-text-muted">损伤位置</span>
                      <span className="font-mono text-text-secondary">x:{diagnosisResult.damage_bbox.x} y:{diagnosisResult.damage_bbox.y}</span>
                    </div>
                  )}
                  <div className="mt-2 p-2 bg-bg-hover rounded text-[10px]">
                    <p className="text-accent-yellow mb-1">建议</p>
                    <p className="text-text-secondary">{diagnosisResult.recommended_action || '根据数据集标注结果安排人工复核。'}</p>
                  </div>
                </div>
              ) : (
                <p className="text-[10px] text-text-muted">点击左侧图像开始诊断</p>
              )}
            </div>
          </div>
        </div>

        <div className="bg-bg-card border border-border-default rounded-lg p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-medium">
              {scadaHistorical ? 'SCADA 历史数据窗口' : 'SCADA 运行数据曲线'}
            </h3>
            {scada.length > 0 && (
              <span className="text-[10px] text-text-muted">
                {scadaSourceDataset || '真实数据集'}
              </span>
            )}
          </div>
          {scada.length > 0 ? (
            <div ref={chartRef} style={{ height: 300 }} />
          ) : (
            <div className="h-[300px] flex items-center justify-center rounded-lg border border-border-default bg-bg-secondary px-4 text-xs text-text-muted">
              {scadaMissing ? '未导入真实 SCADA 数据。' : '加载中...'}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="bg-bg-card border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-medium mb-3">实时气象</h3>
            {wind ? (
              <div className="grid grid-cols-3 gap-2 text-xs">
                {[
                  ['风速', displayValue(wind.wind_speed_ms, 2), 'm/s'],
                  ['阵风', displayValue(wind.wind_gust_ms, 2), 'm/s'],
                  ['风向', displayValue(wind.wind_direction_deg, 0), '°'],
                  ['湍流', displayValue(wind.turbulence_intensity, 2), ''],
                  ['气温', displayValue(wind.air_temperature_c, 1), '°C'],
                  ['气压', displayValue(wind.air_pressure_hpa, 1), 'hPa'],
                ].map(([label, value, unit]) => (
                  <div key={label} className="bg-bg-hover rounded p-2 text-center">
                    <p className="text-text-muted text-[10px]">{label}</p>
                    <p className="text-accent-cyan font-mono font-bold">{value}{unit}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-muted">
                {windMissing ? '未导入真实 ERA5 或现场气象数据。' : '加载中...'}
              </p>
            )}
          </div>

          <div className="bg-bg-card border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-medium mb-3">
              振动波形
              {vibration && (
                <span className="ml-2 text-xs font-normal text-text-muted">
                  RMS: <span className="text-accent-cyan">{displayValue(vibration.rms, 3)}</span>
                  {vibration.fault_detected && <span className="ml-1 px-1.5 py-0.5 rounded bg-accent-red/20 text-accent-red text-[10px]">故障信号</span>}
                </span>
              )}
            </h3>
            {vibration ? (
              <div ref={vibChartRef} style={{ height: 180 }} />
            ) : (
              <p className="text-xs text-text-muted">
                {vibrationMissing ? '未导入真实振动数据集。' : '加载中...'}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="w-72 border-l border-border-default bg-bg-secondary flex flex-col">
        <div className="p-4 flex-1 overflow-auto">
          <h3 className="text-sm font-medium mb-3">故障记录</h3>
          {faults.length === 0 ? (
            <p className="text-xs text-text-muted">暂无故障</p>
          ) : (
            <div className="space-y-2">
              {faults.map((fault) => (
                <div key={fault.id} className="bg-bg-card rounded p-3 text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="font-medium text-accent-red">{fault.fault_type}</span>
                    <span className="text-text-muted">{new Date(fault.detected_at).toLocaleDateString('zh-CN')}</span>
                  </div>
                  <div className="flex justify-between text-text-muted">
                    <span>置信度: {(fault.confidence * 100).toFixed(0)}%</span>
                    <span>{fault.status === 'open' ? '待处理' : '已关闭'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <CopilotFAB />
    </div>
  );
}
