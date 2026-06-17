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
from openai import OpenAI, DefaultHttpxClient

from app.config import get_settings

logger = logging.getLogger(__name__)

# Load from environment
settings = get_settings()

# Patterns that indicate a placeholder / unconfigured API key
_PLACEHOLDER_PATTERNS = (
    "your-", "change-me", "changeme", "change_me", "replace-me",
    "sk-your-", "your_", "placeholder", "xxxxxx", "test-key",
    "your-dashscope", "your-openai", "your-deepseek",
)

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
    "qwen3.7-max-2026-05-17": AIModelConfig("通义千问 DashScope", "通义千问 qwen3.7-max", "qwen3.7-max-2026-05-17", QWEN_CONFIG["base_url"]),
    "qwen3.7-plus-2026-05-26": AIModelConfig("通义千问 DashScope", "通义千问 qwen3.7-plus", "qwen3.7-plus-2026-05-26", QWEN_CONFIG["base_url"]),
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
    "gemini-2.5-flash": AIModelConfig("Google Gemini", "Gemini gemini-2.5-flash", "gemini-2.5-flash", api_style="gemini"),
    "gemini-3.5-flash": AIModelConfig("Google Gemini", "Gemini gemini-3.5-flash", "gemini-3.5-flash", api_style="gemini"),
    "ollama-local": AIModelConfig("Ollama本地模型", "Ollama qwen2.5", "qwen2.5", "http://localhost:11434/v1", requires_api_key=False),
}

MODEL_ALIASES = {
    "qwen3.5-flash": "qwen3.6-flash",
    "deepseek-v3": "deepseek-chat",
}


def _is_placeholder_key(key: Optional[str]) -> bool:
    """Return True if the key looks like an unconfigured placeholder."""
    if not key or not key.strip():
        return True
    lower = key.strip().lower()
    return any(pat in lower for pat in _PLACEHOLDER_PATTERNS)


def normalize_model_preference(model: Optional[str]) -> str:
    """Normalize legacy UI values to a current model preference key."""
    return MODEL_ALIASES.get(model or "", model or QWEN_CONFIG["default_model"])


def resolve_model_config(model: Optional[str]) -> AIModelConfig:
    """Resolve a stored model preference to the exact model called upstream."""
    key = normalize_model_preference(model)
    return MODEL_CATALOG.get(key, MODEL_CATALOG[QWEN_CONFIG["default_model"]])


def describe_model(model: Optional[str], api_key: Optional[str], api_provider: Optional[str] = None, api_base_url: Optional[str] = None) -> dict:
    """Return non-secret status metadata for the configured model."""
    has_key = bool(api_key)
    # Direct connection mode: user set their own base_url
    if api_base_url:
        return {
            "provider": "自定义",
            "api_provider": api_provider,
            "model": model or QWEN_CONFIG["default_model"],
            "label": model or QWEN_CONFIG["default_model"],
            "mode": "remote" if has_key else "local_fallback",
            "billing": "provider_billed" if has_key else "no_remote_charge",
            "requires_api_key": True,
            "has_api_key": has_key,
        }
    # Legacy catalog-based
    config = resolve_model_config(model)
    provider_matches = api_provider == config.provider
    key_bound = bool(api_provider)
    if not config.requires_api_key:
        mode = "remote"
        billing = "no_remote_charge"
    elif not has_key:
        mode = "local_fallback"
        billing = "no_remote_charge"
    elif not key_bound:
        mode = "key_unbound"
        billing = "no_remote_charge"
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


