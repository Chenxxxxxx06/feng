import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import api from '../../services/api';
import type {
  AutoFaultDetectionResult,
  BatchAutoFaultDetectionResult,
  BatchAutoFaultRecord,
  BladeDiagnosisResult,
  DiagnosisSignalInsight,
  Fault,
  FaultDetail,
  Turbine,
  TurbineSummary,
  VibrationPreview,
} from '../../types';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

const COMPONENT_OPTIONS = [
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
  pitch: { x: 360, y: 174 },
  main_bearing: { x: 396, y: 174 },
  main_shaft: { x: 426, y: 174 },
  gearbox: { x: 478, y: 174 },
  brake: { x: 523, y: 174 },
  generator: { x: 566, y: 174 },
  cooling: { x: 566, y: 121 },
  electrical: { x: 546, y: 230 },
  sensor: { x: 584, y: 86 },
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

function bboxToStyle(bbox: { x: number; y: number; w: number; h: number }) {
  const left = Math.min(90, Math.max(0, (bbox.x / 1920) * 100));
  const top = Math.min(90, Math.max(0, (bbox.y / 1440) * 100));
  const width = Math.min(45, Math.max(8, (bbox.w / 1920) * 100));
  const height = Math.min(45, Math.max(8, (bbox.h / 1440) * 100));
  return { left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%` };
}

function DiagnosisTopology({
  turbine,
  causes,
  faults,
  onFaultSelect,
}: {
  turbine: Turbine | null;
  causes: TopologyCauseNode[];
  faults: TopologyFaultNode[];
  onFaultSelect: (id: number) => void;
}) {
  const [hoveredFaultId, setHoveredFaultId] = useState<number | null>(null);
  const [hoveredCauseId, setHoveredCauseId] = useState<string | null>(null);
  const [hoveredComponent, setHoveredComponent] = useState<TurbineComponentKey | null>(null);
  const activeComponents = new Set<TurbineComponentKey>([
    ...causes.map((cause) => cause.component),
    ...faults.map((fault) => fault.component),
  ]);
  const hoveredFault = faults.find((fault) => fault.id === hoveredFaultId);
  const hoveredCause = causes.find((cause) => cause.id === hoveredCauseId);
  const selectedFault = faults.find((fault) => fault.selected);
  const focusedComponent = hoveredComponent || hoveredFault?.component || hoveredCause?.component || selectedFault?.component;
  const selectedComponent = focusedComponent || faults[0]?.component;
  const turbineStatus = turbine ? turbineStatusLabel(turbine.status) : '未选择';
  const modelTone = turbine?.status === 'fault' ? '#ff4d5e' : turbine?.status === 'warning' ? '#f6b94a' : '#39d2c0';
  const componentOpacity = (component: TurbineComponentKey, base = 1) => {
    if (!focusedComponent || component === focusedComponent) return base;
    return Math.max(0.16, base * 0.28);
  };
  const connectionOpacity = (component: TurbineComponentKey, selected: boolean) => {
    if (!focusedComponent) return selected ? 0.72 : 0.42;
    return component === focusedComponent ? 0.86 : 0.13;
  };
  const componentStrokeWidth = (component: TurbineComponentKey) => (focusedComponent === component ? 2.6 : 1.4);
  const leftRows = causes.length ? causes : [{
    id: 'empty-cause',
    label: '暂无故障原因',
    detail: '等待诊断信号',
    priority: 'low',
    score: 0,
    component: selectedComponent || 'gearbox',
  }];
  const rightRows = faults.length ? faults : [{
    id: -1,
    label: '暂无故障记录',
    turbineLabel: turbine?.name || '--',
    component: selectedComponent || 'gearbox',
    confidence: 0,
    priority: 'low',
    processingStatus: 'pending',
    workOrderTitle: null,
    selected: false,
  }];

  return (
    <section className="bg-bg-card border border-border-default rounded-lg overflow-hidden">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
        <div>
          <h3 className="text-sm font-medium">风机故障拓扑</h3>
          <p className="mt-1 text-[10px] text-text-muted">{turbine?.name || '未选择风机'} · {turbine?.region || '未分组'} · {turbineStatus}</p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-right text-[10px]">
          <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">原因 {causes.length}</span>
          <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">故障 {faults.length}</span>
          <span className="rounded bg-bg-hover px-2 py-1 text-text-secondary">部件 {activeComponents.size}</span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg viewBox="0 0 900 360" className="h-[360px] min-w-[900px] w-full bg-bg-secondary/60" role="img" aria-label="风机故障拓扑">
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
            <filter id="topologyGlow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

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
                <circle cx={point.x} cy={point.y} r={focusedComponent === cause.component ? '6' : '4'} fill={componentTone(cause.component, activeComponents, selectedComponent)} filter="url(#topologyGlow)" />
              </g>
            );
          })}

          {rightRows.map((fault, index) => {
            const y = 48 + index * 70;
            const point = COMPONENT_POINTS[fault.component];
            return (
              <g key={fault.id}>
                <path
                  d={`M ${point.x} ${point.y} C ${point.x + 70} ${point.y}, 620 ${y + 24}, 648 ${y + 24}`}
                  fill="none"
                  stroke={componentTone(fault.component, activeComponents, selectedComponent)}
                  strokeOpacity={connectionOpacity(fault.component, fault.selected || hoveredFaultId === fault.id)}
                  strokeWidth={fault.selected || hoveredFaultId === fault.id ? '2.4' : '1.4'}
                />
                <circle cx={point.x} cy={point.y} r={fault.selected || hoveredFaultId === fault.id ? '7' : '4'} fill={componentTone(fault.component, activeComponents, selectedComponent)} filter="url(#topologyGlow)" />
              </g>
            );
          })}

          <g opacity="0.92">
            <path
              d="M372 118 C418 98, 548 102, 616 124 C632 136, 632 214, 612 224 C544 244, 430 238, 376 214 C360 202, 358 134, 372 118 Z"
              fill="url(#nacelleShell)"
              stroke="#c7d7e8"
              strokeOpacity="0.44"
              strokeWidth="1.4"
            />
            <path d="M382 152 H608" stroke="#c7d7e8" strokeOpacity="0.12" />
            <path d="M382 199 H608" stroke="#c7d7e8" strokeOpacity="0.12" />

            <circle cx="360" cy="174" r="27" fill={modelTone} fillOpacity={componentOpacity('blade_root', 0.2)} stroke={componentTone('blade_root', activeComponents, selectedComponent)} strokeOpacity={componentOpacity('blade_root', 0.9)} strokeWidth={componentStrokeWidth('blade_root')} filter="url(#topologyGlow)" />
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
                onMouseEnter={() => setHoveredComponent(component)}
                onMouseLeave={() => setHoveredComponent(null)}
                onFocus={() => setHoveredComponent(component)}
                onBlur={() => setHoveredComponent(null)}
                role="button"
                tabIndex={0}
              >
                <circle cx={point.x} cy={point.y} r={active ? 8 : 5} fill={tone} fillOpacity={active ? '0.8' : '0.25'} stroke={tone} strokeWidth="1.5" />
                <text x={point.x + 10} y={point.y - 8} fill={active ? tone : '#8d9aaa'} fontSize="10" fontWeight={active ? '600' : '500'} opacity={active ? '1' : '0.72'}>
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
                onMouseEnter={() => setHoveredCauseId(cause.id)}
                onMouseLeave={() => setHoveredCauseId(null)}
              >
                <rect x="28" y={y} width="224" height="54" rx="8" fill={hoveredCauseId === cause.id ? '#182536' : '#111923'} stroke={tone} strokeOpacity={hoveredCauseId === cause.id ? '0.84' : '0.34'} strokeWidth={hoveredCauseId === cause.id ? '2' : '1'} />
                <text x="42" y={y + 18} fill="#dcecff" fontSize="12" fontWeight="600">{shortenText(cause.label, 17)}</text>
                <text x="42" y={y + 36} fill="#8d9aaa" fontSize="10">{shortenText(cause.detail, 24)}</text>
                <text x="200" y={y + 36} fill={tone} fontSize="10" textAnchor="end">{cause.score ? `${(cause.score * 100).toFixed(0)}%` : '--'}</text>
              </g>
            );
          })}

          {rightRows.map((fault, index) => {
            const y = 48 + index * 70;
            const tone = componentTone(fault.component, activeComponents, selectedComponent);
            const disabled = fault.id < 0;
            return (
              <g
                key={`fault-${fault.id}`}
                onClick={() => !disabled && onFaultSelect(fault.id)}
                onMouseEnter={() => !disabled && setHoveredFaultId(fault.id)}
                onMouseLeave={() => setHoveredFaultId(null)}
                onFocus={() => !disabled && setHoveredFaultId(fault.id)}
                onBlur={() => setHoveredFaultId(null)}
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
                <text x="662" y={y + 18} fill="#dcecff" fontSize="12" fontWeight="600">{shortenText(fault.label, 16)}</text>
                <text x="662" y={y + 36} fill="#8d9aaa" fontSize="10">{shortenText(fault.turbineLabel, 12)} · {processingStatusLabel(fault.processingStatus)}</text>
                <text x="858" y={y + 18} fill={tone} fontSize="10" textAnchor="end">{fault.confidence ? `${(fault.confidence * 100).toFixed(0)}%` : '--'}</text>
                <text x="858" y={y + 36} fill="#8d9aaa" fontSize="10" textAnchor="end">{shortenText(fault.workOrderTitle || '未关联工单', 10)}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

export default function DiagnosisPage() {
  const [faults, setFaults] = useState<Fault[]>([]);
  const [selected, setSelected] = useState<FaultDetail | null>(null);
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [selectedTurbineId, setSelectedTurbineId] = useState<number | null>(null);
  const [monitorMode, setMonitorMode] = useState<MonitorMode>('single');
  const [component, setComponent] = useState('gearbox_high_speed');
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
  const [bladeResult, setBladeResult] = useState<BladeDiagnosisResult | null>(null);
  const [bladePreview, setBladePreview] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [autoLoading, setAutoLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [bladeLoading, setBladeLoading] = useState(false);
  const [error, setError] = useState('');
  const waveformRef = useRef<HTMLDivElement>(null);
  const spectrumRef = useRef<HTMLDivElement>(null);

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
  }, []);

  useEffect(() => {
    if (!selectedTurbineId) return;
    loadVibration(selectedTurbineId, component, undefined);
  }, [selectedTurbineId, component]);

  useEffect(() => {
    if (monitorMode !== 'single' || !selectedTurbineId) return;
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
  }, [monitorMode, batchRegion, batchStatus, component, windowHours, selectedTurbineId]);

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

  const faultHandlerOptions = useMemo(() => {
    const handlers = new Set(faults.map((f) => f.handler || '未指派'));
    return Array.from(handlers).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [faults]);

  const filteredFaults = useMemo(() => {
    const keyword = faultKeyword.trim().toLowerCase();
    const fromTime = faultDateFrom ? new Date(`${faultDateFrom}T00:00:00`).getTime() : null;
    const toTime = faultDateTo ? new Date(`${faultDateTo}T23:59:59`).getTime() : null;

    return faults.filter((fault) => {
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
  ]);

  const faultManagementCounts = useMemo(() => ({
    processing: filteredFaults.filter((f) => f.processing_status === 'processing' || f.processing_status === 'assigned').length,
    failed: filteredFaults.filter((f) => f.processing_status === 'failed').length,
    closed: filteredFaults.filter((f) => f.processing_status === 'closed').length,
  }), [filteredFaults]);

  const sortedBatchRecords = useMemo(() => {
    const records = [...(batchResult?.records || [])];
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
  }, [batchResult, batchSort]);

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

  const openCount = faults.filter((f) => f.status === 'open').length;
  const weekAgo = new Date(Date.now() - 7 * 86400000);
  const weekNew = faults.filter((f) => new Date(f.detected_at) > weekAgo).length;
  const avgConfidence = faults.length
    ? `${(faults.reduce((sum, f) => sum + f.confidence, 0) / faults.length * 100).toFixed(1)}%`
    : '--';

  const insights: DiagnosisSignalInsight[] = autoResult?.signals
    || selected?.signal_insights
    || selected?.signals?.map((s) => ({
      sensor_name: s.sensor_name,
      value: '待接入',
      normal_range: '待接入',
      contribution_score: s.contribution_score,
      priority: s.priority,
      finding: '该信号由诊断模型标记为故障相关因素',
    }))
    || [];

  const troubleshootingSteps = autoResult?.troubleshooting_steps
    || selected?.troubleshooting_steps
    || bladeResult?.troubleshooting_steps
    || [];

  const groupCauseRecords = sortedBatchRecords;
  const groupTotalTurbinePages = Math.max(1, groupCauseRecords.length);
  const currentGroupTurbinePage = Math.min(groupTurbinePage, groupTotalTurbinePages);
  const currentGroupRecord = groupCauseRecords[currentGroupTurbinePage - 1] || null;
  const activeCauseInsights = monitorMode === 'group'
    ? currentGroupRecord?.signals || []
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
  const groupSuspectedCount = sortedBatchRecords.filter((record) => record.status === 'suspected_fault').length;
  const groupAverageConfidence = sortedBatchRecords.length
    ? `${(sortedBatchRecords.reduce((sum, record) => sum + record.confidence, 0) / sortedBatchRecords.length * 100).toFixed(1)}%`
    : '--';

  const topologyCauses = useMemo<TopologyCauseNode[]>(() => {
    const fallbackFaultType = autoResult?.fault_type || selected?.fault_type;
    return activeCauseInsights.slice(0, 4).map((signal, index) => ({
      id: `${signal.sensor_name}-${index}`,
      label: signal.sensor_name,
      detail: signal.finding || `${signal.value} / ${signal.normal_range}`,
      priority: signal.priority,
      score: signal.contribution_score,
      component: componentForSignal(signal.sensor_name, fallbackFaultType),
    }));
  }, [activeCauseInsights, autoResult?.fault_type, selected?.fault_type]);

  const topologyFaults = useMemo<TopologyFaultNode[]>(() => {
    const scoped = selectedTurbineId
      ? faults.filter((fault) => fault.turbine_id === selectedTurbineId)
      : faults;
    const candidates = selected
      ? [selected, ...scoped.filter((fault) => fault.id !== selected.id)]
      : scoped;

    return candidates.slice(0, 4).map((fault) => {
      const turbine = turbines.find((item) => item.id === fault.turbine_id);
      return {
        id: fault.id,
        label: faultLabel(fault.fault_type),
        turbineLabel: fault.turbine_name || turbine?.name || `风机 #${fault.turbine_id}`,
        component: componentForFaultType(fault.fault_type),
        confidence: fault.confidence,
        priority: fault.priority,
        processingStatus: fault.processing_status,
        workOrderTitle: fault.work_order_title,
        selected: selected?.id === fault.id,
      };
    });
  }, [faults, selected, selectedTurbineId, turbines]);

  useEffect(() => {
    if (groupTurbinePage > groupTotalTurbinePages) setGroupTurbinePage(groupTotalTurbinePages);
  }, [groupTurbinePage, groupTotalTurbinePages]);

  useEffect(() => {
    if (causePage > causeTotalPages) setCausePage(causeTotalPages);
  }, [causePage, causeTotalPages]);

  const cards = [
    { label: '总故障数', value: String(faults.length), unit: '条', color: 'text-accent-blue' },
    { label: '待处理', value: String(openCount), unit: '条', color: openCount ? 'text-accent-red' : 'text-accent-green' },
    { label: '本周新增', value: String(weekNew), unit: '条', color: weekNew ? 'text-accent-yellow' : 'text-text-secondary' },
    { label: '平均置信度', value: avgConfidence, unit: '', color: 'text-accent-cyan' },
    { label: '高优先级信号', value: String(highRiskSignals), unit: '项', color: highRiskSignals ? 'text-accent-red' : 'text-accent-green' },
  ];

  async function viewDetail(id: number) {
    const { data } = await api.get(`/diagnosis/faults/${id}`);
    setSelected(data);
    setSelectedTurbineId(data.turbine_id);
    setAutoResult(null);
  }

  async function loadVibration(turbineId: number, nextComponent: string, faultType: string | undefined) {
    const params: Record<string, string | number> = { turbine_id: turbineId, component: nextComponent };
    if (faultType) params.fault_type = faultType;
    const { data } = await api.get('/diagnosis/vibration', { params });
    setVibration(data);
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

  async function handleBladeFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !selectedTurbineId) return;
    setBladeLoading(true);
    setError('');
    const previewUrl = URL.createObjectURL(file);
    setBladePreview(previewUrl);
    try {
      const form = new FormData();
      form.append('turbine_id', String(selectedTurbineId));
      form.append('image', file);
      const { data } = await api.post('/diagnosis/blade-diagnosis/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setBladeResult(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '叶片图像诊断失败');
    } finally {
      setBladeLoading(false);
    }
  }

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
        <div className="grid grid-cols-5 gap-3">
          {cards.map((c) => (
            <div key={c.label} className="bg-bg-card border border-border-default rounded-lg px-3 py-2.5">
              <p className="text-[10px] text-text-muted">{c.label}</p>
              <p className={`text-lg font-mono font-bold ${c.color}`}>
                {c.value}<span className="text-[10px] font-normal text-text-muted ml-0.5">{c.unit}</span>
              </p>
            </div>
          ))}
        </div>
        {error && <p className="mt-2 text-xs text-accent-red">{error}</p>}
      </div>

      <div className="flex-1 overflow-auto p-5 space-y-4">
        <DiagnosisTopology
          turbine={selectedTurbine}
          causes={topologyCauses}
          faults={topologyFaults}
          onFaultSelect={viewDetail}
        />

        <div className="grid grid-cols-[1.35fr_1fr] gap-4">
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-medium">实时故障监测</h3>
                <p className="text-[10px] text-text-muted mt-1">条件变化立即同步，每30秒自动刷新</p>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded bg-accent-blue/10 text-accent-blue">
                {autoLoading || batchLoading ? '同步中' : '实时监测中'}
              </span>
            </div>

            <div className="mb-3 inline-flex rounded border border-border-default bg-bg-secondary p-1 text-xs">
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

            {monitorMode === 'single' ? (
              <div className="grid grid-cols-3 gap-3">
                <label className="text-xs text-text-muted">
                  风机
                  <select
                    className="mt-1 w-full bg-bg-secondary border border-border-default rounded px-2 py-2 text-text-primary"
                    value={selectedTurbineId || ''}
                    onChange={(e) => setSelectedTurbineId(Number(e.target.value))}
                  >
                    {turbines.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </label>
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
              </div>
            ) : (
              <div className="grid grid-cols-4 gap-3">
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
              </div>
            )}

            <div className="mt-4 grid grid-cols-4 gap-3 text-xs">
              <div className="bg-bg-hover rounded p-3">
                <p className="text-text-muted mb-1">{monitorMode === 'group' ? '覆盖风机' : '监测状态'}</p>
                <p className="font-medium text-text-primary">
                  {monitorMode === 'group'
                    ? `${sortedBatchRecords.length} 台`
                    : autoResult ? detectionStatusLabel(autoResult.status) : '同步中'}
                </p>
              </div>
              <div className="bg-bg-hover rounded p-3">
                <p className="text-text-muted mb-1">{monitorMode === 'group' ? '疑似故障' : '故障类型'}</p>
                <p className="font-medium text-accent-yellow truncate">
                  {monitorMode === 'group'
                    ? `${groupSuspectedCount} 台`
                    : autoResult ? faultLabel(autoResult.fault_type) : '--'}
                </p>
              </div>
              <div className="bg-bg-hover rounded p-3">
                <p className="text-text-muted mb-1">{monitorMode === 'group' ? '平均置信度' : '置信度区间'}</p>
                <p className="font-mono text-accent-cyan">
                  {monitorMode === 'group'
                    ? groupAverageConfidence
                    : autoResult ? `${(autoResult.confidence_interval[0] * 100).toFixed(0)}%-${(autoResult.confidence_interval[1] * 100).toFixed(0)}%` : '--'}
                </p>
              </div>
              <div className="bg-bg-hover rounded p-3">
                <p className="text-text-muted mb-1">模型状态</p>
                <p className="font-medium text-text-secondary truncate">
                  {monitorMode === 'group'
                    ? (batchResult?.success ? 'stub_pending_external_model' : '同步中')
                    : autoResult?.algorithm_status || '同步中'}
                </p>
              </div>
            </div>
            {(monitorMode === 'group' ? batchResult?.message : autoResult?.message) && (
              <p className="mt-3 text-xs text-text-secondary bg-accent-blue/5 border border-accent-blue/20 rounded px-3 py-2">
                {monitorMode === 'group' ? batchResult?.message : autoResult?.message}
              </p>
            )}
          </section>

          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium">叶片图像诊断</h3>
              <label className="px-3 py-1.5 rounded bg-bg-hover border border-border-default text-xs cursor-pointer hover:border-accent-blue">
                选择图像
                <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={handleBladeFile} />
              </label>
            </div>
            <div className="grid grid-cols-[1fr_180px] gap-3">
              <div className="relative h-40 rounded border border-border-default bg-bg-secondary overflow-hidden flex items-center justify-center">
                {bladePreview ? (
                  <img src={bladePreview} alt="叶片预览" className="w-full h-full object-cover opacity-80" />
                ) : (
                  <span className="text-xs text-text-muted">JPG/PNG 图像预览</span>
                )}
                {bladeResult?.damage_bbox && (
                  <div className="absolute border-2 border-accent-red bg-accent-red/10" style={bboxToStyle(bladeResult.damage_bbox)} />
                )}
              </div>
              <div className="bg-bg-hover rounded p-3 text-xs space-y-2">
                <div>
                  <p className="text-text-muted">诊断结果</p>
                  <p className="font-medium text-accent-yellow">{bladeLoading ? '分析中...' : bladeResult ? faultLabel(bladeResult.damage_type) : '--'}</p>
                </div>
                <div>
                  <p className="text-text-muted">置信度</p>
                  <p className="font-mono text-accent-cyan">{bladeResult ? `${(bladeResult.confidence * 100).toFixed(1)}%` : '--'}</p>
                </div>
                <div>
                  <p className="text-text-muted">模型状态</p>
                  <p className="text-text-secondary leading-4">{bladeResult?.algorithm_status || '待接入'}</p>
                </div>
              </div>
            </div>
            {bladeResult?.message && <p className="mt-3 text-xs text-text-secondary">{bladeResult.message}</p>}
          </section>
        </div>

        {monitorMode === 'group' && batchResult?.success && (
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-start justify-between gap-4 mb-3">
              <div>
                <h3 className="text-sm font-medium">分组实时监测记录</h3>
                <p className="text-xs text-text-muted mt-1">
                  共 {batchResult.total} 条 · {Object.entries(batchResult.group_summary).map(([group, count]) => `${group} ${count}台`).join(' / ')}
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
                <div className="grid grid-cols-[1.2fr_0.85fr_0.8fr_1.25fr_0.85fr_1fr_0.85fr] gap-3 bg-bg-secondary px-3 py-2 text-[10px] text-text-muted">
                  <span>风机</span>
                  <span>分组</span>
                  <span>风机状态</span>
                  <span>识别结果</span>
                  <span>置信度</span>
                  <span>模型状态</span>
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
                  return (
                    <button
                      key={record.record_id}
                      onClick={() => selectBatchRecord(record)}
                      className="w-full grid grid-cols-[1.2fr_0.85fr_0.8fr_1.25fr_0.85fr_1fr_0.85fr] gap-3 border-t border-border-default px-3 py-2.5 text-left text-xs hover:bg-bg-hover"
                    >
                      <span className="min-w-0">
                        <span className="block font-medium text-text-primary truncate">{record.turbine_name}</span>
                        <span className="block text-[10px] text-text-muted">#{record.turbine_id}</span>
                      </span>
                      <span className="text-text-secondary truncate">{record.region}</span>
                      <span className={
                        record.turbine_status === 'fault'
                          ? 'text-accent-red'
                          : record.turbine_status === 'warning'
                            ? 'text-accent-yellow'
                            : 'text-accent-green'
                      }>
                        {turbineStatusLabel(record.turbine_status)}
                      </span>
                      <span className="min-w-0">
                        <span className={`inline-flex max-w-full rounded px-2 py-0.5 text-[10px] ${
                          record.status === 'suspected_fault' ? 'bg-accent-red/20 text-accent-red' : 'bg-accent-green/20 text-accent-green'
                        }`}>
                          {detectionStatusLabel(record.status)}
                        </span>
                        <span className="mt-1 block text-text-secondary truncate">{faultLabel(record.fault_type)}</span>
                      </span>
                      <span className="font-mono text-accent-cyan">
                        {(record.confidence * 100).toFixed(0)}%
                        <span className="block text-[10px] text-text-muted">
                          {(record.confidence_interval[0] * 100).toFixed(0)}-{(record.confidence_interval[1] * 100).toFixed(0)}%
                        </span>
                      </span>
                      <span className="text-text-secondary truncate">{record.algorithm_status}</span>
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

        <div className="grid grid-cols-[1.2fr_1fr] gap-4">
          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium">振动波形展示</h3>
              <div className="text-xs text-text-muted">
                RMS <span className="font-mono text-accent-cyan">{vibration?.rms ?? '--'}</span>
                <span className="ml-3">{vibration?.algorithm_status || 'imported_dataset'}</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-bg-secondary rounded border border-border-default p-2">
                <p className="text-[10px] text-text-muted mb-1">近24小时波形占位</p>
                <div ref={waveformRef} className="h-52" />
              </div>
              <div className="bg-bg-secondary rounded border border-border-default p-2">
                <p className="text-[10px] text-text-muted mb-1">频谱分析入口占位</p>
                <div ref={spectrumRef} className="h-52" />
              </div>
            </div>
            <p className="mt-2 text-xs text-text-muted">{vibration?.message || '振动波形来自已导入数据集。'}</p>
          </section>

          <section className="bg-bg-card border border-border-default rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-medium">故障原因排查</h3>
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
              {activeCauseInsights.length === 0 && <p className="text-xs text-text-muted">当前筛选范围暂无故障原因数据</p>}
            </div>
            {activeCauseInsights.length > CAUSE_PAGE_SIZE && (
              <div className="mt-3 flex items-center justify-between text-xs">
                <span className="text-text-muted">原因 {currentCausePage}/{causeTotalPages}</span>
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
      }} />
    </div>
  );
}
