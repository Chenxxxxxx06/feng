import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent as ReactWheelEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import * as echarts from 'echarts';
import api from '../../services/api';
import type { BladeDiagnosisResult, Fault, SCADAPoint, TurbineDetail, VibrationPreview, WeatherReplayPoint } from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import { buildReplayClockState, formatReplayClock } from '../../services/replayClock';

type BladeReplayImage = {
  id: number | null;
  turbine_id: number;
  timestamp: string;
  image_path: string;
  image_url?: string | null;
  diagnosis_type?: string | null;
  confidence?: number | null;
  damage_bbox?: Record<string, any> | null;
  has_damage?: boolean;
  source_dataset?: string | null;
  view?: string | null;
  frame_label?: string | null;
  frame_index?: number | null;
  frame_count?: number | null;
  replay_slot_start_minute?: number | null;
  replay_mode?: string | null;
  inspection_id?: string | null;
  inspection_slot?: number | null;
  image_index?: number | null;
  image_count?: number | null;
  campaign?: string | null;
  quality?: Record<string, any> | null;
};

type ReplaySCADAPoint = SCADAPoint & {
  replay_slot_start_minute: number;
  replay_slot_label: string;
  replay_cycle_hours: number;
  replay_cycle_day_index: number;
  replay_source_index: number;
};

type BladeAnnotationRegion = {
  id: string;
  label: string;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number };
};

type BladeAnnotationDisplay = BladeAnnotationRegion & {
  displayIndex: number;
  badge: {
    cx: number;
    cy: number;
    r: number;
    strokeWidth: number;
    deleteCx: number;
    deleteCy: number;
  };
};

type BladeViewportCrop = {
  blob: Blob;
  sourceLeft: number;
  sourceTop: number;
  sourceWidth: number;
  sourceHeight: number;
  canvasWidth: number;
  canvasHeight: number;
  naturalWidth: number;
  naturalHeight: number;
};

type BladeModelRegion = {
  label: string;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number };
};

const MINUTES_PER_DAY = 1440;
const SCADA_SLOT_MINUTES = 10;
const SCADA_SLOTS_PER_DAY = MINUTES_PER_DAY / SCADA_SLOT_MINUTES;
const WEATHER_REFRESH_MS = 60_000;
const WEATHER_RETRY_DELAYS_MS = [5_000, 15_000, 30_000];

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

function datasetLabel(datasetId: string | null | undefined) {
  if (!datasetId) return '真实巡检图像数据集';
  if (datasetId.includes('mendeley_blade_vibration_faults')) return 'Mendeley 叶片振动';
  if (datasetId.includes('mendeley')) return 'Mendeley 叶片振动';
  if (datasetId.includes('nrel')) return 'NREL 振动数据';
  if (datasetId.includes('dtu')) return 'DTU 无人机巡检';
  if (datasetId.includes('yolo')) return 'YOLO 叶片表面损伤';
  if (datasetId.includes('care')) return 'CARE SCADA';
  if (datasetId.includes('open_meteo')) return 'Open-Meteo';
  return datasetId;
}

function imageFileName(image: BladeReplayImage) {
  return image.image_path.split('/').pop() || 'inspection-image';
}

function imageDisplayTitle(image: BladeReplayImage) {
  if (image.frame_label) return image.frame_label;
  return imageFileName(image).replace(/\.[^.]+$/, '');
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function layoutBladeAnnotationBadges(
  regions: BladeAnnotationRegion[],
  imageSize: { width: number; height: number },
): BladeAnnotationDisplay[] {
  if (!imageSize.width || !imageSize.height) return [];

  const visibleRegions = regions.filter((region) => region.confidence >= 0.1);
  const minDim = Math.min(imageSize.width, imageSize.height);
  const radius = clampNumber(minDim * (visibleRegions.length > 12 ? 0.012 : 0.016), 4, 10);
  const strokeWidth = clampNumber(minDim * 0.0025, 1, 2.5);
  const clearance = radius * 2.7;
  const margin = radius + strokeWidth + 3;
  const placed: BladeAnnotationDisplay[] = [];

  visibleRegions.forEach((region, index) => {
    const { x, y, w, h } = region.bbox;
    const centerX = x + w / 2;
    const centerY = y + h / 2;
    const candidates: Array<[number, number]> = [
      [x, y],
      [x + w, y],
      [x, y + h],
      [x + w, y + h],
      [x + w / 2, y - radius * 1.8],
      [x + w / 2, y + h + radius * 1.8],
      [x - radius * 1.8, y + h / 2],
      [x + w + radius * 1.8, y + h / 2],
    ];

    for (let ring = 1; ring <= 7; ring += 1) {
      const distance = radius * (2.4 + ring * 1.25);
      const angleCount = ring < 4 ? 12 : 18;
      for (let step = 0; step < angleCount; step += 1) {
        const angle = (Math.PI * 2 * step) / angleCount;
        candidates.push([
          centerX + Math.cos(angle) * distance,
          centerY + Math.sin(angle) * distance,
        ]);
      }
    }

    let best = {
      cx: clampNumber(candidates[0][0], margin, imageSize.width - margin),
      cy: clampNumber(candidates[0][1], margin, imageSize.height - margin),
    };
    let bestScore = Number.NEGATIVE_INFINITY;
    candidates.forEach(([rawCx, rawCy]) => {
      const candidate = {
        cx: clampNumber(rawCx, margin, imageSize.width - margin),
        cy: clampNumber(rawCy, margin, imageSize.height - margin),
      };
      const candidateDelete = {
        cx: clampNumber(candidate.cx + radius * 1.45, margin, imageSize.width - margin),
        cy: clampNumber(candidate.cy - radius * 1.45, margin, imageSize.height - margin),
      };
      const overlapPenalty = placed.reduce((penalty, item) => {
        const badgeOverlap = Math.max(
          0,
          clearance - Math.hypot(candidate.cx - item.badge.cx, candidate.cy - item.badge.cy),
        );
        const deleteOverlap = Math.max(
          0,
          radius * 2.1 - Math.hypot(candidateDelete.cx - item.badge.deleteCx, candidateDelete.cy - item.badge.deleteCy),
        );
        const crossOverlap = Math.max(
          0,
          radius * 2.2 - Math.hypot(candidate.cx - item.badge.deleteCx, candidate.cy - item.badge.deleteCy),
        );
        return penalty + badgeOverlap * badgeOverlap + deleteOverlap * deleteOverlap + crossOverlap * crossOverlap;
      }, 0);
      const insideBox = candidate.cx >= x && candidate.cx <= x + w && candidate.cy >= y && candidate.cy <= y + h;
      const anchorDistance = Math.hypot(candidate.cx - centerX, candidate.cy - centerY);
      const score = -overlapPenalty - anchorDistance * 0.12 - (insideBox ? 160 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = candidate;
      }
    });

    const deleteOffset = radius * 1.45;
    placed.push({
      ...region,
      displayIndex: index + 1,
      badge: {
        cx: best.cx,
        cy: best.cy,
        r: radius,
        strokeWidth,
        deleteCx: clampNumber(best.cx + deleteOffset, margin, imageSize.width - margin),
        deleteCy: clampNumber(best.cy - deleteOffset, margin, imageSize.height - margin),
      },
    });
  });

  return placed;
}

function loadCanvasImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('图像加载失败'));
    image.src = src;
  });
}

function canvasToJpegBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error('诊断区域裁剪失败'));
      }
    }, 'image/jpeg', 0.95);
  });
}

function selectScadaReplayCycleHours(sourceCount: number) {
  if (sourceCount >= 72 * 6) return 72;
  if (sourceCount >= 48 * 6) return 48;
  return 24;
}

function buildScadaReplayDay(source: SCADAPoint[], now: Date) {
  if (!source.length) {
    return {
      cycleHours: 24,
      cycleDays: 1,
      daySeries: [] as ReplaySCADAPoint[],
      current: null as ReplaySCADAPoint | null,
    };
  }

  const sorted = [...source].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
  const cycleHours = selectScadaReplayCycleHours(sorted.length);
  const cycleDays = Math.max(1, cycleHours / 24);
  const cycleSlots = cycleDays * SCADA_SLOTS_PER_DAY;
  const cycleSeries: ReplaySCADAPoint[] = Array.from({ length: cycleSlots }, (_, slotIndex) => {
    const sourceIndex = cycleSlots <= 1
      ? 0
      : Math.round((slotIndex * (sorted.length - 1)) / (cycleSlots - 1));
    const slotMinuteInCycle = slotIndex * SCADA_SLOT_MINUTES;
    return {
      ...sorted[sourceIndex],
      replay_slot_start_minute: slotMinuteInCycle % MINUTES_PER_DAY,
      replay_slot_label: formatReplayClock(slotMinuteInCycle % MINUTES_PER_DAY),
      replay_cycle_hours: cycleHours,
      replay_cycle_day_index: Math.floor(slotMinuteInCycle / MINUTES_PER_DAY),
      replay_source_index: sourceIndex,
    };
  });

  const localMidnight = new Date(now);
  localMidnight.setHours(0, 0, 0, 0);
  const epochDay = Math.floor(localMidnight.getTime() / (24 * 60 * 60 * 1000));
  const replayDayIndex = ((epochDay % cycleDays) + cycleDays) % cycleDays;
  const currentSlotIndex = Math.min(
    SCADA_SLOTS_PER_DAY - 1,
    Math.floor((now.getHours() * 60 + now.getMinutes()) / SCADA_SLOT_MINUTES),
  );
  const dayStartSlot = replayDayIndex * SCADA_SLOTS_PER_DAY;
  const daySeries = cycleSeries
    .slice(dayStartSlot, dayStartSlot + currentSlotIndex + 1)
    .map((item, slotIndex) => ({
      ...item,
      replay_slot_start_minute: slotIndex * SCADA_SLOT_MINUTES,
      replay_slot_label: formatReplayClock(slotIndex * SCADA_SLOT_MINUTES),
    }));

  return {
    cycleHours,
    cycleDays,
    daySeries,
    current: daySeries[daySeries.length - 1] ?? null,
  };
}