def get_client(api_key: Optional[str], base_url: str, timeout: float = 30.0) -> OpenAI:
    """Create an OpenAI-compatible client for the selected provider.

    Uses a bounded timeout (default 30s) and disables retries. Chat requests
    may include tool planning plus answer generation, so the threshold needs
    enough room for provider-side latency while still failing predictably.
    """
    http_client = DefaultHttpxClient(
        timeout=httpx.Timeout(timeout, connect=10.0),
    )
    return OpenAI(
        base_url=base_url,
        api_key=api_key or "ollama",
        http_client=http_client,
        max_retries=0,
    )


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False,
) -> str:
    """Single-turn chat with the selected AI provider.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model preference stored for the current user
        api_key: API key saved for the current user
        api_provider: Provider that the saved API key belongs to (deprecated)
        base_url: Direct base URL from user settings (skips MODEL_CATALOG when set)
        temperature: Sampling temperature (0-1)
        max_tokens: Maximum tokens to generate
        stream: Whether to stream the response

    Returns:
        Generated text response

    Raises:
        ValueError: If API key not configured
        Exception: If API call fails
    """
    # Direct-connection mode: use user's own base_url, skip catalog
    if base_url:
        if not api_key:
            raise ValueError("API key not configured")
        client = get_client(api_key, base_url)
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

    # Legacy catalog-based routing
    config = resolve_model_config(model)
    _ensure_remote_available(config, api_key, api_provider)

    if config.api_style == "gemini":
        return _gemini_chat(config, api_key or "", messages, temperature, max_tokens)

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


def _build_copilot_messages(
    messages: list[dict],
    page_context: dict,
    knowledge_results: Optional[list[str]] = None,
    screenshot_description: Optional[str] = None,
) -> list[dict]:
    screenshot_section = ""
    if screenshot_description:
        screenshot_section = (
            f"\n当前页面截图内容（由视觉模型分析）:\n"
            f"{screenshot_description}\n"
        )
    structured_context = page_context.get("context_bundle")
    structured_context_section = ""
    if structured_context:
        structured_context_section = (
            "\n结构化上下文包（后端只读白名单工具生成，优先级高于页面零散字段）:\n"
            f"{json.dumps(structured_context, ensure_ascii=False, default=str)[:7000]}\n"
        )

    task_prompt = (
        f"当前页面上下文:\n"
        f"- 页面: {page_context.get('page_type', 'unknown')}\n"
        f"- 风机总数: {page_context.get('total_turbines', 0)}\n"
        f"- 预警风机: {page_context.get('warning_count', 0)}\n"
        f"- 故障风机: {page_context.get('fault_count', 0)}\n"
        f"- 最近告警: {json.dumps(page_context.get('recent_alerts', []), ensure_ascii=False)}\n"
        f"{structured_context_section}"
        f"{screenshot_section}"
        f"\n"
        f"{('知识库参考:' + chr(10) + chr(10).join(knowledge_results)) if knowledge_results else ''}"
        f"\n"
        f"规则:\n"
        f"1. 基于上下文给出准确回答\n"
        f"2. 优先使用结构化上下文包中的结果；说明数据来源时使用业务名称，不要暴露内部工具函数名\n"
        f'3. 涉及安全决策时提醒"建议人工复核"\n'
        f"4. 回复简洁, 关键数据用数字\n"
        f"5. 如果上下文信息不足, 诚实说明\n"
        f"6. 如果有页面截图描述, 可作为页面状态补充，但不得覆盖结构化数据"
    )
    return [
        {"role": "system", "content": _build_system_prompt(task_prompt)},
        *messages,
    ]


