"""Knowledge Extractor — extract structured knowledge from Copilot conversations.

Pipeline: QualityGate → KnowledgeExtractor(LLM) → Dedup(LLM) → Auto-Ingest
"""

import json
import re
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import async_session
from app.models import FaultKnowledgeNode

logger = logging.getLogger(__name__)

# ── Quality Gate ───────────────────────────────────────────

CONCLUSION_KEYWORDS = ["故障", "诊断", "原因", "方案", "修复", "建议", "更换", "检查", "维修", "停机"]
USER_CONFIRM_KEYWORDS = ["好的", "谢谢", "明白了", "就这个", "对", "确认", "可以", "行", "OK", "是的"]
USER_REJECT_KEYWORDS = ["不对", "不是", "重新", "换个", "错了", "不行", "再试", "不确定"]


def quality_gate(messages: list[dict]) -> bool:
    if len(messages) < 4:
        return False
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    if not assistant_msgs:
        return False
    last_reply = assistant_msgs[-1].get("content", "")
    if not any(kw in last_reply for kw in CONCLUSION_KEYWORDS):
        return False
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if user_msgs and any(kw in user_msgs[-1].get("content", "") for kw in USER_REJECT_KEYWORDS):
        return False
    return True


# ── Extractor Prompt ───────────────────────────────────────

EXTRACTOR_PROMPT = """你是风电故障知识提取器。从以下对话中提取结构化故障知识。

对话:
{messages}

输出JSON:
{{
  "fault_type": "故障名",
  "category": "齿轮箱/轴承/叶片/发电机/偏航/传动/电气/塔筒/其他",
  "severity": "low/medium/high/critical",
  "symptoms": [{{"indicator":"振动RMS","threshold":">12 mm/s","unit":"mm/s"}}],
  "root_causes": ["根因1","根因2"],
  "solutions": [{{"action":"方案","difficulty":"easy/medium/hard","downtime_hours":8}}],
  "spare_parts": [{{"name":"备件名","quantity":1,"est_cost":8000}}],
  "case_summary": {{"turbine":"风机名","summary":"发现和解决过程","resolution":"最终方案","total_cost":null,"downtime_days":null}},
  "confidence": 0.0-1.0,
  "reason": "置信度原因"
}}

要求: 只提取对话明确提到的信息，没提到的用[]或null。没有诊断内容返回{{"skip":true,"reason":"..."}}"""


async def extract_knowledge(messages: list[dict], api_key: str | None = None, api_provider: str | None = None, base_url: str | None = None) -> dict | None:
    import asyncio
    from app.services.qwen_client import chat

    msgs_text = "\n".join(f"{'👤' if m['role'] == 'user' else '🤖'}: {m['content']}" for m in messages)

    prompt = EXTRACTOR_PROMPT.format(messages=msgs_text)
    response = await asyncio.to_thread(
        chat, [{"role": "user", "content": prompt}], "qwen-max", api_key,
        api_provider if not base_url else None, base_url=base_url, temperature=0.2, max_tokens=1024,
    )

    try:
        text = response.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.warning(f"Failed to parse extractor output: {e}")

    return None


# ── Dedup ──────────────────────────────────────────────────

DEDUP_PROMPT = """判断两个风电故障是否指向同一类故障。

故障A: {existing_name} ({existing_cat}) 症状: {existing_symptoms}
故障B: {extracted_name} ({extracted_cat}) 症状: {extracted_symptoms}

输出JSON: {{"is_same": true/false, "similarity": 0.0-1.0, "reason": "..."}}
判断标准: 故障名本质相同或症状≥2个重叠且分类相同 → 同一故障"""


