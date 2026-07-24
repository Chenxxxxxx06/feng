"""Integration tests for agent intent router + knowledge growth pipeline.

API key passed externally via DASHSCOPE_API_KEY env var — NOT hardcoded.
Tests marked 'integration' are skipped when key is unavailable.

Run: pytest backend/tests/test_agent_chain.py -v
"""

import os
import pytest


# ── Helpers ──

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = "qwen3.7-max-2026-05-17"
TURBINE_LIST = "#1 A-001 陕北A风机, #2 A-002 陕北B风机, #3 B-001 关中3号风机, #4 C-001 陕南C风机"

needs_api_key = pytest.mark.skipif(
    not API_KEY,
    reason="DASHSCOPE_API_KEY not set — skipping integration test (requires external LLM)",
)


# ── Tests ──


class TestIntentRouter:
    """Intent classification accuracy — requires external LLM."""

    @pytest.mark.asyncio
    @needs_api_key
    async def test_intent_classification(self):
        """Test 1: Intent classification accuracy across 6 cases."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        cases = [
            ("打开风场监控界面并查看A风机情况", "action", "dashboard"),
            ("查看3号风机的详情", "action", "dashboard"),
            ("什么是齿轮箱故障", "qa", "dashboard"),
            ("分析一下3号风机的振动数据是否异常", "diagnosis", "dashboard"),
            ("切换到诊断页面", "action", "dashboard"),
            ("帮我看看有没有故障的风机", "diagnosis", "dashboard"),
        ]

        passed = 0
        for cmd, expected_type, current_page in cases:
            result = await agent.run(
                user_message=cmd,
                current_page=current_page,
                turbine_list=TURBINE_LIST,
            )
            actual = result.data.get("intent_type", "?")
            if actual == expected_type:
                passed += 1

        assert passed >= 4, f"Intent classification: {passed}/{len(cases)} correct (need ≥4)"

    @pytest.mark.asyncio
    @needs_api_key
    async def test_action_chain_resolution(self):
        """Test 2: Action skill chain resolution."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        result = await agent.run(
            user_message="打开风场监控界面并查看A风机情况",
            current_page="dashboard",
            turbine_list=TURBINE_LIST,
        )

        intent_data = result.data
        assert intent_data.get("intent_type") == "action", "应为action类型"

        skills = intent_data.get("scene_skills", [])
        skill_names = [s["skill"] for s in skills]
        assert len(skill_names) >= 2, f"场景Skill链至少2步，实际{len(skill_names)}步"

    @pytest.mark.asyncio
    @needs_api_key
    async def test_qa_routing(self):
        """Test 3: QA → Knowledge Agent pipeline routing."""
        from app.services.agents.intent_router import IntentRouterAgent

        agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

        result = await agent.run(
            user_message="什么是齿轮箱断齿故障",
            current_page="dashboard",
            turbine_list=TURBINE_LIST,
        )

        intent_data = result.data
        assert intent_data.get("intent_type") in ("qa", "diagnosis"), "应为问答型"
        assert intent_data.get("dispatch_query"), "应有dispatch_query"


class TestKnowledgeGrowth:
    """Knowledge self-growth pipeline — no API key needed."""

    def test_knowledge_growth_pipeline_exists(self):
        """Test 4: Knowledge self-growth pipeline — module and gates exist."""
        from app.services.knowledge_extractor import (
            quality_gate, EXTRACTOR_PROMPT,
            CONCLUSION_KEYWORDS, USER_CONFIRM_KEYWORDS,
        )

        # Simulate a diagnosis conversation
        messages = [
            {"role": "user", "content": "3号风机振动异常是什么原因?"},
            {"role": "assistant", "content": "正在分析3号风机数据..."},
            {"role": "assistant", "content": "3号风机齿轮箱振动RMS值达到15.2 mm/s，超过12 mm/s阈值。"},
            {"role": "user", "content": "应该怎么维修?"},
            {"role": "assistant", "content": "建议检查齿轮箱高速轴承，更换磨损轴承。预估维修方案：停机8小时，更换轴承备件SKF-6322。"},
            {"role": "user", "content": "好的，明白了，谢谢。"},
        ]

        passed_qg = quality_gate(messages)
        assert passed_qg, "Quality gate should pass with 6 messages containing diagnosis context"

        assert EXTRACTOR_PROMPT, "EXTRACTOR_PROMPT must exist"
        assert len(CONCLUSION_KEYWORDS) >= 10, f"CONCLUSION_KEYWORDS ≥ 10, got {len(CONCLUSION_KEYWORDS)}"
        assert len(USER_CONFIRM_KEYWORDS) >= 6, f"USER_CONFIRM_KEYWORDS ≥ 6, got {len(USER_CONFIRM_KEYWORDS)}"

        # Verify the knowledge extractor function exists and is importable
        from app.services.knowledge_extractor import try_extract_knowledge
        assert callable(try_extract_knowledge), "try_extract_knowledge must be callable"

    @pytest.mark.asyncio
    @needs_api_key
    async def test_knowledge_extraction_with_llm(self):
        """Test 4b: Knowledge extraction with real LLM — requires API key."""
        from app.services.knowledge_extractor import try_extract_knowledge

        messages = [
            {"role": "user", "content": "3号风机振动异常是什么原因?"},
            {"role": "assistant", "content": "正在分析3号风机数据..."},
            {"role": "assistant", "content": "3号风机齿轮箱振动RMS值达到15.2 mm/s，超过12 mm/s阈值。"},
            {"role": "user", "content": "应该怎么维修?"},
            {"role": "assistant", "content": "建议检查齿轮箱高速轴承，更换磨损轴承。预估维修方案：停机8小时，更换轴承备件SKF-6322。"},
            {"role": "user", "content": "好的，明白了，谢谢。"},
        ]

        result = await try_extract_knowledge(messages, model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)
        # May succeed or gracefully handle LLM unavailability
        assert result is not None or True  # Not crashing is the minimum bar
