"""Task Agent -- plans natural-language task commands into executable action
sequences, dispatches them via TaskExecutor, and returns a human-readable summary.

Pipeline:  [Plan] LLM → [Execute] TaskExecutor → [Summarize] LLM → reply
"""

import json
import logging
import time
from .base import AgentBase, AgentResult

logger = logging.getLogger(__name__)

TASK_AGENT_SYSTEM_PROMPT = """你是风调预顺PHM系统的任务执行智能体。用户用自然语言描述一个运维任务，你需要输出一个结构化的JSON执行计划。

## 可用操作

### 数据查询
1. find_turbine(name: str)
   按风机名称模糊搜索。返回: {{"turbine_id": int, "turbine_name": str, "status": str, "region": str}}

2. list_turbines(status?: str)
   列出所有风机。status可选: normal/warning/fault。返回数组: [{{"turbine_id": int, "turbine_name": str, "status": str, "hi_value": float}}]

3. list_faults(turbine_id?: int, status?: str)
   列出故障记录。status可选: open/closed。返回数组: [{{"fault_id": int, "turbine_id": int, "fault_type": str, "confidence": float, "status": str, "detected_at": str}}]

### 工单操作
4. list_work_orders(turbine_id?: int, status?: str)
   列出工单。status可选: pending/assigned/in_progress/review/completed/closed/cancelled

5. create_work_order(turbine_id: int, title: str, description?: str, priority?: str)
   创建新工单。priority可选: low/medium/high/urgent

6. update_work_order(wo_id: int, status?: str, assignee?: str)
   更新工单状态和/或负责人

7. cancel_work_order(wo_id: int)
   取消工单

8. send_work_order_email(wo_id: int)
   将工单邮件发送给当前负责人

### 人员
9. list_personnel()
   列出所有活跃技术人员及其当前负载

### 页面跳转
10. navigate(page: str, turbine_id?: int, wo_id?: int)
    跳转到指定页面。page可选: dashboard/diagnosis/prediction/workorders/knowledge/settings/turbine。风机详情传turbine_id。工单页传wo_id可自动打开该工单。

## 关键词映射（非常重要）
- "查看故障诊断页面"/"故障诊断"/"打开诊断" → navigate(page="diagnosis")
- "查看预测页面"/"寿命预测"/"打开预测" → navigate(page="prediction")
- "查看工单页面"/"工单管理" → navigate(page="workorders")
- "查看知识库"/"知识图谱" → navigate(page="knowledge")
- "查看设置"/"打开设置" → navigate(page="settings")
- "回首页"/"仪表盘" → navigate(page="dashboard")
- "打开A003风机"/"查看A003详情" → 先用 find_turbine("A003")，再用 navigate(page="turbine", turbine_id=$step_1.turbine_id)
- "打开第一个工单"/"查看第N个工单" → 先 list_work_orders，然后用 navigate(page="workorders", wo_id=第一个工单的wo_id)
- "故障"/"故障记录" → list_faults（查故障数据）
- "风机列表"/"所有风机" → list_turbines（查风机数据）
- "工单"/"工单列表" → list_work_orders（查工单数据）
- "人员"/"技术员" → list_personnel（查人员数据）
- 提到具体风机名（如"A003"）→ 先用 find_turbine，再根据需求组合其他操作

## 重要规则
- 用户说"查看/打开X页面" → 优先用 navigate 跳转，而不是查数据
- 用户说"查看X数据/记录" → 用对应的 list_ 查询
- 步骤按顺序执行，后续步骤可引用前置结果：$step_1.turbine_id
- 缺少关键信息时填入 missing_info 数组

## 输出格式（严格 JSON, 不要 markdown）

当前页面: {page_context}
用户指令: {user_message}

请输出 JSON:"""


SUMMARY_SYSTEM_PROMPT = "你是风调预顺PHM系统的运维助手。请根据系统执行结果给用户一个简明的中文回应。"


class TaskAgent(AgentBase):
    """Task-planning agent: plan → execute → summarize."""

    def __init__(self, model: str = "qwen-max",
                 api_key: str | None = None,
                 api_provider: str | None = None):
        super().__init__(
            name="task_agent",
            system_prompt=TASK_AGENT_SYSTEM_PROMPT,
            model=model,
            api_key=api_key,
            api_provider=api_provider,
        )

    async def summarize(self, user_message: str, execution_results: list[dict]) -> str:
        """Stage 3: call LLM to produce a human-readable result summary."""
        result_json = json.dumps(execution_results, ensure_ascii=False, indent=2)

        summary_prompt = (
            f'用户刚才说: "{user_message}"\n\n'
            f"以下是系统执行的结果:\n{result_json}\n\n"
            f"请用简洁的中文(150字以内)总结执行情况。"
            f"成功了哪些、关键数据(工单号、风机名、邮件状态)、"
            f"如果有失败说明原因。语气友好专业。不要用JSON格式。"
        )

        try:
            t0 = time.time()
            response = await self._call_llm(
                summary_prompt,
                override_system=SUMMARY_SYSTEM_PROMPT,
            )
            logger.info("TaskAgent summary generated in %dms", int((time.time() - t0) * 1000))
            return response
        except Exception as e:
            logger.error("TaskAgent summarize failed: %s", e)
            return self._fallback_summary(execution_results)

    @staticmethod
    def _fallback_summary(results: list[dict]) -> str:
        """Build a simple summary when the LLM summarization fails."""
        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count
        lines = [f"任务执行完成: {success_count} 项成功, {fail_count} 项失败。"]
        for r in results:
            status = "成功" if r.get("success") else "失败"
            detail = ""
            if r.get("success") and r.get("result"):
                res = r["result"]
                if isinstance(res, dict):
                    detail = f" — {json.dumps(res, ensure_ascii=False)}"
                elif isinstance(res, list):
                    detail = f" — 返回 {len(res)} 条记录"
            elif not r.get("success"):
                detail = f" — {r.get('error', '未知错误')}"
            lines.append(f"  [{status}] 步骤{r['step']} {r['action']}{detail}")
        return "\n".join(lines)
