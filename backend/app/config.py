"""Application configuration module.

All sensitive values are loaded from environment variables.
See .env.example for required variables.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"


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
        env_file = (ROOT_DIR / ".env", BACKEND_DIR / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
