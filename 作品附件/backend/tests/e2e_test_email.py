"""End-to-end test: full email generation chain with real AI API.

Usage:
  cd backend
  DASHSCOPE_API_KEY="your-dashscope-api-key" python tests/e2e_test_email.py
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Write results to UTF-8 file to avoid Windows GBK terminal encoding issues
OUT = Path(__file__).parent / "e2e_output.txt"
REPORT: list[str] = []


def log(line: str = "") -> None:
    """Append to REPORT and also try printing (best-effort)."""
    REPORT.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.database import Base
from app.models import FaultKnowledgeNode, Turbine, User, WorkOrder
from app.api.workorders import (
    _fetch_fault_knowledge,
    _fetch_turbine_info,
    _try_ai_analysis,
    _workorder_html_body,
    _workorder_plain_body,
)

TEST_DB_URL = "sqlite+aiosqlite://"
engine = create_async_engine(TEST_DB_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _make_wo(turbine_id=1, **overrides):
    kwargs = {
        "id": 2,
        "turbine_id": turbine_id,
        "title": "YD-B-007 主轴不对中紧急维修",
        "description": "振动RMS异常，2X/3X频率分量显著，需紧急停机检修",
        "status": "in_progress",
        "priority": "urgent",
        "fault_type": "main_shaft_misalignment",
        "assignee": "曲振华",
        "assignee_email": "quzhenhua@example.com",
        "due_date": datetime(2026, 6, 18, tzinfo=timezone.utc),
        "cost_estimate": 85000.0,
        "created_at": datetime.now(timezone.utc),
    }
    kwargs.update(overrides)
    return WorkOrder(**kwargs)


async def main():
    # ── Setup DB ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # ── Seed test data ──
        turbine = Turbine(
            id=1, name="YD-B-007", model="GW150-3MW",
            power_mw=3.0, region="陕北A区", status="warning", hi_value=72.3,
        )
        db.add(turbine)

        # User WITH valid API key (for AI test)
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        user_ai = User(
            id=1, username="ai_user", email="ai@example.com",
            password_hash="x", role="admin",
            api_key=api_key, api_provider="通义千问 DashScope",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_preference="qwen-plus",
        )
        # User WITHOUT API key (for no-AI test)
        user_noai = User(
            id=2, username="noai_user", email="noai@example.com",
            password_hash="x", role="viewer",
            api_key=None,
        )
        db.add_all([user_ai, user_noai])

        # Fault knowledge
        node = FaultKnowledgeNode(
            fault_type="main_shaft_misalignment",
            category="mechanical",
            root_causes=["联轴器弹性元件磨损", "基础不均匀沉降", "对中精度漂移"],
            solutions=["激光对中仪重新校准", "更换联轴器弹性体", "检查地脚螺栓力矩"],
            spare_parts=["联轴器弹性体 ML-200", "地脚螺栓 M36", "对中垫片组"],
            severity="high",
        )
        db.add(node)
        await db.commit()

        wo = _make_wo(turbine_id=1)

        # ── TEST 1: No API key ──
        log("=" * 70)
        log("TEST 1: User WITHOUT API key")
        log("=" * 70)
        result1 = await _try_ai_analysis(wo, db, user_noai)
        assert result1 is None, f"Expected None, got {result1}"
        log("[OK] _try_ai_analysis returns None (no API key)")
        log()

        # ── TEST 2: With API key ──
        log("=" * 70)
        log("TEST 2: User WITH API key -> real AI diagnosis")
        log("=" * 70)
        if not api_key:
            log("[SKIP] No DASHSCOPE_API_KEY set.")
        else:
            result2 = await _try_ai_analysis(wo, db, user_ai)
            assert result2 is not None
            assert "diagnosis" in result2
            assert "anomalies" in result2
            log(f"  source:        {result2['source']}")
            log(f"  anomalies:     {len(result2.get('anomalies', []))} found")
            for a in result2.get("anomalies", []):
                log(f"    - {a['indicator']}: {a['value']} (normal: {a['normal']}) [{a['level']}]")
            log(f"  diagnosis ({len(result2['diagnosis'])} chars):")
            log(f"    {result2['diagnosis'][:300]}")
            log()

        # ── TEST 3: Email body generation ──
        log("=" * 70)
        log("TEST 3: Email body generation (plain + HTML)")
        log("=" * 70)

        turbine_fetched = await _fetch_turbine_info(wo, db)
        ai_section = await _try_ai_analysis(wo, db, user_ai) if api_key else None
        knowledge = await _fetch_fault_knowledge(wo, db)

        plain = _workorder_plain_body(wo, turbine_fetched, ai_section, knowledge)
        log("\n--- PLAIN TEXT BODY (full) ---")
        log(plain)
        log(f"({len(plain)} total chars)")

        html = _workorder_html_body(wo, turbine_fetched, ai_section, knowledge)
        log("\n--- HTML BODY (full) ---")
        log(html)
        log(f"({len(html)} total chars)")

        assert "WO-0002" in plain
        assert "YD-B-007" in plain
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        if ai_section:
            assert "诊断" in plain
        if knowledge:
            assert "联轴器" in plain
        log("\n[OK] All content assertions passed")

        # ── TEST 4: cost_estimate=None ──
        log("\n" + "=" * 70)
        log("TEST 4: cost_estimate=None safety check")
        log("=" * 70)
        wo_none_cost = _make_wo(turbine_id=1, cost_estimate=None)
        plain_none = _workorder_plain_body(wo_none_cost, None, None, None)
        html_none = _workorder_html_body(wo_none_cost, None, None, None)
        assert "未设置" in plain_none
        assert "未设置" in html_none
        log("[OK] None cost_estimate handled safely")

        # ── TEST 5: cost_estimate=0.0 consistency ──
        log("\n" + "=" * 70)
        log("TEST 5: cost_estimate=0.0 consistency")
        log("=" * 70)
        wo_zero_cost = _make_wo(turbine_id=1, cost_estimate=0.0)
        plain_zero = _workorder_plain_body(wo_zero_cost, None, None, None)
        html_zero = _workorder_html_body(wo_zero_cost, None, None, None)
        assert "未设置" in plain_zero
        assert "未设置" in html_zero
        log("[OK] 0.0 cost handled as '未设置' consistently")

        log("\n" + "=" * 70)
        log("ALL 5 E2E TESTS PASSED")
        log("=" * 70)

        # Write full report to UTF-8 file for user review
        OUT.write_text("\n".join(REPORT), encoding="utf-8")
        print(f"\nFull report written to: {OUT}")

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
