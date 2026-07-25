import { ChangeEvent, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import type {
  AutoFaultDetectionResult,
  BatchAutoFaultDetectionResult,
  BatchAutoFaultRecord,
  DiagnosisSignalInsight,
  Fault,
  FaultDetail,
  Turbine,
  TurbineSummary,
  VibrationPreview,
} from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import { fetchUserPreferences, loadLocalPreferences, PREFERENCES_UPDATED_EVENT, type UserPreferences } from '../../services/preferences';

const COMPONENT_OPTIONS = [
  { value: 'blade', label: '叶片' },
  { value: 'gearbox_high_speed', label: '齿轮箱高速轴' },
  { value: 'gearbox_intermediate', label: '齿轮箱中间轴' },
  { value: 'generator_bearing_de', label: '发电机驱动端轴承' },
  { value: 'generator_bearing_nde', label: '发电机非驱动端轴承' },
  { value: 'main_bearing', label: '主轴承' },
];

const BATCH_PAGE_SIZE = 5;
const CAUSE_PAGE_SIZE = 3;

type BatchSortMode = 'region' | 'turbine' | 'confidence_desc' | 'confidence_asc' | 'status' | 'fault_type' | 'generated_desc';
type BatchGroupMode = 'region' | 'status' | 'fault_type' | 'none';
type FaultTimeField = 'discovered_at' | 'processing_started_at' | 'closed_at' | 'failed_at' | 'last_action_at';
type MonitorMode = 'single' | 'group';
type DetectionFilter = 'all' | 'suspected_fault' | 'no_fault_detected';
type TurbineComponentKey = 'blade_root' | 'pitch' | 'main_shaft' | 'main_bearing' | 'gearbox' | 'brake' | 'generator' | 'cooling' | 'electrical' | 'sensor';

interface TopologyCauseNode {
  id: string;
  label: string;
  detail: string;
  priority: string;
  score: number;
  component: TurbineComponentKey;
}

interface TopologyFaultNode {
  id: number;
  label: string;
  turbineLabel: string;
  component: TurbineComponentKey;
  confidence: number;
  priority?: string;
  processingStatus?: string;
  workOrderTitle?: string | null;
  selected: boolean;
  transient?: boolean;
}

interface TurbineOptionRow {
  turbine: Turbine;
  faultCount: number;
  activeFaultCount: number;
  pendingFaultCount: number;
  highPriorityFaultCount: number;
  suspectedCount: number;
  avgConfidence: number | null;
  latestDetection?: BatchAutoFaultRecord;
}

const PROCESSING_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  assigned: '已指派',
  processing: '处理中',
  closed: '已关闭',
  failed: '处理失败',
};

const PRIORITY_LABELS: Record<string, string> = {
  urgent: '紧急',
  high: '高',
  medium: '中',
  low: '低',
};

const FAULT_LABELS: Record<string, string> = {
  bearing_inner_race_wear: '轴承内圈磨损',
  bearing_inner_race: '轴承内圈故障',
  bearing_outer_race: '轴承外圈故障',
  gearbox_tooth_pitting: '齿轮箱齿面点蚀',
  gearbox_tooth_wear: '齿轮箱齿面磨损',
  generator_overheat: '发电机过热',
  blade_leading_edge_erosion: '叶片前缘腐蚀',
  pitch_system_fault: '变桨系统故障',
  main_shaft_misalignment: '主轴不对中',
  cooling_system_fault: '冷却系统故障',
  electrical_connection: '电气连接异常',
  no_fault_detected: '未识别到明确故障',
};

const COMPONENT_LABELS: Record<TurbineComponentKey, string> = {
  blade_root: '轮毂/叶根',
  pitch: '变桨',
  main_shaft: '主轴',
  main_bearing: '主轴承',
  gearbox: '齿轮箱',
  brake: '制动器',
  generator: '发电机',
  cooling: '冷却',
  electrical: '电气',
  sensor: '风速风向',
};

const COMPONENT_POINTS: Record<TurbineComponentKey, { x: number; y: number }> = {
  blade_root: { x: 360, y: 174 },
  pitch: { x: 360, y: 150 },
  main_bearing: { x: 396, y: 174 },
  main_shaft: { x: 426, y: 174 },
  gearbox: { x: 477, y: 174 },
  brake: { x: 523, y: 174 },
  generator: { x: 567, y: 174 },
  cooling: { x: 566, y: 119 },
  electrical: { x: 546, y: 230 },
  sensor: { x: 584, y: 86 },
};

const COMPONENT_LABEL_OFFSETS: Record<TurbineComponentKey, { x: number; y: number; anchor?: 'start' | 'middle' | 'end' }> = {
  blade_root: { x: -38, y: 42, anchor: 'middle' },
  pitch: { x: -42, y: -24, anchor: 'middle' },
  main_bearing: { x: -10, y: 40, anchor: 'middle' },
  main_shaft: { x: 0, y: -28, anchor: 'middle' },
  gearbox: { x: 0, y: 48, anchor: 'middle' },
  brake: { x: 0, y: -28, anchor: 'middle' },
  generator: { x: 38, y: 42, anchor: 'middle' },
  cooling: { x: 0, y: -28, anchor: 'middle' },
  electrical: { x: 0, y: 42, anchor: 'middle' },
  sensor: { x: 34, y: -6, anchor: 'start' },
};

const COMPONENT_ORDER: TurbineComponentKey[] = [
  'blade_root',
  'pitch',
  'main_bearing',
  'main_shaft',
  'gearbox',
  'brake',
  'generator',
  'cooling',
  'electrical',
  'sensor',
];

const EMPTY_DIAGNOSIS_SIGNALS: DiagnosisSignalInsight[] = [];

function faultLabel(type: string) {
  return FAULT_LABELS[type] || type;
}

function componentForFaultType(faultType: string): TurbineComponentKey {
  if (faultType.includes('blade')) return 'blade_root';
  if (faultType.includes('pitch')) return 'pitch';
  if (faultType.includes('shaft')) return 'main_shaft';
  if (faultType.includes('bearing')) return 'main_bearing';
  if (faultType.includes('gearbox')) return 'gearbox';
  if (faultType.includes('brake')) return 'brake';
  if (faultType.includes('generator')) return 'generator';
  if (faultType.includes('cooling')) return 'cooling';
  if (faultType.includes('electrical')) return 'electrical';
  if (faultType.includes('sensor') || faultType.includes('wind')) return 'sensor';
  return 'gearbox';
}

function componentForSignal(signalName: string, fallbackFaultType?: string): TurbineComponentKey {
  if (signalName.includes('叶片') || signalName.includes('桨距') || signalName.includes('图像')) return 'blade_root';
  if (signalName.includes('变桨')) return 'pitch';
  if (signalName.includes('主轴') || signalName.includes('对中') || signalName.includes('联轴器')) return 'main_shaft';
  if (signalName.includes('轴承') || signalName.includes('包络')) return 'main_bearing';
  if (signalName.includes('齿轮') || signalName.includes('油温') || signalName.includes('金属颗粒') || signalName.includes('扭矩')) return 'gearbox';
  if (signalName.includes('制动') || signalName.includes('刹车')) return 'brake';
  if (signalName.includes('发电机') || signalName.includes('绕组') || signalName.includes('无功')) return 'generator';
  if (signalName.includes('冷却')) return 'cooling';
  if (signalName.includes('电气') || signalName.includes('连接')) return 'electrical';
  if (signalName.includes('风速') || signalName.includes('风向') || signalName.includes('传感器')) return 'sensor';
  return fallbackFaultType ? componentForFaultType(fallbackFaultType) : 'gearbox';
}

function componentTone(component: TurbineComponentKey, activeComponents: Set<TurbineComponentKey>, selectedComponent?: TurbineComponentKey) {
  if (component === selectedComponent) return '#ff4d5e';
  if (activeComponents.has(component)) return '#f6b94a';
  return '#58a6ff';
}

