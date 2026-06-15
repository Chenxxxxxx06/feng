r"""Agent API — multi-agent diagnosis endpoint."""

import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models import User
from app.schemas import AICopilotRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/diagnose")
async def multi_agent_diagnose(
    request: AICopilotRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Multi-agent diagnosis: Orchestrator -> Data + Knowledge -> Synthesizer -> Report."""
    from app.services.agents import (
        OrchestratorAgent, DataAgent, KnowledgeAgent, SynthesizerAgent,
    )
    from app.models import Turbine
    from sqlalchemy import select

    user_msg = request.messages[-1]["content"] if request.messages else ""

    # 1. Get turbine list for orchestrator context
    result = await db.execute(select(Turbine))
    turbine_list = ", ".join(f"#{t.id} {t.name}" for t in result.scalars().all())

    # 2. Orchestrator: parse intent
    api_key = current_user.api_key
    api_provider = current_user.api_provider
    orchestrator = OrchestratorAgent(api_key=api_key, api_provider=api_provider)
    orch_result = await orchestrator.run(user_message=user_msg, turbine_list=turbine_list)

    intent_type = orch_result.data.get("intent_type", "general_chat")

    # For non-diagnosis intents, return simple explanation
    if intent_type == "general_chat":
        return {
            "intent": orch_result.data,
            "report": None,
            "message": orch_result.data.get("explanation", "这是非诊断类问题，请直接使用Copilot对话模式。"),
            "trace": {"orchestrator_ms": orch_result.duration_ms},
        }

    # 3. Parallel dispatch Data + Knowledge agents
    data_result = None
    knowledge_result = None
    tasks = []

    # Extract turbine_id from entities
    entities = orch_result.data.get("entities", {})
    turbine_id = entities.get("turbine_id")

    if orchestrator.needs_data_agent(orch_result.data):
        data_agent = DataAgent(api_key=api_key, api_provider=api_provider)
        context = await data_agent.gather_context(turbine_id, db)
        tasks.append(data_agent.run(
            query=orchestrator.dispatch_query(orch_result.data, "data_agent"),
            data_context=str(context),
        ))

    if orchestrator.needs_knowledge_agent(orch_result.data):
        knowledge_agent = KnowledgeAgent(api_key=api_key, api_provider=api_provider)
        kb_context = await knowledge_agent.load_knowledge_context(db)
        tasks.append(knowledge_agent.run(
            query=orchestrator.dispatch_query(orch_result.data, "knowledge_agent"),
            knowledge_context=kb_context,
        ))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Agent error: {r}")
            elif r.agent == "data_agent":
                data_result = r
            elif r.agent == "knowledge_agent":
                knowledge_result = r

    # 4. Synthesizer: merge results
    synthesizer = SynthesizerAgent(api_key=api_key, api_provider=api_provider)
    synth_result = await synthesizer.run(
        data_result=str(data_result.data) if data_result else "（未查询实时数据）",
        knowledge_result=str(knowledge_result.data) if knowledge_result else "（知识库为空或未匹配）",
    )

    report = synth_result.data.get("reply", str(synth_result.data))

    # 5. Trigger background knowledge extraction from agent diagnosis
    from app.services.knowledge_extractor import try_extract_knowledge
    all_messages = request.messages + [{"role": "assistant", "content": report}]
    background_tasks.add_task(try_extract_knowledge, all_messages, current_user.api_key, current_user.api_provider)

    return {
        "intent": orch_result.data,
        "report": report,
        "data_summary": data_result.data if data_result else None,
        "knowledge_matches": knowledge_result.data if knowledge_result else None,
        "trace": {
            "orchestrator_ms": orch_result.duration_ms,
            "data_agent_ms": data_result.duration_ms if data_result else 0,
            "knowledge_agent_ms": knowledge_result.duration_ms if knowledge_result else 0,
            "synthesizer_ms": synth_result.duration_ms,
        },
    }


@router.post("/agent/task")
async def task_agent_execute(
    request: AICopilotRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Task execution agent: natural language → action plan → execute → summarize.

    Handles commands like:
    - "请帮我打开A003风机的维修工单，并把工单发送至对应工人邮箱"
    - "查看当前所有维护人员的工作量"
    - "为A003风机创建一个紧急齿轮箱检修工单"
    """
    from app.services.agents import TaskAgent
    from app.services.task_executor import TaskExecutor, StepExecutionError

    user_msg = request.messages[-1]["content"] if request.messages else ""

    # Guard: API key required
    if not current_user.api_key:
        return {
            "intent": "error",
            "message": "Agent任务模式需要配置AI API Key。请在系统设置 → AI设置中配置API Key后重试。",
            "report": None,
            "trace": {},
        }

    api_key = current_user.api_key
    api_provider = current_user.api_provider

    # Build page context string for the LLM
    page_ctx = request.page_context or {}
    page_ctx_str = (
        f"turbine_id={page_ctx.get('turbine_id', 'N/A')}, "
        f"turbine_name={page_ctx.get('turbine_name', 'N/A')}, "
        f"total_orders={page_ctx.get('total_orders', 'N/A')}"
    )

    # Stage 1: PLAN
    task_agent = TaskAgent(api_key=api_key, api_provider=api_provider)
    plan_result = await task_agent.run(
        user_message=user_msg,
        page_context=page_ctx_str,
    )

    plan_data = plan_result.data
    intent = plan_data.get("intent", "unknown")

    # If LLM call failed, surface the error
    if plan_result.error:
        return {
            "intent": "error",
            "message": f"AI 规划失败: {plan_result.error}\n\n请检查 API Key 是否正确配置，或尝试更换模型。",
            "report": None,
            "trace": {"plan_ms": plan_result.duration_ms, "error": plan_result.error},
        }

    # Only "unsupported" means truly unsupported; other intents are fine
    if intent == "unsupported":
        return {
            "intent": "unsupported",
            "message": plan_data.get("summary_hint",
                "抱歉，当前 Agent 任务模式暂不支持该操作。\n\n支持的操作：\n- 查看/搜索风机\n- 查看/创建/修改/取消工单\n- 发送工单邮件\n- 查看维护人员及工作量\n\n请尝试换一种说法描述您的任务。"),
            "report": None,
            "trace": {"plan_ms": plan_result.duration_ms},
        }

    missing = plan_data.get("missing_info", [])
    if missing:
        return {
            "intent": "missing_info",
            "message": "需要补充以下信息:\n" + "\n".join(f"  • {m}" for m in missing),
            "report": None,
            "trace": {"plan_ms": plan_result.duration_ms},
        }

    steps = plan_data.get("steps", [])
    if not steps:
        return {
            "intent": "no_action",
            "message": "未能识别到可执行的操作步骤。请更具体地描述您的任务。",
            "report": None,
            "trace": {"plan_ms": plan_result.duration_ms},
        }

    # Stage 2: EXECUTE
    executor = TaskExecutor(db)
    try:
        exec_results = await executor.execute(steps)
    except StepExecutionError as e:
        return {
            "intent": "execution_error",
            "message": f"步骤 {e.step} ({e.action}) 执行失败: {e.message}",
            "report": None,
            "trace": {"plan_ms": plan_result.duration_ms},
        }

    # Stage 3: SUMMARIZE
    report = await task_agent.summarize(user_msg, exec_results)

    all_success = all(r.get("success") for r in exec_results)

    # Extract frontend actions (navigate) from execution results
    frontend_actions = []
    for r in exec_results:
        if r.get("success") and r.get("result") and isinstance(r["result"], dict):
            nav = r["result"].get("navigate_to")
            if nav:
                frontend_actions.append({"type": "navigate", "url": nav})

    return {
        "intent": "task_execution",
        "message": report,
        "report": report,
        "all_success": all_success,
        "actions": frontend_actions or None,
        "trace": {
            "plan_ms": plan_result.duration_ms,
            "steps": exec_results,
        },
    }
