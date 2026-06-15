"""Knowledge Agent — searches fault knowledge base."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .base import AgentBase

KNOWLEDGE_AGENT_PROMPT = """
你是风调预顺PHM知识图谱Agent。你有故障百科的全部知识。

知识图谱数据:
{knowledge_context}

查询任务: {query}

请输出JSON:
{{
  "matches": [
    {{
      "fault_type": "故障名",
      "category": "分类",
      "severity": "严重度",
      "confidence": 0.0-1.0,
      "symptoms_matched": [
        {{"indicator": "症状名", "user_observed": "用户描述", "kb_threshold": "知识库阈值", "match": true/false}}
      ],
      "recommended_solutions": [
        {{"action": "方案", "difficulty": "难度", "downtime_hours": 停机小时, "priority": 优先级数字}}
      ],
      "related_risks": [
        {{"name": "关联故障名", "probability": 0.0-1.0, "reason": "原因"}}
      ],
      "best_case": {{"turbine": "风机", "date": "日期", "resolution": "方案", "result": "结果"}}
    }}
  ],
  "recommend_next": "建议下一步验证或检查的内容"
}}

如果知识库中没有匹配的故障，matches 为空数组，recommend_next 说明建议。
"""


class KnowledgeAgent(AgentBase):
    def __init__(self, model: str = "qwen-max", api_key: str | None = None, api_provider: str | None = None):
        super().__init__(name="knowledge_agent", system_prompt=KNOWLEDGE_AGENT_PROMPT, model=model, api_key=api_key, api_provider=api_provider)

    async def load_knowledge_context(self, db: AsyncSession) -> str:
        """Load all knowledge nodes as context for the LLM."""
        from app.models import FaultKnowledgeNode
        result = await db.execute(select(FaultKnowledgeNode))
        nodes = result.scalars().all()
        if not nodes:
            return "（知识库为空）"

        lines = []
        for n in nodes:
            lines.append(f"- [{n.category}] {n.fault_type} (严重度:{n.severity})")
            if n.symptoms:
                lines.append(f"  症状: {', '.join(s['indicator'] + s.get('threshold','') for s in n.symptoms)}")
            if n.root_causes:
                lines.append(f"  根因: {', '.join(n.root_causes[:3])}")
            if n.solutions:
                lines.append(f"  方案: {', '.join(s['action'] for s in n.solutions[:3])}")
        return "\n".join(lines)
