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
from dataclasses import dataclass
from typing import Optional

import httpx
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

# -- 共享专业身份预设（token高效，作为最早的系统指令嵌入） --
WIND_ENGINEER_PRESET = (
    "你是「风调预顺」PHM系统的AI智能运维助手。"
    "你是一名资深风电工程师，精通以下领域："
    "风电机组结构与运行原理（双馈/直驱/半直驱）、SCADA数据分析与异常检测、"
    "振动监测与CMS信号分析、故障诊断与根因分析（RCA）、"
    "预测性维护（PdM）与剩余寿命预测（RUL）、备件管理与维修策略优化。"
    "回答要求：基于数据给出精准结论，涉及安全决策时提醒人工复核，不确定时诚实说明。"
)

@dataclass(frozen=True)
class AIModelConfig:
    provider: str
    label: str
    model_id: str
    base_url: str = ""
    api_style: str = "openai"
    requires_api_key: bool = True


MODEL_CATALOG: dict[str, AIModelConfig] = {
    "qwen-plus": AIModelConfig("通义千问 DashScope", "通义千问 qwen-plus", "qwen-plus", QWEN_CONFIG["base_url"]),
    "qwen-turbo": AIModelConfig("通义千问 DashScope", "通义千问 qwen-turbo", "qwen-turbo", QWEN_CONFIG["base_url"]),
    "qwen3.6-flash": AIModelConfig("通义千问 DashScope", "通义千问 qwen3.6-flash", "qwen3.6-flash", QWEN_CONFIG["base_url"]),
    "qwen-vl-plus": AIModelConfig("通义千问 DashScope", "通义千问 qwen-vl-plus", "qwen-vl-plus", QWEN_CONFIG["base_url"]),
    "deepseek-v4-flash": AIModelConfig("DeepSeek", "DeepSeek deepseek-v4-flash", "deepseek-v4-flash", "https://api.deepseek.com"),
    "deepseek-chat": AIModelConfig("DeepSeek", "DeepSeek deepseek-chat", "deepseek-chat", "https://api.deepseek.com"),
    "deepseek-reasoner": AIModelConfig("DeepSeek", "DeepSeek deepseek-reasoner", "deepseek-reasoner", "https://api.deepseek.com"),
    "deepseek-v3": AIModelConfig("DeepSeek", "DeepSeek deepseek-v3", "deepseek-chat", "https://api.deepseek.com"),
    "glm-5-flash": AIModelConfig("智谱GLM", "智谱 GLM-5-Flash", "glm-5-flash", "https://open.bigmodel.cn/api/paas/v4/"),
    "kimi-k2.6": AIModelConfig("Kimi Moonshot", "Kimi kimi-k2.6", "kimi-k2.6", "https://api.moonshot.cn/v1"),
    "gpt-4o-mini": AIModelConfig("OpenAI", "OpenAI gpt-4o-mini", "gpt-4o-mini", settings.OPENAI_BASE_URL),
    "gpt-4.1": AIModelConfig("OpenAI", "OpenAI gpt-4.1", "gpt-4.1", settings.OPENAI_BASE_URL),
    "gpt-4": AIModelConfig("OpenAI", "OpenAI gpt-4", "gpt-4", settings.OPENAI_BASE_URL),
    "gpt-3.5-turbo": AIModelConfig("OpenAI", "OpenAI gpt-3.5-turbo", "gpt-3.5-turbo", settings.OPENAI_BASE_URL),
    "claude-sonnet-4-6": AIModelConfig("Claude", "Claude claude-sonnet-4-6", "claude-sonnet-4-6", api_style="anthropic"),
    "claude-haiku-4-5": AIModelConfig("Claude", "Claude claude-haiku-4-5", "claude-haiku-4-5-20251001", api_style="anthropic"),
    "gemini-2.5-flash": AIModelConfig("Google Gemini", "Gemini gemini-2.5-flash", "gemini-2.5-flash", api_style="gemini"),
    "gemini-3.5-flash": AIModelConfig("Google Gemini", "Gemini gemini-3.5-flash", "gemini-3.5-flash", api_style="gemini"),
    "ollama-local": AIModelConfig("Ollama本地模型", "Ollama qwen2.5", "qwen2.5", "http://localhost:11434/v1", requires_api_key=False),
}

