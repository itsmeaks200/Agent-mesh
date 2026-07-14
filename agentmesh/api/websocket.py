"""WebSocket endpoint — live workflow/task state updates for the dashboard.

On connect, sends a full snapshot of the workflow's current state, then
subscribes to the Redis pub/sub channel the executor/coordinator publish
state-change events to (see ``agentmesh.events``) and forwards every event
to the client verbatim until it disconnects.
"""

from __future__ import annotations

import asyncio
import uuid

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.config import get_settings
from agentmesh.events import channel_name
from agentmesh.models.task import Task
from agentmesh.models.workflow import Workflow
from agentmesh.persistence import get_db
from agentmesh.persistence.repository import get_workflow, get_workflow_tasks

log = structlog.get_logger(__name__)

router = APIRouter(tags=["websocket"])


def _snapshot(workflow: Workflow, tasks: list[Task]) -> dict:
    spec_by_key = {s["id"]: s for s in (workflow.workflow_spec or {}).get("tasks", [])}
    return {
        "type": "snapshot",
        "workflow_id": str(workflow.id),
        "status": workflow.status.value,
        "request_text": workflow.request_text,
        "total_tasks": workflow.total_tasks,
        "completed_tasks": workflow.completed_tasks,
        "error_message": workflow.error_message,
        "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
        "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
        "tasks": [
            {
                "task_key": t.task_key,
                "tool_name": t.tool_name,
                "status": t.status.value,
                "retry_count": t.retry_count,
                "duration_ms": t.duration_ms,
                "error_message": t.error_message,
                "depends_on": spec_by_key.get(t.task_key, {}).get("depends_on", []),
                "params": t.params,
            }
            for t in tasks
        ],
    }


@router.websocket("/ws/workflows/{workflow_id}")
async def workflow_events_ws(
    websocket: WebSocket,
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()

    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        await websocket.send_json({"type": "error", "message": f"Workflow '{workflow_id}' not found."})
        await websocket.close(code=4404)
        return

    # Subscribe BEFORE reading the snapshot from the DB — otherwise a task can
    # transition (and publish) in the gap between the snapshot query and the
    # subscribe call, and that event would be silently dropped (Redis pub/sub
    # has no backlog/replay). Subscribing first means we might see a
    # redundant duplicate of an event already reflected in the snapshot,
    # which is harmless — the frontend applies updates idempotently.
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    channel = channel_name(workflow_id)
    await pubsub.subscribe(channel)

    tasks = await get_workflow_tasks(db, workflow_id)
    await websocket.send_json(_snapshot(workflow, tasks))

    async def forward_events() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await websocket.send_text(message["data"])

    async def watch_disconnect() -> None:
        while True:
            await websocket.receive_text()

    forward_task = asyncio.create_task(forward_events())
    disconnect_task = asyncio.create_task(watch_disconnect())

    try:
        done, pending = await asyncio.wait(
            {forward_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        disconnect_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis.close()
        log.debug("WebSocket closed", workflow_id=str(workflow_id))
