"""风调预顺 PHM系统 - FastAPI主入口

Provides REST API for wind turbine health management.
"""

import logging
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
import uvicorn

from app.config import get_settings, get_project_root

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting up PHM system...")
    from app.database import engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    logger.info("Database tables created/verified")
    await seed_knowledge_base_if_empty()
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


async def _ensure_sqlite_column(conn, table_name: str, column_name: str, definition: str):
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = {row[1] for row in result.fetchall()}
    if column_name not in columns:
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
        logger.info("Added %s.%s column", table_name, column_name)


async def seed_knowledge_base_if_empty():
    """Initialize the backend knowledge base from the bundled preset when empty."""
    from sqlalchemy import func, select
    from app.database import async_session
    from app.models import FaultKnowledgeNode

    kb_path = get_project_root() / "backend" / "src" / "data" / "fault-kb.json"
    if not kb_path.exists():
        logger.warning("Knowledge preset not found: %s", kb_path)
        return

    async with async_session() as db:
        result = await db.execute(select(func.count(FaultKnowledgeNode.id)))
        if (result.scalar() or 0) > 0:
            return

        data = json.loads(kb_path.read_text(encoding="utf-8"))
        for node_data in data.get("nodes", []):
            db.add(FaultKnowledgeNode(
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
            ))
        await db.commit()
        logger.info("Knowledge base initialized from preset: %d nodes", len(data.get("nodes", [])))


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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
