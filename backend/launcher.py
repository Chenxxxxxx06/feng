"""风调预顺 PHM 便携版启动器。"""
import os
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
for d in (BACKEND, ROOT):
    if d not in sys.path:
        sys.path.insert(0, d)


def upgrade_database() -> None:
    """Apply every checked-in schema migration before serving requests."""
    from alembic import command
    from alembic.config import Config

    config = Config(os.path.join(BACKEND, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    print("[startup] 正在检查数据库版本并执行迁移...")
    command.upgrade(config, "head")
    print("[startup] 数据库已升级到最新版本。")


def main() -> None:
    import uvicorn

    upgrade_database()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
