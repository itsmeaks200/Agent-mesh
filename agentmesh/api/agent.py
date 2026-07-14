"""Agent endpoint — natural language request → planned workflow → execution."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.api.execution import _run_in_background
from agentmesh.persistence import get_db
from agentmesh.persistence.repository import create_workflow
from agentmesh.planner.planner import PlannerError, WorkflowPlanner
from agentmesh.schemas.workflow import AgentRunRequest

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/run",
    status_code=202,
    summary="Plan and execute a workflow from natural language",
    description=(
        "Convert a natural language request into a validated workflow using the LLM "
        "planner, persist it, and start executing it immediately. Returns right away "
        "(202 Accepted) — poll GET /workflows/{id}/status for progress."
    ),
    responses={422: {"description": "The planner could not produce a valid workflow."}},
)
async def run_agent_endpoint(
    request: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Plan a workflow from natural language, persist it, and execute it."""
    planner = WorkflowPlanner()

    try:
        task_specs = await planner.plan(request.request)
    except PlannerError as exc:
        log.warning("Planning failed", request_text=request.request, error=str(exc))
        raise HTTPException(
            status_code=422,
            detail={"code": "PLANNING_FAILED", "message": str(exc)},
        ) from exc

    workflow = await create_workflow(db, task_specs, request_text=request.request)
    await db.commit()

    log.info(
        "Workflow planned from natural language",
        workflow_id=str(workflow.id), task_count=len(task_specs),
    )

    # Launch execution in the background — non-blocking, same path as
    # POST /workflows/{id}/execute.
    asyncio.create_task(
        _run_in_background(workflow.id),
        name=f"agent-execute:{workflow.id}",
    )

    return {
        "workflow_id": str(workflow.id),
        "status": "SCHEDULED",
        "tasks_planned": len(task_specs),
        "message": "Workflow planned and execution started. Poll GET /workflows/{id}/status for progress.",
    }
