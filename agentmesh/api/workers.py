"""Worker fleet status endpoint."""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import APIRouter

from agentmesh.config import get_settings
from agentmesh.worker.health import WorkerHealth

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get(
    "",
    summary="List active workers",
    description=(
        "Return live status for every worker process currently reporting "
        "heartbeats to Redis. Workers that stop heartbeating disappear from "
        "this list automatically (their Redis key expires)."
    ),
)
async def list_workers_endpoint():
    """Return the current worker fleet status."""
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        workers = await WorkerHealth.list_workers(redis_client)
    finally:
        await redis_client.close()

    return {
        "workers": workers,
        "total": len(workers),
    }
