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
  data_source?: string;
  dataset_window?: 'recent' | 'historical_latest';
  source_dataset?: string | null;
  source_file?: string | null;
  source_row?: number | null;
  source_turbine_id?: string | null;
}

export interface Fault {
  id: number;
  turbine_id: number;
  turbine_name?: string;
  detected_at: string;
  fault_type: string;
  confidence: number;
  status: string;
  details?: Record<string, any>;
}

export interface FaultDetail extends Fault {
  signals: FaultSignal[];
}

export interface FaultSignal {
  id: number;
  sensor_name: string;
  contribution_score: number;
  priority: string;
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
  risk_level: 'low' | 'medium' | 'high';
  estimated_saving: number;
  cost_drivers: string[];
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
