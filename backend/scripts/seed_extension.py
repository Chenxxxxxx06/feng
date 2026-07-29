"""六域扩展统一种子脚本 (W3)

按依赖顺序播种四个新域的演示数据：备件库存 → 供应链 → 质量 → 生产排产。

安全保证：
- 全程**只增不改**：每个域的种子函数以业务唯一键判断，已存在则跳过；
- **绝不删除或修改任何既有表的数据**（风机/SCADA/故障/工单等一律不碰）；
- 幂等：重复执行不会产生重复行。

用法（在 backend 目录下）::

    python -m scripts.seed_extension
"""

import asyncio
import sys

# Windows 控制台默认 GBK，显式切 UTF-8 以正常输出中文与符号
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
from pathlib import Path

# embeddable Python 运行时会忽略 PYTHONPATH，这里显式补上项目根
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database import async_session as AsyncSessionLocal, engine, Base  # noqa: E402

# 导入模型以确保 create_all 能发现全部表
import app.models  # noqa: E402,F401

# 既有表：用于播种前后行数对比，证明未破坏原有数据
LEGACY_TABLES = [
    "turbines",
    "scada_records",
    "faults",
    "work_orders",
    "fault_knowledge",
    "rul_predictions",
    "incidents",
    "users",
]


async def _table_counts(db, tables):
    counts = {}
    for t in tables:
        try:
            row = await db.execute(text(f"SELECT COUNT(*) FROM {t}"))
            counts[t] = row.scalar_one()
        except Exception:
            counts[t] = None
    return counts


async def ensure_tables():
    """创建新域数据表（纯增量，已存在的表不受影响）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> int:
    print("=" * 66)
    print("六域扩展种子数据 — 备件库存 / 供应链风险 / 质量分析 / 生产排产")
    print("=" * 66)

    await ensure_tables()
    print("✓ 数据表已确认/创建（create_all，纯增量）")

    async with AsyncSessionLocal() as db:
        before = await _table_counts(db, LEGACY_TABLES)

    results = {}

    # ── 1. 备件库存 ──
    from scripts.seed_inventory import seed_inventory
    async with AsyncSessionLocal() as db:
        results["inventory"] = await seed_inventory(db)
    print(f"✓ 备件库存: {results['inventory']}")

    # ── 2. 供应链（依赖备件 part_no） ──
    from scripts.seed_supply_chain import seed_supply_chain
    async with AsyncSessionLocal() as db:
        results["supply_chain"] = await seed_supply_chain(db, verbose=False)
    print(f"✓ 供应链风险: {results['supply_chain']}")

    # ── 3. 质量（依赖备件与供应商） ──
    from scripts.seed_quality import seed_quality
    async with AsyncSessionLocal() as db:
        results["quality"] = await seed_quality(db, verbose=False)
    print(f"✓ 质量分析: {results['quality']}")

    # ── 4. 生产排产（依赖工单与 SCADA） ──
    from scripts.seed_production import seed_production
    async with AsyncSessionLocal() as db:
        results["production"] = await seed_production(db, verbose=False)
    print(f"✓ 生产排产: {results['production']}")

    async with AsyncSessionLocal() as db:
        after = await _table_counts(db, LEGACY_TABLES)

    print("\n" + "-" * 66)
    print("既有表数据完整性校验（播种前 → 播种后）")
    print("-" * 66)
    intact = True
    for t in LEGACY_TABLES:
        b, a = before.get(t), after.get(t)
        flag = "OK" if b == a else "!! CHANGED !!"
        if b != a:
            intact = False
        print(f"  {t:<20} {b} → {a}   [{flag}]")

    print("\n结论：", "既有数据零变动 ✓" if intact else "⚠️ 检测到既有数据变动，请检查！")
    return 0 if intact else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
