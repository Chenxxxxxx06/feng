"""Multi-Agent system.

Diagnosis: Orchestrator → Data Agent + Knowledge Agent → Synthesizer → Report
Intent: IntentRouter → classify + plan action chains
"""

from .base import AgentBase, AgentResult
from .intent_router import IntentRouterAgent
from .orchestrator import OrchestratorAgent
from .data_agent import DataAgent
from .knowledge_agent import KnowledgeAgent
from .synthesizer import SynthesizerAgent

__all__ = [
    "AgentBase", "AgentResult",
    "IntentRouterAgent",
    "OrchestratorAgent", "DataAgent", "KnowledgeAgent", "SynthesizerAgent",
]