def summarize_page(
    page_type: str,
    page_data: dict,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    base_url: Optional[str] = None,
    raise_on_error: bool = False,
) -> dict:
    """Generate AI summary for a page.

    Args:
        page_type: "dashboard" | "diagnosis" | "prediction"
        page_data: current page context (turbine stats, alerts, etc.)
        model: Current user's stored model preference
        api_key: Current user's stored AI service key
        api_provider: Provider that the stored key belongs to (deprecated)
        base_url: User's base URL (direct mode when set)

    Returns:
        {"conclusions": [...], "suggestions": [...]}
    """
    # Use system-level API key + provider as fallback
    effective_key = api_key or settings.DASHSCOPE_API_KEY or None
    effective_provider = api_provider if (api_key and api_provider) else ("通义千问 DashScope" if effective_key else None)

    model_status = describe_model(model, effective_key, effective_provider, base_url)

    system_prompt = _build_system_prompt(
        "根据当前页面数据, 生成简洁的分析报告。\n\n"
        "输出格式必须是JSON:\n"
        "{\n"
        '  "conclusions": ["4到5条关键结论, 每条60字以内"],\n'
        '  "suggestions": ["3到4条可执行建议, 每条60字以内"]\n'
        "}\n"
        "只输出JSON, 不要其他文字。"
    )

    user_prompt = f"""页面类型: {page_type}
当前数据: {json.dumps(page_data, ensure_ascii=False)}

请分析页面数据, 输出4到5条关键结论和3到4条建议。"""

    # Use system-level API key + provider as fallback when user hasn't configured
    effective_key = api_key or settings.DASHSCOPE_API_KEY or None
    effective_provider = api_provider if (api_key and api_provider) else ("通义千问 DashScope" if effective_key else None)

    # Short-circuit: placeholder key → skip network call entirely.
    # Otherwise a fake key causes the OpenAI SDK to retry connection/auth
    # failures for 15+ seconds before falling back.
    if _is_placeholder_key(effective_key) or _is_placeholder_key(api_key):
        logger.info("AI summary: API key is a placeholder, using local fallback immediately")
        if raise_on_error:
            raise ValueError("API key not configured")
        fallback = fallback_summary(page_type, page_data)
        fallback.update({**model_status, "mode": "local_fallback", "billing": "no_remote_charge"})
        return fallback

    try:
        result = chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], model=model or QWEN_CONFIG["cheap_model"], api_key=effective_key, api_provider=effective_provider if not base_url else None, base_url=base_url, temperature=0.3, max_tokens=768)

        # Try to parse JSON from response
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
        parsed = json.loads(result)
        parsed.update(model_status)
        return parsed
    except Exception as e:
        logger.warning(f"AI summary failed, using fallback: {e}")
        if raise_on_error:
            raise
        fallback = fallback_summary(page_type, page_data)
        fallback_mode = model_status["mode"] if model_status["mode"] in {"key_unbound", "provider_mismatch"} else "local_fallback"
        fallback.update({**model_status, "mode": fallback_mode, "billing": "no_remote_charge"})
        return fallback