MODEL_ALIASES = {
    "qwen3.5-flash": "qwen3.6-flash",
    "deepseek-v3": "deepseek-chat",
    "claude-sonnet-4": "claude-sonnet-4-6",
    "claude-4": "claude-sonnet-4-6",
}


def normalize_model_preference(model: Optional[str]) -> str:
    """Normalize legacy UI values to a current model preference key."""
    return MODEL_ALIASES.get(model or "", model or QWEN_CONFIG["default_model"])


def resolve_model_config(model: Optional[str]) -> AIModelConfig:
    """Resolve a stored model preference to the exact model called upstream."""
    key = normalize_model_preference(model)
    return MODEL_CATALOG.get(key, MODEL_CATALOG[QWEN_CONFIG["default_model"]])


def describe_model(model: Optional[str], api_key: Optional[str], api_provider: Optional[str] = None) -> dict:
    """Return non-secret status metadata for the configured model."""
    config = resolve_model_config(model)
    has_key = bool(api_key)
    provider_matches = api_provider == config.provider
    key_bound = bool(api_provider)
    if not config.requires_api_key:
        mode = "remote"
        billing = "no_remote_charge"
    elif not has_key:
        mode = "local_fallback"
        billing = "no_remote_charge"
    elif not key_bound:
        # User has key but no provider set — trust the model's default provider
        mode = "remote"
        billing = "provider_billed"
    elif not provider_matches:
        mode = "provider_mismatch"
        billing = "no_remote_charge"
    else:
        mode = "remote"
        billing = "provider_billed"
    return {
        "provider": config.provider,
        "api_provider": api_provider,
        "model": config.model_id,
        "label": config.label,
        "mode": mode,
        "billing": billing,
        "requires_api_key": config.requires_api_key,
        "has_api_key": has_key,
    }


def _ensure_remote_available(config: AIModelConfig, api_key: Optional[str], api_provider: Optional[str]) -> None:
    if not config.requires_api_key:
        return
    if config.requires_api_key and not api_key:
        raise ValueError(f"{config.provider} API key not configured")
    if not api_provider:
        raise ValueError("API key is not bound to a provider; please save it again")
    if api_provider != config.provider:
        raise ValueError(f"API key belongs to {api_provider}, but selected model requires {config.provider}")


def get_client(api_key: Optional[str], base_url: str) -> OpenAI:
    """Create an OpenAI-compatible client for the selected provider."""
    return OpenAI(base_url=base_url, api_key=api_key or "ollama")


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False,
) -> str:
    """Single-turn chat with the selected AI provider.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model preference stored for the current user
        api_key: API key saved for the current user
        api_provider: Provider that the saved API key belongs to
        temperature: Sampling temperature (0-1)
        max_tokens: Maximum tokens to generate
        stream: Whether to stream the response

    Returns:
        Generated text response

    Raises:
        ValueError: If API key not configured
        Exception: If API call fails
    """
    config = resolve_model_config(model)
    _ensure_remote_available(config, api_key, api_provider)

    if config.api_style == "gemini":
        return _gemini_chat(config, api_key or "", messages, temperature, max_tokens)

    if config.api_style == "anthropic":
        return _anthropic_chat(config, api_key or "", messages, temperature, max_tokens)

    client = get_client(api_key, config.base_url)
    response = client.chat.completions.create(
        model=config.model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
    )
    if stream:
        return response
    return response.choices[0].message.content


def _split_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    conversation = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(system_parts).strip(), conversation


def _build_system_prompt(task_instructions: str) -> str:
    """将共享工程师身份预设与任务特定指令合并为单个系统提示词。

    预设始终放在最前面，后面紧跟任务指令。
    """
    return WIND_ENGINEER_PRESET + "\n\n" + task_instructions


