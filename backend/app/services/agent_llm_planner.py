"""Optional LLM planner for Agent task selection.

The LLM is advisory only: it may choose a playbook and propose slots, but the
unified backend planner still validates playbook ids, recomputes deterministic
slots, and routes writes through the controlled action gateway.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.models import AIProviderConfig
from app.services.agent_playbooks import load_agent_knowledge_base
from app.services.qwen_client import chat

logger = logging.getLogger(__name__)


@dataclass
class LLMPlannerResult:
    playbook_id: str | None
    confidence: float
    slots: dict[str, Any]
    missing_slots: list[str]
    reasoning: str = ""
    raw: str = ""
    error: str | None = None


def _compact_playbooks() -> list[dict[str, Any]]:
    kb = load_agent_knowledge_base()
    items: list[dict[str, Any]] = []
    for kind, group, key in (
        ("advanced_workflow", "advanced_workflows", "workflows"),
        ("read_task", "read_tasks", "tasks"),
    ):
        for item in kb[group].get(key, []):
            items.append(
                {
                    "id": item.get("id"),
                    "kind": kind,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "keywords": item.get("keywords", []),
                    "intent_examples": item.get("intent_examples", [])[:4],
                    "required_slots": item.get("required_slots", []),
                    "optional_slots": item.get("optional_slots", []),
                    "implementation_status": item.get("implementation_status"),
                }
            )
    return items


def _extract_json_object(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
    match = re.search(r"\{.*\}", value, flags=re.S)
    if match:
        value = match.group(0)
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _normalize_slots(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, dict) and "value" in item:
            output[str(key)] = item.get("value")
        else:
            output[str(key)] = item
    return output


def _valid_provider(config: AIProviderConfig | None) -> bool:
    if not config or not config.enabled:
        return False
    if config.provider == "ollama":
        return bool(config.base_url)
    return bool(config.api_key and config.base_url)


async def plan_with_llm(
    *,
    message: str,
    page_context: dict[str, Any],
    provider_config: AIProviderConfig | None,
    model: str | None = None,
) -> LLMPlannerResult | None:
    """Ask the configured model to choose one known playbook.

    Returns None when no usable provider is configured. Any upstream or parsing
    failure is returned as a result with error, so callers can annotate fallback
    behavior without failing the Agent request.
    """
    if not _valid_provider(provider_config):
        return None

    provider_name = provider_config.display_name or provider_config.provider
    effective_key = provider_config.api_key or ("ollama" if provider_config.provider == "ollama" else None)
    effective_model = model or provider_config.default_model
    playbooks = _compact_playbooks()
    allowed_ids = {str(item["id"]) for item in playbooks if item.get("id")}

    messages = [
        {
            "role": "system",
            "content": (
                "你是PHM系统Agent任务规划器。你的职责是从给定Playbook列表中选择最合适的一项，"
                "并抽取结构化槽位。你不能编造Playbook id，不能决定执行写入，不能输出自然语言解释。"
                "如果没有合适任务，playbook_id必须为null。"
                "只输出JSON对象，格式："
                "{\"playbook_id\":string|null,\"confidence\":0到1,\"slots\":{},"
                "\"missing_slots\":[],\"reasoning\":\"简短理由\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": message[:1000],
                    "page_context": page_context,
                    "playbooks": playbooks,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await asyncio.to_thread(
            chat,
            messages,
            effective_model,
            effective_key,
            provider_name if not provider_config.base_url else None,
            provider_config.base_url,
            0,
            512,
        )
        parsed = _extract_json_object(raw)
        playbook_id = parsed.get("playbook_id")
        if playbook_id is not None:
            playbook_id = str(playbook_id).strip()
        if playbook_id and playbook_id not in allowed_ids:
            return LLMPlannerResult(
                playbook_id=None,
                confidence=0.0,
                slots={},
                missing_slots=[],
                reasoning="LLM returned unknown playbook id",
                raw=raw,
                error=f"unknown_playbook_id:{playbook_id}",
            )
        confidence = parsed.get("confidence")
        try:
            confidence_value = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_value = 0.0
        missing = parsed.get("missing_slots") if isinstance(parsed.get("missing_slots"), list) else []
        return LLMPlannerResult(
            playbook_id=playbook_id or None,
            confidence=confidence_value,
            slots=_normalize_slots(parsed.get("slots")),
            missing_slots=[str(item) for item in missing if item],
            reasoning=str(parsed.get("reasoning") or ""),
            raw=raw,
        )
    except Exception as exc:
        logger.warning("LLM Agent planner failed: %s", exc)
        return LLMPlannerResult(
            playbook_id=None,
            confidence=0.0,
            slots={},
            missing_slots=[],
            error=str(exc)[:240],
        )
