"""Test mixed intent: action + follow-up analysis."""
import asyncio, sys, io
sys.path.insert(0, "G:\\code\\code_vscode\\rjcx\\feng\\backend")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.services.agents.intent_router import IntentRouterAgent
from app.api.agent import _resolve_atomic_steps

API_KEY = "sk-ff2da15c673e488cbc41b7535176a61d"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.7-max-2026-05-17"
TURBINE_LIST = "#1 A-001 陕北A风机, #2 A-002 陕北B风机, #3 B-001 关中3号风机"


async def test_mixed_intents():
    agent = IntentRouterAgent(model=MODEL, api_key=API_KEY, api_base_url=BASE_URL)

    cases = [
        "打开故障诊断页面看看里面有什么信息",
        "打开风场监控看看风机状态如何",
        "去工单页面看看最新的工单情况",
        "打开诊断页看看有没有故障报警",
    ]

    passed = 0
    for cmd in cases:
        result = await agent.run(user_message=cmd, current_page="dashboard", turbine_list=TURBINE_LIST)
        d = result.data
        intent_type = d.get("intent_type")
        follow_up = d.get("follow_up_analysis", "")
        skills = [s["skill"] for s in d.get("scene_skills", [])]

        has_action = intent_type in ("action", "mixed") and len(skills) > 0
        has_analysis = bool(follow_up)
        is_mixed = intent_type == "mixed"

        status = "✅" if (has_action and has_analysis) else ("⚠️" if has_action else "❌")
        if has_action and has_analysis:
            passed += 1

        print(f"\n{status} 意图={intent_type}(mixed={is_mixed})")
        print(f"   输入: {cmd}")
        print(f"   操作: {' → '.join(skills) if skills else '(无)'}")
        print(f"   后续分析: {follow_up[:80] if follow_up else '❌ 缺失'}")

        if intent_type == "mixed" and skills:
            steps = _resolve_atomic_steps(d.get("scene_skills", []), d.get("entities", {}))
            print(f"   原子步骤({len(steps)}步):")
            for s in steps:
                print(f"     {s.order}. [{s.skill}] {s.params}")

    print(f"\n  → {passed}/{len(cases)} 混合意图识别正确(Action+Analysis兼备)")


async def main():
    print("=" * 60)
    print("  混合型意图 — Action + Analysis 测试")
    print(f"  Model: {MODEL}")
    print("=" * 60)
    await test_mixed_intents()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
