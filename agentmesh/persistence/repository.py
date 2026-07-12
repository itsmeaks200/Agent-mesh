"""Database operations for workflows and tasks."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.models.task import Task, TaskResult, task_dependencies
from agentmesh.models.workflow import Workflow, WorkflowStatus
from agentmesh.schemas.workflow import TaskSpec


async def create_workflow(
    db: AsyncSession,
    task_specs: list[TaskSpec],
    request_text: str | None = None,
    workflow_spec: dict | None = None,
) -> Workflow:
    """Create a workflow with tasks and wire up dependencies.

    Steps:
    1. Create the Workflow row.
    2. Create Task rows for each task spec.
    3. Insert dependency edges into the junction table.
    """
    workflow = Workflow(
        id=uuid.uuid4(),
        status=WorkflowStatus.CREATED,
        request_text=request_text,
        workflow_spec=workflow_spec or {"tasks": [t.model_dump() for t in task_specs]},
        total_tasks=len(task_specs),
    )
    db.add(workflow)
    await db.flush()  # Ensure workflow.id is available

    # Create tasks, keyed by task_key for dependency wiring
    task_map: dict[str, Task] = {}
    for spec in task_specs:
        task = Task(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            task_key=spec.id,
            tool_name=spec.tool,
            params=spec.params,
        )
        db.add(task)
        task_map[spec.id] = task

    await db.flush()  # Ensure all task IDs are available

    # Wire up dependencies
    for spec in task_specs:
        if spec.depends_on:
            task = task_map[spec.id]
            for dep_key in spec.depends_on:
                dep_task = task_map.get(dep_key)
                if dep_task is not None:
                    stmt = task_dependencies.insert().values(
                        task_id=task.id,
                        depends_on_task_id=dep_task.id,
                    )
                    await db.execute(stmt)

    await db.flush()
    return workflow


async def get_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
    """Get a workflow by ID with tasks and results eagerly loaded."""
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_workflows(
    db: AsyncSession,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Workflow], int]:
    """List workflows with optional status filter, returning (workflows, total_count)."""
    # Base query
    base = select(Workflow)
    count_q = select(func.count(Workflow.id))

    if status:
        base = base.where(Workflow.status == status)
        count_q = count_q.where(Workflow.status == status)

    # Total count
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    # Paginated results
    stmt = base.order_by(Workflow.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    workflows = list(result.scalars().all())

    return workflows, total


async def update_workflow_status(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    status: WorkflowStatus,
    error_message: str | None = None,
) -> Workflow | None:
    """Update workflow status and relevant timestamps."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        return None

    workflow.status = status

    now = datetime.now(timezone.utc)
    if status == WorkflowStatus.RUNNING and workflow.started_at is None:
        workflow.started_at = now
    elif status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        workflow.completed_at = now

    if error_message:
        workflow.error_message = error_message

    await db.flush()
    return workflow


async def delete_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> bool:
    """Delete a workflow and all its tasks (cascade)."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        return False
    await db.delete(workflow)
    await db.flush()
    return True
