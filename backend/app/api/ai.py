"""AI API endpoints for fault analysis and copilot chat.

Provides AI-powered analysis using Qwen API with fallback to local analysis.
"""

import asyncio
import json
import logging
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Turbine, SCADARecord, Fault, User, AIProviderConfig
from app.schemas import (
    AISummaryRequest, AISummaryResponse,
    AIFaultAnalysisRequest, AIFaultAnalysisResponse,
    AICopilotRequest, AICopilotResponse,
    AITestConnectionRequest,
)
from app.api.auth import get_current_user
from app.services.copilot_context import (
    build_copilot_context_bundle,
    get_allowed_tool_specs,
    plan_tool_names_rule_based,
)
from app.services.qwen_client import summarize_page, diagnose_fault, copilot_chat, copilot_chat_stream, describe_model, chat

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _safe_ai_error_message(exc: Exception) -> str:
    """Return a compact upstream error message without leaking credentials."""
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)
    text = re.sub(r"(api[_-]?key[=:]\s*)[A-Za-z0-9_\-]{8,}", r"\1***", text, flags=re.I)
    return text[:240]


def _classify_ai_error(exc: Exception) -> tuple[str, str]:
    """Map provider/client exceptions to UI-stable Copilot error codes."""
    status_code = getattr(exc, "status_code", None)
    message = _safe_ai_error_message(exc)
    lower = message.lower()

    if status_code in (401, 403) or any(token in lower for token in ("invalid api key", "unauthorized", "forbidden", "authentication")):
        return "upstream_auth_failed", "AI供应商鉴权失败，请检查 API KEY 是否正确、是否属于当前模型供应商。"
    if status_code == 404 or any(token in lower for token in ("model_not_found", "model not found", "model does not exist", "model not exist", "invalid model")):
        return "model_not_found", "模型名称不可用，请检查系统设置中的模型ID或切换到供应商支持的模型。"
    if status_code == 429 or "rate limit" in lower or "quota" in lower or "insufficient" in lower:
        return "upstream_rate_limited", "AI供应商限流或额度不足，请稍后重试或检查账户余额/配额。"
    if status_code and 500 <= int(status_code) < 600:
        return "upstream_server_error", "AI供应商服务异常，请稍后重试。"
    if "timeout" in lower or "timed out" in lower:
        return "upstream_timeout", "AI请求超时，请检查网络或供应商响应状态。"
    if any(token in lower for token in ("connect", "connection", "network", "dns", "proxy")):
        return "network_error", "无法连接AI供应商，请检查后端服务器网络、代理或 Base URL。"
    if "api key not configured" in lower or "key not configured" in lower:
        return "api_key_missing", "当前账号未配置AI服务密钥，请在系统设置中保存 API KEY。"
    if "provider" in lower and "requires" in lower:
        return "provider_mismatch", "当前 API KEY 供应商与所选模型供应商不匹配，请重新选择模型或保存对应密钥。"
    return "upstream_unknown", f"AI调用失败：{message}"


def _cleanup_session_title(title: str) -> str:
    cleaned = re.sub(r"^[\"'“”‘’\s]+|[\"'“”‘’\s]+$", "", title.strip())
    cleaned = re.sub(r"^(标题|会话名称|名称)[:：]\s*", "", cleaned)
    cleaned = re.sub(r"[\r\n]+", " ", cleaned).strip()
    return cleaned[:24] or "AI会话"


