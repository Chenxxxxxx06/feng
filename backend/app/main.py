"""风调预顺 PHM系统 - FastAPI主入口

Provides REST API for wind turbine health management.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
import uvicorn

from app.config import get_settings, get_offline_database_path, is_sqlite_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting up PHM system...")

    # Check for offline database
    offline_db = get_offline_database_path()
    if offline_db and is_sqlite_url(settings.DATABASE_URL):
        logger.info(f"📦 Using offline dataset database: {offline_db}")

    from app.database import engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    logger.info("Database tables created/verified")
    yield
    # Shutdown
    logger.info("Shutting down PHM system...")


async def ensure_runtime_schema(conn):
    """Apply small additive schema fixes for existing local SQLite databases."""
    if settings.DATABASE_URL.startswith("sqlite"):
        await _ensure_sqlite_column(conn, "users", "api_provider", "VARCHAR(64)")
        await _ensure_sqlite_column(conn, "users", "api_base_url", "VARCHAR(512)")
        work_order_columns = {
            "priority": "VARCHAR(16) DEFAULT 'medium'",
            "fault_type": "VARCHAR(64)",
            "due_date": "DATETIME",
            "assignee_id": "INTEGER",
            "assignee_email": "VARCHAR(128)",
            "updated_at": "DATETIME",
            "cancelled_at": "DATETIME",
            "deleted_at": "DATETIME",
            "notification_sent_at": "DATETIME",
        }
        for column, definition in work_order_columns.items():
            await _ensure_sqlite_column(conn, "work_orders", column, definition)
        fault_columns = {
            "processing_status": "VARCHAR(16) DEFAULT 'pending'",
            "priority": "VARCHAR(16) DEFAULT 'medium'",
            "handler": "VARCHAR(64)",
            "discovered_at": "DATETIME",
            "processing_started_at": "DATETIME",
            "closed_at": "DATETIME",
            "failed_at": "DATETIME",
            "last_action_at": "DATETIME",
            "work_order_id": "INTEGER",
            "work_order_title": "VARCHAR(128)",
            "maintenance_cost_estimate": "FLOAT",
            "maintenance_cost_actual": "FLOAT",
            "status_note": "TEXT",
        }
        for column, definition in fault_columns.items():
            await _ensure_sqlite_column(conn, "faults", column, definition)
    else:
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_provider VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_base_url VARCHAR(512)"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'medium'"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS fault_type VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS due_date TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS assignee_id INTEGER"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS assignee_email VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS processing_status VARCHAR(16) DEFAULT 'pending'"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'medium'"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS handler VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS discovered_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS failed_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS work_order_id INTEGER"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS work_order_title VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS maintenance_cost_estimate FLOAT"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS maintenance_cost_actual FLOAT"))
        await conn.execute(text("ALTER TABLE faults ADD COLUMN IF NOT EXISTS status_note TEXT"))


async def _ensure_sqlite_column(conn, table_name: str, column_name: str, definition: str):
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = {row[1] for row in result.fetchall()}
    if column_name not in columns:
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
        logger.info("Added %s.%s column", table_name, column_name)


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")

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
    workorders, settings as settings_api, ai, personnel, knowledge, agent
)

app.include_router(auth.router, prefix="/api/auth", tags=["认证管理"])
app.include_router(turbines.router, prefix="/api/turbines", tags=["风机管理"])
app.include_router(diagnosis.router, prefix="/api/diagnosis", tags=["故障诊断"])
app.include_router(prediction.router, prefix="/api/prediction", tags=["预测决策"])
app.include_router(workorders.router, prefix="/api/workorders", tags=["工单管理"])
app.include_router(knowledge.router, prefix="/api", tags=["故障百科"])
app.include_router(agent.router, prefix="/api", tags=["AI诊断"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["系统设置"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI服务"])
app.include_router(personnel.router, prefix="/api/personnel", tags=["人员管理"])


# --- Frontend SPA serving (production) ---
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend_assets")

    @app.get("/", include_in_schema=False)
    async def frontend_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_spa_fallback(full_path: str):
        requested_file = (FRONTEND_DIST / full_path).resolve()
        frontend_root = FRONTEND_DIST.resolve()
        if requested_file.is_relative_to(frontend_root) and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
