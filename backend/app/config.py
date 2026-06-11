"""Application configuration module.

All sensitive values are loaded from environment variables.
See .env.example for required variables.
"""

import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "风调预顺 - PHM预测性运维系统"
    DEBUG: bool = False

    # Security - MUST be set in production via env var
    # Default is FIXED for development (not random — avoids breaking all tokens on restart)
    SECRET_KEY: str = "fengdiao-phm-dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./fengdiao_phm.db"
    
    # PostgreSQL specific settings (used when DATABASE_URL starts with postgresql)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Email (optional)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ERA5 Wind Data (optional)
    ERA5_CDS_API_KEY: str = ""
    ERA5_CDS_API_URL: str = "https://cds.climate.copernicus.eu/api"

    # Map (optional)
    MAPBOX_TOKEN: str = ""

    # AI Models (optional)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    DASHSCOPE_API_KEY: str = ""

    # Notifications (optional)
    WEIXIN_WEBHOOK_URL: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def get_project_root() -> Path:
    """Get the project root directory (parent of backend folder)."""
    # app/config.py -> app/ -> backend/ -> project_root/
    return Path(__file__).resolve().parent.parent.parent


def get_offline_dataset_path() -> Path | None:
    """
    Get the path to offline dataset folder.
    
    The offline dataset folder should be placed at the same level as backend/ and frontend/.
    Expected name: fengdiao_dataset_db_handoff_20260611
    
    Returns:
        Path to offline dataset folder if exists, None otherwise.
    """
    project_root = get_project_root()
    dataset_folder = project_root / "fengdiao_dataset_db_handoff_20260611"
    
    if dataset_folder.exists() and dataset_folder.is_dir():
        return dataset_folder
    return None


def get_offline_database_path() -> Path | None:
    """
    Get the path to the SQLite database in the offline dataset folder.
    
    Returns:
        Path to the SQLite database file if exists, None otherwise.
    """
    dataset_path = get_offline_dataset_path()
    if dataset_path:
        db_path = dataset_path / "database" / "fengdiao_phm.db"
        if db_path.exists():
            return db_path
    return None


def is_sqlite_url(url: str) -> bool:
    """Check if the database URL is for SQLite."""
    return url.startswith("sqlite")


def is_postgresql_url(url: str) -> bool:
    """Check if the database URL is for PostgreSQL."""
    return url.startswith("postgresql")