def _gemini_chat(
    config: AIModelConfig,
    api_key: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    system_prompt, conversation = _split_system_messages(messages)
    contents = []
    for message in conversation:
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": str(message.get("content", ""))}]})

    payload: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.model_id}:generateContent"
    with httpx.Client(timeout=30) as client:
        response = client.post(url, params={"key": api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise ValueError("Gemini response did not include text")
    return text


def _anthropic_chat(
    config: AIModelConfig,
    api_key: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    system_prompt, conversation = _split_system_messages(messages)
    payload: dict = {
        "model": config.model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {
                "role": "assistant" if message.get("role") == "assistant" else "user",
                "content": str(message.get("content", "")),
            }
            for message in conversation
        ],
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    with httpx.Client(timeout=30) as client:
        response = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text").strip()
    if not text:
        raise ValueError("Claude response did not include text")
    return text


def summarize_page(
    page_type: str,
    page_data: dict,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
) -> dict:
    """Generate AI summary for a page.

    Args:
        page_type: "dashboard" | "diagnosis" | "prediction"
        page_data: current page context (turbine stats, alerts, etc.)
        model: Current user's stored model preference
        api_key: Current user's stored AI service key
        api_provider: Provider that the stored key belongs to

    Returns:
        {"conclusions": [...], "suggestions": [...]}
    """
    model_status = describe_model(model, api_key, api_provider)

    system_prompt = _build_system_prompt(
        "根据当前页面数据, 生成简洁的分析报告。\n\n"
        "输出格式必须是JSON:\n"
        "{\n"
        '  "conclusions": ["3条关键结论, 每条25字以内"],\n'
        '  "suggestions": ["2条可执行建议, 每条30字以内"]\n'
        "}\n"
        "只输出JSON, 不要其他文字。"
    )

    user_prompt = f"""页面类型: {page_type}
当前数据: {json.dumps(page_data, ensure_ascii=False)}

请分析页面数据, 输出3条关键结论和2条建议。"""

    try:
        result = chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], model=model or QWEN_CONFIG["cheap_model"], api_key=api_key, api_provider=api_provider, temperature=0.3, max_tokens=512)

        # Try to parse JSON from response
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
        parsed = json.loads(result)
        parsed.update(model_status)
        return parsed
    except Exception as e:
        logger.warning(f"AI summary failed, using fallback: {e}")
        fallback = fallback_summary(page_type)
        fallback_mode = model_status["mode"] if model_status["mode"] in {"key_unbound", "provider_mismatch"} else "local_fallback"
        fallback.update({**model_status, "mode": fallback_mode, "billing": "no_remote_charge"})
        return fallback


def diagnose_fault(
    turbine_data: dict,
    fault_data: list[dict],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
) -> str:
    """Generate fault diagnosis report.

    Args:
        turbine_data: Turbine information
        fault_data: Fault records

    Returns:
        Diagnosis report text
    """
    config = describe_model(model, api_key, api_provider)
    if config["mode"] != "remote":
        raise ValueError(f"{config['provider']} API key is not ready for selected model")

    system_prompt = _build_system_prompt(
        "根据风机数据给出故障诊断建议。\n"
        "要求:\n"
        "1. 分析可能的根因\n"
        "2. 评估风险等级\n"
        "3. 给出具体维修建议\n"
        "4. 回复简洁专业, 200字以内"
    )

    user_prompt = f"""风机信息: {json.dumps(turbine_data, ensure_ascii=False)}
故障数据: {json.dumps(fault_data, ensure_ascii=False)}

请给出诊断建议。"""

    try:
        return chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], model=model, api_key=api_key, api_provider=api_provider, temperature=0.5, max_tokens=512)
    except Exception as e:
        logger.warning(f"AI diagnosis failed: {e}")
        raise


