import { SkillRegistry } from './SkillRegistry';
import type { AgentAtomicStep, ExecutionProgress } from './types';

export type ProgressCallback = (p: ExecutionProgress) => void;

/** Executes atomic skill steps sequentially in the browser */
export class AgentExecutor {
  constructor(
    private registry: SkillRegistry,
    private onProgress: ProgressCallback,
  ) {}

  async executeSteps(steps: AgentAtomicStep[]): Promise<{ success: boolean; message: string }> {
    const total = steps.length;
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      this.onProgress({
        status: 'running', stepIndex: i, totalSteps: total,
        message: `步骤 ${step.order}: ${step.reason}`,
      });

      const skill = this.registry.get(step.skill);
      if (!skill) {
        this.onProgress({
          status: 'failed', stepIndex: i, totalSteps: total,
          message: `未知Skill: ${step.skill}`,
          error: `Skill "${step.skill}" 未注册`,
        });
        return { success: false, message: `步骤${step.order}失败: 未知Skill` };
      }

      try {
        const result = await skill.execute(step.params);
        this.onProgress({
          status: 'done', stepIndex: i, totalSteps: total,
          message: result.message, screenshot: result.screenshot,
        });
      } catch (err: any) {
        this.onProgress({
          status: 'failed', stepIndex: i, totalSteps: total,
          message: `步骤 ${step.order} 失败`, error: err.message,
        });
        return { success: false, message: `步骤${step.order}失败: ${err.message}` };
      }
    }
    return { success: true, message: `全部 ${total} 步已完成` };
  }
}
