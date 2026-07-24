"""Tests for work order email body builders and AI integration."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workorders import (
    _fetch_fault_knowledge,
    _fetch_turbine_info,
    _try_ai_analysis,
    _workorder_html_body,
    _workorder_plain_body,
)
from app.models import FaultKnowledgeNode, Turbine, User, WorkOrder


def _utc_now():
    return datetime.now(timezone.utc)


def _make_wo(assignee="张三", **overrides):
    """Minimal valid WorkOrder for body-builder tests."""
    kwargs = {
        "id": 2,
        "turbine_id": 10,
        "fault_id": None,
        "title": "YD-B-007 主轴不对中紧急维修",
        "description": "振动RMS异常，需紧急检修",
        "status": "in_progress",
        "priority": "urgent",
        "fault_type": "main_shaft_misalignment",
        "assignee": assignee,
        "assignee_id": None,
        "assignee_email": "zhangsan@example.com",
        "due_date": datetime(2026, 6, 18, tzinfo=timezone.utc),
        "cost_estimate": 85000.0,
        "created_at": _utc_now(),
    }
    kwargs.update(overrides)
    return WorkOrder(**kwargs)


def _make_turbine(**overrides):
    kwargs = {
        "id": 10,
        "name": "YD-B-007",
        "model": "GW150-3MW",
        "power_mw": 3.0,
        "region": "陕北A区",
        "status": "warning",
        "hi_value": 72.3,
    }
    kwargs.update(overrides)
    return Turbine(**kwargs)


# ── Unit: _workorder_plain_body ──


class TestPlainBody:
    def test_full_with_ai_and_knowledge(self):
        wo = _make_wo()
        turbine = _make_turbine()
        ai_section = {
            "diagnosis": "主轴不对中信号显著，建议72h内停机检修。",
            "anomalies": [
                {
                    "indicator": "发电机温度",
                    "value": "98.5°C",
                    "normal": "75-85°C",
                    "deviation": "+13.5°C",
                    "level": "high",
                },
                {
                    "indicator": "齿轮箱温度",
                    "value": "87.2°C",
                    "normal": "60-70°C",
                    "deviation": "+17.2°C",
                    "level": "medium",
                },
            ],
            "source": "ai",
        }
        knowledge = {
            "root_causes": ["联轴器磨损", "基础沉降"],
            "solutions": ["激光对中", "更换弹性元件"],
            "spare_parts": ["联轴器弹性体", "地脚螺栓"],
        }

        body = _workorder_plain_body(wo, turbine, ai_section, knowledge)

        # Structural assertions
        assert "WO-0002" in body
        assert "YD-B-007 主轴不对中紧急维修" in body
        assert "YD-B-007" in body
        assert "陕北A区" in body
        assert "72.3" in body
        assert "紧急" in body
        assert "张三" in body
        assert "2026-06-18" in body
        assert "85,000" in body
        # AI section
        assert "AI诊断报告" in body
        assert "主轴不对中信号显著" in body
        assert "发电机温度" in body
        assert "98.5°C" in body
        assert "齿轮箱温度" in body
        # Knowledge section
        assert "知识库参考" in body
        assert "联轴器磨损" in body
        assert "激光对中" in body
        assert "联轴器弹性体" in body
        # Footer
        assert "风调预顺 PHM" in body

    def test_without_ai_shows_no_diagnosis_section(self):
        wo = _make_wo()
        turbine = _make_turbine()
        body = _workorder_plain_body(wo, turbine, None, None)

        assert "WO-0002" in body
        assert "AI诊断报告" not in body
        assert "本地规则诊断" not in body

    def test_local_fallback_label(self):
        wo = _make_wo()
        turbine = _make_turbine()
        ai_section = {
            "diagnosis": "基于规则的本地诊断结果",
            "anomalies": [],
            "source": "local",
        }
        body = _workorder_plain_body(wo, turbine, ai_section, None)
        assert "本地规则诊断" in body
        assert "AI诊断报告" not in body

    def test_without_turbine_shows_id(self):
        wo = _make_wo()
        body = _workorder_plain_body(wo, None, None, None)
        assert "风机ID:     10" in body

    def test_without_knowledge_section(self):
        wo = _make_wo()
        turbine = _make_turbine()
        ai_section = {"diagnosis": "ok", "anomalies": [], "source": "ai"}
        body = _workorder_plain_body(wo, turbine, ai_section, None)
        assert "知识库参考" not in body

    def test_no_description_placeholder(self):
        wo = _make_wo(description=None)
        body = _workorder_plain_body(wo, None, None, None)
        assert "（无）" in body


# ── Unit: _workorder_html_body ──


class TestHtmlBody:
    def test_has_html_structure(self):
        wo = _make_wo()
        turbine = _make_turbine()
        ai_section = {
            "diagnosis": "test diagnosis",
            "anomalies": [
                {"indicator": "温度", "value": "90", "normal": "80", "deviation": "+10", "level": "high"}
            ],
            "source": "ai",
        }
        knowledge = {"root_causes": ["原因A"], "solutions": [], "spare_parts": []}

        html = _workorder_html_body(wo, turbine, ai_section, knowledge)

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "WO-0002" in html
        assert "YD-B-007 主轴不对中紧急维修" in html
        assert "AI 诊断报告" in html
        assert "test diagnosis" in html
        # anomaly table
        assert "温度" in html
        assert "90" in html
        assert "80" in html
        assert "#fff1f0" in html  # high-level bg
        assert "知识库参考" in html
        assert "原因A" in html

    def test_no_ai_no_anomaly_table(self):
        wo = _make_wo()
        html = _workorder_html_body(wo, None, None, None)
        assert "AI 诊断报告" not in html
        assert "本地规则诊断" not in html
        assert "知识库参考" not in html


# ── DB-dependent tests ──


@pytest.mark.asyncio
class TestDbHelpers:
    async def test_fetch_turbine_exists(self, db_session: AsyncSession):
        turbine = Turbine(name="TEST-001", model="M1", power_mw=2.0, region="陕北", status="normal", hi_value=90.0)
        db_session.add(turbine)
        await db_session.commit()
        await db_session.refresh(turbine)

        wo = _make_wo(turbine_id=turbine.id)
        result = await _fetch_turbine_info(wo, db_session)
        assert result is not None
        assert result.name == "TEST-001"

    async def test_fetch_turbine_missing(self, db_session: AsyncSession):
        wo = _make_wo(turbine_id=99999)
        result = await _fetch_turbine_info(wo, db_session)
        assert result is None

    async def test_fetch_fault_knowledge_match(self, db_session: AsyncSession):
        node = FaultKnowledgeNode(
            fault_type="main_shaft_misalignment",
            category="mechanical",
            root_causes=["不对中", "基础松动"],
            solutions=["激光对中校准"],
            spare_parts=["联轴器"],
            severity="high",
        )
        db_session.add(node)
        await db_session.commit()

        wo = _make_wo(fault_type="main_shaft_misalignment")
        result = await _fetch_fault_knowledge(wo, db_session)
        assert result is not None
        assert "不对中" in result["root_causes"]
        assert "激光对中校准" in result["solutions"]
        assert "联轴器" in result["spare_parts"]

    async def test_fetch_fault_knowledge_no_match(self, db_session: AsyncSession):
        wo = _make_wo(fault_type="unknown_type_xyz")
        result = await _fetch_fault_knowledge(wo, db_session)
        assert result is None

    async def test_fetch_fault_knowledge_null_fault_type(self, db_session: AsyncSession):
        wo = _make_wo(fault_type=None)
        result = await _fetch_fault_knowledge(wo, db_session)
        assert result is None

    async def test_try_ai_no_api_key_returns_none(self, db_session: AsyncSession):
        """Test AI analysis behavior when user has no personal API key.

        Falls back to DASHSCOPE_API_KEY env var if set, otherwise returns None.
        When env key is set but fails, returns local fallback diagnosis.
        """
        turbine = Turbine(name="T1", model="M", power_mw=2.0, region="陕北", status="normal", hi_value=90.0)
        db_session.add(turbine)
        await db_session.commit()
        await db_session.refresh(turbine)

        user = User(username="nokey", email="nokey@example.com", password_hash="x", api_key=None)
        db_session.add(user)
        await db_session.commit()

        wo = _make_wo(turbine_id=turbine.id)
        result = await _try_ai_analysis(wo, db_session, user)
        # When user has no API key: returns None if env DASHSCOPE_API_KEY also missing,
        # or returns local fallback if env key exists but AI call fails
        assert result is None or (isinstance(result, dict) and "source" in result)

    async def test_try_ai_no_turbine_returns_none(self, db_session: AsyncSession):
        user = User(username="haskey", email="haskey@example.com", password_hash="x",
                     api_key="sk-test", api_provider="通义千问 DashScope",
                     api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                     model_preference="qwen-plus")
        db_session.add(user)
        await db_session.commit()

        wo = _make_wo(turbine_id=99999)
        result = await _try_ai_analysis(wo, db_session, user)
        assert result is None  # no turbine → can't build context

    @pytest.mark.asyncio
    async def test_try_ai_with_api_key_falls_back_to_local(self, db_session: AsyncSession, monkeypatch):
        """When AI is unreachable (bad key / network), return local fallback."""
        turbine = Turbine(name="T1", model="M", power_mw=2.0, region="陕北", status="normal", hi_value=90.0)
        db_session.add(turbine)
        await db_session.commit()
        await db_session.refresh(turbine)

        user = User(username="badkey", email="badkey@example.com", password_hash="x",
                     api_key="sk-fake", api_provider="通义千问 DashScope",
                     api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                     model_preference="qwen-plus")
        db_session.add(user)
        await db_session.commit()

        wo = _make_wo(turbine_id=turbine.id)

        # _try_ai_analysis calls diagnose_fault which will fail → local fallback
        result = await _try_ai_analysis(wo, db_session, user)
        assert result is not None
        assert result["source"] == "local"  # fell back
        assert "diagnosis" in result
        assert "anomalies" in result

    @pytest.mark.asyncio
    async def test_try_ai_real_key_integration(self, db_session: AsyncSession):
        """Integration test with the real DashScope API key.

        Requires: DASHSCOPE_API_KEY env var or the provided test key.
        Skips silently if key not available.
        """
        import os
        from app.config import get_settings

        settings = get_settings()
        api_key = os.environ.get("DASHSCOPE_API_KEY") or settings.DASHSCOPE_API_KEY
        if not api_key:
            pytest.skip("No DASHSCOPE_API_KEY configured")

        turbine = Turbine(name="TEST-INT", model="GW150", power_mw=3.0, region="陕北", status="warning", hi_value=72.0)
        db_session.add(turbine)
        await db_session.commit()
        await db_session.refresh(turbine)

        user = User(username="integration", email="int@example.com", password_hash="x",
                     api_key=api_key, api_provider="通义千问 DashScope",
                     api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                     model_preference="qwen-plus")
        db_session.add(user)
        await db_session.commit()

        # Add a known fault type for knowledge lookup
        node = FaultKnowledgeNode(
            fault_type="main_shaft_misalignment",
            category="mechanical",
            root_causes=["联轴器不对中"],
            solutions=["激光对中"],
            spare_parts=["弹性体"],
            severity="high",
        )
        db_session.add(node)
        await db_session.commit()

        wo = _make_wo(turbine_id=turbine.id)
        result = await _try_ai_analysis(wo, db_session, user)

        # Either "ai" (success) or "local" (fallback) — both acceptable
        assert result is not None
        assert result["source"] in ("ai", "local")
        assert len(result.get("diagnosis", "")) > 0
