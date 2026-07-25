"""Agent task knowledge base.

This package stores deterministic task playbooks used to constrain Agent
planning. The files are data, not execution logic; mutating operations still
have to pass through the Agent Action Gateway.
"""

from .loader import (
    KNOWLEDGE_BASE_DIR,
    find_advanced_workflow,
    load_agent_knowledge_base,
    validate_agent_knowledge_base,
)
from .retriever import retrieve_playbook_matches, retrieve_playbooks

__all__ = [
    "KNOWLEDGE_BASE_DIR",
    "find_advanced_workflow",
    "load_agent_knowledge_base",
    "retrieve_playbook_matches",
    "retrieve_playbooks",
    "validate_agent_knowledge_base",
]
