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

export interface WeatherReplayPoint {
  wind_speed_ms: number | null;
  wind_gust_ms: number | null;
  wind_direction_deg: number | null;
  turbulence_intensity: number | null;
  air_temperature_c: number | null;
  air_pressure_hpa: number | null;
  source_dataset?: string | null;
}

export interface SCADAPoint {
  timestamp: string;
  power_kw: number | null;
  wind_speed_ms: number | null;
  rotor_rpm: number | null;
  gen_temperature_c: number | null;
  gearbox_temperature_c: number | null;
  pitch_angle_deg: number | null;
  dataset_window?: string | null;
  source_dataset?: string | null;
  power_unit?: string | null;
  power_label?: string | null;
  bearing_temperature_c?: number | null;
  grid_frequency_hz?: number | null;
  nacelle_direction_deg?: number | null;
  ambient_temp_c?: number | null;
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
  message?: string;
  source_dataset?: string | null;
}

export interface BladeDiagnosisResult {
  turbine_id: number;
  damage_type: string;
  confidence: number;
  damage_bbox: { x: number; y: number; w: number; h: number } | null;
  image_path: string;
  image_url?: string | null;
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
  risk_level: string;
  estimated_saving: number;
  cost_drivers: string[];
}

export interface WorkOrder {
  id: number;
  turbine_id: number;
  fault_id: number | null;
  incident_id: number | null;
  title: string;
  description: string | null;
  status: string;
  priority?: 'low' | 'medium' | 'high' | 'urgent';
  fault_type?: string | null;
  due_date?: string | null;
  assignee: string | null;
  assignee_email?: string | null;
  cost_estimate: number;
  cost_actual: number | null;
  created_at: string;
  updated_at?: string | null;
  completed_at: string | null;
  cancelled_at?: string | null;
  deleted_at?: string | null;
  downtime_hours?: number | null;
  notification_sent_at?: string | null;
}

export interface AISummary {
  conclusions: string[];
  suggestions: string[];
  status?: 'success' | 'error';
  error_code?: string | null;
  error_message?: string | null;
  model_status?: {
    provider?: string;
    api_provider?: string;
    model?: string;
    mode?: string;
    has_api_key?: boolean;
  } | null;
  warnings?: string[];
}
// ── Drone Scheduler Types ──

export interface Waypoint3D {
  lat: number;
  lng: number;
  altitude: number;
}

export interface NoFlyZone {
  name: string;
  south_lat: number;
  north_lat: number;
  west_lng: number;
  east_lng: number;
  min_altitude: number;
  max_altitude: number;
}

export interface Drone {
  id: number;
  name: string;
  status: 'idle' | 'flying' | 'returning' | 'charging';
  battery: number;
  range: number;
  speed: number;
  color: string;
  assignedTurbines: number[];
  completedTurbines: number[];
  currentPosition: { lat: number; lng: number } | null;
  path: { lat: number; lng: number; alt?: number; turbineId?: number; kind?: 'takeoff' | 'climb' | 'inspect' | 'return' }[];
  progress: number;
  /** 3D 飞行高度 (m) */
  _altitude?: number;
}

export type InspectionTargetPart = 'blade_tip' | 'blade_root' | 'leading_edge' | 'trailing_edge' | 'hub' | 'nacelle';

export interface InspectionWaypoint {
  id: string;
  turbineId: number;
  position: [number, number, number];
  targetOffset: [number, number, number];
  targetPart: string;
  cameraYaw: number;
  cameraPitch: number;
  shootDistance: number;
  action: '拍照' | '悬停';
}

export interface DroneFleetConfig {
  count: number;
  range: number;
  speed: number;
}

export interface DroneSimState {
  fleet: Drone[];
  config: DroneFleetConfig;
  mode: 'tsp' | 'vrp';
  activeFarm: string | null;
  isRunning: boolean;
  speedMultiplier: number;
  totalTurbines: number;
  completedTurbines: number;
  elapsedTime: number;
}

// ── Incident Types ──