function shortenText(text: string | undefined | null, max = 18) {
  if (!text) return '--';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function topologyPercent(value?: number | null) {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`;
}

function priorityLabel(priority: string) {
  if (priority === 'high') return '高';
  if (priority === 'medium') return '中';
  return '低';
}

function priorityClass(priority: string) {
  if (priority === 'high') return 'bg-accent-red/20 text-accent-red';
  if (priority === 'medium') return 'bg-accent-yellow/20 text-accent-yellow';
  return 'bg-text-muted/20 text-text-muted';
}

function detectionStatusLabel(status: string) {
  if (status === 'suspected_fault') return '疑似故障';
  if (status === 'no_fault_detected') return '未检出';
  return status;
}

function turbineStatusLabel(status: string) {
  if (status === 'normal') return '正常';
  if (status === 'warning') return '预警';
  if (status === 'fault') return '故障';
  return status;
}

function processingStatusLabel(status?: string) {
  return PROCESSING_STATUS_LABELS[status || 'pending'] || status || '待处理';
}

function processingStatusClass(status?: string) {
  if (status === 'failed') return 'bg-accent-red/20 text-accent-red';
  if (status === 'closed') return 'bg-accent-green/20 text-accent-green';
  if (status === 'processing') return 'bg-accent-blue/20 text-accent-blue';
  if (status === 'assigned') return 'bg-accent-cyan/20 text-accent-cyan';
  return 'bg-accent-yellow/20 text-accent-yellow';
}

function priorityLabelValue(priority?: string) {
  return PRIORITY_LABELS[priority || 'medium'] || priority || '中';
}

function faultPriorityClass(priority?: string) {
  if (priority === 'urgent') return 'bg-accent-red text-white';
  if (priority === 'high') return 'bg-accent-red/20 text-accent-red';
  if (priority === 'low') return 'bg-text-muted/20 text-text-muted';
  return 'bg-accent-yellow/20 text-accent-yellow';
}

function diagnosisTypeClass(faultType: string) {
  const value = faultType.toLowerCase();
  if (value.includes('healthy') || value.includes('normal') || value.includes('no_fault')) return 'text-accent-green';
  if (value.includes('erosion') || value.includes('blade')) return 'text-accent-yellow';
  if (value.includes('unbalance') || value.includes('imbalance') || value.includes('shaft')) return 'text-accent-cyan';
  if (value.includes('bearing') || value.includes('gearbox') || value.includes('fault')) return 'text-accent-red';
  return 'text-text-secondary';
}

function formatDateTime(value?: string | null) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function confidenceText(value?: number | null, digits = 0) {
  return typeof value === 'number' ? `${(value * 100).toFixed(digits)}%` : '--';
}

function batchGroupLabel(record: BatchAutoFaultRecord, mode: BatchGroupMode) {
  if (mode === 'region') return record.region || '未分组';
  if (mode === 'status') return detectionStatusLabel(record.status);
  if (mode === 'fault_type') return faultLabel(record.fault_type);
  return '';
}

function toVibrationFaultType(faultType: string) {
  if (faultType.includes('bearing')) return 'bearing_inner_race';
  if (faultType.includes('gearbox')) return 'gearbox_tooth_wear';
  if (faultType.includes('shaft')) return 'misalignment';
  return undefined;
}

function turbineStatusClass(status: string) {
  if (status === 'fault') return 'text-accent-red';
  if (status === 'warning') return 'text-accent-yellow';
  return 'text-accent-green';
}

function TurbinePicker({
  value,
  rows,
  onChange,
  align = 'right',
}: {
  value: number | null;
  rows: TurbineOptionRow[];
  onChange: (id: number) => void;
  align?: 'left' | 'right';
}) {
  const [open, setOpen] = useState(false);
  const selected = rows.find((row) => row.turbine.id === value);

  return (
    <div className="relative min-w-[260px]">
      <button
        type="button"
        onClick={() => setOpen((next) => !next)}
        className="w-full rounded border border-border-default bg-bg-secondary px-3 py-2 text-left text-xs text-text-primary hover:border-accent-blue focus:outline-none focus:border-accent-blue"
      >
        <span className="block truncate">{selected ? `${selected.turbine.name} · ${selected.turbine.region || '未分组'}` : '选择风机...'}</span>
        {selected && (
          <span className="mt-1 grid grid-cols-3 gap-1 text-[10px] text-text-muted">
            <span>故障 {selected.faultCount}</span>
            <span>疑似 {selected.suspectedCount}</span>
            <span>置信 {confidenceText(selected.avgConfidence)}</span>
          </span>
        )}
      </button>
      {open && (
        <div className={`absolute z-40 mt-1 w-[560px] max-w-[calc(100vw-56px)] overflow-hidden rounded-lg border border-border-default bg-bg-card shadow-xl ${align === 'right' ? 'right-0' : 'left-0'}`}>
          <div className="grid grid-cols-[1.5fr_0.7fr_0.55fr_0.55fr_0.7fr] gap-2 border-b border-border-default bg-bg-secondary px-3 py-2 text-[10px] text-text-muted">
            <span>风机</span>
            <span>状态</span>
            <span>故障</span>
            <span>疑似</span>
            <span>置信度</span>
          </div>
          <div className="max-h-72 overflow-auto">
            {rows.map((row) => (
              <button
                key={row.turbine.id}
                type="button"
                onClick={() => {
                  onChange(row.turbine.id);
                  setOpen(false);
                }}
                className={`grid w-full grid-cols-[1.5fr_0.7fr_0.55fr_0.55fr_0.7fr] gap-2 border-b border-border-default px-3 py-2 text-left text-xs hover:bg-bg-hover ${
                  row.turbine.id === value ? 'bg-accent-blue/10' : ''
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-text-primary">{row.turbine.name}</span>
                  <span className="block truncate text-[10px] text-text-muted">{row.turbine.region || '未分组'} · HI {row.turbine.hi_value?.toFixed?.(1) ?? '--'}</span>
                </span>
                <span className={turbineStatusClass(row.turbine.status)}>{turbineStatusLabel(row.turbine.status)}</span>
                <span className="font-mono text-text-secondary">{row.faultCount}</span>
                <span className="font-mono text-accent-yellow">{row.suspectedCount}</span>
                <span className="font-mono text-accent-cyan">{confidenceText(row.avgConfidence)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SignalEvidencePanel({ insights }: { insights: DiagnosisSignalInsight[] }) {
  const rows = insights.slice(0, 4);
  return (
    <section className="bg-bg-card border border-border-default rounded-lg overflow-hidden">
      <div className="border-b border-border-default px-4 py-3">
        <h3 className="text-sm font-medium">诊断依据</h3>
        <p className="mt-1 text-[10px] text-text-muted">信号特征、当前值和模型贡献度</p>
      </div>
      <div className="space-y-3 p-4">
        {rows.map((signal) => {
          const score = Math.max(0, Math.min(1, signal.contribution_score || 0));
          const component = componentForSignal(signal.sensor_name);
          const tone = signal.priority === 'high'
            ? 'bg-accent-red'
            : signal.priority === 'medium'
              ? 'bg-accent-yellow'
              : 'bg-accent-cyan';
          return (
            <div key={`${signal.sensor_name}-${signal.value}`} className="rounded border border-border-default bg-bg-secondary px-3 py-3">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-text-primary">{signal.sensor_name}</p>
                  <p className="mt-1 truncate text-[10px] text-text-muted">{COMPONENT_LABELS[component]} · {priorityLabel(signal.priority)}</p>
                </div>
                <span className="shrink-0 font-mono text-xs text-accent-cyan">{(score * 100).toFixed(0)}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-bg-hover">
                <div className={`h-full rounded ${tone}`} style={{ width: `${Math.max(4, score * 100)}%` }} />
              </div>
              <div className="mt-2 grid grid-cols-[0.8fr_1.2fr] gap-2 text-[10px] text-text-muted">
                <span className="truncate">当前值 <b className="font-normal text-text-secondary">{signal.value}</b></span>
                <span className="truncate">参考 <b className="font-normal text-text-secondary">{signal.normal_range}</b></span>
              </div>
              <p className="mt-2 line-clamp-2 text-[11px] leading-4 text-text-secondary">{signal.finding}</p>
            </div>
          );
        })}
        {rows.length === 0 && (
          <div className="rounded border border-border-default bg-bg-secondary px-3 py-8 text-center text-xs text-text-muted">
            暂无诊断依据
          </div>
        )}
      </div>
    </section>
  );
}

const DiagnosisTopology = memo(function DiagnosisTopology({
  turbine,
  turbineRows,
  causes,
  faults,
  onFaultSelect,
  onTurbineChange,
}: {
  turbine: Turbine | null;
  turbineRows: TurbineOptionRow[];
  causes: TopologyCauseNode[];
  faults: TopologyFaultNode[];
  onFaultSelect: (id: number) => void;
  onTurbineChange: (id: number) => void;
}) {
  const [hoveredFaultId, setHoveredFaultId] = useState<number | null>(null);
  const [hoveredCauseId, setHoveredCauseId] = useState<string | null>(null);
  const [hoveredComponent, setHoveredComponent] = useState<TurbineComponentKey | null>(null);
  const activeComponents = useMemo(
    () => new Set<TurbineComponentKey>([
      ...causes.map((cause) => cause.component),
      ...faults.map((fault) => fault.component),
    ]),
    [causes, faults],
  );
  const hoveredFault = useMemo(
    () => faults.find((fault) => fault.id === hoveredFaultId),
    [faults, hoveredFaultId],
  );
  const hoveredCause = useMemo(
    () => causes.find((cause) => cause.id === hoveredCauseId),
    [causes, hoveredCauseId],
  );
  const selectedFault = useMemo(
    () => faults.find((fault) => fault.selected),
    [faults],
  );
  const focusedComponent = hoveredComponent || hoveredFault?.component || hoveredCause?.component || selectedFault?.component;
  const selectedComponent = focusedComponent || faults[0]?.component;
  const turbineStatus = turbine ? turbineStatusLabel(turbine.status) : '未选择';
  const modelTone = turbine?.status === 'fault' ? '#ff4d5e' : turbine?.status === 'warning' ? '#f6b94a' : '#39d2c0';
  const updateHoveredComponent = useCallback((component: TurbineComponentKey | null) => {
    setHoveredComponent((current) => (current === component ? current : component));
  }, []);
  const updateHoveredCause = useCallback((causeId: string | null) => {
    setHoveredCauseId((current) => (current === causeId ? current : causeId));
  }, []);
  const updateHoveredFault = useCallback((faultId: number | null) => {
    setHoveredFaultId((current) => (current === faultId ? current : faultId));
  }, []);
  const componentOpacity = (component: TurbineComponentKey, base = 1) => {
    if (!focusedComponent || component === focusedComponent) return base;
    return Math.max(0.16, base * 0.28);
  };
  const connectionOpacity = (component: TurbineComponentKey, selected: boolean) => {
    if (!focusedComponent) return selected ? 0.72 : 0.42;
    return component === focusedComponent ? 0.86 : 0.13;
  };
  const componentStrokeWidth = (component: TurbineComponentKey) => (focusedComponent === component ? 2.6 : 1.4);
  const leftRows = causes;
  const rightRows = faults;

  return (
    <section className="bg-bg-card border border-border-default rounded-lg overflow-hidden">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
        <div>
          <h3 className="text-sm font-medium">风机故障拓扑</h3>
          <p className="mt-1 text-[10px] text-text-muted">{turbine?.name || '未选择风机'} · {turbine?.region || '未分组'} · {turbineStatus}</p>
        </div>
        <div className="flex items-center gap-3">
          <TurbinePicker value={turbine?.id || null} rows={turbineRows} onChange={onTurbineChange} />
          <div className="grid grid-cols-3 gap-2 text-right text-[10px]">
            <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">依据 {causes.length}</span>
            <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">故障 {faults.length}</span>
            <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">部件 {activeComponents.size}</span>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg viewBox="0 0 1040 430" className="h-[430px] min-w-[1040px] w-full bg-bg-secondary/60" role="img" aria-label="风机故障拓扑">
          <defs>
            <linearGradient id="nacelleShell" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#dcecff" stopOpacity="0.2" />
              <stop offset="48%" stopColor="#8fb9e8" stopOpacity="0.12" />
              <stop offset="100%" stopColor="#dcecff" stopOpacity="0.08" />
            </linearGradient>
            <linearGradient id="drivetrainSteel" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#dcecff" stopOpacity="0.82" />
              <stop offset="100%" stopColor="#58a6ff" stopOpacity="0.48" />
            </linearGradient>
          </defs>

          {leftRows.length === 0 && (
            <text x={310} y={200} fill="#8b949e" fontSize="12" textAnchor="middle">暂无故障原因 · 运行自动检测获取信号</text>
          )}
          {leftRows.map((cause, index) => {
            const y = 48 + index * 70;
            const point = COMPONENT_POINTS[cause.component];
            return (
              <g key={cause.id}>
                <path
                  d={`M 252 ${y + 24} C 320 ${y + 24}, ${point.x - 65} ${point.y}, ${point.x} ${point.y}`}
                  fill="none"
                  stroke={componentTone(cause.component, activeComponents, selectedComponent)}
                  strokeOpacity={connectionOpacity(cause.component, hoveredCauseId === cause.id)}
                  strokeWidth={focusedComponent === cause.component ? '2.2' : '1.4'}
                />
                <circle cx={point.x} cy={point.y} r={focusedComponent === cause.component ? '6' : '4'} fill={componentTone(cause.component, activeComponents, selectedComponent)} />
              </g>
            );
          })}

          {rightRows.length === 0 && (
            <text x={480} y={200} fill="#8b949e" fontSize="12" textAnchor="middle">暂无故障记录</text>
          )}
          {rightRows.map((fault, index) => {
            const y = 58 + index * 80;
            const point = COMPONENT_POINTS[fault.component];
            return (
              <g key={fault.id}>
                <path
                  d={`M ${point.x} ${point.y} C ${point.x + 72} ${point.y}, 616 ${y + 26}, 648 ${y + 26}`}
                  fill="none"
                  stroke={componentTone(fault.component, activeComponents, selectedComponent)}
                  strokeOpacity={connectionOpacity(fault.component, fault.selected || hoveredFaultId === fault.id)}
                  strokeWidth={fault.selected || hoveredFaultId === fault.id ? '2.4' : '1.4'}
                />
                <circle cx={point.x} cy={point.y} r={fault.selected || hoveredFaultId === fault.id ? '7' : '4'} fill={componentTone(fault.component, activeComponents, selectedComponent)} />
              </g>
            );
          })}

          <g opacity="0.92">
            <path
              d="M372 136 C426 102, 558 102, 612 136 C626 145, 628 206, 614 216 C560 238, 438 238, 380 216 C366 206, 366 145, 372 136 Z"
              fill="url(#nacelleShell)"
              stroke="#c7d7e8"
              strokeOpacity="0.44"
              strokeWidth="1.4"
            />
            <path d="M384 152 H604" stroke="#c7d7e8" strokeOpacity="0.12" />
            <path d="M384 184 H604" stroke="#c7d7e8" strokeOpacity="0.12" />

            <circle cx="360" cy="174" r="27" fill={modelTone} fillOpacity={componentOpacity('blade_root', 0.2)} stroke={componentTone('blade_root', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('blade_root', 0.9)} strokeWidth={componentStrokeWidth('blade_root')} />
            <circle cx="360" cy="174" r="15" fill="#111923" stroke={componentTone('pitch', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('pitch', 0.78)} strokeWidth={componentStrokeWidth('pitch')} />
            <path d="M360 148 V160 M337 186 L348 180 M383 186 L372 180" stroke={componentTone('blade_root', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('blade_root', 0.58)} strokeWidth="5" strokeLinecap="round" />

            <rect x="390" y="153" width="12" height="42" rx="5" fill="#101923" stroke={componentTone('main_bearing', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('main_bearing', 0.82)} strokeWidth={componentStrokeWidth('main_bearing')} />
            <circle cx="396" cy="174" r="12" fill="#58a6ff" fillOpacity={componentOpacity('main_bearing', 0.14)} stroke={componentTone('main_bearing', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('main_bearing', 0.78)} />
            <rect x="402" y="169" width="48" height="10" rx="5" fill="url(#drivetrainSteel)" opacity={componentOpacity('main_shaft', 1)} stroke={componentTone('main_shaft', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('main_shaft', 0.76)} strokeWidth={componentStrokeWidth('main_shaft')} />
            <path d="M450 143 H506 L514 174 L506 205 H450 L440 174 Z" fill="#172233" fillOpacity={componentOpacity('gearbox', 1)} stroke={componentTone('gearbox', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('gearbox', 0.88)} strokeWidth={componentStrokeWidth('gearbox')} />
            <circle cx="466" cy="169" r="9" fill="#f6b94a" fillOpacity="0.16" stroke="#f6b94a" strokeOpacity="0.55" />
            <circle cx="488" cy="180" r="12" fill="#f6b94a" fillOpacity="0.12" stroke="#f6b94a" strokeOpacity="0.48" />
            <rect x="514" y="158" width="18" height="32" rx="5" fill="#101923" stroke={componentTone('brake', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('brake', 0.86)} strokeWidth={componentStrokeWidth('brake')} />
            <line x1="523" y1="158" x2="523" y2="190" stroke={componentTone('brake', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('brake', 0.5)} />
            <rect x="536" y="146" width="62" height="56" rx="18" fill="#122437" fillOpacity={componentOpacity('generator', 1)} stroke={componentTone('generator', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('generator', 0.9)} strokeWidth={componentStrokeWidth('generator')} />
            <circle cx="566" cy="174" r="19" fill="#39d2c0" fillOpacity="0.12" stroke="#39d2c0" strokeOpacity="0.48" />
            <path d="M548 166 C558 156, 576 156, 586 166 M548 182 C558 192, 576 192, 586 182" stroke="#39d2c0" strokeOpacity="0.45" fill="none" />

            <rect x="540" y="108" width="52" height="22" rx="6" fill="#101923" stroke={componentTone('cooling', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('cooling', 0.78)} strokeWidth={componentStrokeWidth('cooling')} />
            <path d="M548 114 H584 M548 121 H584" stroke={componentTone('cooling', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('cooling', 0.5)} />
            <rect x="522" y="216" width="48" height="28" rx="7" fill="#101923" stroke={componentTone('electrical', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('electrical', 0.78)} strokeWidth={componentStrokeWidth('electrical')} />
            <path d="M534 230 H558 M546 220 V240" stroke={componentTone('electrical', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('electrical', 0.54)} />
            <path d="M584 108 V86 M572 86 H596 M584 86 L599 78" stroke={componentTone('sensor', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('sensor', 0.8)} strokeWidth={componentStrokeWidth('sensor')} />
            <circle cx="584" cy="86" r="5" fill={componentTone('sensor', activeComponents, selectedComponent)} fillOpacity={componentOpacity('sensor', 0.42)} stroke={componentTone('sensor', activeComponents, selectedComponent)} />
          </g>

          {COMPONENT_ORDER.map((component) => {
            const point = COMPONENT_POINTS[component];
            const active = activeComponents.has(component);
            const tone = componentTone(component, activeComponents, selectedComponent);
            return (
              <g
                key={component}
                className="cursor-pointer"
                onMouseEnter={() => updateHoveredComponent(component)}
                onMouseLeave={() => updateHoveredComponent(null)}
                onFocus={() => updateHoveredComponent(component)}
                onBlur={() => updateHoveredComponent(null)}
                role="button"
                tabIndex={0}
              >
                <circle cx={point.x} cy={point.y} r={active ? 8 : 5} fill={tone} fillOpacity={active ? '0.8' : '0.25'} stroke={tone} strokeWidth="1.5" />
                <text
                  x={point.x + COMPONENT_LABEL_OFFSETS[component].x}
                  y={point.y + COMPONENT_LABEL_OFFSETS[component].y}
                  fill={active ? tone : '#8d9aaa'}
                  fontSize="11"
                  fontWeight={active ? '600' : '500'}
                  opacity={active ? '1' : '0.72'}
                  textAnchor={COMPONENT_LABEL_OFFSETS[component].anchor || 'start'}
                >
                  {COMPONENT_LABELS[component]}
                </text>
              </g>
            );
          })}

          {leftRows.map((cause, index) => {
            const y = 48 + index * 70;
            const tone = componentTone(cause.component, activeComponents, selectedComponent);
            return (
              <g
                key={`cause-${cause.id}`}
                onMouseEnter={() => updateHoveredCause(cause.id)}
                onMouseLeave={() => updateHoveredCause(null)}
              >
                <rect x="28" y={y} width="224" height="54" rx="8" fill={hoveredCauseId === cause.id ? '#182536' : '#111923'} stroke={tone} strokeOpacity={hoveredCauseId === cause.id ? '0.84' : '0.34'} strokeWidth={hoveredCauseId === cause.id ? '2' : '1'} />
                <text x="42" y={y + 18} fill="#dcecff" fontSize="12" fontWeight="600">{shortenText(cause.label, 15)}</text>
                <text x="42" y={y + 36} fill="#8d9aaa" fontSize="10">{shortenText(cause.detail, 18)}</text>
                <rect x="201" y={y + 25} width="39" height="16" rx="8" fill="#071A35" stroke={tone} strokeOpacity="0.38" />
                <text x="220.5" y={y + 36} fill={tone} fontSize="10" fontWeight="700" textAnchor="middle">{topologyPercent(cause.score)}</text>
              </g>
            );
          })}

          {rightRows.map((fault, index) => {
            const y = 58 + index * 80;
            const tone = componentTone(fault.component, activeComponents, selectedComponent);
            const disabled = Boolean(fault.transient);
            return (
              <g
                key={`fault-${fault.id}`}
                onClick={() => !disabled && onFaultSelect(fault.id)}
                onMouseEnter={() => !disabled && updateHoveredFault(fault.id)}
                onMouseLeave={() => updateHoveredFault(null)}
                onFocus={() => !disabled && updateHoveredFault(fault.id)}
                onBlur={() => updateHoveredFault(null)}
                onKeyDown={(event) => {
                  if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault();
                    onFaultSelect(fault.id);
                  }
                }}
                className={disabled ? '' : 'cursor-pointer'}
                role={disabled ? undefined : 'button'}
                tabIndex={disabled ? undefined : 0}
              >
                <rect x="648" y={y} width="224" height="54" rx="8" fill={fault.selected || hoveredFaultId === fault.id ? '#182536' : '#111923'} stroke={tone} strokeOpacity={fault.selected || hoveredFaultId === fault.id ? '0.9' : '0.38'} strokeWidth={fault.selected || hoveredFaultId === fault.id ? '2' : '1'} />
                <text x="662" y={y + 18} fill="#dcecff" fontSize="12" fontWeight="600">{shortenText(fault.label, 14)}</text>
                <text x="662" y={y + 36} fill="#8d9aaa" fontSize="10">{shortenText(fault.turbineLabel, 9)} · {shortenText(processingStatusLabel(fault.processingStatus), 4)}</text>
                <rect x="823" y={y + 8} width="38" height="16" rx="8" fill="#071A35" stroke={tone} strokeOpacity="0.38" />
                <text x="842" y={y + 19} fill={tone} fontSize="10" fontWeight="700" textAnchor="middle">{topologyPercent(fault.confidence)}</text>
                <text x="858" y={y + 36} fill="#8d9aaa" fontSize="10" textAnchor="end">{shortenText(fault.workOrderTitle || '未关联工单', 8)}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
});

export default function DiagnosisPage() {
  const [faults, setFaults] = useState<Fault[]>([]);
  const [selected, setSelected] = useState<FaultDetail | null>(null);
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [selectedTurbineId, setSelectedTurbineId] = useState<number | null>(null);
  const [monitorMode, setMonitorMode] = useState<MonitorMode>('single');
  const [component, setComponent] = useState('blade');
  const [windowHours, setWindowHours] = useState(24);
  const [autoResult, setAutoResult] = useState<AutoFaultDetectionResult | null>(null);
  const [batchResult, setBatchResult] = useState<BatchAutoFaultDetectionResult | null>(null);
  const [batchPage, setBatchPage] = useState(1);
  const [groupTurbinePage, setGroupTurbinePage] = useState(1);
  const [causePage, setCausePage] = useState(1);
  const [batchSort, setBatchSort] = useState<BatchSortMode>('region');
  const [batchGroup, setBatchGroup] = useState<BatchGroupMode>('region');
  const [batchRegion, setBatchRegion] = useState('all');
  const [batchStatus, setBatchStatus] = useState('all');
  const [detectionFilter, setDetectionFilter] = useState<DetectionFilter>('all');
  const [confidenceMin, setConfidenceMin] = useState(0);
  const [topologyFaultTypeFilter, setTopologyFaultTypeFilter] = useState('all');
  const [openStatCard, setOpenStatCard] = useState<string | null>(null);
  const [faultKeyword, setFaultKeyword] = useState('');
  const [faultRegionFilter, setFaultRegionFilter] = useState('all');
  const [faultStatusFilter, setFaultStatusFilter] = useState('all');
  const [faultProcessingFilter, setFaultProcessingFilter] = useState('all');
  const [faultHandlerFilter, setFaultHandlerFilter] = useState('all');
  const [faultPriorityFilter, setFaultPriorityFilter] = useState('all');
  const [faultTimeField, setFaultTimeField] = useState<FaultTimeField>('discovered_at');
  const [faultDateFrom, setFaultDateFrom] = useState('');
  const [faultDateTo, setFaultDateTo] = useState('');
  const [vibration, setVibration] = useState<VibrationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoLoading, setAutoLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [error, setError] = useState('');
  const [riskFirst, setRiskFirst] = useState(() => loadLocalPreferences().riskFirst);
  const waveformRef = useRef<HTMLDivElement>(null);
  const spectrumRef = useRef<HTMLDivElement>(null);

  const viewDetail = useCallback(async (id: number) => {
    const { data } = await api.get(`/diagnosis/faults/${id}`);
    setSelected(data);
    setSelectedTurbineId(data.turbine_id);
    setAutoResult(null);
  }, []);

  const loadVibration = useCallback(async (turbineId: number, nextComponent: string, faultType: string | undefined) => {
    const params: Record<string, string | number> = { turbine_id: turbineId, component: nextComponent };
    if (faultType) params.fault_type = faultType;
    const { data } = await api.get('/diagnosis/vibration', { params });
    setVibration(data);
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.all([
      api.get('/diagnosis/faults'),
      api.get('/turbines/'),
    ])
      .then(([faultRes, turbineRes]) => {
        if (!mounted) return;
        const faultData = faultRes.data as Fault[];
        const turbineData = turbineRes.data as TurbineSummary;
        setFaults(faultData);
        setTurbines(turbineData.turbines);
        const initialTurbineId = faultData[0]?.turbine_id || turbineData.turbines[0]?.id || null;
        setSelectedTurbineId(initialTurbineId);
        if (faultData[0]) viewDetail(faultData[0].id);
      })
      .catch(() => setError('诊断数据加载失败'))
      .finally(() => setLoading(false));
    return () => { mounted = false; };
  }, [viewDetail]);

  useEffect(() => {
    const applyPrefs = (prefs: UserPreferences) => setRiskFirst(prefs.riskFirst);
    applyPrefs(loadLocalPreferences());
    fetchUserPreferences().then(applyPrefs).catch(() => undefined);
    const handlePreferences = (event: Event) => {
      applyPrefs((event as CustomEvent<UserPreferences>).detail || loadLocalPreferences());
    };
    window.addEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
    return () => window.removeEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
  }, []);

  useEffect(() => {
    if (!selectedTurbineId) return;
    loadVibration(selectedTurbineId, component, undefined);
  }, [selectedTurbineId, component, loadVibration]);

  useEffect(() => {
    if (selected && selectedTurbineId && selected.turbine_id !== selectedTurbineId) {
      setSelected(null);
    }
  }, [selected, selectedTurbineId]);

  useEffect(() => {
    if (monitorMode !== 'single' || !selectedTurbineId) return;
    setAutoResult(null);  // Clear stale data on turbine switch
    runAutoDetect();
    const timer = window.setInterval(runAutoDetect, 30000);
    return () => window.clearInterval(timer);
  }, [monitorMode, selectedTurbineId, component, windowHours]);

  useEffect(() => {
    if (monitorMode !== 'group' || turbines.length === 0) return;
    runBatchDetect();
    const timer = window.setInterval(runBatchDetect, 30000);
    return () => window.clearInterval(timer);
  }, [monitorMode, batchRegion, batchStatus, component, windowHours, turbines.length]);

  useEffect(() => {
    setBatchPage(1);
    setGroupTurbinePage(1);
    setCausePage(1);
  }, [monitorMode, batchRegion, batchStatus, component, windowHours, selectedTurbineId, detectionFilter, confidenceMin, topologyFaultTypeFilter]);

  useEffect(() => {
    setCausePage(1);
  }, [groupTurbinePage, batchSort]);

  useEffect(() => {
    if (!waveformRef.current || !vibration?.waveform?.length) return;
    const chart = echarts.init(waveformRef.current, 'dark');
    const times = vibration.waveform.map((_, i) => (i * vibration.duration_seconds / vibration.waveform.length).toFixed(3));
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 24, right: 18, bottom: 26, left: 42 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: times, axisLabel: { color: '#5c6975', fontSize: 9 } },
      yAxis: { type: 'value', name: 'mm/s²', axisLabel: { color: '#5c6975', fontSize: 10 } },
      series: [{ name: '振动波形', type: 'line', data: vibration.waveform, symbol: 'none', lineStyle: { color: '#39d2c0', width: 1 }, areaStyle: { color: 'rgba(57,210,192,0.06)' } }],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [vibration]);

  useEffect(() => {
    if (!spectrumRef.current || !vibration?.spectrum?.length) return;
    const chart = echarts.init(spectrumRef.current, 'dark');
    const display = vibration.spectrum.slice(0, 120);
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { top: 24, right: 16, bottom: 26, left: 38 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: display.map((_, i) => String(i)), axisLabel: { color: '#5c6975', fontSize: 9 } },
      yAxis: { type: 'value', name: 'Amp', axisLabel: { color: '#5c6975', fontSize: 10 } },
      series: [{ name: '频谱占位', type: 'bar', data: display, itemStyle: { color: '#58a6ff' }, barWidth: 3 }],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [vibration]);

  const selectedTurbine = useMemo(
    () => turbines.find((t) => t.id === selectedTurbineId) || null,
    [selectedTurbineId, turbines],
  );

  const regionOptions = useMemo(
    () => Array.from(new Set(turbines.map((t) => t.region).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN')),
    [turbines],
  );

  const turbineRows = useMemo<TurbineOptionRow[]>(() => {
    const detectionByTurbine = new Map<number, BatchAutoFaultRecord[]>();
    for (const record of batchResult?.records || []) {
      const list = detectionByTurbine.get(record.turbine_id) || [];
      list.push(record);
      detectionByTurbine.set(record.turbine_id, list);
    }

    return turbines.map((turbine) => {
      const turbineFaults = faults.filter((fault) => fault.turbine_id === turbine.id);
      const detections = detectionByTurbine.get(turbine.id) || [];
      const confidenceValues = [
        ...turbineFaults.map((fault) => fault.confidence),
        ...detections.map((record) => record.confidence),
      ].filter((value) => typeof value === 'number');
      const latestDetection = detections
        .slice()
        .sort((a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime())[0];

      return {
        turbine,
        faultCount: turbineFaults.length,
        activeFaultCount: turbineFaults.filter((fault) => fault.status !== 'closed' && (fault.processing_status || 'pending') !== 'closed').length,
        pendingFaultCount: turbineFaults.filter((fault) => (fault.processing_status || 'pending') === 'pending').length,
        highPriorityFaultCount: turbineFaults.filter((fault) => ['urgent', 'high'].includes(fault.priority || 'medium')).length,
        suspectedCount: detections.filter((record) => record.status === 'suspected_fault').length,
        avgConfidence: confidenceValues.length
          ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length
          : null,
        latestDetection,
      };
    }).sort((a, b) => {
      if (!riskFirst) return a.turbine.name.localeCompare(b.turbine.name, 'zh-CN');
      const statusRank = (status: string) => (status === 'fault' ? 0 : status === 'warning' ? 1 : 2);
      return statusRank(a.turbine.status) - statusRank(b.turbine.status)
        || b.activeFaultCount - a.activeFaultCount
        || a.turbine.name.localeCompare(b.turbine.name, 'zh-CN');
      });
  }, [batchResult?.records, faults, riskFirst, turbines]);

  const turbineRowById = useMemo(() => {
    const map = new Map<number, TurbineOptionRow>();
    turbineRows.forEach((row) => map.set(row.turbine.id, row));
    return map;
  }, [turbineRows]);

  const faultHandlerOptions = useMemo(() => {
    const handlers = new Set(faults.map((f) => f.handler || '未指派'));
    return Array.from(handlers).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [faults]);

  const filteredFaults = useMemo(() => {
    const keyword = faultKeyword.trim().toLowerCase();
    const fromTime = faultDateFrom ? new Date(`${faultDateFrom}T00:00:00`).getTime() : null;
    const toTime = faultDateTo ? new Date(`${faultDateTo}T23:59:59`).getTime() : null;

    const filtered = faults.filter((fault) => {
      if (faultRegionFilter !== 'all' && fault.turbine_region !== faultRegionFilter) return false;
      if (faultStatusFilter !== 'all' && fault.status !== faultStatusFilter) return false;
      if (faultProcessingFilter !== 'all' && (fault.processing_status || 'pending') !== faultProcessingFilter) return false;
      if (faultHandlerFilter !== 'all' && (fault.handler || '未指派') !== faultHandlerFilter) return false;
      if (faultPriorityFilter !== 'all' && (fault.priority || 'medium') !== faultPriorityFilter) return false;

      if (keyword) {
        const text = [
          faultLabel(fault.fault_type),
          fault.fault_type,
          fault.turbine_name,
          fault.turbine_region,
          fault.handler || '未指派',
          fault.work_order_title,
          fault.status_note,
        ].join(' ').toLowerCase();
        if (!text.includes(keyword)) return false;
      }

      const rawTime = faultTimeField === 'discovered_at'
        ? fault.discovered_at || fault.detected_at
        : fault[faultTimeField];
      const recordTime = rawTime ? new Date(rawTime).getTime() : null;
      if ((fromTime || toTime) && !recordTime) return false;
      if (fromTime && recordTime && recordTime < fromTime) return false;
      if (toTime && recordTime && recordTime > toTime) return false;
      return true;
    });
    if (!riskFirst) return filtered;
    const priorityRank: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 };
    const processingRank: Record<string, number> = { failed: 0, pending: 1, assigned: 2, processing: 3, closed: 4 };
    return filtered.sort((a, b) => (
      (priorityRank[a.priority || 'medium'] ?? 4) - (priorityRank[b.priority || 'medium'] ?? 4)
      || (processingRank[a.processing_status || 'pending'] ?? 5) - (processingRank[b.processing_status || 'pending'] ?? 5)
      || new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
    ));
  }, [
    faultDateFrom,
    faultDateTo,
    faultHandlerFilter,
    faultKeyword,
    faultPriorityFilter,
    faultProcessingFilter,
    faultRegionFilter,
    faults,
    faultStatusFilter,
    faultTimeField,
    riskFirst,
  ]);

  const faultManagementCounts = useMemo(() => ({
    processing: filteredFaults.filter((f) => f.processing_status === 'processing' || f.processing_status === 'assigned').length,
    failed: filteredFaults.filter((f) => f.processing_status === 'failed').length,
    closed: filteredFaults.filter((f) => f.processing_status === 'closed').length,
  }), [filteredFaults]);

  const topologyFaultTypeOptions = useMemo(() => {
    const types = new Set<string>();
    faults.forEach((fault) => types.add(fault.fault_type));
    batchResult?.records?.forEach((record) => types.add(record.fault_type));
    return Array.from(types).sort((a, b) => faultLabel(a).localeCompare(faultLabel(b), 'zh-CN'));
  }, [batchResult?.records, faults]);

  const filteredBatchRecords = useMemo(() => {
    return (batchResult?.records || []).filter((record) => {
      if (detectionFilter !== 'all' && record.status !== detectionFilter) return false;
      if (record.confidence < confidenceMin) return false;
      if (topologyFaultTypeFilter !== 'all' && record.fault_type !== topologyFaultTypeFilter) return false;
      return true;
    });
  }, [batchResult?.records, confidenceMin, detectionFilter, topologyFaultTypeFilter]);

  const sortedBatchRecords = useMemo(() => {
    const records = [...filteredBatchRecords];
    records.sort((a, b) => {
      if (batchSort === 'confidence_desc') return b.confidence - a.confidence;
      if (batchSort === 'confidence_asc') return a.confidence - b.confidence;
      if (batchSort === 'turbine') return a.turbine_name.localeCompare(b.turbine_name, 'zh-CN');
      if (batchSort === 'status') {
        return a.status.localeCompare(b.status, 'zh-CN') || b.confidence - a.confidence;
      }
      if (batchSort === 'fault_type') {
        return faultLabel(a.fault_type).localeCompare(faultLabel(b.fault_type), 'zh-CN') || b.confidence - a.confidence;
      }
      if (batchSort === 'generated_desc') {
        return new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime();
      }
      return a.region.localeCompare(b.region, 'zh-CN') || a.turbine_name.localeCompare(b.turbine_name, 'zh-CN');
    });
    return records;
  }, [batchSort, filteredBatchRecords]);

  const totalBatchPages = Math.max(1, Math.ceil(sortedBatchRecords.length / BATCH_PAGE_SIZE));
  const currentBatchPage = Math.min(batchPage, totalBatchPages);
  const pagedBatchRecords = sortedBatchRecords.slice(
    (currentBatchPage - 1) * BATCH_PAGE_SIZE,
    currentBatchPage * BATCH_PAGE_SIZE,
  );

  const pagedBatchRows = useMemo(() => {
    const rows: Array<{ type: 'group'; label: string } | { type: 'record'; record: BatchAutoFaultRecord }> = [];
    let lastGroup = '';
    for (const record of pagedBatchRecords) {
      const nextGroup = batchGroupLabel(record, batchGroup);
      if (batchGroup !== 'none' && nextGroup !== lastGroup) {
        rows.push({ type: 'group', label: nextGroup });
        lastGroup = nextGroup;
      }
      rows.push({ type: 'record', record });
    }
    return rows;
  }, [batchGroup, pagedBatchRecords]);

  useEffect(() => {
    if (batchPage > totalBatchPages) setBatchPage(totalBatchPages);
  }, [batchPage, totalBatchPages]);

  const activeFaults = faults.filter((f) => f.status !== 'closed' && (f.processing_status || 'pending') !== 'closed');
  const pendingCount = faults.filter((f) => (f.processing_status || 'pending') === 'pending').length;
  const assignedOrProcessingCount = faults.filter((f) => ['assigned', 'processing'].includes(f.processing_status || '')).length;
  const closedCount = faults.filter((f) => f.status === 'closed' || f.processing_status === 'closed').length;
  const failedCount = faults.filter((f) => f.processing_status === 'failed').length;
  const highPriorityCount = faults.filter((f) => ['urgent', 'high'].includes(f.priority || 'medium')).length;
  const faultTurbineCount = turbines.filter((t) => t.status === 'fault').length;
  const warningTurbineCount = turbines.filter((t) => t.status === 'warning').length;
  const weekAgo = new Date(Date.now() - 7 * 86400000);
  const weekNew = faults.filter((f) => new Date(f.discovered_at || f.detected_at) > weekAgo).length;
  const avgConfidence = faults.length
    ? `${(faults.reduce((sum, f) => sum + f.confidence, 0) / faults.length * 100).toFixed(1)}%`
    : '--';

  const insights = useMemo<DiagnosisSignalInsight[]>(() => (
    autoResult?.signals
      || selected?.signal_insights
      || selected?.signals?.map((s) => ({
        sensor_name: s.sensor_name,
        value: `贡献度${(s.contribution_score * 100).toFixed(0)}%`,
        normal_range: `优先级${priorityLabelValue(s.priority)}`,
        contribution_score: s.contribution_score,
        priority: s.priority,
        finding: `${s.sensor_name}信号贡献度${(s.contribution_score * 100).toFixed(0)}%，来自故障诊断模型`,
      }))
      || EMPTY_DIAGNOSIS_SIGNALS
  ), [autoResult?.signals, selected?.signal_insights, selected?.signals]);

  const troubleshootingSteps = autoResult?.troubleshooting_steps
    || selected?.troubleshooting_steps
   
    || [];

  const groupCauseRecords = sortedBatchRecords;
  const groupTotalTurbinePages = Math.max(1, groupCauseRecords.length);
  const currentGroupTurbinePage = Math.min(groupTurbinePage, groupTotalTurbinePages);
  const currentGroupRecord = groupCauseRecords[currentGroupTurbinePage - 1] || null;
  const activeCauseInsights = monitorMode === 'group'
    ? currentGroupRecord?.signals || EMPTY_DIAGNOSIS_SIGNALS
    : insights;
  const activeTroubleshootingSteps = monitorMode === 'group'
    ? currentGroupRecord?.troubleshooting_steps || []
    : troubleshootingSteps;
  const causeTotalPages = Math.max(1, Math.ceil(activeCauseInsights.length / CAUSE_PAGE_SIZE));
  const currentCausePage = Math.min(causePage, causeTotalPages);
  const pagedCauseInsights = activeCauseInsights.slice(
    (currentCausePage - 1) * CAUSE_PAGE_SIZE,
    currentCausePage * CAUSE_PAGE_SIZE,
  );
  const highRiskSignals = activeCauseInsights.filter((s) => s.priority === 'high').length;
  const topologyCauses = useMemo<TopologyCauseNode[]>(() => {
    const fallbackFaultType = autoResult?.fault_type || selected?.fault_type;
    return activeCauseInsights.slice(0, 4).map((signal, index) => ({
      id: `${signal.sensor_name}-${index}`,
      label: signal.sensor_name,
      detail: `${signal.value} · ${signal.finding || signal.normal_range}`,
      priority: signal.priority,
      score: signal.contribution_score,
      component: componentForSignal(signal.sensor_name, fallbackFaultType),
    }));
  }, [activeCauseInsights, autoResult?.fault_type, selected?.fault_type]);

  const topologyFaults = useMemo<TopologyFaultNode[]>(() => {
    const scoped = selectedTurbineId
      ? faults.filter((fault) => fault.turbine_id === selectedTurbineId)
      : faults;
    const filtered = scoped.filter((fault) => {
      if (fault.confidence < confidenceMin) return false;
      if (topologyFaultTypeFilter !== 'all' && fault.fault_type !== topologyFaultTypeFilter) return false;
      return true;
    });
    const selectedInScope = selected && (!selectedTurbineId || selected.turbine_id === selectedTurbineId)
      && selected.confidence >= confidenceMin
      && (topologyFaultTypeFilter === 'all' || selected.fault_type === topologyFaultTypeFilter)
      ? selected
      : null;
    const provisionalDetection = autoResult
      && monitorMode === 'single'
      && selectedTurbineId === autoResult.turbine_id
      && autoResult.status === 'suspected_fault'
      && autoResult.confidence >= confidenceMin
      && (topologyFaultTypeFilter === 'all' || autoResult.fault_type === topologyFaultTypeFilter)
      && !filtered.some((fault) => fault.fault_type === autoResult.fault_type)
      ? {
        id: -900000 - autoResult.turbine_id,
        turbine_id: autoResult.turbine_id,
        turbine_name: selectedTurbine?.name,
        fault_type: autoResult.fault_type,
        confidence: autoResult.confidence,
        priority: autoResult.confidence >= 0.85 ? 'high' : 'medium',
        processing_status: 'pending',
        work_order_title: '实时检测',
      } as Fault
      : null;
    const candidates = selectedInScope
      ? [selectedInScope, ...filtered.filter((fault) => fault.id !== selectedInScope.id)]
      : filtered;
    const combinedCandidates = provisionalDetection
      ? [provisionalDetection, ...candidates]
      : candidates;

    return combinedCandidates.slice(0, 4).map((fault) => {
      const turbine = turbines.find((item) => item.id === fault.turbine_id);
      const transient = provisionalDetection?.id === fault.id;
      return {
        id: fault.id,
        label: faultLabel(fault.fault_type),
        turbineLabel: fault.turbine_name || turbine?.name || `风机 #${fault.turbine_id}`,
        component: componentForFaultType(fault.fault_type),
        confidence: fault.confidence,
        priority: fault.priority,
        processingStatus: fault.processing_status,
        workOrderTitle: transient ? '实时检测' : fault.work_order_title,
        selected: selectedInScope?.id === fault.id,
        transient,
      };
    });
  }, [autoResult, confidenceMin, faults, monitorMode, selected, selectedTurbine, selectedTurbineId, topologyFaultTypeFilter, turbines]);

  useEffect(() => {
    if (groupTurbinePage > groupTotalTurbinePages) setGroupTurbinePage(groupTotalTurbinePages);
  }, [groupTurbinePage, groupTotalTurbinePages]);

  useEffect(() => {
    if (causePage > causeTotalPages) setCausePage(causeTotalPages);
  }, [causePage, causeTotalPages]);

  const activeFaultRows = turbineRows.filter((row) => row.activeFaultCount > 0);
  const pendingFaultRows = turbineRows.filter((row) => row.pendingFaultCount > 0);
  const problemTurbineRows = turbineRows.filter((row) => row.turbine.status === 'fault' || row.turbine.status === 'warning');
  const highPriorityFaultRows = turbineRows.filter((row) => row.highPriorityFaultCount > 0);
  const cards = [
    { key: 'total', label: '总故障数', value: String(faults.length), unit: '条', color: 'text-accent-blue' },
    { key: 'active', label: '活跃故障', value: String(activeFaults.length), unit: '条', color: activeFaults.length ? 'text-accent-red' : 'text-accent-green', rows: activeFaultRows },
    { key: 'pending', label: '待处理', value: String(pendingCount), unit: '条', color: pendingCount ? 'text-accent-yellow' : 'text-accent-green', rows: pendingFaultRows },
    { key: 'processing', label: '处理中', value: String(assignedOrProcessingCount), unit: '条', color: assignedOrProcessingCount ? 'text-accent-cyan' : 'text-text-secondary' },
    { key: 'closed', label: '已关闭', value: String(closedCount), unit: '条', color: 'text-accent-green' },
    { key: 'failed', label: '处理失败', value: String(failedCount), unit: '条', color: failedCount ? 'text-accent-red' : 'text-text-secondary' },
    { key: 'problem-turbines', label: '故障/预警风机', value: `${faultTurbineCount}/${warningTurbineCount}`, unit: '台', color: faultTurbineCount ? 'text-accent-red' : 'text-accent-yellow', rows: problemTurbineRows },
    { key: 'avg-confidence', label: '平均置信度', value: avgConfidence, unit: '', color: 'text-accent-cyan' },
    { key: 'week-new', label: '本周新增', value: String(weekNew), unit: '条', color: weekNew ? 'text-accent-yellow' : 'text-text-secondary' },
    { key: 'high-priority', label: '高优先级', value: String(highPriorityCount), unit: '条', color: highPriorityCount ? 'text-accent-red' : 'text-accent-green', rows: highPriorityFaultRows },
    { key: 'high-signal', label: '高优先级信号', value: String(highRiskSignals), unit: '项', color: highRiskSignals ? 'text-accent-red' : 'text-accent-green' },
  ];

  function handleTurbineChange(id: number) {
    setSelectedTurbineId(id);
    setSelected(null);
    setAutoResult(null);
  }

  async function runAutoDetect() {
    if (!selectedTurbineId) return;
    setAutoLoading(true);
    setError('');
    try {
      const { data } = await api.post('/diagnosis/auto-detect', {
        turbine_id: selectedTurbineId,
        component,
        window_hours: windowHours,
        data_source: 'vibration',
      });
      setAutoResult(data);
      await loadVibration(selectedTurbineId, component, toVibrationFaultType(data.fault_type));
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '自动识别失败');
    } finally {
      setAutoLoading(false);
    }
  }

  async function runBatchDetect() {
    setBatchLoading(true);
    setError('');
    try {
      const payload: Record<string, string | number> = {
        component,
        window_hours: windowHours,
        data_source: 'vibration',
      };
      if (batchRegion !== 'all') payload.region = batchRegion;
      if (batchStatus !== 'all') payload.status = batchStatus;

      const { data } = await api.post('/diagnosis/auto-detect/batch', payload);
      setBatchResult(data);
      setBatchPage(1);
      if (!data.success) setError(data.message || '分组实时监测暂无记录');
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '分组实时监测同步失败');
    } finally {
      setBatchLoading(false);
    }
  }

  async function selectBatchRecord(record: BatchAutoFaultRecord) {
    setMonitorMode('single');
    setSelected(null);
    setSelectedTurbineId(record.turbine_id);
    setComponent(record.component);
    setAutoResult({
      turbine_id: record.turbine_id,
      component: record.component,
      analysis_window_hours: record.analysis_window_hours,
      status: record.status,
      fault_type: record.fault_type,
      confidence: record.confidence,
      confidence_interval: record.confidence_interval,
      algorithm_status: record.algorithm_status,
      message: record.message,
      generated_at: record.generated_at,
      signals: record.signals,
      troubleshooting_steps: record.troubleshooting_steps,
    });
    await loadVibration(record.turbine_id, record.component, toVibrationFaultType(record.fault_type));
  }

    const topologyMonitoringPanel = (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded border border-border-default bg-bg-secondary p-1 text-xs">
          <button
            onClick={() => setMonitorMode('single')}
            className={`rounded px-3 py-1.5 ${monitorMode === 'single' ? 'bg-accent-blue text-white' : 'text-text-secondary hover:text-text-primary'}`}
          >
            单台风机
          </button>
          <button
            onClick={() => setMonitorMode('group')}
            className={`rounded px-3 py-1.5 ${monitorMode === 'group' ? 'bg-accent-blue text-white' : 'text-text-secondary hover:text-text-primary'}`}
          >
            分组风机
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`rounded px-2 py-1 ${autoLoading || batchLoading ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-green/20 text-accent-green'}`}>
            {autoLoading || batchLoading ? '同步中' : '检测就绪'}
          </span>
          <button
            onClick={() => (monitorMode === 'group' ? runBatchDetect() : runAutoDetect())}
            className="rounded border border-border-default px-3 py-1.5 text-text-secondary hover:border-accent-blue hover:text-text-primary disabled:opacity-50"
            disabled={autoLoading || batchLoading}
          >
            立即刷新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-2">
        {monitorMode === 'single' ? (
          <div className="text-xs text-text-muted lg:col-span-2">
            <p className="mb-1">风机</p>
            <TurbinePicker value={selectedTurbineId} rows={turbineRows} onChange={handleTurbineChange} align="left" />
          </div>
        ) : (
          <>
            <label className="text-xs text-text-muted">
              风机分组
              <select
                className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
                value={batchRegion}
                onChange={(e) => setBatchRegion(e.target.value)}
              >
                <option value="all">全部分组</option>
                {regionOptions.map((region) => <option key={region} value={region}>{region}</option>)}
              </select>
            </label>
            <label className="text-xs text-text-muted">
              风机状态
              <select
                className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
                value={batchStatus}
                onChange={(e) => setBatchStatus(e.target.value)}
              >
                <option value="all">全部状态</option>
                <option value="normal">正常</option>
                <option value="warning">预警</option>
                <option value="fault">故障</option>
              </select>
            </label>
          </>
        )}
        <label className="text-xs text-text-muted">
          部件
          <select
            className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
            value={component}
            onChange={(e) => setComponent(e.target.value)}
          >
            {COMPONENT_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </label>
        <label className="text-xs text-text-muted">
          时间窗
          <select
            className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
            value={windowHours}
            onChange={(e) => setWindowHours(Number(e.target.value))}
          >
            <option value={6}>近6小时</option>
            <option value={24}>近24小时</option>
            <option value={72}>近72小时</option>
            <option value={168}>近7天</option>
          </select>
        </label>
        <label className="text-xs text-text-muted">
          检测状态
          <select
            className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
            value={detectionFilter}
            onChange={(e) => {
              setDetectionFilter(e.target.value as DetectionFilter);
              setBatchPage(1);
            }}
          >
            <option value="all">全部检测</option>
            <option value="suspected_fault">疑似故障</option>
            <option value="no_fault_detected">未检出</option>
          </select>
        </label>
        <label className="text-xs text-text-muted">
          置信度
          <select
            className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
            value={confidenceMin}
            onChange={(e) => {
              setConfidenceMin(Number(e.target.value));
              setBatchPage(1);
            }}
          >
            <option value={0}>全部</option>
            <option value={0.6}>≥60%</option>
            <option value={0.75}>≥75%</option>
            <option value={0.85}>≥85%</option>
          </select>
        </label>
        <label className="text-xs text-text-muted">
          故障类型
          <select
            className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
            value={topologyFaultTypeFilter}
            onChange={(e) => {
              setTopologyFaultTypeFilter(e.target.value);
              setBatchPage(1);
            }}
          >
            <option value="all">全部类型</option>
            {topologyFaultTypeOptions.map((type) => <option key={type} value={type}>{faultLabel(type)}</option>)}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div className="bg-bg-hover rounded p-3">
          <p className="text-text-muted mb-1">{monitorMode === 'group' ? '筛选覆盖' : '检测状态'}</p>
          <p className="font-medium text-text-primary">
            {monitorMode === 'group'
              ? `${filteredBatchRecords.length}/${batchResult?.total || 0} 台`
              : autoResult ? detectionStatusLabel(autoResult.status) : '同步中'}
          </p>
        </div>
        <div className="bg-bg-hover rounded p-3">
          <p className="text-text-muted mb-1">{monitorMode === 'group' ? '疑似故障' : '故障类型'}</p>
          <p className="font-medium text-accent-yellow truncate">
            {monitorMode === 'group'
              ? `${filteredBatchRecords.filter((record) => record.status === 'suspected_fault').length} 台`
              : autoResult ? faultLabel(autoResult.fault_type) : '--'}
          </p>
        </div>
        <div className="bg-bg-hover rounded p-3">
          <p className="text-text-muted mb-1">{monitorMode === 'group' ? '平均置信度' : '置信度'}</p>
          <p className="font-mono text-accent-cyan">
            {monitorMode === 'group'
              ? (filteredBatchRecords.length
                ? confidenceText(filteredBatchRecords.reduce((sum, record) => sum + record.confidence, 0) / filteredBatchRecords.length, 1)
                : '--')
              : autoResult ? `${confidenceText(autoResult.confidence)} (${confidenceText(autoResult.confidence_interval[0])}-${confidenceText(autoResult.confidence_interval[1])})` : '--'}
          </p>
        </div>
        <div className="bg-bg-hover rounded p-3">
          <p className="text-text-muted mb-1">模型状态</p>
          <p className="font-medium text-text-secondary truncate">
            {monitorMode === 'group'
              ? (batchResult?.success ? (batchResult.records[0]?.algorithm_status || '--') : '同步中')
              : autoResult?.algorithm_status || '--'}
          </p>
        </div>
      </div>

      {(monitorMode === 'group' ? batchResult?.message : autoResult?.message) && (
        <p className="text-xs text-text-secondary bg-accent-blue/5 border border-accent-blue/20 rounded px-3 py-2">
          {monitorMode === 'group' ? batchResult?.message : autoResult?.message}
        </p>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b border-border-default bg-bg-secondary px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">故障诊断中心</h2>
            <p className="text-[11px] text-text-muted mt-1">实时监测、图像诊断、振动预览和根因排查</p>
          </div>
          {selectedTurbine && (
            <div className="text-right text-xs">
              <p className="text-text-muted">当前风机</p>
              <p className="font-mono text-accent-cyan">{selectedTurbine.name}</p>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
          {cards.map((c) => (
            <div key={c.key} className="relative">
              <button
                type="button"
                onClick={() => c.rows ? setOpenStatCard(openStatCard === c.key ? null : c.key) : undefined}
                className={`w-full bg-bg-card border border-border-default rounded-lg px-3 py-2.5 text-left ${
                  c.rows ? 'hover:border-accent-blue cursor-pointer' : 'cursor-default'
                }`}
              >
                <p className="flex items-center justify-between gap-2 text-[10px] text-text-muted">
                  <span>{c.label}</span>
                  {c.rows && <span className="text-[9px] text-accent-blue">查看</span>}
                </p>
                <p className={`text-lg font-mono font-bold ${c.color}`}>
                  {c.value}<span className="text-[10px] font-normal text-text-muted ml-0.5">{c.unit}</span>
                </p>
              </button>
              {c.rows && openStatCard === c.key && (
                <div className="absolute left-0 z-50 mt-1 w-[430px] max-w-[calc(100vw-48px)] overflow-hidden rounded-lg border border-border-default bg-bg-card shadow-xl">
                  <div className="grid grid-cols-[1.4fr_0.55fr_0.55fr_0.7fr] gap-2 border-b border-border-default bg-bg-secondary px-3 py-2 text-[10px] text-text-muted">
                    <span>问题风机</span>
                    <span>故障</span>
                    <span>疑似</span>
                    <span>置信度</span>
                  </div>
                  <div className="max-h-64 overflow-auto">
                    {c.rows.length > 0 ? c.rows.map((row) => (
                      <button
                        key={`${c.key}-${row.turbine.id}`}
                        type="button"
                        onClick={() => {
                          handleTurbineChange(row.turbine.id);
                          setOpenStatCard(null);
                        }}
                        className="grid w-full grid-cols-[1.4fr_0.55fr_0.55fr_0.7fr] gap-2 border-b border-border-default px-3 py-2 text-left text-xs hover:bg-bg-hover"
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium text-text-primary">{row.turbine.name}</span>
                          <span className={`block truncate text-[10px] ${turbineStatusClass(row.turbine.status)}`}>
                            {row.turbine.region || '未分组'} · {turbineStatusLabel(row.turbine.status)} · HI {row.turbine.hi_value?.toFixed?.(1) ?? '--'}
                          </span>
                        </span>
                        <span className="font-mono text-text-secondary">{row.faultCount}</span>
                        <span className="font-mono text-accent-yellow">{row.suspectedCount}</span>
                        <span className="font-mono text-accent-cyan">{confidenceText(row.avgConfidence)}</span>
                      </button>
                    )) : (
                      <div className="px-3 py-3 text-xs text-text-muted">当前没有符合条件的风机</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        {error && <p className="mt-2 text-xs text-accent-red">{error}</p>}
      </div>

      <div className="flex-1 overflow-auto p-5 space-y-4">
        <section className="bg-bg-card border border-border-default rounded-lg p-4">
          {topologyMonitoringPanel}
        </section>

        {monitorMode === 'single' && (
          <div className="grid grid-cols-[320px_minmax(0,1fr)] gap-4">
            <SignalEvidencePanel insights={activeCauseInsights} />
            <DiagnosisTopology
              turbine={selectedTurbine}
              turbineRows={turbineRows}
              causes={topologyCauses}
              faults={topologyFaults}
              onFaultSelect={viewDetail}
              onTurbineChange={handleTurbineChange}
            />
          </div>
        )}


        {monitorMode === 'group' && batchResult?.success && (
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-start justify-between gap-4 mb-3">
              <div>
                <h3 className="text-sm font-medium">分组实时监测记录</h3>
                <p className="text-xs text-text-muted mt-1">
                  筛选 {sortedBatchRecords.length}/{batchResult.total} 条 · {Object.entries(batchResult.group_summary).map(([group, count]) => `${group} ${count}台`).join(' / ')}
                </p>
              </div>
              <div className="flex items-end gap-3">
                <label className="text-xs text-text-muted">
                  排序
                  <select
                    className="mt-1 w-36 bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-text-primary"
                    value={batchSort}
                    onChange={(e) => {
                      setBatchSort(e.target.value as BatchSortMode);
                      setBatchPage(1);
                    }}
                  >
                    <option value="region">按分组</option>
                    <option value="turbine">按风机</option>
                    <option value="confidence_desc">置信度高到低</option>
                    <option value="confidence_asc">置信度低到高</option>
                    <option value="status">按识别状态</option>
                    <option value="fault_type">按故障类型</option>
                    <option value="generated_desc">按识别时间</option>
                  </select>
                </label>
                <label className="text-xs text-text-muted">
                  展示
                  <select
                    className="mt-1 w-32 bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-text-primary"
                    value={batchGroup}
                    onChange={(e) => {
                      setBatchGroup(e.target.value as BatchGroupMode);
                      setBatchPage(1);
                    }}
                  >
                    <option value="region">按分组</option>
                    <option value="status">按状态</option>
                    <option value="fault_type">按故障</option>
                    <option value="none">不分组</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="overflow-x-auto">
              <div className="min-w-[920px] rounded-lg border border-border-default overflow-hidden">
                <div className="grid grid-cols-[1.25fr_0.72fr_1.2fr_0.75fr_0.55fr_0.55fr_0.65fr_0.75fr] gap-3 bg-bg-secondary px-3 py-2 text-[10px] text-text-muted">
                  <span>风机</span>
                  <span>风机状态</span>
                  <span>识别结果</span>
                  <span>置信度</span>
                  <span>故障数</span>
                  <span>疑似</span>
                  <span>HI</span>
                  <span>识别时间</span>
                </div>
                {pagedBatchRows.map((row, index) => {
                  if (row.type === 'group') {
                    return (
                      <div key={`group-${row.label}-${index}`} className="border-t border-border-default bg-accent-blue/5 px-3 py-1.5 text-[10px] font-medium text-accent-blue">
                        {row.label}
                      </div>
                    );
                  }
                  const record = row.record;
                  const turbineStats = turbineRowById.get(record.turbine_id);
                  return (
                    <button
                      key={record.record_id}
                      onClick={() => selectBatchRecord(record)}
                      className="w-full grid grid-cols-[1.25fr_0.72fr_1.2fr_0.75fr_0.55fr_0.55fr_0.65fr_0.75fr] gap-3 border-t border-border-default px-3 py-2.5 text-left text-xs hover:bg-bg-hover"
                    >
                      <span className="min-w-0">
                        <span className="block font-medium text-text-primary truncate">{record.turbine_name}</span>
                        <span className="block text-[10px] text-text-muted">#{record.turbine_id} · {record.region}</span>
                      </span>
                      <span className={
                        record.turbine_status === 'fault'
                          ? 'text-accent-red'
                          : record.turbine_status === 'warning'
                            ? 'text-accent-yellow'
                            : 'text-accent-green'
                      }>
                        {turbineStatusLabel(record.turbine_status)}
                      </span>
                      <span className={`min-w-0 truncate font-mono ${diagnosisTypeClass(record.fault_type)}`}>
                        {shortenText(record.fault_type, 24)}
                      </span>
                      <span className="font-mono text-accent-cyan">
                        {(record.confidence * 100).toFixed(0)}%
                        <span className="block text-[10px] text-text-muted">
                          {(record.confidence_interval[0] * 100).toFixed(0)}-{(record.confidence_interval[1] * 100).toFixed(0)}%
                        </span>
                      </span>
                      <span className="font-mono text-text-secondary">{turbineStats?.faultCount ?? 0}</span>
                      <span className="font-mono text-accent-yellow">{turbineStats?.suspectedCount ?? (record.status === 'suspected_fault' ? 1 : 0)}</span>
                      <span className={`font-mono ${record.turbine_status === 'normal' ? 'text-accent-green' : record.turbine_status === 'warning' ? 'text-accent-yellow' : 'text-accent-red'}`}>
                        {turbineStats?.turbine.hi_value?.toFixed?.(1) ?? '--'}
                      </span>
                      <span className="text-text-muted">
                        {new Date(record.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between text-xs">
              <span className="text-text-muted">第 {currentBatchPage} / {totalBatchPages} 页</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setBatchPage((page) => Math.max(1, page - 1))}
                  disabled={currentBatchPage <= 1}
                  className="rounded border border-border-default px-3 py-1.5 text-text-secondary disabled:opacity-40"
                >
                  上一页
                </button>
                <button
                  onClick={() => setBatchPage((page) => Math.min(totalBatchPages, page + 1))}
                  disabled={currentBatchPage >= totalBatchPages}
                  className="rounded border border-border-default px-3 py-1.5 text-text-secondary disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>
          </section>
        )}

        {monitorMode === 'group' && !batchResult?.success && (
          <section className="bg-bg-card border border-border-default rounded-lg p-8 text-center">
            <p className="text-sm text-text-secondary">{batchLoading ? '分组监测同步中...' : '当前筛选条件下暂无分组监测记录'}</p>
            <p className="mt-2 text-xs text-text-muted">调整风机分组、状态、置信度或故障类型后可重新刷新。</p>
          </section>
        )}

        <div className="grid grid-cols-[1.2fr_1fr] gap-4">
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium">振动波形展示</h3>
              <div className="text-xs text-text-muted">
                RMS <span className="font-mono text-accent-cyan">{vibration?.rms ?? '--'}</span>
                <span className="ml-3">{vibration?.algorithm_status || (vibration ? '已加载' : '无数据')}</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-bg-secondary rounded border border-border-default p-2">
                <p className="text-[10px] text-text-muted mb-1">{vibration ? `波形 (${(vibration.duration_seconds || 0).toFixed(2)}s)` : '波形无数据'}</p>
                <div ref={waveformRef} className="h-52" />
              </div>
              <div className="bg-bg-secondary rounded border border-border-default p-2">
                <p className="text-[10px] text-text-muted mb-1">{vibration?.spectrum?.length ? `频谱 (${vibration.spectrum.length}点)` : '频谱无数据'}</p>
                <div ref={spectrumRef} className="h-52" />
              </div>
            </div>
            <p className="mt-2 text-xs text-text-muted">{vibration?.message || '振动波形来自已导入数据集。'}</p>
          </section>

          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-medium">信号贡献分析</h3>
                <p className="text-[10px] text-text-muted mt-1">
                  {monitorMode === 'group'
                    ? currentGroupRecord
                      ? `${currentGroupRecord.turbine_name} · ${currentGroupRecord.region} · ${faultLabel(currentGroupRecord.fault_type)}`
                      : '暂无分组数据'
                    : selectedTurbine
                      ? `${selectedTurbine.name} · ${selectedTurbine.region}`
                      : '暂无风机'}
                </p>
              </div>
              {monitorMode === 'group' && (
                <div className="flex items-center gap-2 text-xs">
                  <button
                    onClick={() => {
                      setGroupTurbinePage((page) => Math.max(1, page - 1));
                      setCausePage(1);
                    }}
                    disabled={currentGroupTurbinePage <= 1}
                    className="rounded border border-border-default px-2 py-1 text-text-secondary disabled:opacity-40"
                  >
                    上一台
                  </button>
                  <span className="text-text-muted">{currentGroupTurbinePage}/{groupTotalTurbinePages}</span>
                  <button
                    onClick={() => {
                      setGroupTurbinePage((page) => Math.min(groupTotalTurbinePages, page + 1));
                      setCausePage(1);
                    }}
                    disabled={currentGroupTurbinePage >= groupTotalTurbinePages}
                    className="rounded border border-border-default px-2 py-1 text-text-secondary disabled:opacity-40"
                  >
                    下一台
                  </button>
                </div>
              )}
            </div>
            <div className="space-y-2 max-h-[246px] overflow-auto pr-1">
              {pagedCauseInsights.map((sig) => (
                <div key={`${sig.sensor_name}-${sig.priority}`} className="bg-bg-hover rounded px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className={`w-10 px-1 py-0.5 rounded text-center text-[10px] ${priorityClass(sig.priority)}`}>{priorityLabel(sig.priority)}</span>
                    <span className="flex-1 font-medium">{sig.sensor_name}</span>
                    <span className="font-mono text-accent-blue">{(sig.contribution_score * 100).toFixed(1)}%</span>
                  </div>
                  <div className="mt-2 grid grid-cols-[1fr_1fr] gap-2 text-[10px] text-text-muted">
                    <span>当前值: <b className="text-text-secondary font-normal">{sig.value}</b></span>
                    <span>正常范围: <b className="text-text-secondary font-normal">{sig.normal_range}</b></span>
                  </div>
                  <p className="mt-1 text-[11px] text-text-secondary">{sig.finding}</p>
                </div>
              ))}
              {activeCauseInsights.length === 0 && <p className="text-xs text-text-muted">当前筛选范围暂无诊断依据数据</p>}
            </div>
            {activeCauseInsights.length > CAUSE_PAGE_SIZE && (
              <div className="mt-3 flex items-center justify-between text-xs">
                <span className="text-text-muted">依据 {currentCausePage}/{causeTotalPages}</span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCausePage((page) => Math.max(1, page - 1))}
                    disabled={currentCausePage <= 1}
                    className="rounded border border-border-default px-2.5 py-1 text-text-secondary disabled:opacity-40"
                  >
                    上一页
                  </button>
                  <button
                    onClick={() => setCausePage((page) => Math.min(causeTotalPages, page + 1))}
                    disabled={currentCausePage >= causeTotalPages}
                    className="rounded border border-border-default px-2.5 py-1 text-text-secondary disabled:opacity-40"
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>

        <div className="grid grid-cols-[0.85fr_1.35fr] gap-4">
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-medium mb-3">标准排查步骤</h3>
            <div className="space-y-2">
              {activeTroubleshootingSteps.map((step) => (
                <div key={step.order} className="grid grid-cols-[28px_1fr] gap-3 bg-bg-hover rounded p-3 text-xs">
                  <span className="w-7 h-7 rounded-full bg-accent-blue/20 text-accent-blue flex items-center justify-center font-mono">{step.order}</span>
                  <div>
                    <p className="font-medium text-text-primary mb-1">{step.title}</p>
                    <p className="text-text-secondary leading-5">{step.action}</p>
                    <p className="text-[10px] text-text-muted mt-1">预期效果: {step.expected_effect}</p>
                  </div>
                </div>
              ))}
              {activeTroubleshootingSteps.length === 0 && <p className="text-xs text-text-muted">暂无排查步骤</p>}
            </div>
          </section>

          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-medium">故障记录管理</h3>
                <p className="text-[10px] text-text-muted mt-1">
                  筛选 {filteredFaults.length}/{faults.length} 条 · 处理中 {faultManagementCounts.processing} · 已关闭 {faultManagementCounts.closed} · 失败 {faultManagementCounts.failed}
                </p>
              </div>
              <button
                onClick={() => {
                  setFaultKeyword('');
                  setFaultRegionFilter('all');
                  setFaultStatusFilter('all');
                  setFaultProcessingFilter('all');
                  setFaultHandlerFilter('all');
                  setFaultPriorityFilter('all');
                  setFaultTimeField('discovered_at');
                  setFaultDateFrom('');
                  setFaultDateTo('');
                }}
                className="rounded border border-border-default px-2.5 py-1 text-[10px] text-text-secondary hover:border-border-active"
              >
                清空筛选
              </button>
            </div>

            <div className="mb-3 grid grid-cols-3 gap-2">
              <input
                value={faultKeyword}
                onChange={(e) => setFaultKeyword(e.target.value)}
                placeholder="搜索风机/故障/人员/工单"
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted"
              />
              <select
                value={faultRegionFilter}
                onChange={(e) => setFaultRegionFilter(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="all">全部分组</option>
                {regionOptions.map((region) => <option key={region} value={region}>{region}</option>)}
              </select>
              <select
                value={faultStatusFilter}
                onChange={(e) => setFaultStatusFilter(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="all">全部故障状态</option>
                <option value="open">待处理故障</option>
                <option value="closed">已关闭故障</option>
              </select>
              <select
                value={faultProcessingFilter}
                onChange={(e) => setFaultProcessingFilter(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="all">全部处理状态</option>
                <option value="pending">待处理</option>
                <option value="assigned">已指派</option>
                <option value="processing">处理中</option>
                <option value="closed">已关闭</option>
                <option value="failed">处理失败</option>
              </select>
              <select
                value={faultHandlerFilter}
                onChange={(e) => setFaultHandlerFilter(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="all">全部处理人员</option>
                {faultHandlerOptions.map((handler) => <option key={handler} value={handler}>{handler}</option>)}
              </select>
              <select
                value={faultPriorityFilter}
                onChange={(e) => setFaultPriorityFilter(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="all">全部优先级</option>
                <option value="urgent">紧急</option>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>

            <div className="mb-3 grid grid-cols-[1fr_1fr_1fr] gap-2">
              <select
                value={faultTimeField}
                onChange={(e) => setFaultTimeField(e.target.value as FaultTimeField)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              >
                <option value="discovered_at">按发现时间</option>
                <option value="processing_started_at">按处理时间</option>
                <option value="closed_at">按关闭时间</option>
                <option value="failed_at">按失败时间</option>
                <option value="last_action_at">按最近动作</option>
              </select>
              <input
                type="date"
                value={faultDateFrom}
                onChange={(e) => setFaultDateFrom(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              />
              <input
                type="date"
                value={faultDateTo}
                onChange={(e) => setFaultDateTo(e.target.value)}
                className="bg-bg-secondary border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              />
            </div>

            {loading ? (
              <p className="text-xs text-text-muted">加载中...</p>
            ) : (
              <div className="space-y-2 max-h-[460px] overflow-auto pr-1">
                {filteredFaults.map((f) => (
                  <button
                    key={f.id}
                    onClick={() => viewDetail(f.id)}
                    className={`w-full text-left bg-bg-hover border rounded-lg p-3 transition-colors ${
                      selected?.id === f.id ? 'border-accent-blue' : 'border-border-default hover:border-border-active'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] ${faultPriorityClass(f.priority)}`}>
                            {priorityLabelValue(f.priority)}
                          </span>
                          <p className="text-sm font-medium truncate">{faultLabel(f.fault_type)}</p>
                        </div>
                        <p className="text-xs text-text-muted mt-1">
                          {f.turbine_name || `风机 #${f.turbine_id}`} · {f.turbine_region || '未分组'}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-xs">
                        <p className="font-mono text-accent-yellow">{(f.confidence * 100).toFixed(0)}%</p>
                        <span className={`inline-flex rounded px-2 py-0.5 text-[10px] ${processingStatusClass(f.processing_status)}`}>
                          {processingStatusLabel(f.processing_status)}
                        </span>
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] text-text-muted">
                      <span>发现: <b className="font-normal text-text-secondary">{formatDateTime(f.discovered_at || f.detected_at)}</b></span>
                      <span>处理: <b className="font-normal text-text-secondary">{formatDateTime(f.processing_started_at)}</b></span>
                      <span>关闭: <b className="font-normal text-text-secondary">{formatDateTime(f.closed_at)}</b></span>
                      <span>失败: <b className="font-normal text-text-secondary">{formatDateTime(f.failed_at)}</b></span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-text-muted">
                      <span>人员: <b className="font-normal text-text-secondary">{f.handler || '未指派'}</b></span>
                      <span>故障状态: <b className={f.status === 'open' ? 'font-normal text-accent-red' : 'font-normal text-accent-green'}>{f.status === 'open' ? '待处理' : '已关闭'}</b></span>
                      <span>工单: <b className="font-normal text-text-secondary">{f.work_order_title || '未关联'}</b></span>
                      {f.maintenance_cost_estimate != null && (
                        <span>估算: <b className="font-normal text-text-secondary">{Math.round(f.maintenance_cost_estimate).toLocaleString('zh-CN')}</b></span>
                      )}
                    </div>
                  </button>
                ))}
                {faults.length === 0 && <p className="text-xs text-text-muted">暂无故障记录</p>}
                {faults.length > 0 && filteredFaults.length === 0 && <p className="text-xs text-text-muted">没有符合条件的故障记录</p>}
              </div>
            )}
          </section>
        </div>
      </div>

      <CopilotFAB pageContext={{
        total_faults: faults.length,
        open_faults: faults.filter(f => f.status === 'open').length,
        selected_turbine_id: selectedTurbineId ?? undefined,
        monitor_mode: monitorMode,
        top_fault_types: [...new Set(faults.map(f => f.fault_type))].slice(0, 10),
        auto_detect_result: autoResult ? { fault_type: autoResult.fault_type, confidence: autoResult.confidence } : undefined,
        batch_summary: batchResult?.group_summary,
        risk_first: riskFirst,
      }} />
    </div>
  );
}
