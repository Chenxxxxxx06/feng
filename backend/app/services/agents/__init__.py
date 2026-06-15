"""Multi-Agent system.

Diagnosis: Orchestrator → Data Agent + Knowledge Agent → Synthesizer → Report
"""

from .base import AgentBase, AgentResult
from .orchestrator import OrchestratorAgent
from .data_agent import DataAgent
from .knowledge_agent import KnowledgeAgent
from .synthesizer import SynthesizerAgent

__all__ = [
    "AgentBase", "AgentResult",
    "OrchestratorAgent", "DataAgent", "KnowledgeAgent", "SynthesizerAgent",
]
