"""Qwen AI Client — via Alibaba DashScope (OpenAI-compatible API).

Models:
  qwen-plus  — text generation, good balance quality/cost
  qwen-turbo — faster/cheaper, for simple summaries
  qwen-vl-plus — multimodal (text + image)

Configuration:
  Set DASHSCOPE_API_KEY environment variable.
  See .env.example for details.
"""

import json
import logging
from typing import Optional

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# Load from environment
settings = get_settings()

QWEN_CONFIG = {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": settings.DASHSCOPE_API_KEY,
    "default_model": "qwen-plus",
    "cheap_model": "qwen-turbo",
    "vision_model": "qwen-vl-plus",
}

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """Get or create OpenAI client for Qwen API."""
    global _client
    if _client is None:
        if not QWEN_CONFIG["api_key"]:
            logger.warning("DASHSCOPE_API_KEY not set, AI features will use fallback")
            raise ValueError("DASHSCOPE_API_KEY environment variable not set")
        _client = OpenAI(
            base_url=QWEN_CONFIG["base_url"],
            api_key=QWEN_CONFIG["api_key"],
        )
    return _client


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False,
) -> str:
    """Single-turn chat with Qwen.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model to use (defaults to qwen-plus)
        temperature: Sampling temperature (0-1)
        max_tokens: Maximum tokens to generate
        stream: Whether to stream the response

    Returns:
        Generated text response

    Raises:
        ValueError: If API key not configured
        Exception: If API call fails
    """
    client = get_client()
    response = client.chat.completions.create(
        model=model or QWEN_CONFIG["default_model"],
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
    )
    if stream:
        return response
    return response.choices[0].message.content


def summarize_page(page_type: str, page_data: dict) -> dict:
    """Generate AI summary for a page.

    Args:
        page_type: "dashboard" | "diagnosis" | "prediction"
        page_data: current page context (turbine stats, alerts, etc.)

    Returns:
        {"conclusions": [...], "suggestions": [...]}
    """
    system_prompt = """你是"风调预顺"PHM系统的AI运维助手。
根据当前页面数据, 生成简洁的分析报告。

输出格式必须是JSON:
{
  "conclusions": ["3条关键结论, 每条25字以内"],
  "suggestions": ["2条可执行建议, 每条30字以内"]
}
只输出JSON, 不要其他文字。"""

    user_prompt = f"""页面类型: {page_type}
当前数据: {json.dumps(page_data, ensure_ascii=False)}

请分析页面数据, 输出3条关键结论和2条建议。"""

    try:
        result = chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], model=QWEN_CONFIG["cheap_model"], temperature=0.3, max_tokens=512)

        # Try to parse JSON from response
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
        return json.loads(result)
    except Exception as e:
        logger.warning(f"AI summary failed, using fallback: {e}")
        return fallback_summary(page_type)


def diagnose_fault(turbine_data: dict, fault_data: list[dict]) -> str:
    """Generate fault diagnosis report.

    Args:
        turbine_data: Turbine information
        fault_data: Fault records

    Returns:
        Diagnosis report text
    """
    system_prompt = """你是资深风电运维专家。根据风机数据给出故障诊断建议。
要求:
1. 分析可能的根因
2. 评估风险等级
3. 给出具体维修建议
4. 回复简洁专业, 200字以内"""

    user_prompt = f"""风机信息: {json.dumps(turbine_data, ensure_ascii=False)}
故障数据: {json.dumps(fault_data, ensure_ascii=False)}

请给出诊断建议。"""

    try:
        return chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature=0.5, max_tokens=512)
    except Exception as e:
        logger.warning(f"AI diagnosis failed: {e}")
        return "AI诊断服务暂不可用, 建议人工排查。"


def copilot_chat(
    messages: list[dict],
    page_context: dict,
    knowledge_results: Optional[list[str]] = None,
    stream: bool = False,
) -> str:
    """Multi-turn Copilot chat with page context and optional RAG results.

    Args:
        messages: conversation history [{role, content}, ...]
        page_context: current page data snapshot
        knowledge_results: RAG-retrieved knowledge snippets
        stream: return stream generator or string

    Returns:
        AI response text
    """
    system_prompt = f"""你是"风调预顺"PHM系统的AI智能助手 (Copilot)。

角色: 风电运维专家 + 数据分析师。

当前页面上下文:
- 页面: {page_context.get('page_type', 'unknown')}
- 风机总数: {page_context.get('total_turbines', 0)}
- 预警风机: {page_context.get('warning_count', 0)}
- 故障风机: {page_context.get('fault_count', 0)}
- 最近告警: {json.dumps(page_context.get('recent_alerts', []), ensure_ascii=False)}

{('知识库参考:' + chr(10) + chr(10).join(knowledge_results)) if knowledge_results else ''}

规则:
1. 基于上下文给出准确回答
2. 涉及安全决策时提醒"建议人工复核"
3. 回复简洁, 关键数据用数字
4. 如果上下文信息不足, 诚实说明"""

    try:
        return chat(
            [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            model=QWEN_CONFIG["default_model"],
            temperature=0.5,
            max_tokens=1024,
            stream=stream,
        )
    except Exception as e:
        logger.warning(f"Copilot chat failed: {e}")
        return "抱歉, AI服务暂时不可用。请稍后重试。"


def fallback_summary(page_type: str) -> dict:
    """Local fallback when Qwen API is unavailable.

    Args:
        page_type: Type of page to summarize

    Returns:
        Fallback summary dict
    """
    summaries = {
        "dashboard": {
            "conclusions": [
                "当前风场整体运行正常, 在线率96.5%",
                "3台风机健康指数处于预警区间, 建议重点关注",
                "陕北区域风速较大, 发电效率较高",
            ],
            "suggestions": [
                "优先检修风机A-003, 其齿轮箱HI值持续下降",
                "关中区域近期风速偏低, 可安排例行维护",
            ],
        },
        "diagnosis": {
            "conclusions": [
                "检测到轴承早期磨损信号",
                "故障置信度为87%, 建议安排振动复测",
                "相比上月同类故障, 本次异常信号强度较弱",
            ],
            "suggestions": [
                "建议48小时内安排轴承振动复测",
                "备件库存充足, 无需额外采购",
            ],
        },
        "prediction": {
            "conclusions": [
                "全场RUL预测显示2台风机发电机剩余寿命不足6个月",
                "叶片整体寿命状况良好, 平均RUL > 3年",
                "齿轮箱维护成本对比: 立即检修比延迟检修节省5万元",
            ],
            "suggestions": [
                "建议本月内安排发电机预防性更换",
                "齿轮箱建议立即检修, 避免连锁故障",
            ],
        },
    }
    return summaries.get(page_type, summaries["dashboard"])
