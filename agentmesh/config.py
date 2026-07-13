"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings, loaded from environment variables."""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_title: str = "AgentMesh"
    api_version: str = "0.1.0"

    # Database
    database_url: str = "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Worker / Redis Streams (Phase 5)
    execution_mode: str = "distributed"   # "distributed" (Redis Streams + workers) or "inprocess" (Phase 4 asyncio)
    worker_concurrency: int = 4           # max concurrent tasks per worker
    task_stream_key: str = "agentmesh:tasks"
    result_stream_prefix: str = "agentmesh:results:"
    dead_letter_stream_key: str = "agentmesh:dead-letter"
    consumer_group: str = "workers"
    task_stream_max_len: int = 10_000     # MAXLEN for the task stream
    worker_heartbeat_interval: int = 10   # seconds between health updates
    pending_claim_idle_ms: int = 60_000   # ms idle before XCLAIM reclaim

    # Gemini (Phase 6)
    gemini_api_key: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
