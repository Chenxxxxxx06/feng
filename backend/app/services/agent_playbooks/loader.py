"""Load and validate the local Agent task knowledge base."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent / "knowledge_base"

KB_FILES = {
    "entities": "entities.json",
    "primitive_actions": "primitive_actions.json",
    "read_tasks": "read_tasks.json",
    "advanced_workflows": "advanced_workflows.json",
}

REQUIRED_WORKFLOW_KEYS = {
    "id",
    "name",
    "category",
    "risk_level",
    "implementation_status",
    "intent_examples",
    "required_slots",
    "standard_workflow",
    "allowed_actions",
    "confirmation_required",
    "business_rules",
    "forbidden",
}


def _load_json(name: str) -> dict[str, Any]:
    path = KNOWLEDGE_BASE_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_agent_knowledge_base() -> dict[str, Any]:
    return {key: _load_json(filename) for key, filename in KB_FILES.items()}


def validate_agent_knowledge_base() -> list[str]:
    errors: list[str] = []
    for label, filename in KB_FILES.items():
        path = KNOWLEDGE_BASE_DIR / filename
        if not path.exists():
            errors.append(f"missing file: {label} -> {filename}")
            continue
        try:
            _load_json(filename)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid json: {filename}: {exc}")

    if errors:
        return errors

    primitive_actions = {
        item.get("id")
        for item in _load_json(KB_FILES["primitive_actions"]).get("actions", [])
        if item.get("id")
    }
    workflows = _load_json(KB_FILES["advanced_workflows"]).get("workflows", [])
    ids: set[str] = set()
    for index, workflow in enumerate(workflows):
        missing = REQUIRED_WORKFLOW_KEYS - set(workflow)
        if missing:
            errors.append(f"workflow[{index}] missing keys: {sorted(missing)}")
        workflow_id = workflow.get("id")
        if workflow_id in ids:
            errors.append(f"duplicate workflow id: {workflow_id}")
        if workflow_id:
            ids.add(workflow_id)
        if workflow.get("confirmation_required") and "require_confirmation" not in [
            step.get("step") for step in workflow.get("standard_workflow", [])
        ]:
            errors.append(f"{workflow_id} requires confirmation but lacks require_confirmation step")
        for step in workflow.get("standard_workflow", []):
            step_id = step.get("step")
            if step_id and step_id not in primitive_actions:
                errors.append(f"{workflow_id} references unknown step: {step_id}")
        for action_id in workflow.get("allowed_actions", []):
            if action_id and action_id not in primitive_actions:
                errors.append(f"{workflow_id} allows unknown action: {action_id}")
    read_tasks = _load_json(KB_FILES["read_tasks"]).get("tasks", [])
    for task in read_tasks:
        task_id = task.get("id")
        for step in task.get("standard_workflow", []):
            step_id = step.get("step")
            if step_id and step_id not in primitive_actions:
                errors.append(f"{task_id} references unknown step: {step_id}")
        for action_id in task.get("allowed_actions", []):
            if action_id and action_id not in primitive_actions:
                errors.append(f"{task_id} allows unknown action: {action_id}")
    return errors


def find_advanced_workflow(workflow_id: str) -> dict[str, Any] | None:
    workflows = _load_json(KB_FILES["advanced_workflows"]).get("workflows", [])
    return next((item for item in workflows if item.get("id") == workflow_id), None)
