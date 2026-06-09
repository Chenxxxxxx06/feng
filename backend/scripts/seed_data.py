"""Initialize system metadata without generating business data.

This script intentionally does not create turbines, SCADA records, faults,
RUL predictions, work orders, vibration samples, or blade images. Business data
must be imported from real datasets or measured project files.

Usage:
    cd backend
    python -m scripts.seed_data
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from app.core.security import hash_password
from app.database import Base, async_session, engine
from app.models import DataSource, NotificationConfig, User


SYSTEM_SOURCES = [
    ("scada", "SCADA运行数据", "disconnected"),
    ("vibration", "振动监测数据", "disconnected"),
    ("image", "叶片图像数据", "disconnected"),
    ("weather", "气象环境数据", "disconnected"),
]


async def seed():
    """Create required tables, admin user, and empty data-source metadata."""
    print("=" * 60)
    print("风调预顺 PHM系统 - 系统元数据初始化")
    print("=" * 60)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("数据表已创建或确认存在")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                username="admin",
                email="admin@fengdiao.com",
                password_hash=hash_password("admin123"),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            await db.flush()
            print("已创建管理员账号：admin / admin123")
        else:
            print("管理员账号已存在，未覆盖")

        result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == admin.id))
        if not result.scalar_one_or_none():
            db.add(NotificationConfig(
                user_id=admin.id,
                hi_threshold=70.0,
                email_enabled=False,
                email_address="admin@fengdiao.com",
                wechat_enabled=False,
            ))
            print("已创建默认通知阈值")

        for source_type, name, status in SYSTEM_SOURCES:
            result = await db.execute(select(DataSource).where(DataSource.source_type == source_type))
            source = result.scalar_one_or_none()
            if source:
                source.name = name
                source.status = status
            else:
                db.add(DataSource(source_type=source_type, name=name, status=status))

        await db.commit()

    print("数据源元信息已初始化为未连接状态")
    print("业务数据未生成。请使用 scripts.import_real_datasets 导入真实数据集。")


if __name__ == "__main__":
    asyncio.run(seed())
