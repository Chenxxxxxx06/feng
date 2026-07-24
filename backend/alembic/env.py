"""Alembic environment config for async SQLAlchemy migrations."""
import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure backend/ is on sys.path for app imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models import *  # noqa: F401, F403 — register all models for autogenerate
from app.config import get_settings

config = context.config
settings = get_settings()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use the database URL from settings (supports offline DB auto-detection)
# Allow env override for migration-specific scenarios
_database_url = os.getenv("ALEMBIC_DATABASE_URL", settings.DATABASE_URL)


def _get_sync_url() -> str:
    """Derive a sync-compatible URL for Alembic's connection engine.

    Alembic still needs a synchronous driver for DDL execution even when
    the target metadata comes from async models.
    """
    url = _database_url
    # aiosqlite → sqlite (sync driver for migrations)
    if "aiosqlite" in url:
        url = url.replace("sqlite+aiosqlite:///", "sqlite:///")
    # asyncpg → postgresql (sync driver for migrations)
    elif "asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Execute migrations with the given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(
        _database_url,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
