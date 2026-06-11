"""Database management tool for PHM system.

Provides commands for database initialization, migration, and maintenance.

Usage:
    python -m scripts.manage_db <command>
    
Commands:
    init            - Create tables and initialize with demo data
    create-tables   - Create all database tables
    drop-tables     - Drop all database tables (destructive!)
    check-offline   - Check if offline dataset exists
    info            - Show database connection info
    help            - Show this help message

Examples:
    python -m scripts.manage_db init
    python -m scripts.manage_db create-tables
    python -m scripts.manage_db check-offline
"""

import asyncio
import sys
import os
from pathlib import Path

# Load .env file before importing database modules
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"🔧 Loaded .env from: {env_path}")
else:
    print(f"⚠️ .env file not found at: {env_path}")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import create_tables, drop_tables, engine
from app.config import get_settings, get_offline_database_path, is_sqlite_url, is_postgresql_url
from scripts.seed_data import seed


async def cmd_create_tables():
    """Create all database tables."""
    print("🗄️  Creating database tables...")
    await create_tables()
    print("✅ Tables created successfully")


async def cmd_drop_tables():
    """Drop all database tables."""
    confirm = input("⚠️  WARNING: This will delete ALL data! Are you sure? (y/N): ")
    if confirm.lower() != 'y':
        print("❌ Operation cancelled")
        return
    
    print("🗑️  Dropping database tables...")
    await drop_tables()
    print("✅ Tables dropped successfully")


async def cmd_init():
    """Initialize database with demo data."""
    await seed()


async def cmd_check_offline():
    """Check if offline dataset exists."""
    offline_db = get_offline_database_path()
    if offline_db:
        print(f"✅ 离线数据集存在: {offline_db}")
    else:
        print("❌ 离线数据集不存在")
        print("   请将 fengdiao_dataset_db_handoff_20260611 文件夹放置于项目根目录")


async def cmd_info():
    """Show database connection info."""
    settings = get_settings()
    url = settings.DATABASE_URL
    
    print("📊 数据库连接信息:")
    print(f"  URL: {url}")
    
    if is_sqlite_url(url):
        print("  类型: SQLite")
        offline_db = get_offline_database_path()
        if offline_db:
            print(f"  离线数据库: ✅ {offline_db}")
        else:
            print(f"  离线数据库: ❌ 未检测到")
    elif is_postgresql_url(url):
        print("  类型: PostgreSQL")
        print(f"  连接池大小: {settings.DB_POOL_SIZE}")
        print(f"  最大溢出: {settings.DB_MAX_OVERFLOW}")
        print(f"  连接回收: {settings.DB_POOL_RECYCLE}s")
    
    print(f"\n  PostgreSQL驱动: asyncpg")
    print(f"  SQLite驱动: aiosqlite")


def show_help():
    """Show help message."""
    print(__doc__)


async def main():
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    commands = {
        'init': cmd_init,
        'create-tables': cmd_create_tables,
        'drop-tables': cmd_drop_tables,
        'check-offline': cmd_check_offline,
        'info': cmd_info,
        'help': show_help,
    }
    
    if command not in commands:
        print(f"❌ Unknown command: {command}")
        show_help()
        sys.exit(1)
    
    if command == 'help':
        show_help()
        return
    
    try:
        await commands[command]()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())