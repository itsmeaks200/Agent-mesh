"""Redis pub/sub event bus for real-time workflow/task state broadcasts.

Publishers (WorkflowExecutor, WorkflowCoordinator) fire a JSON event on the
channel returned by ``channel_name`` every time a task or workflow changes
state. The WebSocket endpoint (``agentmesh.api.websocket``) subscribes to
that channel per-connection and forwards events verbatim to the client.

Publishing is best-effort: a broken Redis connection must never fail a
workflow run, so every publish swallows and logs its own exceptions.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

_global_client: Redis | None = None

# Publishing must never stall core orchestration (dispatch/retry/completion).
# A slow or wedged broker degrades to "no live updates" rather than a hang.
_PUBLISH_TIMEOUT_SECONDS = 2.0


def channel_name(workflow_id: uuid.UUID | str) -> str:
    return f"agentmesh:events:{workflow_id}"


async def publish_event(redis: Redis, workflow_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    """Best-effort publish of a workflow/task state-change event."""
    try:
        await asyncio.wait_for(
            redis.publish(channel_name(workflow_id), json.dumps(event)),
            timeout=_PUBLISH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        log.warning("Failed to publish workflow event", workflow_id=str(workflow_id), error=str(exc))


def publish_event_nowait(redis: Redis, workflow_id: uuid.UUID | str, event: dict[str, Any]) -> asyncio.Task:
    """Schedule a publish without awaiting it inline.

    Callers on a hot orchestration path (dispatch/retry/completion loops that
    also issue blocking stream reads on the same Redis client) must not await
    the publish in-line — interleaving a PUBLISH with an in-flight blocking
    XREADGROUP on one shared connection can wedge certain Redis client
    implementations. Firing the publish as a detached task keeps the
    broadcast best-effort in truth, not just in name.
    """
    return asyncio.create_task(publish_event(redis, workflow_id, event))


def get_global_redis() -> Redis:
    """Lazily create a shared Redis client for callers without one on hand.

    Used by the in-process ``WorkflowExecutor``, which otherwise has no
    Redis dependency at all.
    """
    global _global_client
    if _global_client is None:
        import redis.asyncio as aioredis

        from agentmesh.config import get_settings

        _global_client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _global_client
