"""Seed Shaanxi wind farm turbine data.

Comprehensive seed script for PHM system demonstration.
Populates database with turbines, SCADA data, faults, predictions, and work orders.

This script detects if an offline dataset exists and skips seeding if it does,
to avoid overwriting pre-populated CARE dataset data.

Usage:
    cd backend
    python -m scripts.seed_data
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
import random

# Windows consoles often default to GBK; keep the seed command Unicode-safe.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import delete, select
from app.database import async_session, database_url, engine, Base
from app.config import get_offline_database_path
from app.models import (
    Turbine, SCADARecord, Fault, FaultSignal, RULPrediction,
    WorkOrder, User, NotificationConfig, DataSource
)
from app.core.security import hash_password


def check_offline_dataset_exists() -> bool:
    """Check whether this process is actually connected to the offline database."""
    offline_db = get_offline_database_path()
    if offline_db is None:
        return False
    normalized_url = str(database_url).replace("\\", "/").lower()
    normalized_path = str(offline_db.resolve()).replace("\\", "/").lower()
    return normalized_path in normalized_url


# 陕西省风场数据 — 真实地理坐标
SHAANXI_TURBINES = [
    # 陕北 — 榆林定边（陕西最大风场）
    {"name": "DB-A-001", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.3250, "lng": 107.5980, "region": "陕北"},
    {"name": "DB-A-002", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.3310, "lng": 107.5820, "region": "陕北"},
    {"name": "DB-A-003", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.3190, "lng": 107.6100, "region": "陕北"},
    {"name": "DB-A-004", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.3080, "lng": 107.6240, "region": "陕北"},
    {"name": "DB-A-005", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.3120, "lng": 107.6050, "region": "陕北"},
    {"name": "DB-B-001", "model": "Vestas V112-3.3MW", "power_mw": 3.3, "lat": 37.3400, "lng": 107.5700, "region": "陕北"},
    {"name": "DB-B-002", "model": "Vestas V112-3.3MW", "power_mw": 3.3, "lat": 37.3450, "lng": 107.5580, "region": "陕北"},
    {"name": "DB-B-003", "model": "明阳MySE3.2-156", "power_mw": 3.2, "lat": 37.3350, "lng": 107.5450, "region": "陕北"},
    # 陕北 — 榆林靖边
    {"name": "JB-C-001", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.4210, "lng": 108.8050, "region": "陕北"},
    {"name": "JB-C-002", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.4280, "lng": 108.8120, "region": "陕北"},
    {"name": "JB-C-003", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.4150, "lng": 108.7980, "region": "陕北"},
    {"name": "JB-C-004", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.4320, "lng": 108.8200, "region": "陕北"},
    # 陕北 — 延安子长
    {"name": "ZC-D-001", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 37.2459, "lng": 109.4088, "region": "陕北"},
    {"name": "ZC-D-002", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 37.2520, "lng": 109.4150, "region": "陕北"},
    {"name": "ZC-D-003", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 37.2400, "lng": 109.4020, "region": "陕北"},
    {"name": "ZC-E-001", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.2937, "lng": 109.2602, "region": "陕北"},
    {"name": "ZC-E-002", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 37.2880, "lng": 109.2550, "region": "陕北"},
    # 陕北 — 神木
    {"name": "SM-F-001", "model": "Vestas V112-3.3MW", "power_mw": 3.3, "lat": 38.7220, "lng": 110.1530, "region": "陕北"},
    {"name": "SM-F-002", "model": "Vestas V112-3.3MW", "power_mw": 3.3, "lat": 38.7280, "lng": 110.1480, "region": "陕北"},
    {"name": "SM-F-003", "model": "明阳MySE3.2-156", "power_mw": 3.2, "lat": 38.7150, "lng": 110.1600, "region": "陕北"},
    # 陕北 — 横山
    {"name": "HS-G-001", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.8820, "lng": 109.3250, "region": "陕北"},
    {"name": "HS-G-002", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 37.8880, "lng": 109.3180, "region": "陕北"},
    # 关中 — 渭南大荔
    {"name": "DL-H-001", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 34.7127, "lng": 109.9905, "region": "关中"},
    {"name": "DL-H-002", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 34.7200, "lng": 109.9850, "region": "关中"},
    {"name": "DL-H-003", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 34.7080, "lng": 109.9980, "region": "关中"},
    # 关中 — 渭南合阳
    {"name": "HY-I-001", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 35.2150, "lng": 110.1450, "region": "关中"},
    {"name": "HY-I-002", "model": "远景EN-156/3.3", "power_mw": 3.3, "lat": 35.2220, "lng": 110.1380, "region": "关中"},
    # 陕南 — 商洛
    {"name": "SL-J-001", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 33.6950, "lng": 109.9480, "region": "陕南"},
    {"name": "SL-J-002", "model": "华能H120-2.0MW", "power_mw": 2.0, "lat": 33.7020, "lng": 109.9420, "region": "陕南"},
    # 陕南 — 安康
    {"name": "AK-K-001", "model": "金风GW150-3MW", "power_mw": 3.0, "lat": 32.6850, "lng": 109.0250, "region": "陕南"},
]

FAULT_TYPES = [
    "bearing_inner_race_wear",  # 轴承内圈磨损
    "gearbox_tooth_pitting",    # 齿轮箱点蚀
    "generator_overheat",       # 发电机过热
    "blade_leading_edge_erosion", # 叶片前缘腐蚀
    "pitch_system_fault",       # 变桨系统故障
    "main_shaft_misalignment",  # 主轴不对中
    "cooling_system_fault",     # 冷却系统故障
    "electrical_connection",    # 电气连接松动
]

COMPONENTS = ["齿轮箱", "发电机", "主轴承", "叶片", "变桨系统"]

WORK_ORDER_TEMPLATES = [
    {"title": "轴承更换", "desc": "高速轴轴承磨损超标，需更换", "priority": "urgent", "cost": 85000},
    {"title": "齿轮箱检修", "desc": "齿轮箱点蚀修复，检查润滑系统", "priority": "high", "cost": 120000},
    {"title": "叶片修复", "desc": "叶片前缘腐蚀修复，打磨+涂装", "priority": "medium", "cost": 35000},
    {"title": "发电机维护", "desc": "发电机温度异常，检查冷却系统", "priority": "high", "cost": 45000},
    {"title": "变桨系统调整", "desc": "变桨角度偏差校正", "priority": "medium", "cost": 18000},
    {"title": "例行巡检", "desc": "季度例行巡检维护", "priority": "low", "cost": 5000},
    {"title": "年度大修", "desc": "年度全面检修维护", "priority": "medium", "cost": 25000},
    {"title": "振动复测", "desc": "异常振动信号复测确认", "priority": "high", "cost": 8000},
]


async def check_existing_data() -> bool:
    """Check if database already has significant data."""
    async with async_session() as db:
        # Check if there are any turbines
        result = await db.execute(select(Turbine).limit(1))
        if result.scalar_one_or_none() is not None:
            return True
        
        # Check if there are any users
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return True
        
        return False


async def seed():
    """Main seed function."""
    random.seed(20260729)
    print("=" * 60)
    print("🌱 风调预顺 PHM系统 — 数据库初始化")
    print("=" * 60)

    # Check if offline dataset exists
    if check_offline_dataset_exists():
        print("📦 检测到离线数据集，跳过演示数据初始化")
        print("   离线数据库路径: ", get_offline_database_path())
        
        # Still create tables if they don't exist
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ 数据表已创建/验证")
        
        # Check if users exist, if not create admin user
        if not await check_existing_data():
            print("\n⚠️ 数据库为空，创建默认管理员用户...")
            await create_default_admin()

        await seed_knowledge_base()

        print("\n" + "=" * 60)
        print("🎉 数据库配置完成！")
        print("=" * 60)
        return

    # Create tables first (needed before check_existing_data can query)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ 数据表创建完成")

    # Check if database already has data
    if await check_existing_data():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await seed_knowledge_base()
        print("⚠️ 数据库中已存在数据，跳过演示数据初始化")
        print("   已补充知识库数据（如有新增）")
        return

    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # 1. Create users
        print("\n👤 创建用户...")
        admin = User(
            username="admin",
            email="admin@fengdiao.com",
            password_hash=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)

        technicians = [
            ("张工", "zhang@fengdiao.com"),
            ("李工", "li@fengdiao.com"),
            ("王工", "wang@fengdiao.com"),
            ("赵工", "zhao@fengdiao.com"),
        ]
        tech_objs = []
        for name, email in technicians:
            user = User(
                username=name,
                email=email,
                password_hash=hash_password("tech123"),
                role="technician",
                is_active=True,
            )
            db.add(user)
            tech_objs.append(user)

        await db.commit()
        print(f"   ✅ 创建 {len(technicians) + 1} 个用户")

        # 2. Create turbines
        print("\n🌀 创建风机...")
        turbine_objs = []
        for i, t in enumerate(SHAANXI_TURBINES):
            # Assign realistic status distribution
            rand = random.random()
            if rand < 0.05:  # 5% fault
                hi = random.uniform(35, 55)
                status = "fault"
            elif rand < 0.20:  # 15% warning
                hi = random.uniform(60, 79)
                status = "warning"
            else:  # 80% normal
                hi = random.uniform(80, 98)
                status = "normal"

            obj = Turbine(
                name=t["name"],
                model=t["model"],
                power_mw=t["power_mw"],
                lat=t["lat"],
                lng=t["lng"],
                region=t["region"],
                status=status,
                hi_value=round(hi, 1),
                last_maintenance=now - timedelta(days=random.randint(10, 365)),
                commissioned_at=now - timedelta(days=random.randint(365, 1825)),
            )
            turbine_objs.append(obj)

        db.add_all(turbine_objs)
        await db.commit()
        for obj in turbine_objs:
            await db.refresh(obj)
        print(f"   ✅ 创建 {len(turbine_objs)} 台风机")

        # 3. Seed SCADA data (last 24h for each turbine)
        print("\n📊 生成SCADA数据...")
        scada_count = 0
        for t in turbine_objs:
            for h in range(24):
                for m in [0, 10, 20, 30, 40, 50]:
                    # Realistic power curve
                    wind = random.uniform(3, 18)
                    if wind < 3:
                        power_ratio = 0
                    elif wind < 12:
                        power_ratio = ((wind - 3) / 9) ** 3
                    else:
                        power_ratio = min(1.0, random.uniform(0.9, 1.0))

                    rec = SCADARecord(
                        turbine_id=t.id,
                        timestamp=now - timedelta(hours=h, minutes=m),
                        power_kw=round(t.power_mw * 1000 * power_ratio * random.uniform(0.85, 1.0), 1),
                        wind_speed_ms=round(wind, 1),
                        rotor_rpm=round(8 + power_ratio * 10 + random.uniform(-0.5, 0.5), 1),
                        gen_temperature_c=round(50 + power_ratio * 40 + random.uniform(-3, 3), 1),
                        gearbox_temperature_c=round(45 + power_ratio * 30 + random.uniform(-2, 2), 1),
                        bearing_temperature_c=round(40 + power_ratio * 25 + random.uniform(-2, 2), 1),
                        pitch_angle_deg=round(max(0, (wind - 12) * 2.5 + random.uniform(-1, 1)), 1),
                        nacelle_direction_deg=round(random.uniform(0, 360), 0),
                        grid_frequency_hz=round(50.0 + random.uniform(-0.05, 0.05), 2),
                        ambient_temp_c=round(15 + random.uniform(-5, 10), 1),
                    )
                    db.add(rec)
                    scada_count += 1

            # Commit every 5 turbines to avoid huge transaction
            if len(turbine_objs) > 0 and turbine_objs.index(t) % 5 == 4:
                await db.commit()

        await db.commit()
        print(f"   ✅ 生成 {scada_count} 条SCADA记录")

        # 4. Seed faults
        print("\n⚠️ 创建故障记录...")
        fault_count = 0
        fault_objs = []
        handler_names = ["张工", "李工", "王工"]
        for i, t in enumerate(turbine_objs[:8]):  # First 8 turbines have faults
            ft = random.choice(FAULT_TYPES)
            confidence = round(random.uniform(0.72, 0.96), 2)
            fault_status = "open" if i < 3 else "closed"
            detected_hours_ago = random.randint(1, 168)

            f = Fault(
                turbine_id=t.id,
                detected_at=now - timedelta(hours=detected_hours_ago),
                fault_type=ft,
                confidence=confidence,
                status=fault_status,
                processing_status="pending" if fault_status == "open" else "closed",
                priority=random.choice(["urgent", "high", "medium", "low"]),
                handler=random.choice(handler_names) if fault_status == "open" else handler_names[i % 3],
                discovered_at=now - timedelta(hours=detected_hours_ago),
                processing_started_at=now - timedelta(hours=detected_hours_ago - random.randint(1, 4)) if fault_status != "open" else None,
                closed_at=now - timedelta(hours=random.randint(1, 48)) if fault_status == "closed" else None,
                last_action_at=now - timedelta(hours=random.randint(1, 12)),
                work_order_title=f"{t.name}-{ft}维修工单" if fault_status != "open" else None,
                maintenance_cost_estimate=round(random.uniform(5000, 50000), 2),
                maintenance_cost_actual=round(random.uniform(5000, 50000), 2) if fault_status == "closed" else None,
                status_note="已自动检测，待人工确认" if fault_status == "open" else "检修完成，风机恢复正常运行",
                details={
                    "root_cause": f"基于振动分析和SCADA数据的{ft}诊断",
                    "recommendation": f"建议检查{ft}相关部件，安排振动复测",
                },
            )
            db.add(f)
            await db.flush()
            fault_objs.append(f)

            # Add fault signals
            signals_data = [
                ("振动RMS值", round(random.uniform(0.6, 0.95), 2), "high"),
                ("轴承温度", round(random.uniform(0.5, 0.85), 2), "high"),
                ("发电机温度", round(random.uniform(0.3, 0.7), 2), "medium"),
                ("功率偏差", round(random.uniform(0.2, 0.5), 2), "low"),
                ("频率特征", round(random.uniform(0.1, 0.4), 2), "low"),
            ]
            for s_name, score, pri in signals_data:
                sig = FaultSignal(
                    fault_id=f.id,
                    sensor_name=s_name,
                    contribution_score=score,
                    priority=pri,
                )
                db.add(sig)
            fault_count += 1

        await db.commit()
        print(f"   ✅ 创建 {fault_count} 个故障记录")

        # 5. Seed RUL predictions
        print("\n🔮 生成RUL预测...")
        rul_count = 0
        for t in turbine_objs:
            # Each turbine has 2-4 component predictions
            for comp in random.sample(COMPONENTS, random.randint(2, 4)):
                remaining = random.uniform(30, 1200)
                r = RULPrediction(
                    turbine_id=t.id,
                    component=comp,
                    predicted_at=now,
                    remaining_life_days=round(remaining, 1),
                    confidence_lower=round(remaining * random.uniform(0.7, 0.9), 1),
                    confidence_upper=round(remaining * random.uniform(1.1, 1.3), 1),
                )
                db.add(r)
                rul_count += 1
        await db.commit()
        print(f"   ✅ 生成 {rul_count} 条RUL预测")

        # 6. Seed work orders
        print("\n📋 创建工单...")
        wo_count = 0
        for i, (t, template) in enumerate(zip(turbine_objs[:8], WORK_ORDER_TEMPLATES)):
            has_assignee = random.random() > 0.3
            assigned_user = random.choice(tech_objs) if has_assignee else None
            wo = WorkOrder(
                turbine_id=t.id,
                fault_id=fault_objs[i].id if i < len(fault_objs) else None,
                title=f"{t.name} {template['title']}",
                description=template["desc"],
                status=random.choice(["pending", "assigned", "in_progress", "completed"]),
                assignee=assigned_user.username if assigned_user else None,
                assignee_id=assigned_user.id if assigned_user else None,
                assignee_email=assigned_user.email if assigned_user else None,
                cost_estimate=template["cost"],
                cost_actual=template["cost"] * random.uniform(0.8, 1.2) if random.random() > 0.5 else None,
                due_date=now + timedelta(days=random.randint(1, 90)),
            )
            db.add(wo)
            wo_count += 1
        await db.commit()
        print(f"   ✅ 创建 {wo_count} 个工单")

        # 7. Create notification config
        print("\n🔔 配置通知...")
        config = NotificationConfig(
            user_id=admin.id,
            hi_threshold=70.0,
            email_enabled=True,
            email_address="admin@fengdiao.com",
            wechat_enabled=False,
        )
        db.add(config)
        await db.commit()
        print("   ✅ 通知配置完成")

        # 8. Create data sources
        print("\n📡 配置数据源...")
        data_sources = [
            ("scada", "SCADA运行数据", "connected"),
            ("vibration", "振动监测数据", "partial"),
            ("image", "叶片图像数据", "partial"),
            ("weather", "气象环境数据", "connected"),
        ]
        for src_type, name, status in data_sources:
            ds = DataSource(
                source_type=src_type,
                name=name,
                status=status,
                last_connected_at=now,
                last_data_at=now,
            )
            db.add(ds)
        await db.commit()
        print("   ✅ 数据源配置完成")

    # Seed knowledge base
    await seed_knowledge_base()

    print("\n" + "=" * 60)
    print("🎉 数据库初始化完成！")
    print("=" * 60)
    print(f"""
