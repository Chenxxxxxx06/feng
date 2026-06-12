"""Database configuration module.

Supports both SQLite (development) and PostgreSQL (production).
Configure DATABASE_URL in .env file.

When offline dataset folder exists with a pre-populated SQLite database,
the application will automatically use that database for development.
"""

import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings, is_sqlite_url, is_postgresql_url, get_offline_database_path

logger = logging.getLogger(__name__)
settings = get_settings()

# Check for offline database
offline_db_path = get_offline_database_path()
if offline_db_path and is_sqlite_url(settings.DATABASE_URL):
    # Use offline database if available and using SQLite
    database_url = f"sqlite+aiosqlite:///{offline_db_path}"
    logger.info(f"Using offline dataset database: {offline_db_path}")
else:
    database_url = settings.DATABASE_URL

# Determine database type from URL
is_sqlite = is_sqlite_url(database_url)
is_postgresql = is_postgresql_url(database_url)

# Engine configuration
engine_kwargs = {
    "echo": settings.DEBUG,
}

if is_postgresql:
    # PostgreSQL-specific settings
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    })

engine = create_async_engine(database_url, **engine_kwargs)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session.

    Usage:
        @app.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all database tables defined in models.

    Should be called once during application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def drop_tables() -> None:
    """Drop all database tables.

    Use with caution - this will delete all data!
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("Database tables dropped successfully")
