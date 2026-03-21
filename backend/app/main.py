from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.core.logging import logger
from app.models.database import Base
from app.db.session import engine
from app.api.routes import health, repos, runs, analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DynamicAnalyser API")
    Base.metadata.create_all(bind=engine)
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
