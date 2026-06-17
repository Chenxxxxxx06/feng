"""Small deterministic retriever for Agent playbooks.

This is intentionally simple. It gives Flash-class models only the most relevant
playbooks and keeps final validation in backend code.
"""

from __future__ import annotations

from typing import Any

from .loader import load_agent_knowledge_base

MIN_RELEVANCE_SCORE = 4
LOW_SIGNAL_KEYWORDS = {
    "风场",
    "风机",
    "状态",
    "运行",
    "齿轮箱",
    "故障",
    "健康",
    "查询",
    "查看",
}


def _is_cjk_text(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _text_blob(playbook: dict[str, Any]) -> str:
    parts: list[str] = [
        str(playbook.get("id", "")),
        str(playbook.get("name", "")),
        str(playbook.get("category", "")),
        str(playbook.get("description", "")),
    ]
    parts.extend(str(item) for item in playbook.get("intent_examples", []))
    parts.extend(str(item) for item in playbook.get("keywords", []))
    parts.extend(str(item) for item in playbook.get("required_slots", []))
    return "\n".join(parts).lower()


def _score(query: str, playbook: dict[str, Any]) -> int:
    query_text = query.lower()
    score = 0
    blob = _text_blob(playbook)
    for field in ("id", "name"):
        value = str(playbook.get(field, "")).lower()
        if value and value in query_text:
            score += 8
    for token in playbook.get("keywords", []):
        if str(token).lower() in query_text:
            token_text = str(token)
            if token_text in LOW_SIGNAL_KEYWORDS:
                score += 2
            elif len(token_text) >= 3 or _is_cjk_text(token_text):
                score += 6
            else:
                score += 2
    for example in playbook.get("intent_examples", []):
        example_text = str(example).lower()
        if example_text and (example_text in query_text or query_text in example_text):
            score += 12
        for token in str(example).replace("，", " ").replace("。", " ").split():
            if token and token.lower() in query_text:
                score += 3
    for word in query_text.replace("，", " ").replace("。", " ").split():
        if word and word in blob:
            score += 1
    return score


def retrieve_playbook_matches(
    query: str,
    *,
    top_k: int = 3,
    include_read_tasks: bool = True,
    min_score: int = MIN_RELEVANCE_SCORE,
) -> list[dict[str, Any]]:
    knowledge_base = load_agent_knowledge_base()
    candidates = list(knowledge_base["advanced_workflows"].get("workflows", []))
    if include_read_tasks:
        candidates.extend(knowledge_base["read_tasks"].get("tasks", []))
    ranked = sorted(
        ((playbook, _score(query, playbook)) for playbook in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    matches: list[dict[str, Any]] = []
    for playbook, score in ranked[:top_k]:
        if score < min_score:
            continue
        item = dict(playbook)
        item["_score"] = score
        matches.append(item)
    return matches


def retrieve_playbooks(query: str, *, top_k: int = 3, include_read_tasks: bool = True) -> list[dict[str, Any]]:
    return retrieve_playbook_matches(query, top_k=top_k, include_read_tasks=include_read_tasks, min_score=1)