export interface Incident {
  id: number;
  incident_id: string;
  turbine_id: number;
  turbine_name: string;
  title: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  stage: string;
  status: string;
  owner_id: number | null;
  verification_status: string | null;
  alarm_count: number;
  compressed_count: number;
  trace_id: string | null;
  summary: string | null;
  resolution: string | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface AlarmRecord {
  id: number;
  incident_id: number;
  turbine_id: number;
  fault_id: number | null;
  source: string;
  alarm_type: string;
  component: string | null;
  severity: string;
  message: string | null;
  value: number | null;
  threshold: number | null;
  is_primary: boolean;
  compression_rule: string | null;
  compressed: boolean;
  fired_at: string;
}

export interface AlarmCluster {
  incident_id: string;
  primary_alarm: AlarmRecord | null;
  total_alarms: number;
  compressed_alarms: number;
  compression_rules: string[];
  alarms: AlarmRecord[];
}

export interface EvidenceNode {
  id: number;
  incident_id: number;
  node_type: 'observation' | 'hypothesis' | 'check' | 'action' | 'result';
  label: string;
  description: string | null;
  source: 'observation' | 'rule' | 'model' | 'llm' | 'human';
  confidence: number;
  props: Record<string, any> | null;
  created_at: string;
}

export interface EvidenceEdge {
  id: number;
  incident_id: number;
  source_node_id: number;
  target_node_id: number;
  edge_type: 'supports' | 'contradicts' | 'requires_check' | 'caused_by' | 'resolved_by';
  source: string;
  confidence: number;
  evidence_ref: string | null;
  created_at: string;
}

export interface EvidenceGraph {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
}

export interface DecisionPlan {
  id: number;
  incident_id: number;
  plan_name: string;
  strategy: string;
  safety_risk: number;
  downtime_loss: number;
  repair_cost: number;
  recovery_days: number;
  personnel_available: boolean;
  parts_available: boolean;
  weather_compatible: boolean;
  total_score: number;
  is_recommended: boolean;
  llm_explanation: string | null;
  decision_flip_point: string | null;
  created_at: string;
}

export interface DecisionSandbox {
  incident_id: string;
  plans: DecisionPlan[];
  recommended_index: number;
}

// One plan in the POST /incidents/{id}/generate-plans response
// (serialized in backend/app/api/incidents.py generate_decision_plans)
export interface GeneratedDecisionPlan {
  id: string; // 'PLAN-xxxxxxxx'
  plan_name: string;
  strategy: string;
  safety_risk: number;
  repair_cost: number;
  downtime_hours: number;
  downtime_loss: number;
  recovery_days: number;
  personnel_feasible: boolean;
  parts_feasible: boolean;
  weather_feasible: boolean;
  safety_score: number;
  economic_score: number;
  resource_score: number;
  recovery_time_score?: number; // computed server-side but not currently serialized
  total_score: number;
  is_recommended: boolean;
  is_feasible: boolean;
  infeasible_reasons: string[];
  score_confidence_interval: [number, number];
  data_quality_warnings: string[];
}

export interface PolicyCheckRequest {
  action: string;
  incident_id?: number;
  context?: Record<string, any>;
}

export interface PolicyCheckResponse {
  action: string;
  decision: 'allowed' | 'denied' | 'require_approval';
  matched_rules: string[];
  reason: string | null;
}

export interface PolicyRule {
  id: number;
  rule_id: string;
  description: string;
  action_pattern: string;
  risk_level: number;
  rule_type: string;
  is_active: boolean;
  version: string;
}

export interface AgentSpan {
  id: number;
  trace_id: string;
  parent_span_id: string | null;
  span_id: string;
  span_name: string;
  agent_name: string | null;
  tool_name: string | null;
  step_order: number;
  input_digest: string | null;
  output_digest: string | null;
  status: string;
  duration_ms: number;
  policy_decision: string | null;
  approval_by: string | null;
  error_code: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface AgentTrace {
  id: number;
  trace_id: string;
  incident_id: number | null;
  user_id: number | null;
  status: string;
  total_spans: number;
  total_duration_ms: number;
  token_usage: Record<string, any> | null;
  cost_estimate: number;
  error_code: string | null;
  started_at: string;
  ended_at: string | null;
  spans: AgentSpan[];
}
