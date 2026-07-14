"""Startup recovery — reconcile workflows left ``RUNNING`` by a crashed process.

Both the in-process executor and the distributed coordinator drive a
workflow to completion as a single long-lived background asyncio task with
no external checkpoint of their own. If the API process dies mid-workflow,
the only durable record left behind is the ``RUNNING`` row in Postgres.
On the next startup we reconcile that state:

- **Distributed mode:** hand the workflow back to a fresh
  ``WorkflowCoordinator``. Per-task progress is reconstructed from
  ``Task.status`` / ``Task.result``, and any task still in flight in Redis
  still delivers its result to the shared, per-workflow result stream once
  the new coordinator subscribes — nothing is re-dispatched needlessly.
- **In-process mode:** there's no external queue holding in-flight task
  state, so a crashed run can't be safely reattached — it's marked FAILED
  instead, so it doesn't sit as "RUNNING" forever.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select

from agentmesh.config import get_settings
from agentmesh.models.workflow import Workflow, WorkflowStatus
from agentmesh.persistence import async_session_factory
from agentmesh.persistence.repository import update_workflow_status

log = structlog.get_logger(__name__)


async def resume_incomplete_workflows() -> None:
    """Find workflows stuck ``RUNNING`` from a previous process and reconcile them."""
    settings = get_settings()

    async with async_session_factory() as db:
        result = await db.execute(
            select(Workflow.id).where(Workflow.status == WorkflowStatus.RUNNING)
        )
        stuck_ids = [row[0] for row in result.all()]

    if not stuck_ids:
        return

    if settings.execution_mode == "distributed":
        log.info(
            "Resuming workflows interrupted by restart",
            count=len(stuck_ids), workflow_ids=[str(i) for i in stuck_ids],
        )
        for workflow_id in stuck_ids:
            asyncio.create_task(_resume_one(workflow_id), name=f"resume:{workflow_id}")
    else:
        log.warning(
            "Failing out workflows interrupted by restart (in-process runs cannot be resumed)",
            count=len(stuck_ids), workflow_ids=[str(i) for i in stuck_ids],
        )
        async with async_session_factory() as db:
            for workflow_id in stuck_ids:
                await update_workflow_status(
                    db, workflow_id, WorkflowStatus.FAILED,
                    error_message="Interrupted by server restart.",
                )
            await db.commit()


async def _resume_one(workflow_id: uuid.UUID) -> None:
    import redis.asyncio as aioredis

    from agentmesh.scheduler.coordinator import WorkflowCoordinator

    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with async_session_factory() as db:
            coordinator = WorkflowCoordinator(redis_client)
            await coordinator.resume(workflow_id, db)
    finally:
        await redis_client.close()
