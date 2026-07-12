"""AgentMesh — FastAPI application entrypoint."""

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentmesh.api.router import api_router
from agentmesh.config import get_settings
from agentmesh.persistence import engine


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
        print(f"⚠️  Redis connection failed: {e}")
        app.state.redis = None

    print("✅ AgentMesh API started")
    print(f"   Database: {settings.database_url.split('@')[-1] if '@' in settings.database_url else 'configured'}")
    print(f"   Redis: {settings.redis_url}")

    yield

    # Shutdown — clean up
    if app.state.redis:
        await app.state.redis.close()
    await engine.dispose()
    print("🛑 AgentMesh API stopped")


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

    # Mount API routes
    app.include_router(api_router)

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
