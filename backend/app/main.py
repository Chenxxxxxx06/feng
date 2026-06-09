"""风调预顺 PHM系统 - FastAPI主入口

Provides REST API for wind turbine health management.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting up PHM system...")
    from app.database import engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")
    yield
    # Shutdown
    logger.info("Shutting down PHM system...")


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS configuration
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler with logging."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "message": str(exc)}
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "2.0.0",
    }


# --- Router registration ---
from app.api import (
    auth, turbines, diagnosis, prediction,
    workorders, settings as settings_api, ai, personnel
)

app.include_router(auth.router, prefix="/api/auth", tags=["认证管理"])
app.include_router(turbines.router, prefix="/api/turbines", tags=["风机管理"])
app.include_router(diagnosis.router, prefix="/api/diagnosis", tags=["故障诊断"])
app.include_router(prediction.router, prefix="/api/prediction", tags=["预测决策"])
app.include_router(workorders.router, prefix="/api/workorders", tags=["工单管理"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["系统设置"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI服务"])
app.include_router(personnel.router, prefix="/api/personnel", tags=["人员管理"])


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
