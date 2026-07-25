r"""Agent API — multi-agent diagnosis endpoint + unified agent execution."""

import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models import User
from app.schemas import AICopilotRequest, AgentExecuteRequest, AgentExecuteResponse, AgentAtomicStep, AgentSceneSkill

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
            screenshot_description = await asyncio.to_thread(
                describe_screenshot,
                screenshot_base64=request.screenshot,
                page_type=request.page_context.get("page_type", "unknown") if request.page_context else "unknown",
                api_key=current_user.api_key,
                api_provider=current_user.api_provider,
                base_url=current_user.api_base_url,
            )
            logger.info(f"Screenshot analyzed for agent: {screenshot_description[:100]}...")
        except Exception as e:
            logger.warning(f"Screenshot analysis failed in agent path: {e}")

    # 1. Get turbine list for orchestrator context (include region)
    result = await db.execute(select(Turbine))
    turbine_list = ", ".join(f"#{t.id} {t.name}({t.region or ''})" for t in result.scalars().all())

    # 2. Orchestrator: parse intent
    api_key = current_user.api_key
    api_provider = current_user.api_provider
    api_base_url = current_user.api_base_url
    agent_model = "qwen-turbo"  # fast model for intent routing
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


@router.post("/agent/execute", response_model=AgentExecuteResponse)
async def execute_agent_command(
    request: AgentExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unified agent entry: classify intent → route to action or diagnosis."""
    from app.services.agents import IntentRouterAgent
    from app.models import Turbine
    from sqlalchemy import select

    # 1. Turbine list for entity resolution (include region for "区域A" matching)
    result = await db.execute(select(Turbine))
    turbines = result.scalars().all()
    turbine_list = ", ".join(f"#{t.id} {t.name}({t.region or ''})" for t in turbines)

    # 2. IntentRouter: classify + plan
    api_key = current_user.api_key
    api_provider = current_user.api_provider
    api_base_url = current_user.api_base_url
    agent_model = "qwen-turbo"  # fast model for intent routing

    router = IntentRouterAgent(
        model=agent_model, api_key=api_key,
        api_provider=api_provider, api_base_url=api_base_url,
    )
    router_result = await router.run(
        user_message=request.command,
        current_page=request.current_page or "unknown",
        turbine_list=turbine_list,
    )

    intent_data = router_result.data or {}
    # Check for LLM failure
    if router_result.error and not intent_data:
        return AgentExecuteResponse(
            intent_type="qa", confidence=0.0, entities={},
            scene_skills=[], atomic_steps=[],
            explanation="",
            requires_clarification=True,
            clarification_question="AI服务暂时不可用, 请稍后重试",
        )

    intent_type = intent_data.get("intent_type", "qa")
    confidence = intent_data.get("confidence", 0.5)
    entities = intent_data.get("entities", {})

    # 3. Build atomic steps — prefer LLM direct output, fallback to resolver
    atomic_steps: list[AgentAtomicStep] = []
    scene_skills_data: list[dict] = []
    if intent_type in ("action", "mixed"):
        llm_steps: list[dict] = intent_data.get("atomic_steps", [])
        if llm_steps:
            # LLM already decomposed into atomic operations → use directly
            for i, s in enumerate(llm_steps):
                atomic_steps.append(AgentAtomicStep(
                    order=s.get("order", i + 1),
                    skill=s["skill"],
                    params=s.get("params", {}),
                    reason=s.get("reason", ""),
                ))
        else:
            # Fallback: resolve scene_skills via hardcoded mapping
            scene_skills_data = intent_data.get("scene_skills", [])
            if scene_skills_data:
                atomic_steps = _resolve_atomic_steps(scene_skills_data, entities)

    # 4. Clarification check
    requires_clarification = router.needs_clarification(intent_data)
    clarification = None
    if requires_clarification:
        clarification = (
            f"不太确定您的意图（置信度{confidence:.0%}）。"
            f"您是想：1) 操作界面  2) 提问知识  3) 诊断风机？"
        )

    return AgentExecuteResponse(
        intent_type=intent_type,
        confidence=confidence,
        entities=entities,
        scene_skills=[AgentSceneSkill(skill=s["skill"], params=s.get("params", {}))
                      for s in scene_skills_data],
        atomic_steps=atomic_steps,
        explanation=intent_data.get("explanation", ""),
        follow_up_analysis=intent_data.get("follow_up_analysis") or None,
        requires_clarification=requires_clarification,
        clarification_question=clarification,
    )


def _resolve_atomic_steps(scene_skills: list[dict], entities: dict | None = None) -> list[AgentAtomicStep]:
    """Resolve scene skills to atomic DOM operation steps."""
    entities = entities or {}
    step_defs = {
        # ── Navigation ──
        "NavigateToMonitor": [
            {"skill": "navigate", "params": {"path": "/dashboard"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "NavigateToDiagnosis": [
            {"skill": "navigate", "params": {"path": "/diagnosis"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "NavigateToPrediction": [
            {"skill": "navigate", "params": {"path": "/prediction"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "NavigateToWorkOrder": [
            {"skill": "navigate", "params": {"path": "/workorder"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "GoToWorkOrder": [
            {"skill": "navigate", "params": {"path": "/workorder"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "NavigateToKnowledge": [
            {"skill": "navigate", "params": {"path": "/knowledge"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "NavigateToTurbineDetail": [
            {"skill": "navigate", "params": {"path": "/turbine/{turbine_id}"}},
            {"skill": "wait", "params": {"ms": "1000"}},
            {"skill": "screenshot", "params": {}},
        ],
        "GoBack": [
            {"skill": "click", "params": {"selector": "[data-action='back']"}},
            {"skill": "wait", "params": {"ms": "500"}},
        ],
        # ── Turbine interaction ──
        "LocateTurbineOnMap": [
            {"skill": "waitForElement",
             "params": {"selector": "[data-turbine-id='{turbine_id}']", "timeout": "5000"}},
            {"skill": "click",
             "params": {"selector": "[data-turbine-id='{turbine_id}']"}},
            {"skill": "wait", "params": {"ms": "500"}},
        ],
        "OpenTurbineDetailPanel": [
            {"skill": "waitForElement",
             "params": {"selector": "[data-turbine-id='{turbine_id}']", "timeout": "5000"}},
            {"skill": "click",
             "params": {"selector": "[data-turbine-id='{turbine_id}']"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        "SelectTurbineInDiagnosis": [
            {"skill": "click", "params": {"selector": "[data-action='select-turbine']"}},
            {"skill": "wait", "params": {"ms": "300"}},
            {"skill": "click",
             "params": {"selector": "option[value='{turbine_id}']"}},
            {"skill": "wait", "params": {"ms": "800"}},
        ],
        "RunAutoDetect": [
            {"skill": "click", "params": {"selector": "[data-action='run-auto-detect']"}},
            {"skill": "wait", "params": {"ms": "3000"}},
            {"skill": "screenshot", "params": {}},
        ],
        # ── Work Order ──
        "CreateWorkOrder": [
            {"skill": "click", "params": {"selector": "[data-action='create-workorder']"}},
            {"skill": "wait", "params": {"ms": "500"}},
            {"skill": "screenshot", "params": {}},
        ],
        "OpenWorkOrderPreview": [
            {"skill": "waitForElement",
             "params": {"selector": "[data-action='preview-workorder'][data-wo-assignee*='{assignee}']", "timeout": "5000"}},
            {"skill": "click",
             "params": {"selector": "[data-action='preview-workorder'][data-wo-assignee*='{assignee}']"}},
            {"skill": "wait", "params": {"ms": "1200"}},
            {"skill": "screenshot", "params": {}},
        ],
        "FilterWorkOrders": [
            {"skill": "click", "params": {"selector": "[data-action='filter-status']"}},
            {"skill": "wait", "params": {"ms": "300"}},
            {"skill": "click", "params": {"selector": "option[value='{status}']"}},
            {"skill": "wait", "params": {"ms": "800"}},
            {"skill": "screenshot", "params": {}},
        ],
        # ── Prediction ──
        "RunSchedule": [
            {"skill": "click", "params": {"selector": "[data-action='run-schedule']"}},
            {"skill": "wait", "params": {"ms": "2000"}},
            {"skill": "screenshot", "params": {}},
        ],
        "CompareCost": [
            {"skill": "click", "params": {"selector": "[data-action='compare-cost']"}},
            {"skill": "wait", "params": {"ms": "2000"}},
            {"skill": "screenshot", "params": {}},
        ],
        # ── Analysis combos ──
        "AnalyzeAndReport": [
            {"skill": "screenshot", "params": {}},
            {"skill": "wait", "params": {"ms": "1000"}},
        ],
        "MultiPageAudit": [
            {"skill": "navigate", "params": {"path": "/dashboard"}},
            {"skill": "wait", "params": {"ms": "1000"}},
            {"skill": "screenshot", "params": {}},
            {"skill": "navigate", "params": {"path": "/diagnosis"}},
            {"skill": "wait", "params": {"ms": "1000"}},
            {"skill": "screenshot", "params": {}},
            {"skill": "navigate", "params": {"path": "/prediction"}},
            {"skill": "wait", "params": {"ms": "1000"}},
            {"skill": "screenshot", "params": {}},
        ],
    }

    steps: list[AgentAtomicStep] = []
    order = 0
    for scene in scene_skills:
        skill_name = scene.get("skill", "")
        params = scene.get("params", {})
        defs = step_defs.get(skill_name, [])
        for d in defs:
            order += 1
            resolved: dict = {}
            # Merge entities as fallback for missing param keys
            merged = {**entities, **params}
            for k, v in d["params"].items():
                if isinstance(v, str) and "{" in v:
                    try:
                        resolved[k] = v.format(**merged)
                    except KeyError:
                        resolved[k] = v  # keep placeholder as-is on missing key
                else:
                    resolved[k] = v
            steps.append(AgentAtomicStep(
                order=order, skill=d["skill"], params=resolved,
                reason=f"{skill_name}.{d['skill']}",
            ))
    return steps


@router.post("/agent/task")
async def agent_task(
    request: AICopilotRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Agent task endpoint — delegates to multi-agent diagnose for complex analysis.

    Frontend CopilotFAB 'Agent任务' mode target.
    """
    # Extract last user message as the task description
    user_msgs = [m for m in request.messages if m.get("role") == "user"]
    task_desc = user_msgs[-1].get("content", "") if user_msgs else "分析当前风场状态"

    # Try to identify turbine_id from page_context
    turbine_id = None
    if request.page_context:
        turbine_id = request.page_context.get("turbine_id")
        if not turbine_id:
            turbine_id = request.page_context.get("selectedTurbineId")

    from app.models import Turbine, Fault, SCADARecord
    from sqlalchemy import select, func

    # Gather context
    report_parts: list[str] = [f"## Agent任务报告\n\n**任务**: {task_desc}\n"]

    # Fleet overview
    total = (await db.execute(select(func.count(Turbine.id)))).scalar() or 0
    healthy = (await db.execute(select(func.count(Turbine.id)).where(Turbine.status == "normal"))).scalar() or 0
    warning = (await db.execute(select(func.count(Turbine.id)).where(Turbine.status == "warning"))).scalar() or 0
    faulty = (await db.execute(select(func.count(Turbine.id)).where(Turbine.status == "fault"))).scalar() or 0
    report_parts.append(f"**全场状态**: {total}台风机, {healthy}正常/{warning}预警/{faulty}故障")

    if turbine_id:
        turbine = await db.get(Turbine, turbine_id)
        if turbine:
            report_parts.append(f"\n**目标风机**: {turbine.name} (HI: {turbine.hi_value:.0f}, 状态: {turbine.status})")
            faults = (await db.execute(
                select(Fault).where(Fault.turbine_id == turbine_id).order_by(Fault.detected_at.desc()).limit(3)
            )).scalars().all()
            if faults:
                report_parts.append(f"**关联故障**: {len(faults)}条")
                for f in faults:
                    report_parts.append(f"- {f.fault_type} (置信度{f.confidence:.0%})")

    # Try AI analysis
    try:
        from app.services.qwen_client import copilot_chat
        ai_reply = await asyncio.to_thread(
            copilot_chat,
            messages=[{"role": "user", "content": task_desc}],
            page_context=request.page_context or {},
            model=current_user.model_preference,
            api_key=current_user.api_key,
            api_provider=current_user.api_provider,
        )
        report_parts.append(f"\n### AI分析结果\n{ai_reply}")
    except Exception:
        report_parts.append("\n### 建议\nAI服务暂不可用，请检查API密钥配置。")

    return {
        "success": True,
        "report": "\n".join(report_parts),
        "message": "Agent任务分析完成",
    }
