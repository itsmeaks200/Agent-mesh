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
