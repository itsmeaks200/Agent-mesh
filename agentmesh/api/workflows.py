"""Workflow CRUD API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.compiler import CompilationError, MultipleCompilationErrors, WorkflowCompiler
from agentmesh.persistence import get_db
from agentmesh.persistence.repository import (
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
)
from agentmesh.schemas.workflow import (
    CompileErrorDetail,
    CompileResponse,
    ErrorResponse,
    TaskResponse,
    WorkflowCreateRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _task_to_response(task) -> TaskResponse:
    """Convert a Task ORM instance to a TaskResponse schema."""
    return TaskResponse(
        id=task.id,
        task_key=task.task_key,
        tool_name=task.tool_name,
        params=task.params,
        status=task.status.value,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        timeout_seconds=task.timeout_seconds,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        duration_ms=task.duration_ms,
        error_message=task.error_message,
        worker_id=task.worker_id,
        depends_on_keys=[dep.task_key for dep in task.depends_on] if task.depends_on else [],
        result=task.result,
    )


def _workflow_to_response(workflow) -> WorkflowResponse:
    """Convert a Workflow ORM instance to a WorkflowResponse schema."""
    return WorkflowResponse(
        id=workflow.id,
        status=workflow.status.value,
        request_text=workflow.request_text,
        total_tasks=workflow.total_tasks,
        completed_tasks=workflow.completed_tasks,
        error_message=workflow.error_message,
        created_at=workflow.created_at,
        started_at=workflow.started_at,
        completed_at=workflow.completed_at,
        duration_ms=workflow.duration_ms,
        tasks=[_task_to_response(t) for t in workflow.tasks],
    )


@router.post(
    "/compile",
    response_model=CompileResponse,
    summary="Compile and validate a workflow",
    description=(
        "Validate a workflow specification and return the execution order "
        "without persisting to the database. Use this to check for cycles, "
        "missing dependencies, and other errors before creating a workflow."
    ),
)
async def compile_workflow_endpoint(
    request: WorkflowCreateRequest,
):
    """Compile a workflow spec into a DAG and return the validation result."""
    compiler = WorkflowCompiler()
    try:
        graph = compiler.compile(request.tasks)
        execution_order = graph.get_execution_order()
        return CompileResponse(
            valid=True,
            execution_order=execution_order,
            topological_sort=graph.topological_sort(),
            total_tasks=graph.node_count,
            total_levels=len(execution_order),
            graph=graph.to_dict(),
        )
    except MultipleCompilationErrors as e:
        return CompileResponse(
            valid=False,
            errors=[CompileErrorDetail(**err) for err in e.details["errors"]],
        )
    except CompilationError as e:
        return CompileResponse(
            valid=False,
            errors=[CompileErrorDetail(code=e.code, message=e.message, details=e.details)],
        )


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=201,
    summary="Create a workflow",
    description="Create a new workflow from an explicit task specification.",
)
async def create_workflow_endpoint(
    request: WorkflowCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new workflow with the specified tasks and dependencies."""
    # Validate that all dependency references exist within the spec
    task_ids = {t.id for t in request.tasks}
    for task in request.tasks:
        for dep in task.depends_on:
            if dep not in task_ids:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_DEPENDENCY",
                        "message": f"Task '{task.id}' depends on '{dep}' which does not exist",
                    },
                )

    # Check for duplicate task IDs
    if len(task_ids) != len(request.tasks):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DUPLICATE_TASK_ID",
                "message": "Task IDs must be unique within a workflow",
            },
        )

    workflow = await create_workflow(db, request.tasks)
    return _workflow_to_response(workflow)


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List workflows",
    description="List all workflows with optional status filter and pagination.",
)
async def list_workflows_endpoint(
    status: str | None = Query(None, description="Filter by workflow status"),
    limit: int = Query(20, ge=1, le=100, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
):
    """List workflows with pagination."""
    workflows, total = await list_workflows(db, status=status, limit=limit, offset=offset)
    return WorkflowListResponse(
        workflows=[
            WorkflowSummaryResponse(
                id=w.id,
                status=w.status.value,
                request_text=w.request_text,
                total_tasks=w.total_tasks,
                completed_tasks=w.completed_tasks,
                created_at=w.created_at,
                started_at=w.started_at,
                completed_at=w.completed_at,
                duration_ms=w.duration_ms,
            )
            for w in workflows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Get workflow details",
    description="Get a workflow by ID with all tasks and their results.",
    responses={404: {"model": ErrorResponse}},
)
async def get_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single workflow with full task details."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WORKFLOW_NOT_FOUND",
                "message": f"Workflow with ID '{workflow_id}' not found",
            },
        )
    return _workflow_to_response(workflow)


@router.delete(
    "/{workflow_id}",
    status_code=204,
    summary="Delete a workflow",
    description="Delete a workflow and all its tasks.",
    responses={404: {"model": ErrorResponse}},
)
async def delete_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a workflow by ID."""
    deleted = await delete_workflow(db, workflow_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WORKFLOW_NOT_FOUND",
                "message": f"Workflow with ID '{workflow_id}' not found",
            },
        )
