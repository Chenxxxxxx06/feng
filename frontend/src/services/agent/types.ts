export interface AgentAtomicStep {
  order: number;
  skill: string;
  params: Record<string, string>;
  reason: string;
}

export interface AgentExecuteResponse {
  intent_type: string;
  confidence: number;
  entities: Record<string, string | null>;
  scene_skills: Array<{ skill: string; params: Record<string, string> }>;
  atomic_steps: AgentAtomicStep[];
  explanation: string;
  follow_up_analysis: string | null;
  requires_clarification: boolean;
  clarification_question: string | null;
}

export interface ExecutionProgress {
  status: 'pending' | 'running' | 'done' | 'failed';
  stepIndex: number;
  totalSteps: number;
  message: string;
  screenshot?: string;
  error?: string;
}