def _generate_session_title(
    messages: list[dict],
    model: Optional[str],
    api_key: Optional[str],
    api_provider: Optional[str],
    base_url: Optional[str],
) -> Optional[str]:
    user_text = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    if not user_text:
        return None
    prompt = (
        "请根据用户首轮问题生成一个中文会话名称。"
        "要求：不超过12个汉字或24个字符；不要包含供应商名称；不要解释；只输出名称。\n\n"
        f"用户问题：{user_text[:600]}"
    )
    try:
        title = chat(
            [{"role": "user", "content": prompt}],
            model=model,
            api_key=api_key,
            api_provider=api_provider if not base_url else None,
            base_url=base_url,
            temperature=0.2,
            max_tokens=32,
        )
        return _cleanup_session_title(title or "")
    except Exception as exc:
        logger.warning("Session title generation failed: %s", _safe_ai_error_message(exc))
        return _cleanup_session_title(user_text)


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _extract_tool_plan(raw: str, allowed_names: set[str]) -> list[str]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    calls = payload.get("tool_calls") if isinstance(payload, dict) else payload
    planned: list[str] = []
    if not isinstance(calls, list):
        return planned
    for item in calls:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name in allowed_names and name not in planned:
            planned.append(name)
    return planned[:6]


async def _plan_context_tools(
    *,
    messages: list[dict],
    page_context: dict,
    selected_contexts: list[str],
    model: Optional[str],
    api_key: Optional[str],
    api_provider: Optional[str],
    base_url: Optional[str],
) -> tuple[list[str], bool]:
    """Ask the selected model to choose read-only context tools within user scope."""
    question = _last_user_text(messages)
    allowed = get_allowed_tool_specs(selected_contexts, page_context)
    allowed_names = {item["name"] for item in allowed}
    fallback = plan_tool_names_rule_based(question, page_context, selected_contexts)
    if not allowed_names:
        return fallback, False

    planner_messages = [
        {
            "role": "system",
            "content": (
                "你是PHM系统AI助手的上下文工具规划器。"
                "只能从给定工具列表中选择只读工具；不得编造工具名；"
                "输出必须是JSON，格式为 {\"tool_calls\":[{\"name\":\"工具名\"}]}。"
                "不要解释，不要输出Markdown。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "用户问题": question[:800],
                    "当前页面": page_context.get("page_type", "unknown"),
                    "用户已选择的数据范围": selected_contexts,
                    "可用工具": allowed,
                    "选择要求": "最多选择6个最必要工具。必须尊重用户已选择的数据范围。",
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = await asyncio.to_thread(
        chat,
        planner_messages,
        model,
        api_key,
        api_provider if not base_url else None,
        base_url,
        0,
        256,
    )
    planned = _extract_tool_plan(raw, allowed_names)
    return planned or fallback, True


def _supports_qwen_vision(session_provider: Optional[AIProviderConfig], api_provider: Optional[str], base_url: Optional[str]) -> bool:
    provider_key = (session_provider.provider if session_provider else api_provider or "").lower()
    url = (base_url or "").lower()
    return any(token in provider_key for token in ("dashscope", "qwen", "通义")) or "dashscope.aliyuncs.com" in url


def _json_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


@router.post("/summary", response_model=AISummaryResponse)
async def generate_summary(
    data: AISummaryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate AI summary for a page.

    Uses Qwen API with fallback to local summary.
    When turbine_id is set, fetches live turbine + SCADA data automatically.
    """
    # Build page_data from turbine when turbine_id is provided
    if data.turbine_id and not data.page_data:
        from datetime import datetime, timedelta, timezone as _tz
        turbine = await db.get(Turbine, data.turbine_id)
        if turbine:
            since = datetime.now(_tz.utc) - timedelta(hours=24)
            scada_result = await db.execute(
                select(SCADARecord)
                .where(SCADARecord.turbine_id == data.turbine_id, SCADARecord.timestamp >= since)
                .order_by(SCADARecord.timestamp.desc())
                .limit(144)
            )
            scada_rows = scada_result.scalars().all()
            winds = [r.wind_speed_ms for r in scada_rows if r.wind_speed_ms is not None]
            powers = [r.power_kw for r in scada_rows if r.power_kw is not None]
            gen_temps = [r.gen_temperature_c for r in scada_rows if r.gen_temperature_c is not None]
            avg_wind = sum(winds) / len(winds) if winds else 0
            avg_power = sum(powers) / len(powers) if powers else 0
            avg_gen_temp = sum(gen_temps) / len(gen_temps) if gen_temps else 0
            data.page_data = {
                "turbineName": turbine.name,
                "turbineModel": turbine.model or "",
                "turbineRegion": getattr(turbine, "region", "") or "",
                "powerMW": turbine.power_mw or 0,
                "hiValue": turbine.hi_value or 0,
                "status": turbine.status or "normal",
                "scadaRecords": len(scada_rows),
                "avgWindSpeed": round(avg_wind, 2),
                "avgPowerKW": round(avg_power, 1),
                "avgGenTempC": round(avg_gen_temp, 1),
                "faultType": "",
                "confidence": 0,
            }

    session_provider: Optional[AIProviderConfig] = None
    if data.provider_config_id:
        provider_result = await db.execute(
            select(AIProviderConfig).where(
                AIProviderConfig.id == data.provider_config_id,
                AIProviderConfig.user_id == current_user.id,
            )
        )
        session_provider = provider_result.scalar_one_or_none()
        if not session_provider:
            from app.services.qwen_client import fallback_summary
            fallback = fallback_summary(data.page_type, data.page_data)
            return AISummaryResponse(
                **fallback,
                status="error",
                error_code="ai_provider_not_found",
                error_message="当前选择的AI供应商配置不存在，请重新选择供应商。",
                model_status={},
            )
        if not session_provider.enabled:
            from app.services.qwen_client import fallback_summary
            fallback = fallback_summary(data.page_type, data.page_data)
            return AISummaryResponse(
                **fallback,
                status="error",
                error_code="ai_provider_disabled",
                error_message="当前选择的AI供应商已停用，请在系统设置中启用或选择其他供应商。",
                model_status={},
            )

    effective_model = (data.model or session_provider.default_model) if session_provider else (data.model or current_user.model_preference)
    effective_key = session_provider.api_key if session_provider else current_user.api_key
    effective_provider = (session_provider.display_name or session_provider.provider) if session_provider else current_user.api_provider
    effective_base_url = session_provider.base_url if session_provider else current_user.api_base_url
    model_status = describe_model(
        effective_model,
        effective_key,
        effective_provider,
        effective_base_url,
    )
    if session_provider:
        model_status.update({
            "provider": session_provider.display_name or session_provider.provider,
            "api_provider": session_provider.display_name or session_provider.provider,
            "model": effective_model,
            "has_api_key": bool(effective_key),
        })

    try:
        # Use qwen-turbo for page summaries — fast enough for inline UX
        summary_model = effective_model
        provider_str = (session_provider.provider if session_provider else effective_provider) or ""
        if "dashscope" in str(provider_str).lower():
            summary_model = "qwen-turbo"
        summary = await asyncio.wait_for(
            asyncio.to_thread(
                summarize_page,
                data.page_type,
                data.page_data,
                model=summary_model,
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
                raise_on_error=True,
            ),
            timeout=20.0,
        )
        return AISummaryResponse(
            **summary,
            status="success",
            model_status=model_status,
        )
    except (Exception, asyncio.TimeoutError) as exc:
        error_code, error_message = _classify_ai_error(exc)
        logger.warning(f"AI summary failed [{error_code}]: {_safe_ai_error_message(exc)}")
        from app.services.qwen_client import fallback_summary
        fallback = fallback_summary(data.page_type, data.page_data)
        fallback_mode = model_status["mode"] if model_status.get("mode") in {"key_unbound", "provider_mismatch"} else "local_fallback"
        return AISummaryResponse(
            **fallback,
            status="error",
            error_code=error_code,
            error_message=error_message,
            model_status={**model_status, "mode": fallback_mode},
            warnings=["summary_ai_failed_local_fallback"],
        )


@router.post("/analyze-fault", response_model=AIFaultAnalysisResponse)
async def analyze_fault(
    data: AIFaultAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze fault using AI and SCADA data.

    Combines turbine data, recent SCADA records, and fault history
    to generate comprehensive diagnosis.
    """
    # Get turbine info
    result = await db.execute(
        select(Turbine).where(Turbine.id == data.turbine_id)
    )
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    # Get recent SCADA data (last 24 hours)
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    scada_result = await db.execute(
        select(SCADARecord)
        .where(
            SCADARecord.turbine_id == data.turbine_id,
            SCADARecord.timestamp >= since
        )
        .order_by(SCADARecord.timestamp.desc())
        .limit(100)
    )
    scada_records = scada_result.scalars().all()

    # Get fault history
    fault_result = await db.execute(
        select(Fault)
        .where(Fault.turbine_id == data.turbine_id)
        .order_by(Fault.detected_at.desc())
        .limit(10)
    )
    faults = fault_result.scalars().all()

    # Prepare data for AI analysis
    turbine_data = {
        "name": turbine.name,
        "model": turbine.model,
        "power_mw": turbine.power_mw,
        "region": turbine.region,
        "hi_value": turbine.hi_value,
        "status": turbine.status,
    }

    # Analyze SCADA data for anomalies
    anomalies = _detect_anomalies(scada_records, turbine.power_mw)

    # Generate diagnosis
    fault_data = [
        {
            "type": f.fault_type,
            "confidence": f.confidence,
            "detected_at": f.detected_at.isoformat() if f.detected_at else None,
        }
        for f in faults
    ]

    try:
        diagnosis = await asyncio.wait_for(
            asyncio.to_thread(
                diagnose_fault,
                turbine_data,
                fault_data,
                model=current_user.model_preference,
                api_key=current_user.api_key,
                api_provider=current_user.api_provider,
                base_url=current_user.api_base_url,
            ),
            timeout=25.0,
        )
    except (Exception, asyncio.TimeoutError):
        logger.warning(f"AI diagnosis failed for turbine {turbine.id}, falling back to local")
        diagnosis = _generate_local_diagnosis(turbine_data, anomalies)

    return AIFaultAnalysisResponse(
        turbine_name=turbine.name,
        fault_type=data.fault_type,
        diagnosis=diagnosis,
        anomalies=anomalies,
    )


@router.post("/copilot", response_model=AICopilotResponse)
async def copilot_endpoint(
    data: AICopilotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copilot chat endpoint with page context and optional screenshot.

    If a screenshot is provided, it is first analyzed by a vision model
    (qwen-vl-plus) to extract a text description of the current page state.
    That description is then fed into the regular chat as additional context.
    """
    # Get current page context
    page_context = data.page_context or {}
    warnings: list[str] = []
    session_provider: Optional[AIProviderConfig] = None
    if data.provider_config_id:
        provider_result = await db.execute(
            select(AIProviderConfig).where(
                AIProviderConfig.id == data.provider_config_id,
                AIProviderConfig.user_id == current_user.id,
            )
        )
        session_provider = provider_result.scalar_one_or_none()
        if not session_provider:
            return AICopilotResponse(
                reply="当前会话选择的AI供应商配置不存在，请重新选择供应商和模型。",
                status="error",
                error_code="ai_provider_not_found",
                error_message="当前会话选择的AI供应商配置不存在，请重新选择供应商和模型。",
                warnings=warnings,
            )
        if not session_provider.enabled:
            return AICopilotResponse(
                reply="当前会话选择的AI供应商已停用，请在AI对话中选择其他供应商。",
                status="error",
                error_code="ai_provider_disabled",
                error_message="当前会话选择的AI供应商已停用，请在AI对话中选择其他供应商。",
                warnings=warnings,
            )

    effective_model = data.model or session_provider.default_model if session_provider else current_user.model_preference
    effective_key = session_provider.api_key if session_provider else current_user.api_key
    effective_provider = (session_provider.display_name or session_provider.provider) if session_provider else current_user.api_provider
    effective_base_url = session_provider.base_url if session_provider else current_user.api_base_url

    model_status = describe_model(
        effective_model,
        effective_key,
        effective_provider,
        effective_base_url,
    )
    if session_provider:
        model_status.update({
            "provider": session_provider.display_name or session_provider.provider,
            "api_provider": session_provider.display_name or session_provider.provider,
            "model": effective_model,
            "has_api_key": bool(effective_key),
        })
        if session_provider.provider == "ollama":
            model_status.update({
                "mode": "remote",
                "billing": "no_remote_charge",
                "requires_api_key": False,
                "has_api_key": bool(effective_key),
            })

    if model_status.get("mode") != "remote":
        code_map = {
            "local_fallback": ("api_key_missing", "当前账号未配置AI服务密钥，请在系统设置中保存 API KEY。"),
            "key_unbound": ("provider_unbound", "API KEY 未绑定供应商，请在系统设置中重新保存AI设置。"),
            "provider_mismatch": ("provider_mismatch", "当前 API KEY 供应商与所选模型供应商不匹配，请重新选择模型或保存对应密钥。"),
        }
        error_code, error_message = code_map.get(
            str(model_status.get("mode")),
            ("ai_config_not_ready", "当前AI模型配置尚未就绪，请检查系统设置。"),
        )
        return AICopilotResponse(
            reply=error_message,
            status="error",
            error_code=error_code,
            error_message=error_message,
            model_status=model_status,
            warnings=warnings,
        )

    # Build structured context with a read-only allowlist of backend data tools.
    context_bundle: dict = {}
    try:
        planned_tool_names: Optional[list[str]] = None
        try:
            planned_tool_names, used_llm_planner = await _plan_context_tools(
                messages=data.messages,
                page_context=page_context,
                selected_contexts=data.selected_contexts,
                model=effective_model,
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
            )
            if not used_llm_planner:
                warnings.append("context_tool_planner_rule_fallback")
        except Exception as e:
            logger.warning(f"Context tool planning failed, using rule fallback: {_safe_ai_error_message(e)}")
            warnings.append("context_tool_planning_failed")

        context_bundle = await build_copilot_context_bundle(
            db,
            session_id=data.session_id,
            messages=data.messages,
            page_context=page_context,
            selected_contexts=data.selected_contexts,
            requested_tools=planned_tool_names,
        )
        if context_bundle.get("selected_contexts_defaulted"):
            warnings.append("selected_contexts_defaulted")
        overview_tool = next(
            (tool for tool in context_bundle.get("tools", []) if tool.get("name") == "fleet_overview"),
            None,
        )
        overview = (overview_tool or {}).get("result") or {}
        page_context.update({
            "total_turbines": overview.get("total_turbines", 0),
            "warning_count": overview.get("warning_turbines", 0),
            "fault_count": overview.get("fault_turbines", 0),
            "context_bundle": context_bundle,
        })
    except Exception as e:
        logger.warning(f"Failed to build structured Copilot context: {e}")
        warnings.append("structured_context_failed")

    # Analyze screenshot if provided (best-effort, failure does not block chat)
    screenshot_description: Optional[str] = None
    if data.screenshot and _supports_qwen_vision(session_provider, effective_provider, effective_base_url):
        try:
            from app.services.qwen_client import describe_screenshot
            screenshot_description = await asyncio.to_thread(
                describe_screenshot,
                screenshot_base64=data.screenshot,
                page_type=page_context.get("page_type", "unknown"),
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
            )
            logger.info(f"Screenshot analyzed: {screenshot_description[:100]}...")
        except Exception as e:
            logger.warning(f"Screenshot analysis failed, proceeding text-only: {e}")
            warnings.append("screenshot_analysis_failed")
    elif data.screenshot:
        warnings.append("screenshot_analysis_skipped_unsupported_provider")

    try:
        reply = await asyncio.to_thread(
            copilot_chat,
            messages=data.messages,
            page_context=page_context,
            knowledge_results=data.knowledge_results,
            screenshot_description=screenshot_description,
            model=effective_model,
            api_key=effective_key,
            api_provider=effective_provider,
            base_url=effective_base_url,
            raise_on_error=True,
        )
        # Trigger knowledge extraction in background
        from app.services.knowledge_extractor import try_extract_knowledge
        all_messages = data.messages + [{"role": "assistant", "content": reply}]
        background_tasks.add_task(try_extract_knowledge, all_messages, effective_key, effective_provider, effective_base_url)

        return AICopilotResponse(
            reply=reply,
            status="success",
            model_status=model_status,
            warnings=warnings,
            context_sources=context_bundle.get("context_sources", []),
            session_title=_generate_session_title(
                data.messages,
                effective_model,
                effective_key,
                effective_provider,
                effective_base_url,
            ) if data.session_title_needed else None,
        )
    except Exception as e:
        error_code, error_message = _classify_ai_error(e)
        logger.error(f"Copilot chat failed [{error_code}]: {_safe_ai_error_message(e)}")
        return AICopilotResponse(
            reply=error_message,
            status="error",
            error_code=error_code,
            error_message=error_message,
            model_status=model_status,
            warnings=warnings,
        )


@router.post("/copilot/stream")
async def copilot_stream_endpoint(
    data: AICopilotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Streaming Copilot chat endpoint.

    Returns newline-delimited JSON events:
    - meta: model and context source metadata
    - delta: one answer fragment
    - title: optional generated session title
    - done: stream completed
    - error: structured error
    """
    page_context = data.page_context or {}
    warnings: list[str] = []
    session_provider: Optional[AIProviderConfig] = None

    def error_response(code: str, message: str, model_status: Optional[dict] = None) -> StreamingResponse:
        return StreamingResponse(
            iter([_json_line({
                "type": "error",
                "error_code": code,
                "error_message": message,
                "model_status": model_status or {},
                "warnings": warnings,
            })]),
            media_type="application/x-ndjson",
        )

    if data.provider_config_id:
        provider_result = await db.execute(
            select(AIProviderConfig).where(
                AIProviderConfig.id == data.provider_config_id,
                AIProviderConfig.user_id == current_user.id,
            )
        )
        session_provider = provider_result.scalar_one_or_none()
        if not session_provider:
            return error_response(
                "ai_provider_not_found",
                "当前会话选择的AI供应商配置不存在，请重新选择供应商和模型。",
            )
        if not session_provider.enabled:
            return error_response(
                "ai_provider_disabled",
                "当前会话选择的AI供应商已停用，请在AI对话中选择其他供应商。",
            )

    effective_model = data.model or session_provider.default_model if session_provider else current_user.model_preference
    effective_key = session_provider.api_key if session_provider else current_user.api_key
    effective_provider = (session_provider.display_name or session_provider.provider) if session_provider else current_user.api_provider
    effective_base_url = session_provider.base_url if session_provider else current_user.api_base_url

    model_status = describe_model(
        effective_model,
        effective_key,
        effective_provider,
        effective_base_url,
    )
    if session_provider:
        model_status.update({
            "provider": session_provider.display_name or session_provider.provider,
            "api_provider": session_provider.display_name or session_provider.provider,
            "model": effective_model,
            "has_api_key": bool(effective_key),
        })
        if session_provider.provider == "ollama":
            model_status.update({
                "mode": "remote",
                "billing": "no_remote_charge",
                "requires_api_key": False,
                "has_api_key": bool(effective_key),
            })

    if model_status.get("mode") != "remote":
        code_map = {
            "local_fallback": ("api_key_missing", "当前账号未配置AI服务密钥，请在系统设置中保存 API KEY。"),
            "key_unbound": ("provider_unbound", "API KEY 未绑定供应商，请在系统设置中重新保存AI设置。"),
            "provider_mismatch": ("provider_mismatch", "当前 API KEY 供应商与所选模型供应商不匹配，请重新选择模型或保存对应密钥。"),
        }
        error_code, error_message = code_map.get(
            str(model_status.get("mode")),
            ("ai_config_not_ready", "当前AI模型配置尚未就绪，请检查系统设置。"),
        )
        return error_response(error_code, error_message, model_status)

    context_bundle: dict = {}
    try:
        planned_tool_names: Optional[list[str]] = None
        try:
            planned_tool_names, used_llm_planner = await _plan_context_tools(
                messages=data.messages,
                page_context=page_context,
                selected_contexts=data.selected_contexts,
                model=effective_model,
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
            )
            if not used_llm_planner:
                warnings.append("context_tool_planner_rule_fallback")
        except Exception as e:
            logger.warning(f"Context tool planning failed, using rule fallback: {_safe_ai_error_message(e)}")
            warnings.append("context_tool_planning_failed")

        context_bundle = await build_copilot_context_bundle(
            db,
            session_id=data.session_id,
            messages=data.messages,
            page_context=page_context,
            selected_contexts=data.selected_contexts,
            requested_tools=planned_tool_names,
        )
        if context_bundle.get("selected_contexts_defaulted"):
            warnings.append("selected_contexts_defaulted")
        overview_tool = next(
            (tool for tool in context_bundle.get("tools", []) if tool.get("name") == "fleet_overview"),
            None,
        )
        overview = (overview_tool or {}).get("result") or {}
        page_context.update({
            "total_turbines": overview.get("total_turbines", 0),
            "warning_count": overview.get("warning_turbines", 0),
            "fault_count": overview.get("fault_turbines", 0),
            "context_bundle": context_bundle,
        })
    except Exception as e:
        logger.warning(f"Failed to build structured Copilot context: {e}")
        warnings.append("structured_context_failed")

    screenshot_description: Optional[str] = None
    if data.screenshot and _supports_qwen_vision(session_provider, effective_provider, effective_base_url):
        try:
            from app.services.qwen_client import describe_screenshot
            screenshot_description = await asyncio.to_thread(
                describe_screenshot,
                screenshot_base64=data.screenshot,
                page_type=page_context.get("page_type", "unknown"),
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
            )
        except Exception as e:
            logger.warning(f"Screenshot analysis failed, proceeding text-only: {e}")
            warnings.append("screenshot_analysis_failed")
    elif data.screenshot:
        warnings.append("screenshot_analysis_skipped_unsupported_provider")

    def event_stream():
        reply_parts: list[str] = []
        try:
            yield _json_line({
                "type": "meta",
                "model_status": model_status,
                "warnings": warnings,
                "context_sources": context_bundle.get("context_sources", []),
            })
            for delta in copilot_chat_stream(
                messages=data.messages,
                page_context=page_context,
                knowledge_results=data.knowledge_results,
                screenshot_description=screenshot_description,
                model=effective_model,
                api_key=effective_key,
                api_provider=effective_provider,
                base_url=effective_base_url,
            ):
                reply_parts.append(delta)
                yield _json_line({"type": "delta", "delta": delta})

            reply = "".join(reply_parts)
            if reply:
                from app.services.knowledge_extractor import try_extract_knowledge
                all_messages = data.messages + [{"role": "assistant", "content": reply}]
                background_tasks.add_task(try_extract_knowledge, all_messages, effective_key, effective_provider, effective_base_url)

            if data.session_title_needed:
                title = _generate_session_title(
                    data.messages,
                    effective_model,
                    effective_key,
                    effective_provider,
                    effective_base_url,
                )
                if title:
                    yield _json_line({"type": "title", "session_title": title})

            yield _json_line({"type": "done"})
        except Exception as e:
            error_code, error_message = _classify_ai_error(e)
            logger.error(f"Copilot stream failed [{error_code}]: {_safe_ai_error_message(e)}")
            yield _json_line({
                "type": "error",
                "error_code": error_code,
                "error_message": error_message,
                "model_status": model_status,
                "warnings": warnings,
            })

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/test-connection")
async def test_ai_connection(data: AITestConnectionRequest):
    """Test AI connection with ad-hoc credentials (no save required)."""
    try:
        from app.services.qwen_client import get_client
        base_url = data.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        client = get_client(data.api_key, base_url)
        response = client.chat.completions.create(
            model=data.model,
            messages=[{"role": "user", "content": "Respond with exactly one word: ok"}],
            max_tokens=10,
            temperature=0,
        )
        reply = response.choices[0].message.content.strip().lower()
        if "ok" in reply:
            return {"status": "success", "message": f"连接成功，模型 {data.model} 响应正常", "model": data.model}
        return {"status": "unexpected", "message": f"模型响应异常: {reply[:100]}", "model": data.model}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {str(e)[:200]}", "model": data.model}


def _detect_anomalies(scada_records: list, rated_power_mw: float) -> list[dict]:
    """Detect anomalies in SCADA data.

    Returns list of anomalies with indicator, value, normal range, and deviation.
    """
    if not scada_records:
        return []

    anomalies = []
    rated_power_kw = rated_power_mw * 1000

    def avg(attr: str) -> float | None:
        values = [getattr(r, attr) for r in scada_records if getattr(r, attr) is not None]
        if not values:
            return None
        return sum(values) / len(values)

    avg_power = avg("power_kw")
    avg_gen_temp = avg("gen_temperature_c")
    avg_gearbox_temp = avg("gearbox_temperature_c")
    avg_bearing_temp = avg("bearing_temperature_c")

    # Check generator temperature
    if avg_gen_temp is not None and avg_gen_temp > 95:
        deviation = f"+{avg_gen_temp - 85:.1f}°C"
        anomalies.append({
            "indicator": "发电机温度",
            "value": f"{avg_gen_temp:.1f}°C",
            "normal": "75-85°C",
            "deviation": deviation,
            "level": "high" if avg_gen_temp > 105 else "medium",
        })

    # Check gearbox temperature
    if avg_gearbox_temp is not None and avg_gearbox_temp > 80:
        deviation = f"+{avg_gearbox_temp - 70:.1f}°C"
        anomalies.append({
            "indicator": "齿轮箱温度",
            "value": f"{avg_gearbox_temp:.1f}°C",
            "normal": "60-70°C",
            "deviation": deviation,
            "level": "high" if avg_gearbox_temp > 90 else "medium",
        })

    # Check bearing temperature
    if avg_bearing_temp is not None and avg_bearing_temp > 75:
        deviation = f"+{avg_bearing_temp - 65:.1f}°C"
        anomalies.append({
            "indicator": "轴承温度",
            "value": f"{avg_bearing_temp:.1f}°C",
            "normal": "55-65°C",
            "deviation": deviation,
            "level": "high" if avg_bearing_temp > 85 else "medium",
        })

    # Check power output (low power at high wind)
    avg_wind = avg("wind_speed_ms")
    if (
        avg_wind is not None
        and avg_power is not None
        and avg_wind > 8
        and avg_power < rated_power_kw * 0.5
    ):
        anomalies.append({
            "indicator": "功率输出",
            "value": f"{avg_power:.0f}kW",
            "normal": f">{rated_power_kw * 0.6:.0f}kW",
            "deviation": f"-{(rated_power_kw * 0.6 - avg_power):.0f}kW",
            "level": "medium",
        })

    return anomalies


def _generate_local_diagnosis(turbine_data: dict, anomalies: list[dict]) -> str:
    """Generate local diagnosis when AI is unavailable."""
    name = turbine_data.get("name", "未知")
    hi = turbine_data.get("hi_value", 0)
    status = turbine_data.get("status", "unknown")

    parts = [f"风机{name}诊断报告:"]

    if hi < 60:
        parts.append("健康指数严重偏低, 建议立即停机检查。")
    elif hi < 80:
        parts.append("健康指数处于预警区间, 建议加强监控。")

    if anomalies:
        parts.append(f"检测到{len(anomalies)}项异常指标:")
        for a in anomalies:
            parts.append(f"- {a['indicator']}: {a['value']} (正常范围: {a['normal']})")

    if not anomalies:
        parts.append("当前运行参数正常, 无明显异常。")

    parts.append("建议: 安排例行巡检, 持续监测关键参数变化趋势。")

    return "\n".join(parts)
