"""Test mixed intent: action + follow-up analysis.

API key passed externally via DASHSCOPE_API_KEY env var — NOT hardcoded.
Tests marked 'integration' are skipped when key is unavailable.

Run: pytest backend/tests/test_mixed_intent.py -v
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


class TestMixedIntent:
    """Mixed intent: action + follow-up analysis — requires external LLM."""

    @pytest.mark.asyncio
    @needs_api_key
    async def test_mixed_intents_action_and_analysis(self):
        """All mixed-intent commands should have BOTH action skills AND follow-up analysis."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        cases = [
            "打开故障诊断页面看看里面有什么信息",
            "打开风场监控看看风机状态如何",
            "去工单页面看看最新的工单情况",
            "打开诊断页看看有没有故障报警",
        ]

        passed = 0
        for cmd in cases:
            result = await agent.run(
                user_message=cmd, current_page="dashboard", turbine_list=TURBINE_LIST
            )
            d = result.data
            intent_type = d.get("intent_type")
            follow_up = d.get("follow_up_analysis", "")
            skills = [s["skill"] for s in d.get("scene_skills", [])]

            has_action = intent_type in ("action", "mixed") and len(skills) > 0
            has_analysis = bool(follow_up)

            if has_action and has_analysis:
                passed += 1

        assert passed >= 2, (
            f"Mixed intent: {passed}/{len(cases)} have both action+analysis (need ≥2)"
        )
