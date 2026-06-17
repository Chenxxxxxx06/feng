/**
 * Prediction API service layer — centralized prediction-related API calls.
 */
import api from './api';
import type { RULPrediction, CostComparison, Turbine } from '../types';

export interface PredictionSummary {
  fleet: {
    total: number;
    healthy: number;
    warning: number;
    fault: number;
    avg_hi: number | null;
  };
  rul: {
    total_predictions: number;
    avg_days: number | null;
    min_days: number | null;
    max_days: number | null;
    imminent_count: number;
    critical_count: number;
  };
  reliability: {
    mtbf_hours: number;
    mttr_hours: number;
  };
  by_region: Record<string, { avg_rul: number; count: number }>;
  generated_at: string;
}

export interface FaultTypeOption {
  value: string;
  label: string;
  component: string;
}

export const predictionService = {
  /** Get all RUL predictions, optionally filtered */
  async getRUL(params?: {
    turbine_id?: number;
    component?: string;
    max_remaining_days?: number;
  }): Promise<RULPrediction[]> {
    const { data } = await api.get('/prediction/rul', { params });
    return data.predictions || [];
  },

  /** Get aggregated prediction statistics */
  async getSummary(): Promise<PredictionSummary> {
    const { data } = await api.get('/prediction/summary');
    return data;
  },

  /** Get valid fault types for cost comparison */
  async getFaultTypes(): Promise<FaultTypeOption[]> {
    const { data } = await api.get('/prediction/fault-types');
    return data.types || [];
  },

  /** Compare repair costs */
  async compareCost(turbineId: number, faultType: string): Promise<CostComparison> {
    const { data } = await api.post('/prediction/cost-comparison', {
      turbine_id: turbineId,
      fault_type: faultType,
    });
    return data;
  },

  /** Get all turbines (for dropdowns) */
  async getTurbines(): Promise<Turbine[]> {
    const { data } = await api.get('/turbines/');
    return data.turbines || [];
  },
};