def copilot_chat(
    messages: list[dict],
    page_context: dict,
    knowledge_results: Optional[list[str]] = None,
    screenshot_description: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    stream: bool = False,
) -> str:
    """Multi-turn Copilot chat with page context, optional RAG results,
    and optional screenshot description.

    Args:
        messages: conversation history [{role, content}, ...]
        page_context: current page data snapshot
        knowledge_results: RAG-retrieved knowledge snippets
        screenshot_description: text description of current page screenshot
        stream: return stream generator or string

    Returns:
        AI response text
    """
    screenshot_section = ""
    if screenshot_description:
        screenshot_section = (
            f"\n当前页面截图内容（由视觉模型分析）:\n"
            f"{screenshot_description}\n"
        )

    task_prompt = (
        f"当前页面上下文:\n"
        f"- 页面: {page_context.get('page_type', 'unknown')}\n"
        f"- 风机总数: {page_context.get('total_turbines', 0)}\n"
        f"- 预警风机: {page_context.get('warning_count', 0)}\n"
        f"- 故障风机: {page_context.get('fault_count', 0)}\n"
        f"- 最近告警: {json.dumps(page_context.get('recent_alerts', []), ensure_ascii=False)}\n"
        f"{screenshot_section}"
        f"\n"
        f"{('知识库参考:' + chr(10) + chr(10).join(knowledge_results)) if knowledge_results else ''}"
        f"\n"
        f"规则:\n"
        f"1. 基于上下文给出准确回答\n"
        f'2. 涉及安全决策时提醒"建议人工复核"\n'
        f"3. 回复简洁, 关键数据用数字\n"
        f"4. 如果上下文信息不足, 诚实说明\n"
        f"5. 如果有页面截图描述, 优先参考截图中的实时数据"
    )
    system_prompt = _build_system_prompt(task_prompt)

    try:
        return chat(
            [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            model=model or QWEN_CONFIG["default_model"],
            api_key=api_key,
            api_provider=api_provider,
            temperature=0.5,
            max_tokens=1024,
            stream=stream,
        )
    except Exception as e:
        logger.warning(f"Copilot chat failed: {e}")
        return "抱歉, AI服务暂时不可用。请稍后重试。"


def describe_screenshot(
    screenshot_base64: str,
    page_type: str,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
) -> str:
    """Use qwen-vl-plus to describe what's visible on the page screenshot.

    Args:
        screenshot_base64: Raw base64-encoded JPEG (without data:image prefix)
        page_type: The page type (dashboard, diagnosis, etc.)
        api_key: User's DashScope API key
        api_provider: Provider that the key belongs to

    Returns:
        Text description of what's visible on screen.

    Raises:
        ValueError: If API key is not configured for DashScope
    """
    config = MODEL_CATALOG["qwen-vl-plus"]
    # Fallback to env var when user hasn't set their own key in Settings
    if not api_key:
        api_key = settings.DASHSCOPE_API_KEY
    if not api_provider and api_key:
        api_provider = config.provider
    _ensure_remote_available(config, api_key, api_provider)

    vision_prompt = (
        f"你正在查看「风调预顺」PHM系统的{page_type}页面截图。\n"
        "请用中文简洁描述截图中可以看到的内容：\n"
        "1. 页面显示了哪些关键数据（数字、图表、状态指标等）\n"
        "2. 有哪些异常或值得注意的信息\n"
        "3. 当前页面的风机状态概况\n\n"
        "要求：\n"
        "- 描述控制在300字以内\n"
        "- 只描述你看到的客观信息，不要推测或建议\n"
        "- 用项目符号列出关键数据点\n"
        "- 如果截图不清晰或无法识别，诚实说明"
    )

    client = get_client(api_key, config.base_url)
    response = client.chat.completions.create(
        model=config.model_id,
        messages=[
            {"role": "system", "content": WIND_ENGINEER_PRESET},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": vision_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_base64}"
                        },
                    },
                ],
            },
        ],
        temperature=0.3,
        max_tokens=512,
    )
    return response.choices[0].message.content


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
