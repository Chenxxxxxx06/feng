"""Orchestrator Agent — parses intent, dispatches to Data/Knowledge agents."""

from .base import AgentBase

ORCHESTRATOR_PROMPT = """
你是风调预顺PHM调度器。解析用户意图，决定调度哪些子Agent。

子Agent:
1. data_agent: 查风机当前可用数据 (历史SCADA/历史故障/RUL/振动)
2. knowledge_agent: 查故障知识图谱 (症状匹配/根因/方案/案例/备件)

判断规则:
- 提到具体风机号/名称 → 必须调 data_agent
- 描述症状/故障现象 → 必须调 knowledge_agent
- 问"什么原因"/"怎么修"/"备件" → 两个都调
- 只查通用知识 → 只调 knowledge_agent
- 只查数据 → 只调 data_agent
- 闲聊/非诊断类 → 两个都不调，标记 intent_type="general_chat"

当前可用风机: {turbine_list}

用户消息: {user_message}

输出JSON:
{{
  "intent_type": "fault_diagnosis|knowledge_query|data_query|general_chat",
  "entities": {{"turbine_id": 风机ID或null, "symptoms": ["症状1","症状2"]}},
  "dispatch": [
    {{"agent": "data_agent", "query": "具体查询任务描述"}},
    {{"agent": "knowledge_agent", "query": "具体查询任务描述"}}
  ],
  "explanation": "一句话说明为什么这样调度"
}}
"""


class OrchestratorAgent(AgentBase):
    def __init__(self, model: str = "qwen-max", api_key: str | None = None, api_provider: str | None = None, api_base_url: str | None = None):
        super().__init__(name="orchestrator", system_prompt=ORCHESTRATOR_PROMPT, model=model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)

    def needs_data_agent(self, result: dict) -> bool:
        return any(d.get("agent") == "data_agent" for d in result.get("dispatch", []))

    def needs_knowledge_agent(self, result: dict) -> bool:
        return any(d.get("agent") == "knowledge_agent" for d in result.get("dispatch", []))

    def dispatch_query(self, result: dict, agent_name: str) -> str:
        for d in result.get("dispatch", []):
            if d.get("agent") == agent_name:
                return d.get("query", "")
        return ""
