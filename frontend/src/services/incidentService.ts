import api from './api';
import type {
  AgentTrace,
  AlarmCluster,
  DecisionSandbox,
  EvidenceEdge,
  EvidenceGraph,
  EvidenceNode,
  Incident,
  PolicyCheckRequest,
  PolicyCheckResponse,
  PolicyRule,
} from '../types';

const BASE = '/incidents';

export async function fetchIncidents(params?: {
  status?: string;
  turbine_id?: number;
}): Promise<Incident[]> {
  const { data } = await api.get(BASE, { params });
  return Array.isArray(data) ? data : [];
}

export async function fetchIncident(id: number): Promise<Incident> {
  const { data } = await api.get(`${BASE}/${id}`);
  return data;
}

export async function createIncident(body: {
  turbine_id: number;
  title: string;
  severity?: string;
  summary?: string;
}): Promise<Incident> {
  const { data } = await api.post(BASE, body);
  return data;
}

export async function updateIncident(
  id: number,
  body: Record<string, any>
): Promise<Incident> {
  const { data } = await api.put(`${BASE}/${id}`, body);
  return data;
}

export async function transitionIncident(
  id: number,
  target_stage: string,
  note?: string
): Promise<Incident> {
  const { data } = await api.post(`${BASE}/${id}/transition`, {
    target_stage,
    note,
  });
  return data;
}

export async function compressAlarms(
  id: number,
  turbine_id: number,
  window_minutes = 15
): Promise<AlarmCluster> {
  const { data } = await api.post(`${BASE}/${id}/compress-alarms`, {
    turbine_id,
    window_minutes,
  });
  return data;
}

export async function fetchEvidenceGraph(id: number): Promise<EvidenceGraph> {
  const { data } = await api.get(`${BASE}/${id}/evidence-graph`);
  return data;
}

export async function addEvidenceNode(
  id: number,
  body: {
    node_type: string;
    label: string;
    description?: string;
    source?: string;
    confidence?: number;
    props?: Record<string, any>;
  }
): Promise<EvidenceNode> {
  const { data } = await api.post(`${BASE}/${id}/evidence-nodes`, body);
  return data;
}

export async function addEvidenceEdge(
  id: number,
  body: {
    source_node_id: number;
    target_node_id: number;
    edge_type: string;
    source?: string;
    confidence?: number;
    evidence_ref?: string;
  }
): Promise<EvidenceEdge> {
  const { data } = await api.post(`${BASE}/${id}/evidence-edges`, body);
  return data;
}

export async function generateDecisionSandbox(
  id: number
): Promise<DecisionSandbox> {
  const { data } = await api.post(`${BASE}/${id}/decision-sandbox`);
  return data;
}

export async function checkPolicy(
  body: PolicyCheckRequest
): Promise<PolicyCheckResponse> {
  const { data } = await api.post('/policies/check', body);
  return data;
}

export async function fetchPolicies(): Promise<PolicyRule[]> {
  const { data } = await api.get('/policies');
  return Array.isArray(data) ? data : [];
}

export async function startTrace(id: number): Promise<AgentTrace> {
  const { data } = await api.post(`${BASE}/${id}/trace/start`);
  return data;
}

export async function fetchTraces(id: number): Promise<AgentTrace[]> {
  const { data } = await api.get(`${BASE}/${id}/trace`);
  return Array.isArray(data) ? data : [];
}

// ── Phase 1-2: ProofLoop endpoints ──

export async function startInvestigation(id: number): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/start-investigation`);
  return data;
}

export async function generatePlans(id: number): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/generate-plans`);
  return data;
}

export async function verifyRecovery(id: number): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/verify-recovery`);
  return data;
}

export async function getEvidenceCompleteness(id: number): Promise<any> {
  const { data } = await api.get(`${BASE}/${id}/evidence-completeness`);
  return data;
}

export async function getEconomicImpact(id: number): Promise<any> {
  const { data } = await api.get(`${BASE}/${id}/economic-impact`);
  return data;
}

export async function getAuditChain(id: number): Promise<any> {
  const { data } = await api.get(`${BASE}/${id}/audit-chain`);
  return data;
}

export async function verifyAuditChain(id: number): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/audit-chain/verify`);
  return data;
}

export async function getWhatIfAnalysis(id: number): Promise<any> {
  const { data } = await api.get(`${BASE}/${id}/what-if`);
  return data;
}

export async function getTaskPackage(id: number): Promise<any> {
  const { data } = await api.get(`${BASE}/${id}/task-package`);
  return data;
}

export async function getComplianceCheck(id: number, action?: string): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/compliance/check`, null, {
    params: { action: action || 'close_incident' },
  });
  return data;
}

export async function runRedTeamScenario(id: number, scenarioKey: string): Promise<any> {
  const { data } = await api.post(`${BASE}/${id}/red-team/run`, null, {
    params: { scenario_key: scenarioKey },
  });
  return data;
}

export async function getHealthPassport(turbineId: number): Promise<any> {
  const { data } = await api.get(`/turbines/${turbineId}/health-passport`);
  return data;
}
