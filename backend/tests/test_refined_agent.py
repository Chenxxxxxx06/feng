"""Refined test: fine-grained scene skills for work order operations.
API key passed externally — NOT hardcoded in project code.
"""
import asyncio, sys, io, os
sys.path.insert(0, "G:\\code\\code_vscode\\rjcx\\feng\\backend")

from app.services.agents.intent_router import IntentRouterAgent
from app.api.agent import _resolve_atomic_steps

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = "qwen3.7-max-2026-05-17"
TURBINE_LIST = "#1 A-001 陕北A风机, #2 A-002 陕北B风机, #3 B-001 关中3号风机"


async def test_workorder_scenario():
    """The exact user scenario."""
    print("=" * 60)
    print("场景: 打开维修工单查看王工最新的工单预览")
    print("=" * 60)

    agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

    result = await agent.run(
        user_message="打开维修工单，给我查看最新的王工的工单预览",
        current_page="dashboard",
        turbine_list=TURBINE_LIST,
    )

    d = result.data
    print(f"\n类型: {d.get('intent_type')} (置信度: {d.get('confidence')})")
    print(f"实体: {d.get('entities')}")
    print(f"场景Skill链: {[s['skill'] for s in d.get('scene_skills', [])]}")
    print(f"说明: {d.get('explanation')}")
    print(f"耗时: {result.duration_ms}ms")

    if d.get('intent_type') == 'action' and d.get('scene_skills'):
        steps = _resolve_atomic_steps(d['scene_skills'], d.get('entities', {}))
        print(f"\n解析为 {len(steps)} 个原子步骤:")
        for s in steps:
            print(f"  {s.order}. [{s.skill}] {s.params} — {s.reason}")

    # Verify: should have both GoToWorkOrder AND OpenWorkOrderPreview
    skills = [s['skill'] for s in d.get('scene_skills', [])]
    has_nav = any('WorkOrder' in s or 'GoTo' in s for s in skills)
    has_preview = any('Preview' in s for s in skills)
    print(f"\n验证: 导航到工单页={'✅' if has_nav else '❌'} | 打开预览={'✅' if has_preview else '❌'}")


async def test_entity_extraction():
    """Test that '王工' gets extracted as assignee entity."""
    print("\n" + "=" * 60)
    print("实体提取: 王工 → assignee")
    print("=" * 60)

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

        # Check entities
        entity_ok = True
        for key, expected_val in expected_entities.items():
            actual_val = entities.get(key, "")
            if expected_val not in str(actual_val):
                entity_ok = False

        # Check scene skills reference the entity
        skill_has_entity = False
        for s in scene_skills:
            params = s.get("params", {})
            for key, expected_val in expected_entities.items():
                if expected_val in str(params.get(key, "")):
                    skill_has_entity = True

        status = "✅" if (entity_ok and skill_has_entity) else "❌"
        if entity_ok and skill_has_entity:
            passed += 1

        print(f"\n{status} 输入: {cmd}")
        print(f"   实体: {entities}")
        print(f"   场景Skill: {[s['skill'] for s in scene_skills]}")
        print(f"   Skill参数: {[s.get('params', {}) for s in scene_skills]}")

    print(f"\n  → {passed}/{len(cases)} 实体提取正确")


async def main():
    print("=" * 60)
    print("  细粒度场景Skill — 验证测试")
    print(f"  Model: {MODEL}")
    print("=" * 60)

    await test_workorder_scenario()
    await test_entity_extraction()

    print("\n" + "=" * 60)
    print("  测试完成")
    print("=" * 60)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    asyncio.run(main())