async def check_dedup(extracted: dict, db_session: AsyncSession, api_key: str | None = None, api_provider: str | None = None, base_url: str | None = None) -> tuple[bool, int | None]:
    if extracted.get("skip"):
        return False, None

    # Simple pre-filter: same fault_type name → merge
    result = await db_session.execute(
        select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == extracted["fault_type"])
    )
    existing = result.scalar_one_or_none()
    if existing:
        return True, existing.id

    # LLM semantic dedup against all existing nodes
    result = await db_session.execute(select(FaultKnowledgeNode))
    all_nodes = result.scalars().all()

    import asyncio
    from app.services.qwen_client import chat

    ext_name = extracted.get("fault_type", "")
    ext_cat = extracted.get("category", "")
    ext_symptoms = ", ".join(s["indicator"] for s in extracted.get("symptoms", [])[:5])

    for node in all_nodes:
        existing_symptoms = ", ".join(s["indicator"] for s in (node.symptoms or [])[:5])

        prompt = DEDUP_PROMPT.format(
            existing_name=node.fault_type, existing_cat=node.category,
            existing_symptoms=existing_symptoms,
            extracted_name=ext_name, extracted_cat=ext_cat,
            extracted_symptoms=ext_symptoms,
        )
        try:
            response = await asyncio.to_thread(
                chat, [{"role": "user", "content": prompt}], "qwen-max", api_key,
                api_provider if not base_url else None, base_url=base_url, temperature=0.1, max_tokens=256,
            )
            text = response.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                dedup_result = json.loads(match.group(0))
                if dedup_result.get("is_same") and dedup_result.get("similarity", 0) > 0.75:
                    return True, node.id
        except Exception:
            continue

    return False, None


# ── Auto-Ingest ────────────────────────────────────────────

CATEGORY_ICONS = {
    "齿轮箱": "⚙️", "轴承": "🔩", "叶片": "🪶", "发电机": "🔥",
    "偏航": "🧭", "传动": "⚡", "电气": "🔌", "塔筒": "🗼",
}


async def auto_ingest(extracted: dict, is_dup: bool, existing_id: int | None, messages: list[dict], db: AsyncSession):
    if is_dup and existing_id:
        node = await db.get(FaultKnowledgeNode, existing_id)
        if node:
            if extracted.get("case_summary"):
                node.cases = (node.cases or []) + [extracted["case_summary"]]
            if extracted.get("symptoms"):
                existing_indicators = {s["indicator"] for s in (node.symptoms or [])}
                node.symptoms = (node.symptoms or []) + [
                    s for s in extracted["symptoms"] if s["indicator"] not in existing_indicators
                ]
            if extracted.get("solutions"):
                existing_actions = {s["action"] for s in (node.solutions or [])}
                node.solutions = (node.solutions or []) + [
                    s for s in extracted["solutions"] if s["action"] not in existing_actions
                ]
            node.confidence = max(node.confidence or 1.0, extracted.get("confidence", 0.5))
            node.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Merged knowledge: {node.fault_type}")

    else:
        node = FaultKnowledgeNode(
            fault_type=extracted["fault_type"],
            category=extracted.get("category", "其他"),
            icon=CATEGORY_ICONS.get(extracted.get("category", ""), "⚠️"),
            severity=extracted.get("severity", "medium"),
            symptoms=extracted.get("symptoms", []),
            root_causes=extracted.get("root_causes", []),
            solutions=extracted.get("solutions", []),
            spare_parts=extracted.get("spare_parts", []),
            related_faults=[],
            cases=[extracted["case_summary"]] if extracted.get("case_summary") else [],
            source="ai_extracted",
            confidence=extracted.get("confidence", 0.5),
            verified=False,
        )
        db.add(node)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(f"Failed to insert duplicate: {extracted.get('fault_type')}")
            return
        logger.info(f"New knowledge node: {extracted['fault_type']} (confidence:{extracted.get('confidence',0.5)})")


# ── Main entry ─────────────────────────────────────────────

async def try_extract_knowledge(messages: list[dict], api_key: str | None = None, api_provider: str | None = None, base_url: str | None = None):
    """Main pipeline: called as background task after Copilot response."""
    try:
        if not quality_gate(messages):
            return

        extracted = await extract_knowledge(messages, api_key, api_provider, base_url)
        if not extracted or extracted.get("skip"):
            return

        # Use single session for dedup + ingest to avoid TOCTOU race
        async with async_session() as db:
            is_dup, existing_id = await check_dedup(extracted, db, api_key, api_provider, base_url)
            await auto_ingest(extracted, is_dup, existing_id, messages, db)

    except Exception as e:
        logger.error(f"Knowledge extraction failed: {e}")