📊 数据统计:
   - 用户: {len(technicians) + 1} (1管理员 + {len(technicians)}技术员)
   - 风机: {len(turbine_objs)} 台
   - SCADA记录: {scada_count} 条
   - 故障记录: {fault_count} 个
   - RUL预测: {rul_count} 条
   - 工单: {wo_count} 个

🔑 登录账号:
   管理员: admin / admin123
   技术员: 张工 / tech123
""")


async def create_default_admin():
    """Create default admin user if no users exist."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        admin = User(
            username="admin",
            email="admin@fengdiao.com",
            password_hash=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.commit()

        # Create notification config
        config = NotificationConfig(
            user_id=admin.id,
            hi_threshold=70.0,
            email_enabled=True,
            email_address="admin@fengdiao.com",
            wechat_enabled=False,
        )
        db.add(config)
        await db.commit()

        print("   ✅ 创建默认管理员用户")
        print("   🔑 登录账号: admin / admin123")


async def seed_knowledge_base():
    """Seed fault knowledge base from JSON preset."""
    import json
    from pathlib import Path
    from app.models import FaultKnowledgeNode

    kb_path = Path(__file__).resolve().parents[1] / "app" / "data" / "fault-kb.json"
    if not kb_path.exists():
        print("   ⚠️  fault-kb.json 不存在, 跳过知识库初始化")
        return

    data = json.loads(kb_path.read_text(encoding="utf-8"))
    async with async_session() as db:
        count = 0
        for node_data in data.get("nodes", []):
            existing = await db.execute(
                select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == node_data["fault_type"])
            )
            if existing.scalar_one_or_none():
                continue
            node = FaultKnowledgeNode(
                fault_type=node_data["fault_type"],
                category=node_data["category"],
                icon=node_data.get("icon", "⚠️"),
                severity=node_data.get("severity", "medium"),
                symptoms=node_data.get("symptoms", []),
                root_causes=node_data.get("root_causes", []),
                solutions=node_data.get("solutions", []),
                related_faults=node_data.get("related_faults", []),
                spare_parts=node_data.get("spare_parts", []),
                cases=node_data.get("cases", []),
            )
            db.add(node)
            count += 1
        await db.commit()
        if count > 0:
            print(f"   ✅ 知识库: 导入 {count} 个故障节点")


if __name__ == "__main__":
    asyncio.run(seed())
