"""Refined test: fine-grained scene skills for work order operations.

API key passed externally via DASHSCOPE_API_KEY env var — NOT hardcoded.
Tests marked 'integration' are skipped when key is unavailable.

Run: pytest backend/tests/test_refined_agent.py -v
"""

import os
import pytest


API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = "qwen3.7-max-2026-05-17"
TURBINE_LIST = "#1 A-001 陕北A风机, #2 A-002 陕北B风机, #3 B-001 关中3号风机"

needs_api_key = pytest.mark.skipif(
    not API_KEY,
    reason="DASHSCOPE_API_KEY not set — skipping integration test (requires external LLM)",
)


class TestRefinedAgent:
    """Fine-grained scene skills — requires external LLM."""

    @pytest.mark.asyncio
    @needs_api_key
    async def test_workorder_scenario(self):
        """Work order scenario: navigate to work orders and open preview."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        result = await agent.run(
            user_message="打开维修工单，给我查看最新的王工的工单预览",
            current_page="dashboard",
            turbine_list=TURBINE_LIST,
        )

        d = result.data
        skills = [s["skill"] for s in d.get("scene_skills", [])]

        has_nav = any("WorkOrder" in s or "GoTo" in s for s in skills)
        has_preview = any("Preview" in s for s in skills)

        assert d.get("intent_type") == "action", f"Expected action, got {d.get('intent_type')}"
        assert has_nav, f"Should have work-order navigation skill, got: {skills}"
        assert has_preview, f"Should have preview skill, got: {skills}"

    @pytest.mark.asyncio
    @needs_api_key
    async def test_entity_extraction(self):
        """Entity extraction: person names and turbine IDs in context."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        cases = [
            ("查看王工的工单", {"assignee": "王工"}),
            ("查看李工最新的工单预览", {"assignee": "李工"}),
            ("打开维修工单查看张工的", {"assignee": "张工"}),
            ("查看3号风机的最新工单", {"turbine_id": "3"}),
        ]

        passed = 0
        for cmd, expected_entities in cases:
            result = await agent.run(
                user_message=cmd,
                current_page="dashboard",
                turbine_list=TURBINE_LIST,
            )
            entities = result.data.get("entities", {})
            scene_skills = result.data.get("scene_skills", [])

            entity_ok = True
            for key, expected_val in expected_entities.items():
                actual_val = entities.get(key, "")
                if expected_val not in str(actual_val):
                    entity_ok = False

            skill_has_entity = False
            for s in scene_skills:
                params = s.get("params", {})
                for key, expected_val in expected_entities.items():
                    if expected_val in str(params.get(key, "")):
                        skill_has_entity = True

            if entity_ok and skill_has_entity:
                passed += 1

        assert passed >= 2, f"Entity extraction: {passed}/{len(cases)} correct (need ≥2)"
