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

    # 0. Analyze screenshot if provided
    screenshot_description = None
    if request.screenshot:
        try:
            from app.services.qwen_client import describe_screenshot
            screenshot_description = describe_screenshot(
                screenshot_base64=request.screenshot,
                page_type=request.page_context.get("page_type", "unknown") if request.page_context else "unknown",
                api_key=current_user.api_key,
                api_provider=current_user.api_provider,
                base_url=current_user.api_base_url,
            )
            logger.info(f"Screenshot analyzed for agent: {screenshot_description[:100]}...")
        except Exception as e:
            logger.warning(f"Screenshot analysis failed in agent path: {e}")

    # 1. Get turbine list for orchestrator context
    result = await db.execute(select(Turbine))
    turbine_list = ", ".join(f"#{t.id} {t.name}" for t in result.scalars().all())

    # 2. Orchestrator: parse intent
    api_key = current_user.api_key
    api_provider = current_user.api_provider
    api_base_url = current_user.api_base_url
    agent_model = current_user.model_preference or "qwen-max"
    orchestrator = OrchestratorAgent(model=agent_model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)
    orch_result = await orchestrator.run(user_message=user_msg, turbine_list=turbine_list)

    intent_type = orch_result.data.get("intent_type", "general_chat")

    # Inject screenshot description into user message context
    if screenshot_description:
        user_msg += f"\n\n[当前页面截图分析]\n{screenshot_description}"

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
        data_agent = DataAgent(model=agent_model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)
        context = await data_agent.gather_context(turbine_id, db)
        tasks.append(data_agent.run(
            query=orchestrator.dispatch_query(orch_result.data, "data_agent"),
            data_context=str(context),
        ))

    if orchestrator.needs_knowledge_agent(orch_result.data):
        knowledge_agent = KnowledgeAgent(model=agent_model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)
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
    synthesizer = SynthesizerAgent(model=agent_model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)
    synth_result = await synthesizer.run(
        data_result=str(data_result.data) if data_result else "（未查询实时数据）",
        knowledge_result=str(knowledge_result.data) if knowledge_result else "（知识库为空或未匹配）",
    )

    reply = synth_result.data.get("reply", str(synth_result.data))

    # 5. Trigger knowledge extraction as background task
    from app.services.knowledge_extractor import try_extract_knowledge
    all_messages = request.messages + [{"role": "assistant", "content": reply}]
    background_tasks.add_task(try_extract_knowledge, all_messages, api_key, api_provider, api_base_url)

    return {
        "intent": orch_result.data,
        "report": reply,
        "data_summary": data_result.data if data_result else None,
        "knowledge_matches": knowledge_result.data if knowledge_result else None,
        "trace": {
            "orchestrator_ms": orch_result.duration_ms,
            "data_agent_ms": data_result.duration_ms if data_result else 0,
            "knowledge_agent_ms": knowledge_result.duration_ms if knowledge_result else 0,
            "synthesizer_ms": synth_result.duration_ms,
        },
    }
