export interface Turbine {
  id: number;
  name: string;
  model: string;
  power_mw: number;
  lat: number;
  lng: number;
  region: string;
  status: 'normal' | 'warning' | 'fault';
  hi_value: number;
  last_maintenance: string | null;
}

export interface TurbineSummary {
  turbines: Turbine[];
  total: number;
  healthy: number;
  warning: number;
  faulty: number;
}

export type TurbineDetail = Turbine;

export interface SCADAPoint {
  timestamp: string;
  power_kw: number | null;
  wind_speed_ms: number | null;
  rotor_rpm: number | null;
  gen_temperature_c: number | null;
  gearbox_temperature_c: number | null;
  pitch_angle_deg: number | null;
}

export interface Fault {
  id: number;
  turbine_id: number;
  turbine_name?: string;
  turbine_region?: string;
  detected_at: string;
  discovered_at?: string | null;
  processing_started_at?: string | null;
  closed_at?: string | null;
  failed_at?: string | null;
  handler?: string | null;
  processing_status?: string;
  priority?: string;
  work_order_id?: number | null;
  work_order_title?: string | null;
  last_action_at?: string | null;
  maintenance_cost_estimate?: number | null;
  maintenance_cost_actual?: number | null;
  status_note?: string;
  fault_type: string;
  confidence: number;
  status: string;
  details?: Record<string, any>;
}

export interface FaultDetail extends Fault {
  signals: FaultSignal[];
  signal_insights?: DiagnosisSignalInsight[];
  troubleshooting_steps?: TroubleshootingStep[];
}

export interface FaultSignal {
  id: number;
  sensor_name: string;
  contribution_score: number;
  priority: string;
}

export interface DiagnosisSignalInsight {
  sensor_name: string;
  value: string;
  normal_range: string;
  contribution_score: number;
  priority: string;
  finding: string;
}

export interface TroubleshootingStep {
  order: number;
  title: string;
  action: string;
  expected_effect: string;
}

export interface AutoFaultDetectionResult {
  turbine_id: number;
  component: string;
  analysis_window_hours: number;
  status: string;
  fault_type: string;
  confidence: number;
  confidence_interval: number[];
  algorithm_status: string;
  message: string;
  generated_at: string;
  signals: DiagnosisSignalInsight[];
  troubleshooting_steps: TroubleshootingStep[];
}

export interface BatchAutoFaultRecord {
  record_id: string;
  turbine_id: number;
  turbine_name: string;
  region: string;
  turbine_status: string;
  component: string;
  analysis_window_hours: number;
  status: string;
  fault_type: string;
  confidence: number;
  confidence_interval: number[];
  algorithm_status: string;
  message: string;
  generated_at: string;
  group_key: string;
  signals: DiagnosisSignalInsight[];
  troubleshooting_steps: TroubleshootingStep[];
}

export interface BatchAutoFaultDetectionResult {
  success: boolean;
  total: number;
  generated_at: string;
  records: BatchAutoFaultRecord[];
  group_summary: Record<string, number>;
  message: string;
}

export interface VibrationPreview {
  turbine_id: number;
  component: string;
  timestamp: string;
  duration_seconds: number;
  sample_rate_hz: number;
  rms: number;
  waveform: number[];
  spectrum: number[];
  peak_frequencies: { frequency_hz: number; amplitude: number }[];
  fault_detected: boolean;
  algorithm_status: string;
  message: string;
}

export interface BladeDiagnosisResult {
  turbine_id: number;
  damage_type: string;
  confidence: number;
  damage_bbox: { x: number; y: number; w: number; h: number } | null;
  image_path: string;
  algorithm_status: string;
  message: string;
  damage_regions: { label: string; bbox: { x: number; y: number; w: number; h: number }; confidence: number }[];
  troubleshooting_steps: TroubleshootingStep[];
}

export interface RULPrediction {
  turbine_id: number;
  turbine_name: string;
  component: string;
  remaining_life_days: number;
  confidence_lower: number;
  confidence_upper: number;
  predicted_at: string;
}

export interface CostComparison {
  immediate_repair_cost: number;
  delayed_repair_cost: number;
  downtime_loss_per_day: number;
  failure_probability: number;
  recommendation: string;
  optimal_window_days: number;
}

export interface WorkOrder {
  id: number;
  turbine_id: number;
  fault_id: number | null;
  title: string;
  description: string | null;
  status: string;
  assignee: string | null;
  cost_estimate: number;
  cost_actual: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface AISummary {
  conclusions: string[];
  suggestions: string[];
}
