"""AI API endpoints for fault analysis and copilot chat.

Provides AI-powered analysis using Qwen API with fallback to local analysis.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Turbine, SCADARecord, Fault, User
from app.schemas import (
    AISummaryRequest, AISummaryResponse,
    AIFaultAnalysisRequest, AIFaultAnalysisResponse,
    AICopilotRequest, AICopilotResponse,
    AITestConnectionRequest,
)
from app.api.auth import get_current_user
from app.services.qwen_client import summarize_page, diagnose_fault, copilot_chat

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/summary", response_model=AISummaryResponse)
async def generate_summary(
    data: AISummaryRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate AI summary for a page.

    Uses Qwen API with fallback to local summary.
    """
    try:
        summary = summarize_page(
            data.page_type,
            data.page_data,
            model=current_user.model_preference,
            api_key=current_user.api_key,
            api_provider=current_user.api_provider,
            base_url=current_user.api_base_url,
        )
        return AISummaryResponse(**summary)
    except Exception as e:
        logger.warning(f"AI summary failed, using fallback: {e}")
        # Fallback to local summary
        from app.services.qwen_client import fallback_summary
        return AISummaryResponse(**fallback_summary(data.page_type, data.page_data))


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
        diagnosis = diagnose_fault(
            turbine_data,
            fault_data,
            model=current_user.model_preference,
            api_key=current_user.api_key,
            api_provider=current_user.api_provider,
            base_url=current_user.api_base_url,
        )
    except Exception as e:
        logger.warning(f"AI diagnosis failed: {e}")
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

    # Enhance context with real data
    try:
        # Get turbine stats
        turbines_result = await db.execute(select(Turbine))
        turbines = turbines_result.scalars().all()

        page_context.update({
            "total_turbines": len(turbines),
            "warning_count": sum(1 for t in turbines if t.status == "warning"),
            "fault_count": sum(1 for t in turbines if t.status == "fault"),
        })
    except Exception as e:
        logger.warning(f"Failed to enhance context: {e}")

    # Analyze screenshot if provided (best-effort, failure does not block chat)
    screenshot_description: Optional[str] = None
    if data.screenshot:
        try:
            from app.services.qwen_client import describe_screenshot
            screenshot_description = describe_screenshot(
                screenshot_base64=data.screenshot,
                page_type=page_context.get("page_type", "unknown"),
                api_key=current_user.api_key,
                api_provider=current_user.api_provider,
                base_url=current_user.api_base_url,
            )
            logger.info(f"Screenshot analyzed: {screenshot_description[:100]}...")
        except Exception as e:
            logger.warning(f"Screenshot analysis failed, proceeding text-only: {e}")

    try:
        reply = copilot_chat(
            messages=data.messages,
            page_context=page_context,
            knowledge_results=data.knowledge_results,
            screenshot_description=screenshot_description,
            model=current_user.model_preference,
            api_key=current_user.api_key,
            api_provider=current_user.api_provider,
            base_url=current_user.api_base_url,
        )
        # Trigger knowledge extraction in background
        from app.services.knowledge_extractor import try_extract_knowledge
        all_messages = data.messages + [{"role": "assistant", "content": reply}]
        background_tasks.add_task(try_extract_knowledge, all_messages, current_user.api_key, current_user.api_provider, current_user.api_base_url)

        return AICopilotResponse(reply=reply)
    except Exception as e:
        logger.error(f"Copilot chat failed: {e}")
        return AICopilotResponse(
            reply="抱歉, AI服务暂时不可用。请稍后重试。"
        )


@router.post("/test-connection")
async def test_ai_connection(data: AITestConnectionRequest):
    """Test AI connection with ad-hoc credentials (no save required)."""
    try:
        from app.services.qwen_client import get_client
        client = get_client(data.api_key, data.base_url)
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