export default function TurbineDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [turbine, setTurbine] = useState<TurbineDetail | null>(null);
  const [scada, setScada] = useState<SCADAPoint[]>([]);
  const [scadaMissing, setScadaMissing] = useState(false);
  const [wind, setWind] = useState<WeatherReplayPoint | null>(null);
  const [windMissing, setWindMissing] = useState(false);
  const [faults, setFaults] = useState<Fault[]>([]);
  const [vibration, setVibration] = useState<VibrationPreview | null>(null);
  const [vibrationMissing, setVibrationMissing] = useState(false);
  const [bladeImages, setBladeImages] = useState<BladeReplayImage[]>([]);
  const [selectedBladeImagePath, setSelectedBladeImagePath] = useState<string | null>(null);
  const [bladeModelResults, setBladeModelResults] = useState<Record<string, BladeDiagnosisResult>>({});
  const [bladeAnnotationRegions, setBladeAnnotationRegions] = useState<Record<string, BladeAnnotationRegion[]>>({});
  const [bladeModelLoading, setBladeModelLoading] = useState(false);
  const [bladeModelErrors, setBladeModelErrors] = useState<Record<string, string>>({});
  const [showBladeAnnotation, setShowBladeAnnotation] = useState(false);
  const [bladeImageScale, setBladeImageScale] = useState(1);
  const [bladeImageOffset, setBladeImageOffset] = useState({ x: 0, y: 0 });
  const [bladeImageNaturalSize, setBladeImageNaturalSize] = useState({ width: 0, height: 0 });
  const [bladeImageDrag, setBladeImageDrag] = useState<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [replayNow, setReplayNow] = useState(() => new Date());
  const bladeImageViewportRef = useRef<HTMLDivElement>(null);
  const bladeImageElementRef = useRef<HTMLImageElement>(null);
  const bladeThumbsRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const vibChartRef = useRef<HTMLDivElement>(null);
  const hasWindDataRef = useRef(false);
  const scadaHistorical = scada.some((item) => item.dataset_window === 'historical_latest');
  const scadaSourceDataset = scada.find((item) => item.source_dataset)?.source_dataset;
  const replayClock = useMemo(() => buildReplayClockState(replayNow), [replayNow]);
  const windMetricCards = useMemo(
    () => (wind ? [
      wind.wind_speed_ms != null ? ['风速', displayValue(wind.wind_speed_ms, 2), 'm/s'] : null,
      wind.wind_gust_ms != null ? ['阵风', displayValue(wind.wind_gust_ms, 2), 'm/s'] : null,
      wind.wind_direction_deg != null ? ['风向', displayValue(wind.wind_direction_deg, 0), '°'] : null,
      wind.turbulence_intensity != null ? ['湍流', displayValue(wind.turbulence_intensity, 2), ''] : null,
      wind.air_temperature_c != null ? ['气温', displayValue(wind.air_temperature_c, 1), '°C'] : null,
      wind.air_pressure_hpa != null ? ['气压', displayValue(wind.air_pressure_hpa, 1), 'hPa'] : null,
    ].filter((item): item is [string, string, string] => Boolean(item)) : []),
    [wind],
  );

  useEffect(() => {
    if (!id) return;
    api.get(`/turbines/${id}`).then(({ data }) => setTurbine(data));
    api.get(`/turbines/${id}/scada?hours=72`)
      .then(({ data }) => {
        setScada(data);
        setScadaMissing(data.length === 0);
      })
      .catch(() => {
        setScada([]);
        setScadaMissing(true);
      });
    api.get(`/diagnosis/faults?turbine_id=${id}`).then(({ data }) => setFaults(data));
    api.get(`/diagnosis/vibration?turbine_id=${id}&component=blade`)
      .then(({ data }) => {
        setVibration(data);
        setVibrationMissing(false);
      })
      .catch(() => {
        setVibration(null);
        setVibrationMissing(true);
      });
    api.get(`/diagnosis/blade-images?turbine_id=${id}`)
      .then(({ data }) => setBladeImages(data))
      .catch(() => setBladeImages([]));
    setSelectedBladeImagePath(null);
    setBladeModelResults({});
    setBladeAnnotationRegions({});
    setBladeModelErrors({});
    setShowBladeAnnotation(false);
    setBladeImageScale(1);
    setBladeImageOffset({ x: 0, y: 0 });
    setBladeImageDrag(null);
    setBladeImageNaturalSize({ width: 0, height: 0 });
  }, [id]);

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    const retryTimers: number[] = [];
    hasWindDataRef.current = false;
    setWind(null);
    setWindMissing(false);

    const fetchWind = async (retryIndex = 0) => {
      try {
        const { data } = await api.get(`/turbines/${id}/wind`);
        if (cancelled) return;
        hasWindDataRef.current = true;
        setWind(data);
        setWindMissing(false);
      } catch {
        if (cancelled) return;
        const nextDelay = WEATHER_RETRY_DELAYS_MS[retryIndex];
        if (nextDelay != null) {
          const timer = window.setTimeout(() => fetchWind(retryIndex + 1), nextDelay);
          retryTimers.push(timer);
          return;
        }
        setWindMissing(!hasWindDataRef.current);
      }
    };

    fetchWind();
    const refreshTimer = window.setInterval(() => fetchWind(), WEATHER_REFRESH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
      retryTimers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [id]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setReplayNow(new Date());
    }, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const scadaReplay = useMemo(() => {
    return buildScadaReplayDay(scada, replayNow);
  }, [scada, replayNow]);

  useEffect(() => {
    if (!chartRef.current || !scadaReplay.daySeries.length) return;
    const chart = echarts.init(chartRef.current, 'dark');
    const times = scadaReplay.daySeries.map((item) => item.replay_slot_label);
    const currentPowerUnit = scadaReplay.current?.power_unit || 'p.u.';
    const currentPowerLabel = scadaReplay.current?.power_label || '有功功率';
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 40, right: 60, bottom: 30, left: 50 },
      legend: { top: 5, textStyle: { color: '#8b949e', fontSize: 11 } },
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => displayValue(value, currentPowerUnit === 'p.u.' ? 3 : 1) },
      xAxis: { type: 'category', data: times, axisLabel: { color: '#5c6975', fontSize: 10 } },
      yAxis: [
        { type: 'value', name: currentPowerUnit === 'p.u.' ? '功率(p.u.)' : '功率(kW)', axisLabel: { color: '#5c6975', formatter: (value: number) => value.toFixed(currentPowerUnit === 'p.u.' ? 2 : 0) } },
        { type: 'value', name: '°C', axisLabel: { color: '#5c6975', formatter: (value: number) => value.toFixed(1) } },
      ],
      series: [
        {
          name: currentPowerLabel,
          type: 'line',
          data: scadaReplay.daySeries.map((item) => rounded(item.power_kw, 3)),
          smooth: true,
          lineStyle: { color: '#58a6ff', width: 1.5 },
          areaStyle: { color: 'rgba(88,166,255,0.08)' },
          symbol: 'none',
        },
        {
          name: '风速',
          type: 'line',
          data: scadaReplay.daySeries.map((item) => rounded(item.wind_speed_ms, 2)),
          smooth: true,
          lineStyle: { color: '#39d2c0', width: 1 },
          symbol: 'none',
        },
        {
          name: '发电机温度',
          yAxisIndex: 1,
          type: 'line',
          data: scadaReplay.daySeries.map((item) => rounded(item.gen_temperature_c, 1)),
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
  }, [scadaReplay]);

  useEffect(() => {
    if (!vibChartRef.current || !vibration?.waveform) return;
    const chart = echarts.init(vibChartRef.current, 'dark');
    const waveform = vibration.waveform.slice(0, 2048);
    const sampleRate = Number(vibration.sample_rate_hz) || 1;
    const waveformPoints = waveform.map((value: number, index: number) => [
      Number((index / sampleRate).toFixed(6)),
      rounded(value, 6),
    ]);
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 30, right: 20, bottom: 30, left: 45 },
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => displayValue(value, 3) },
      xAxis: {
        type: 'value',
        name: 's',
        axisLabel: { color: '#5c6975', fontSize: 9 },
      },
      yAxis: { type: 'value', name: 'mm/s²', axisLabel: { color: '#5c6975' } },
      dataZoom: [{ type: 'inside', start: 0, end: 30 }],
      series: [{
        name: '振动',
        type: 'line',
        data: waveformPoints,
        smooth: false,
        lineStyle: { color: '#39d2c0', width: 1 },
        areaStyle: { color: 'rgba(57,210,192,0.06)' },
        symbol: 'none',
        showSymbol: false,
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [vibration]);

  const vibrationReplay = useMemo(() => {
    if (!vibration) return null;
    return { current: vibration };
  }, [vibration, replayClock.replayMinuteOfDay]);

  const bladeReplay = useMemo(() => {
    if (!bladeImages.length) return null;
    const sorted = [...bladeImages].sort(
      (a, b) => (a.image_index ?? a.frame_index ?? 0) - (b.image_index ?? b.frame_index ?? 0),
    );
    const currentIndex = 0;
    const current = sorted[0];
    const frameCount = sorted[0]?.image_count || sorted[0]?.frame_count || sorted.length;
    const manualSelectedIndex = selectedBladeImagePath
      ? sorted.findIndex((item) => item.image_path === selectedBladeImagePath)
      : -1;
    const selectedIndex = manualSelectedIndex >= 0 ? manualSelectedIndex : currentIndex;
    const selected = sorted[selectedIndex] || current;
    return {
      frames: sorted,
      current,
      currentIndex,
      selected,
      selectedIndex,
      frameCount,
      isManualSelection: manualSelectedIndex >= 0,
    };
  }, [bladeImages, selectedBladeImagePath]);

  const buildSelectedBladeViewportCrop = async (
    viewState = { scale: bladeImageScale, offset: bladeImageOffset },
  ): Promise<BladeViewportCrop> => {
    const selectedImageUrl = bladeReplay?.selected?.image_url;
    const viewport = bladeImageViewportRef.current;
    if (!selectedImageUrl || !viewport) {
      throw new Error('未选中可诊断图像');
    }

    const image = await loadCanvasImage(selectedImageUrl);
    const rect = viewport.getBoundingClientRect();
    const naturalWidth = image.naturalWidth || image.width;
    const naturalHeight = image.naturalHeight || image.height;
    if (!rect.width || !rect.height || !naturalWidth || !naturalHeight) {
      throw new Error('图像尺寸异常');
    }
    setBladeImageNaturalSize((size) => {
      if (size.width === naturalWidth && size.height === naturalHeight) return size;
      return { width: naturalWidth, height: naturalHeight };
    });

    const coverScale = Math.max(rect.width / naturalWidth, rect.height / naturalHeight);
    const renderedWidth = naturalWidth * coverScale;
    const renderedHeight = naturalHeight * coverScale;
    const coverOffsetX = (rect.width - renderedWidth) / 2;
    const coverOffsetY = (rect.height - renderedHeight) / 2;

    const visibleLeft = (-viewState.offset.x) / viewState.scale;
    const visibleTop = (-viewState.offset.y) / viewState.scale;
    const visibleRight = (rect.width - viewState.offset.x) / viewState.scale;
    const visibleBottom = (rect.height - viewState.offset.y) / viewState.scale;

    const sourceLeft = clampNumber((visibleLeft - coverOffsetX) / coverScale, 0, naturalWidth);
    const sourceTop = clampNumber((visibleTop - coverOffsetY) / coverScale, 0, naturalHeight);
    const sourceRight = clampNumber((visibleRight - coverOffsetX) / coverScale, 0, naturalWidth);
    const sourceBottom = clampNumber((visibleBottom - coverOffsetY) / coverScale, 0, naturalHeight);
    const sourceWidth = Math.max(1, sourceRight - sourceLeft);
    const sourceHeight = Math.max(1, sourceBottom - sourceTop);

    const canvas = document.createElement('canvas');
    canvas.width = Math.round(sourceWidth);
    canvas.height = Math.round(sourceHeight);
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('浏览器无法创建诊断裁剪画布');
    }
    ctx.drawImage(
      image,
      sourceLeft,
      sourceTop,
      sourceWidth,
      sourceHeight,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    return {
      blob: await canvasToJpegBlob(canvas),
      sourceLeft,
      sourceTop,
      sourceWidth,
      sourceHeight,
      canvasWidth: canvas.width,
      canvasHeight: canvas.height,
      naturalWidth,
      naturalHeight,
    };
  };

  const runSelectedBladeDiagnosis = async () => {
    if (!id || !bladeReplay?.selected?.image_path) return;
    const selectedImagePath = bladeReplay.selected.image_path;
    const cropView = { scale: bladeImageScale, offset: bladeImageOffset };
    setBladeModelLoading(true);
    setBladeModelErrors((errors) => {
      const next = { ...errors };
      delete next[selectedImagePath];
      return next;
    });
    try {
      const crop = await buildSelectedBladeViewportCrop(cropView);
      const formData = new FormData();
      formData.append('turbine_id', String(Number(id)));
      formData.append('image', crop.blob, `${imageDisplayTitle(bladeReplay.selected)}-viewport.jpg`);
      const { data } = await api.post('/diagnosis/blade-diagnosis/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setBladeModelResults((results) => ({
        ...results,
        [selectedImagePath]: data,
      }));

      const resultRegions: BladeModelRegion[] = data.damage_regions?.length
        ? data.damage_regions
        : data.damage_bbox
          ? [{ label: data.damage_type, bbox: data.damage_bbox, confidence: data.confidence }]
          : [];
      if (resultRegions.length) {
        const mappedRegions = resultRegions.map((region, index) => ({
          id: `${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
          label: region.label,
          confidence: region.confidence,
          bbox: {
            x: crop.sourceLeft + (region.bbox.x * crop.sourceWidth) / crop.canvasWidth,
            y: crop.sourceTop + (region.bbox.y * crop.sourceHeight) / crop.canvasHeight,
            w: (region.bbox.w * crop.sourceWidth) / crop.canvasWidth,
            h: (region.bbox.h * crop.sourceHeight) / crop.canvasHeight,
          },
        }));
        setBladeAnnotationRegions((regions) => ({
          ...regions,
          [selectedImagePath]: [
            ...(regions[selectedImagePath] || []),
            ...mappedRegions,
          ],
        }));
      }
      setBladeImageNaturalSize({ width: crop.naturalWidth, height: crop.naturalHeight });
      setShowBladeAnnotation((current) => (resultRegions.length > 0 ? true : current));
      requestAnimationFrame(syncBladeImageNaturalSize);
    } catch (err: any) {
      setBladeModelErrors((errors) => ({
        ...errors,
        [selectedImagePath]: err.response?.data?.detail || err.message || '模型诊断失败',
      }));
    } finally {
      setBladeModelLoading(false);
    }
  };

  const selectBladeImage = (imagePath: string) => {
    setSelectedBladeImagePath(imagePath === bladeReplay?.current.image_path ? null : imagePath);
    setShowBladeAnnotation(Boolean(bladeAnnotationRegions[imagePath]?.length));
    setBladeImageScale(1);
    setBladeImageOffset({ x: 0, y: 0 });
    setBladeImageDrag(null);
    setBladeImageNaturalSize({ width: 0, height: 0 });
  };

  const toggleBladeAnnotation = () => {
    if (!selectedBladeHasAnnotations) return;
    setShowBladeAnnotation((value) => !value);
    setBladeImageDrag(null);
  };

  const returnToFirstBladeImage = () => {
    if (!bladeReplay?.current.image_path) return;
    selectBladeImage(bladeReplay.current.image_path);
    requestAnimationFrame(() => {
      if (bladeThumbsRef.current) {
        bladeThumbsRef.current.scrollTop = 0;
      }
    });
  };

  const selectedBladeModelResult = bladeReplay?.selected?.image_path
    ? bladeModelResults[bladeReplay.selected.image_path]
    : null;
  const selectedBladeModelError = bladeReplay?.selected?.image_path
    ? bladeModelErrors[bladeReplay.selected.image_path]
    : '';
  const selectedBladeAnnotationRegions = bladeReplay?.selected?.image_path
    ? bladeAnnotationRegions[bladeReplay.selected.image_path] || []
    : [];
  const selectedBladeHasModelResult = Boolean(selectedBladeModelResult);
  const selectedBladeHasAnnotations = selectedBladeAnnotationRegions.length > 0;
  const selectedBladeModelImageUrl = selectedBladeModelResult?.image_url || '';
  const selectedBladeImageUrl = bladeReplay?.selected?.image_url || '';
  const displayedBladeAnnotations = useMemo(
    () => layoutBladeAnnotationBadges(selectedBladeAnnotationRegions, bladeImageNaturalSize),
    [bladeImageNaturalSize, selectedBladeAnnotationRegions],
  );

  const syncBladeImageNaturalSize = () => {
    const image = bladeImageElementRef.current;
    if (!image || !image.complete || !image.naturalWidth || !image.naturalHeight) return;
    setBladeImageNaturalSize((size) => {
      if (size.width === image.naturalWidth && size.height === image.naturalHeight) return size;
      return {
        width: image.naturalWidth,
        height: image.naturalHeight,
      };
    });
  };

  useEffect(() => {
    syncBladeImageNaturalSize();
  }, [selectedBladeImageUrl, selectedBladeHasAnnotations, showBladeAnnotation]);

  const deleteBladeAnnotation = (annotationId: string) => {
    const selectedImagePath = bladeReplay?.selected?.image_path;
    if (!selectedImagePath) return;
    setBladeAnnotationRegions((regions) => {
      const nextRegions = (regions[selectedImagePath] || []).filter((region) => region.id !== annotationId);
      return {
        ...regions,
        [selectedImagePath]: nextRegions,
      };
    });
  };

  const clampBladeImageOffset = (offset: { x: number; y: number }, scale: number) => {
    const viewport = bladeImageViewportRef.current;
    if (!viewport || scale <= 1) return { x: 0, y: 0 };
    const rect = viewport.getBoundingClientRect();
    const minX = rect.width * (1 - scale);
    const minY = rect.height * (1 - scale);
    return {
      x: Math.min(0, Math.max(minX, offset.x)),
      y: Math.min(0, Math.max(minY, offset.y)),
    };
  };

  useEffect(() => {
    const viewport = bladeImageViewportRef.current;
    if (!viewport) return;

    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();

      const rect = viewport.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const nextScale = Math.min(5, Math.max(1, Number((bladeImageScale + (event.deltaY < 0 ? 0.25 : -0.25)).toFixed(2))));

      if (nextScale === 1) {
        setBladeImageScale(1);
        setBladeImageOffset({ x: 0, y: 0 });
        return;
      }

      const imageX = (mouseX - bladeImageOffset.x) / bladeImageScale;
      const imageY = (mouseY - bladeImageOffset.y) / bladeImageScale;
      setBladeImageScale(nextScale);
      setBladeImageOffset(clampBladeImageOffset({
        x: mouseX - imageX * nextScale,
        y: mouseY - imageY * nextScale,
      }, nextScale));
    };

    viewport.addEventListener('wheel', handleWheel, { passive: false });
    return () => viewport.removeEventListener('wheel', handleWheel);
  }, [bladeImageOffset, bladeImageScale, selectedBladeImageUrl]);

  const handleBladePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (bladeImageScale <= 1) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setBladeImageDrag({
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: bladeImageOffset.x,
      originY: bladeImageOffset.y,
    });
  };

  const handleBladePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!bladeImageDrag || bladeImageDrag.pointerId !== event.pointerId) return;
    setBladeImageOffset(clampBladeImageOffset({
      x: bladeImageDrag.originX + event.clientX - bladeImageDrag.startX,
      y: bladeImageDrag.originY + event.clientY - bladeImageDrag.startY,
    }, bladeImageScale));
  };

  const handleBladePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (bladeImageDrag?.pointerId === event.pointerId) {
      setBladeImageDrag(null);
    }
  };

  const handleBladeFrameWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.scrollTop += event.deltaY;
  };

  const exportBladeDiagnosisImage = () => {
    if (!selectedBladeModelImageUrl || !bladeReplay?.selected) return;
    const link = document.createElement('a');
    link.href = selectedBladeModelImageUrl;
    link.download = `${imageDisplayTitle(bladeReplay.selected)}-diagnosis.jpg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
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
          <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 className="text-sm font-medium">叶片巡检照片</h3>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
            <div className="min-w-0 space-y-3">
              {bladeReplay?.selected?.image_url ? (
                <>
                  <div
                    ref={bladeImageViewportRef}
                    className={`relative overflow-hidden rounded-lg border border-border-default bg-bg-secondary ${bladeImageScale > 1 ? (bladeImageDrag ? 'cursor-grabbing' : 'cursor-grab') : 'cursor-zoom-in'}`}
                    onPointerDown={handleBladePointerDown}
                    onPointerMove={handleBladePointerMove}
                    onPointerUp={handleBladePointerUp}
                    onPointerCancel={handleBladePointerUp}
                  >
                    <img
                      ref={bladeImageElementRef}
                      src={selectedBladeImageUrl}
                      alt={bladeReplay.selected.view || '叶片巡检图像'}
                      className="h-[320px] w-full select-none object-cover bg-bg-secondary transition-transform duration-75"
                      draggable={false}
                      onLoad={syncBladeImageNaturalSize}
                      style={{
                        transform: `translate(${bladeImageOffset.x}px, ${bladeImageOffset.y}px) scale(${bladeImageScale})`,
                        transformOrigin: '0 0',
                      }}
                    />
                    {showBladeAnnotation && selectedBladeHasAnnotations && bladeImageNaturalSize.width > 0 && bladeImageNaturalSize.height > 0 && (
                      <svg
                        className="absolute inset-0 h-[320px] w-full transition-transform duration-75"
                        viewBox={`0 0 ${bladeImageNaturalSize.width} ${bladeImageNaturalSize.height}`}
                        preserveAspectRatio="xMidYMid slice"
                        style={{
                          transform: `translate(${bladeImageOffset.x}px, ${bladeImageOffset.y}px) scale(${bladeImageScale})`,
                          transformOrigin: '0 0',
                        }}
                      >
                        {displayedBladeAnnotations.map((region) => (
                          <g key={region.id}>
                            <rect
                              x={region.bbox.x}
                              y={region.bbox.y}
                              width={region.bbox.w}
                              height={region.bbox.h}
                              fill="rgba(248,81,73,0.08)"
                              stroke="#f85149"
                              strokeWidth={region.badge.strokeWidth}
                              pointerEvents="none"
                            />
                            <circle
                              cx={region.badge.cx}
                              cy={region.badge.cy}
                              r={region.badge.r}
                              fill="#f85149"
                              stroke="rgba(8,12,18,0.9)"
                              strokeWidth={region.badge.strokeWidth}
                              pointerEvents="none"
                            />
                            <text
                              x={region.badge.cx}
                              y={region.badge.cy + region.badge.r * 0.12}
                              fill="#ffffff"
                              fontSize={region.badge.r * 1.15}
                              fontWeight="700"
                              textAnchor="middle"
                              dominantBaseline="middle"
                              pointerEvents="none"
                            >
                              {region.displayIndex}
                            </text>
                            <g
                              pointerEvents="auto"
                              className="cursor-pointer"
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => {
                                event.stopPropagation();
                                deleteBladeAnnotation(region.id);
                              }}
                            >
                              <circle
                                cx={region.badge.deleteCx}
                                cy={region.badge.deleteCy}
                                r={region.badge.r * 0.72}
                                fill="#161b22"
                                stroke="#f85149"
                                strokeWidth={region.badge.strokeWidth}
                              />
                              <text
                                x={region.badge.deleteCx}
                                y={region.badge.deleteCy + region.badge.r * 0.04}
                                fill="#f85149"
                                fontSize={region.badge.r}
                                fontWeight="800"
                                textAnchor="middle"
                                dominantBaseline="middle"
                                pointerEvents="none"
                              >
                                ×
                              </text>
                            </g>
                          </g>
                        ))}
                      </svg>
                    )}
                  </div>

                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-text-primary">
                        {imageDisplayTitle(bladeReplay.selected)} · {datasetLabel(bladeReplay.selected.source_dataset)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {selectedBladeHasAnnotations && (
                        <button
                          type="button"
                          onClick={toggleBladeAnnotation}
                          className="rounded border border-accent-blue/40 px-2 py-1 text-[10px] text-accent-blue transition hover:border-accent-blue"
                        >
                          {showBladeAnnotation ? '隐藏标注' : '显示标注'}
                        </button>
                      )}
                      {selectedBladeHasModelResult && selectedBladeModelImageUrl && (
                        <>
                          <button
                            type="button"
                            onClick={exportBladeDiagnosisImage}
                            className="rounded border border-border-default px-2 py-1 text-[10px] text-text-secondary transition hover:border-accent-blue hover:text-accent-blue"
                          >
                            导出诊断图片
                          </button>
                        </>
                      )}
                      {bladeReplay.selected.has_damage && (
                        <span className="rounded bg-accent-yellow/15 px-2 py-1 text-[10px] text-accent-yellow">
                          损伤标注
                        </span>
                      )}
                      {bladeReplay.isManualSelection && (
                        <button
                          type="button"
                          onClick={returnToFirstBladeImage}
                          className="rounded border border-border-default px-2 py-1 text-[10px] text-text-secondary transition hover:border-accent-blue hover:text-accent-blue"
                        >
                          回到首张
                        </button>
                      )}
                    </div>
                  </div>

                  <div
                    ref={bladeThumbsRef}
                    className="grid max-h-[320px] grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-4"
                    onWheel={handleBladeFrameWheel}
                  >
                    {bladeReplay.frames.map((img, index) => {
                      const isSelected = img.image_path === bladeReplay.selected.image_path;
                      const isCurrent = img.image_path === bladeReplay.current.image_path;
                      return (
                        <button
                          key={`${img.image_path}-${index}`}
                          type="button"
                          onClick={() => selectBladeImage(img.image_path)}
                          className={`overflow-hidden rounded-lg border text-left transition ${isSelected ? 'border-accent-blue bg-accent-blue/5' : 'border-border-default bg-bg-secondary hover:border-accent-blue/60'}`}
                        >
                          {img.image_url ? (
                            <img src={img.image_url} alt={img.view || '巡检图像'} className="h-24 w-full object-cover bg-bg-secondary" />
                          ) : (
                            <div className="flex h-24 items-center justify-center text-[10px] text-text-muted">无图像</div>
                          )}
                          <div className="px-2 py-1.5">                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-[10px] text-text-secondary">
                                第 {(img.image_index ?? index) + 1}/{img.image_count || bladeReplay.frameCount} 张
                              </p>
                              {isCurrent && (
                                <span className="rounded bg-accent-green/15 px-1.5 py-0.5 text-[9px] text-accent-green">
                                  首张
                                </span>
                              )}
                            </div>
                            <p className="truncate text-[10px] text-text-muted">{imageDisplayTitle(img)}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="flex h-[320px] items-center justify-center rounded-lg border border-border-default bg-bg-secondary px-4 text-xs text-text-muted">
                  未接入真实叶片巡检图像数据。
                </div>
              )}
            </div>

            <div className="flex min-h-[320px] flex-col justify-between rounded-lg border border-border-default bg-bg-secondary p-4">
              <div>
                <div className="flex items-center justify-between gap-3">
                  <h4 className="text-sm font-medium">叶片诊断</h4>
                  <span className="text-[10px] text-text-muted">WindBlade YOLO</span>
                </div>
                {bladeReplay?.selected && (
                  <div className="mt-4 space-y-3 text-xs">
                    {[
                      ['数据集', datasetLabel(bladeReplay.selected.source_dataset)],
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-center justify-between gap-3 border-b border-border-default/60 pb-2">
                        <span className="text-text-muted">{label}</span>
                        <span className="max-w-[150px] truncate text-right font-mono text-text-secondary">{value}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-4 rounded border border-border-default/70 bg-bg-card/50 p-3 text-xs">
                  <p className="mb-2 font-medium text-text-primary">诊断结果</p>
                  {selectedBladeModelError ? (
                    <p className="text-accent-red">{selectedBladeModelError}</p>
                  ) : selectedBladeHasModelResult && selectedBladeModelResult ? (
                    <div className="space-y-2">
                      {[
                        ['结果', selectedBladeModelResult.damage_type],
                        ['置信度', `${(selectedBladeModelResult.confidence * 100).toFixed(1)}%`],
                        ['本次区域', `${selectedBladeModelResult.damage_regions.length}`],
                        ['累计标注', `${selectedBladeAnnotationRegions.length}`],
                      ].map(([label, value]) => (
                        <div key={label} className="flex items-center justify-between gap-3">
                          <span className="text-text-muted">{label}</span>
                          <span className="max-w-[150px] truncate text-right font-mono text-text-secondary">{value}</span>
                        </div>
                      ))}
                      {selectedBladeModelResult.message && (
                        <p className="pt-1 text-[10px] leading-4 text-text-muted">
                          {selectedBladeModelResult.message}
                        </p>
                      )}
                      {selectedBladeAnnotationRegions.length > 0 && (
                        <div className="max-h-[260px] space-y-1 overflow-y-auto border-t border-border-default/60 pt-2 pr-1">
                          {selectedBladeAnnotationRegions.map((region, index) => (
                            <div key={region.id} className="flex items-center justify-between gap-2">
                              <span className="min-w-0 truncate text-text-muted">
                                #{index + 1} {region.label} {(region.confidence * 100).toFixed(1)}%
                              </span>
                              <button
                                type="button"
                                onClick={() => deleteBladeAnnotation(region.id)}
                                className="shrink-0 rounded border border-border-default px-1.5 py-0.5 text-[10px] text-text-secondary hover:border-accent-red hover:text-accent-red"
                              >
                                删除
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-text-muted">未运行模型诊断</p>
                  )}
                </div>
              </div>

              <button
                type="button"
                disabled={!bladeReplay?.selected || bladeModelLoading}
                onClick={runSelectedBladeDiagnosis}
                className="mt-4 rounded-lg border border-accent-blue/35 bg-accent-blue/10 px-4 py-3 text-sm font-medium text-accent-blue transition hover:border-accent-blue disabled:cursor-not-allowed disabled:opacity-60"
              >
                {bladeModelLoading ? '模型诊断中...' : '运行模型诊断'}
              
              </button>
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
          {scadaReplay.current && (
            <div className="mb-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4 xl:grid-cols-8">
              {[
                [scadaReplay.current.power_label || '有功功率', displayValue(scadaReplay.current.power_kw, 3), scadaReplay.current.power_unit || 'p.u.'],
                ['风速', displayValue(scadaReplay.current.wind_speed_ms, 2), 'm/s'],
                ['转速', displayValue(scadaReplay.current.rotor_rpm, 2), 'rpm'],
                ['发电机温度', displayValue(scadaReplay.current.gen_temperature_c, 1), '°C'],
                ['齿轮箱温度', displayValue(scadaReplay.current.gearbox_temperature_c, 1), '°C'],
                ['轴承温度', displayValue(scadaReplay.current.bearing_temperature_c, 1), '°C'],
                ['桨距角', displayValue(scadaReplay.current.pitch_angle_deg, 1), '°'],
                ['电网频率', displayValue(scadaReplay.current.grid_frequency_hz, 2), 'Hz'],
                scadaReplay.current.nacelle_direction_deg != null ? ['机舱方向', displayValue(scadaReplay.current.nacelle_direction_deg, 1), '°'] : null,
                scadaReplay.current.ambient_temp_c != null ? ['环境温度', displayValue(scadaReplay.current.ambient_temp_c, 1), '°C'] : null,
              ].filter((item): item is [string, string, string] => Boolean(item)).map(([label, value, unit]) => (
                <div key={label} className="rounded bg-bg-secondary px-3 py-2">
                  <p className="text-[10px] text-text-muted">{label}</p>
                  <p className="mt-1 font-mono text-accent-cyan">{value}{unit ? ` ${unit}` : ''}</p>
                </div>
              ))}
            </div>
          )}
          {scada.length > 0 ? (
            <div ref={chartRef} style={{ height: 300 }} />
          ) : (
            <div className="h-[300px] flex items-center justify-center rounded-lg border border-border-default bg-bg-secondary px-4 text-xs text-text-muted">
              {scadaMissing ? '未导入真实 SCADA 数据。' : '加载中...'}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium">环境监控</h3>
              {wind?.source_dataset && (
                <span className="text-[10px] text-text-muted">
                  {datasetLabel(wind.source_dataset)}
                </span>
              )}
            </div>
            {wind ? (
              <>
                <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-3">
                {windMetricCards.map(([label, value, unit]) => (
                  <div key={label} className="bg-bg-hover rounded p-2 text-center">
                    <p className="text-text-muted text-[10px]">{label}</p>
                    <p className="text-accent-cyan font-mono font-bold">{value}{unit}</p>
                  </div>
                ))}
                </div>
              </>
            ) : (
              <p className="text-xs text-text-muted">
                {windMissing ? '未接入环境数据。' : '加载中...'}
              </p>
            )}
          </div>

          <div className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium">
              振动波形
              {vibrationReplay?.current && (
                <span className="ml-2 text-xs font-normal text-text-muted">
                  RMS: <span className="text-accent-cyan">{displayValue(vibrationReplay.current.rms, 3)}</span>
                  {vibrationReplay.current.fault_detected && <span className="ml-1 px-1.5 py-0.5 rounded bg-accent-red/20 text-accent-red text-[10px]">故障信号</span>}
                </span>
              )}
              </h3>
              {vibrationReplay?.current?.source_dataset && (
                <span className="text-[10px] text-text-muted">
                  {datasetLabel(vibrationReplay.current.source_dataset)}
                </span>
              )}
            </div>
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
                    <span>置信度 {(fault.confidence * 100).toFixed(0)}%</span>
                    <span>{fault.status === 'open' ? '待处理' : '已关闭'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <CopilotFAB pageContext={{
        turbine_id: id ? Number(id) : undefined,
        turbine_name: turbine?.name,
        turbine_status: turbine?.status,
        hi_value: turbine?.hi_value,
        power_mw: turbine?.power_mw,
        fault_count: faults.length,
        recent_faults: faults.slice(0, 5).map(f => f.fault_type),
        has_vibration: !!vibration?.rms,
        has_blade_images: bladeImages.length > 0,
      }} />
    </div>
  );
}

