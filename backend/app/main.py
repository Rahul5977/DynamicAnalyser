from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from app.config import get_settings
from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.core.logging import logger
from app.models.database import Base
from app.db.session import engine
from app.api.routes import health, repos, runs, analysis, ai_analysis, dashboard, chat, benchmarks, static_analysis
from app.api.routes import app_logs


def _ensure_sqlite_analysis_columns():
    """Backfill new Analysis columns for existing SQLite databases.

    SQLAlchemy's create_all() creates missing tables but does not ALTER
    existing ones. This keeps older local DBs compatible after model updates.
    """
    if engine.dialect.name != "sqlite":
        return

    columns_to_add = {
        "debt_score": "INTEGER",
        "llm_prompt_tokens": "INTEGER",
        "llm_completion_tokens": "INTEGER",
    }

    with engine.begin() as conn:
        inspector = inspect(conn)
        table_names = inspector.get_table_names()
        if "analyses" not in table_names:
            return

        existing = {col["name"] for col in inspector.get_columns("analyses")}
        for col_name, col_type in columns_to_add.items():
            if col_name in existing:
                continue
            logger.info("Applying SQLite schema patch: analyses.%s", col_name)
            conn.execute(text(f"ALTER TABLE analyses ADD COLUMN {col_name} {col_type}"))


def _ensure_static_analysis_table():
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        inspector = inspect(conn)
        if "static_analysis_jobs" in inspector.get_table_names():
            return
        conn.execute(
            text(
                """
                CREATE TABLE static_analysis_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id VARCHAR(64) UNIQUE NOT NULL,
                    repo_url VARCHAR(1024) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    created_at DATETIME NOT NULL,
                    completed_at DATETIME NULL,
                    error_message TEXT NULL,
                    report_json TEXT NULL,
                    health_score INTEGER NULL,
                    finding_count INTEGER NULL,
                    primary_language VARCHAR(64) NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_static_analysis_jobs_job_id ON static_analysis_jobs(job_id)"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DynamicAnalyser API")
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_analysis_columns()
    _ensure_static_analysis_table()
    logger.info("Database tables created")
    yield
    logger.info("Shutting down DynamicAnalyser API")


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DynamicAnalyserError)
async def domain_exception_handler(request: Request, exc: DynamicAnalyserError):
    http_exc = to_http_exception(exc)
    return JSONResponse(
        status_code=http_exc.status_code,
        content=http_exc.detail,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": None},
    )


# Mount routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(repos.router, prefix="/api", tags=["repositories"])
app.include_router(runs.router, prefix="/api", tags=["runs"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(ai_analysis.router, prefix="/api", tags=["ai-analysis"])
app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(app_logs.router, prefix="/api", tags=["app-logs"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(benchmarks.router, prefix="/api", tags=["benchmarks"])
app.include_router(static_analysis.router, prefix="/api", tags=["static-analysis"])
