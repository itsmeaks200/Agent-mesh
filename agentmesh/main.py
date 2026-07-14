"""AgentMesh — FastAPI application entrypoint."""

import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentmesh.api.router import api_router
from agentmesh.config import get_settings
from agentmesh.middleware.auth import APIKeyMiddleware
from agentmesh.middleware.correlation import CorrelationIdMiddleware
from agentmesh.observability.logger import configure_logging
from agentmesh.persistence import engine
from agentmesh.scheduler.recovery import resume_incomplete_workflows

configure_logging()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown hooks."""
    settings = get_settings()

    # Startup — verify connections
    # Test Redis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
        app.state.redis = redis_client
    except Exception as e:
        log.warning("Redis connection failed", error=str(e))
        app.state.redis = None

    db_display = (
        settings.database_url.split("@")[-1] if "@" in settings.database_url else "configured"
    )
    log.info(
        "AgentMesh API started",
        database=db_display,
        redis=settings.redis_url,
        execution_mode=settings.execution_mode,
    )

    # Reconcile any workflows left RUNNING by a previous process that crashed
    # or was restarted mid-execution.
    try:
        await resume_incomplete_workflows()
    except Exception as e:
        log.exception("Failed to reconcile interrupted workflows on startup", error=str(e))

    yield

    # Shutdown — clean up
    if app.state.redis:
        await app.state.redis.close()
    await engine.dispose()
    log.info("AgentMesh API stopped")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "AgentMesh — Distributed AI Workflow Execution Engine. "
            "Converts natural language requests into executable workflow graphs "
            "and reliably executes them across asynchronous workers."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow all during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Every request gets a correlation ID bound to its log lines before
    # auth runs, so rejected requests are traceable too.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(APIKeyMiddleware)

    # Mount API routes
    app.include_router(api_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Keep the default FastAPI `{"detail": ...}` shape (existing clients and
        # tests depend on it) and just add a correlation ID alongside it.
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": exc.errors(),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        log.exception(
            "Unhandled exception", path=request.url.path, request_id=request_id, error=str(exc)
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error.", "request_id": request_id},
        )

    # Health check (outside versioned API)
    @app.get("/health", tags=["system"])
    async def health_check():
        """Basic health check endpoint."""
        redis_ok = False
        if hasattr(app.state, "redis") and app.state.redis:
            try:
                await app.state.redis.ping()
                redis_ok = True
            except Exception:
                pass

        return {
            "status": "healthy",
            "version": settings.api_version,
            "redis": "connected" if redis_ok else "disconnected",
        }

    return app


# Module-level app instance for uvicorn
app = create_app()