def diagnose_fault(
    turbine_data: dict,
    fault_data: list[dict],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Generate fault diagnosis report.

    Args:
        turbine_data: Turbine information
        fault_data: Fault records

    Returns:
        Diagnosis report text
    """
    # Apply same fallback logic as copilot_chat for consistency
    effective_key = api_key or settings.DASHSCOPE_API_KEY or None
    effective_provider = (
        api_provider
        if (api_key and api_provider)
        else ("通义千问 DashScope" if effective_key else None)
    )

    config = describe_model(model, effective_key, effective_provider, base_url)
    if config["mode"] != "remote":
        raise ValueError(f"{config['provider']} API key is not ready for selected model")

    system_prompt = _build_system_prompt(
        "风电机组故障诊断专家。基于风机数据给出诊断。"
        "输出格式（纯文本）：\n"
        "【根因】1-2句\n【风险】低/中/高/紧急\n【建议】2-3条\n"
        "总字数100字内。"
    )

    user_prompt = f"""风机:{turbine_data.get('name','?')} HI:{turbine_data.get('hi_value','?')} 状态:{turbine_data.get('status','?')}
最近故障:{fault_data[0].get('type','无') if fault_data else '无'}
诊断建议:"""

    try:
        return chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], model="qwen-turbo", api_key=effective_key,
           api_provider=effective_provider if not base_url else None,
           base_url=base_url, temperature=0.3, max_tokens=200)
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
    base_url: Optional[str] = None,
    stream: bool = False,
    raise_on_error: bool = False,
) -> str:
    """Multi-turn Copilot chat with page context, optional RAG results,
    and optional screenshot description.

    Args:
        messages: conversation history [{role, content}, ...]
        page_context: current page data snapshot
        knowledge_results: RAG-retrieved knowledge snippets
        screenshot_description: text description of current page screenshot
        base_url: User's base URL (direct mode when set)
        stream: return stream generator or string

    Returns:
        AI response text
    """
    try:
        eff_key = api_key or settings.DASHSCOPE_API_KEY or None
        eff_provider = api_provider if (api_key and api_provider) else ("通义千问 DashScope" if eff_key else None)
        return chat(
            _build_copilot_messages(messages, page_context, knowledge_results, screenshot_description),
            model=model or QWEN_CONFIG["default_model"],
            api_key=eff_key,
            api_provider=eff_provider if not base_url else None,
            base_url=base_url,
            temperature=0.5,
            max_tokens=1024,
            stream=stream,
        )
    except Exception as e:
        logger.warning(f"Copilot chat failed: {e}")
        if raise_on_error:
            raise
        return "抱歉, AI服务暂时不可用。请稍后重试。"


def copilot_chat_stream(
    messages: list[dict],
    page_context: dict,
    knowledge_results: Optional[list[str]] = None,
    screenshot_description: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """Yield Copilot answer deltas from an OpenAI-compatible streaming response."""
    eff_key = api_key or settings.DASHSCOPE_API_KEY or None
    eff_provider = api_provider if (api_key and api_provider) else ("通义千问 DashScope" if eff_key else None)
    response = chat(
        _build_copilot_messages(messages, page_context, knowledge_results, screenshot_description),
        model=model or QWEN_CONFIG["default_model"],
        api_key=eff_key,
        api_provider=eff_provider if not base_url else None,
        base_url=base_url,
        temperature=0.5,
        max_tokens=1024,
        stream=True,
    )
    if isinstance(response, str):
        yield response
        return
    for chunk in response:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta else None
        if content:
            yield content


def describe_screenshot(
    screenshot_base64: str,
    page_type: str,
    api_key: Optional[str] = None,
    api_provider: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Use vision model to describe what's visible on the page screenshot.

    Args:
        screenshot_base64: Raw base64-encoded JPEG (without data:image prefix)
        page_type: The page type (dashboard, diagnosis, etc.)
        api_key: User's API key
        api_provider: Provider that the key belongs to (deprecated)
        base_url: User's base URL (uses MODEL_CATALOG fallback if not set)

    Returns:
        Text description of what's visible on screen.

    Raises:
        ValueError: If API key is not configured
    """
    # Use user's base_url if provided, else fall back to catalog
    effective_url = base_url or MODEL_CATALOG["qwen-vl-plus"].base_url
    vision_model = "qwen-vl-plus"  # Default vision model
    if not api_key:
        api_key = settings.DASHSCOPE_API_KEY
    if not api_key:
        raise ValueError("API key not configured for screenshot analysis")

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

    client = get_client(api_key, effective_url)
    response = client.chat.completions.create(
        model=vision_model,
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


def fallback_summary(page_type: str, page_data: dict | None = None) -> dict:
    """Data-aware local fallback when AI API is unavailable.

    Uses actual page_data to generate contextually relevant summaries
    rather than static hardcoded text. Falls back to generic text when
    no data is provided.
    """
    data = page_data or {}

    if page_type == "dashboard":
        total = data.get("total", 0)
        healthy = data.get("healthy", 0)
        warning = data.get("warning", 0)
        faulty = data.get("faulty", 0)
        avg_hi = data.get("avgHi", "--")
        mtbf = data.get("mtbfHours")
        mttr = data.get("mttrHours")

        conclusions = []
        if total > 0:
            online_pct = ((healthy + warning) / total * 100) if total > 0 else 100
            conclusions.append(f"当前风场共{total}台风机，在线率{online_pct:.1f}%")
        if warning > 0:
            conclusions.append(f"{warning}台风机处于预警状态，健康指数偏低需关注")
        if faulty > 0:
            conclusions.append(f"{faulty}台风机处于故障状态，需立即处理")
        if avg_hi not in (None, "--", 0, "0"):
            conclusions.append(f"全场平均健康指数约{avg_hi}，可作为巡检优先级排序依据")
        if mtbf and mtbf > 0:
            conclusions.append(f"当前MTBF约{mtbf:.0f}h，反映全场平均故障间隔水平")
        if not conclusions:
            conclusions.append("风场运行数据正常，暂无异常")

        suggestions = []
        if faulty > 0:
            suggestions.append(f"优先处理{faulty}台故障风机，避免停机损失扩大")
        if warning > 0:
            suggestions.append(f"对{warning}台预警风机安排近期巡检，检查HI下降原因")
        if mtbf and mtbf > 0:
            suggestions.append(f"当前MTBF约{mtbf:.0f}h，合理安排预防性维护可进一步提高可靠性")
        if mttr and mttr > 0:
            suggestions.append(f"当前MTTR约{mttr:.1f}h，建议复盘长耗时维修环节")
        if not suggestions:
            suggestions.append("保持当前运维频率，持续监测HI变化趋势")
        suggestions.append("结合地图分布和HI趋势筛选重点风机，形成下一轮巡检清单")

        return {"conclusions": conclusions, "suggestions": suggestions}

    if page_type == "diagnosis":
        fault_type = data.get("faultType") or data.get("fault_type", "")
        confidence = data.get("confidence", 0)
        turbine_name = data.get("turbineName", "")
        conclusions = []
        if fault_type and confidence:
            conclusions.append(f"检测到{turbine_name or '风机'}存在{fault_type}异常信号")
            conclusions.append(f"故障置信度{confidence:.0%}，建议安排现场确认")
            conclusions.append("以上结论基于SCADA历史数据规则引擎分析")
        else:
            conclusions.append("故障诊断模块需要接入风机SCADA数据进行分析")
        suggestions = [
            "建议48小时内安排针对性检查",
            "检查相关备件库存，确认供应充足",
        ]
        return {"conclusions": conclusions, "suggestions": suggestions}

    if page_type == "prediction":
        avg_rul = data.get("avgRulDays")
        critical = data.get("criticalCount", 0)
        imminent = data.get("imminentCount", 0)
        maintenance_plan = data.get("maintenance_plan") or {}
        plan_total = maintenance_plan.get("total", 0) if isinstance(maintenance_plan, dict) else 0
        urgent_count = maintenance_plan.get("urgent_count", 0) if isinstance(maintenance_plan, dict) else 0
        high_count = maintenance_plan.get("high_count", 0) if isinstance(maintenance_plan, dict) else 0
        total_cost = maintenance_plan.get("total_cost_estimate", 0) if isinstance(maintenance_plan, dict) else 0
        plan_items = maintenance_plan.get("items", []) if isinstance(maintenance_plan, dict) else []
        conclusions = []
        if avg_rul:
            conclusions.append(f"全场风机平均剩余寿命约{avg_rul:.0f}天")
        if plan_total:
            conclusions.append(f"当前维修计划共{plan_total}项，其中{urgent_count}项紧急、{high_count}项高优先级")
        if total_cost:
            conclusions.append(f"维修计划预估总费用约{total_cost:,.0f}元")
        if critical:
            conclusions.append(f"{critical}台风机RUL不足90天，处于关键风险区")
        if imminent:
            conclusions.append(f"{imminent}台风机RUL不足30天，需紧急处理")
        suggestions = []
        if imminent:
            suggestions.append("紧急安排RUL<30天的风机维修，避免非计划停机")
        if urgent_count:
            suggestions.append("优先锁定紧急维修项的人力、备件和停机窗口")
        if plan_items:
            top = plan_items[0]
            if isinstance(top, dict):
                suggestions.append(f"优先复核{top.get('turbine_name', '高风险风机')}{top.get('component', '')}，建议动作：{top.get('action', '安排检修')}")
        if high_count and not urgent_count:
            suggestions.append("将高优先级任务纳入近期滚动排程，避免演变为紧急维修")
        if not conclusions:
            conclusions.append("当前未获取到可用于维护决策的RUL预测数据")
            suggestions.append("请检查预测数据导入、模型任务状态或后端预测服务配置")
        return {"conclusions": conclusions, "suggestions": suggestions}

    return {
        "conclusions": ["AI服务暂不可用，请检查API密钥配置"],
        "suggestions": ["前往设置页面配置AI模型密钥以启用智能总结"],
    }
