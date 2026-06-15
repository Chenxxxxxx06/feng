"""Multi-Agent system.

Diagnosis: Orchestrator → Data Agent + Knowledge Agent → Synthesizer → Report
IntentRouter → action execution | diagnosis pipeline
Task:     TaskAgent → Plan → Execute → Summarize → Reply
"""

from .base import AgentBase, AgentResult
from .orchestrator import OrchestratorAgent
from .data_agent import DataAgent
from .knowledge_agent import KnowledgeAgent
from .synthesizer import SynthesizerAgent
from .intent_router import IntentRouterAgent
from .task_agent import TaskAgent

__all__ = [
    "AgentBase", "AgentResult",
    "OrchestratorAgent", "DataAgent", "KnowledgeAgent", "SynthesizerAgent",
    "IntentRouterAgent",
    "TaskAgent",
]
