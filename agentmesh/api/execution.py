"""Execution endpoints — start workflow execution and query live status."""

from __future__ import annotations

import uuid
from typing import Annotated

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.models.workflow import WorkflowStatus
from agentmesh.persistence import get_db
from agentmesh.persistence.repository import get_workflow, get_workflow_tasks
from agentmesh.scheduler.executor import WorkflowExecutor

router = APIRouter(tags=["execution"])


@router.post(
    "/workflows/{workflow_id}/execute",
    status_code=202,
    summary="Execute a workflow",
    description=(
        "Start executing a workflow. Returns immediately (202 Accepted). "
        "Use GET /workflows/{id}/status to track progress."
    ),
)
async def execute_workflow_endpoint(
    workflow_id: Annotated[uuid.UUID, Path(description="Workflow ID")],
    db: AsyncSession = Depends(get_db),
):
    """Queue a workflow for execution."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")

    if workflow.status not in (WorkflowStatus.CREATED,):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workflow is in '{workflow.status.value}' state and cannot be executed. "
                "Only CREATED workflows can be executed."
            ),
        )

    # Launch execution in the background — non-blocking
    # A new DB session is passed to the executor so it can operate independently
    asyncio.create_task(
        _run_in_background(workflow_id),
        name=f"execute:{workflow_id}",
    )

    return {
        "workflow_id": str(workflow_id),
        "status": "SCHEDULED",
        "message": "Workflow execution started. Poll GET /workflows/{id}/status for progress.",
    }


@router.get(
    "/workflows/{workflow_id}/status",
    summary="Get live workflow execution status",
    description="Return the current status of a workflow and all its tasks.",
)
async def workflow_status_endpoint(
    workflow_id: Annotated[uuid.UUID, Path(description="Workflow ID")],
    db: AsyncSession = Depends(get_db),
):
    """Return real-time task statuses for a workflow."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")

    tasks = await get_workflow_tasks(db, workflow_id)

    return {
        "workflow_id": str(workflow_id),
        "status": workflow.status.value,
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
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
    }


async def _run_in_background(workflow_id: uuid.UUID) -> None:
    """Create a fresh DB session and run the executor.

    This runs outside the request lifecycle — it gets its own session.
    """
    from agentmesh.persistence import async_session_factory

    async with async_session_factory() as db:
        executor = WorkflowExecutor()
        await executor.execute(workflow_id, db)
