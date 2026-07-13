"""WorkflowExecutor — orchestrates the full compile → execute → persist pipeline.

The executor owns the database session and drives state transitions.
It delegates concurrent task dispatch to WorkflowScheduler, which it
hooks via async callbacks to persist every state change.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.compiler.compiler import WorkflowCompiler
from agentmesh.compiler.errors import CompilationError, MultipleCompilationErrors
from agentmesh.models.task import Task, TaskStatus
from agentmesh.models.workflow import Workflow, WorkflowStatus
from agentmesh.persistence.repository import (
    get_workflow_tasks,
    save_task_result,
    update_task_status,
    update_workflow_status,
)
from agentmesh.scheduler.retry import RetryPolicy
from agentmesh.scheduler.scheduler import WorkflowScheduler, TaskRunner
from agentmesh.scheduler.state import TaskRun
from agentmesh.tools.base import ToolContext, ToolResult
from agentmesh.tools.registry import default_registry

log = structlog.get_logger(__name__)


class ExecutionError(Exception):
    """Raised when the executor cannot start or complete a workflow."""


class WorkflowExecutor:
    """Drives end-to-end workflow execution.

    Steps:
        1. Load workflow + tasks from DB.
        2. Compile ``workflow_spec`` → ``WorkflowGraph`` (validates again).
        3. Persist ``compiled_graph`` to the Workflow row.
        4. Transition workflow: CREATED → RUNNING.
        5. Build runner callables from ToolRegistry.
        6. Attach DB-persisting lifecycle callbacks to the scheduler.
        7. Run ``WorkflowScheduler.run(graph, runners, task_configs)``.
        8. Transition workflow: RUNNING → COMPLETED or FAILED.
        9. Persist all task results.

    Args:
        retry_policy: Retry configuration (uses default if omitted).
    """

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self._retry_policy = retry_policy

    async def execute(self, workflow_id: uuid.UUID, db: AsyncSession) -> None:
        """Execute the workflow identified by ``workflow_id``.

        This method is designed to be run as a background asyncio task.
        All exceptions are caught and persisted as workflow failures.
        """
        bound_log = log.bind(workflow_id=str(workflow_id))

        try:
            await self._execute_inner(workflow_id, db, bound_log)
        except Exception as exc:
            bound_log.exception("Unhandled error in executor", error=str(exc))
            await update_workflow_status(
                db, workflow_id, WorkflowStatus.FAILED,
                error_message=f"Internal executor error: {exc}",
            )
            await db.commit()

    async def _execute_inner(
        self,
        workflow_id: uuid.UUID,
        db: AsyncSession,
        bound_log: Any,
    ) -> None:
        # ── 1. Load workflow ──────────────────────────────────────────────
        workflow = await _load_workflow(db, workflow_id)
        tasks = await get_workflow_tasks(db, workflow_id)

        if not tasks:
            raise ExecutionError("Workflow has no tasks.")

        # ── 2. Compile ────────────────────────────────────────────────────
        from agentmesh.schemas.workflow import TaskSpec

        task_specs = [
            TaskSpec(
                id=t.task_key,
                tool=t.tool_name,
                params=t.params or {},
                depends_on=[],  # rebuilt from graph in compiler
            )
            for t in tasks
        ]

        # Re-read depends_on from workflow_spec (source of truth)
        spec_tasks_by_key = {
            s["id"]: s
            for s in (workflow.workflow_spec or {}).get("tasks", [])
        }
        for spec in task_specs:
            spec.depends_on = spec_tasks_by_key.get(spec.id, {}).get("depends_on", [])

        try:
            compiler = WorkflowCompiler()
            graph = compiler.compile(task_specs)
        except (CompilationError, MultipleCompilationErrors) as exc:
            await update_workflow_status(
                db, workflow_id, WorkflowStatus.FAILED,
                error_message=f"Compilation failed: {exc}",
            )
            await db.commit()
            return

        # ── 3. Persist compiled graph ─────────────────────────────────────
        workflow.compiled_graph = graph.to_dict()
        await db.flush()

        # ── 4. Transition → RUNNING ───────────────────────────────────────
        await update_workflow_status(db, workflow_id, WorkflowStatus.RUNNING)
        await db.commit()
        bound_log.info("Workflow started")

        # ── 5. Build runners & task configs ──────────────────────────────
        task_db_map: dict[str, Task] = {t.task_key: t for t in tasks}

        runners: dict[str, TaskRunner] = {}
        task_configs: dict[str, TaskRun] = {}

        for task in tasks:
            tool = default_registry.get(task.tool_name)
            runners[task.task_key] = tool.safe_execute
            task_configs[task.task_key] = TaskRun(
                task_key=task.task_key,
                tool_name=task.tool_name,
                params=task.params or {},
                depends_on=spec_tasks_by_key.get(task.task_key, {}).get("depends_on", []),
                retry_count=0,
                max_retries=task.max_retries,
                timeout_seconds=task.timeout_seconds,
            )

        # ── 6. Build DB-persisting callbacks ──────────────────────────────
        async def on_task_started(task_key: str) -> None:
            task = task_db_map.get(task_key)
            if task:
                await update_task_status(db, task.id, TaskStatus.RUNNING)
                await db.commit()
            bound_log.debug("Task started", task_key=task_key)

        async def on_task_completed(task_key: str, result: ToolResult) -> None:
            task = task_db_map.get(task_key)
            if task:
                await update_task_status(db, task.id, TaskStatus.COMPLETED)
                await save_task_result(db, task.id, result)
                await db.commit()
            bound_log.info("Task completed", task_key=task_key, duration_ms=result.duration_ms)

        async def on_task_failed(task_key: str, error: str, will_retry: bool) -> None:
            task = task_db_map.get(task_key)
            if task:
                status = TaskStatus.RETRYING if will_retry else TaskStatus.FAILED
                await update_task_status(db, task.id, status, error_message=error)
                await db.commit()
            bound_log.warning("Task failed", task_key=task_key, will_retry=will_retry, error=error)

        # ── 7. Run scheduler ──────────────────────────────────────────────
        scheduler = WorkflowScheduler(
            retry_policy=self._retry_policy,
            workflow_id=str(workflow_id),
            on_task_started=on_task_started,
            on_task_completed=on_task_completed,
            on_task_failed=on_task_failed,
        )

        final_state = await scheduler.run(graph, runners, task_configs)

        # ── 8. Transition workflow to terminal state ───────────────────────
        if final_state.has_failures:
            error_summary = "; ".join(
                f"{k}: {v}" for k, v in final_state.errors.items()
            )
            await update_workflow_status(
                db, workflow_id, WorkflowStatus.FAILED,
                error_message=error_summary,
            )
            bound_log.error("Workflow failed", failed_tasks=list(final_state.failed))
        else:
            workflow_obj = await _load_workflow(db, workflow_id)
            workflow_obj.completed_tasks = len(final_state.completed)
            await update_workflow_status(db, workflow_id, WorkflowStatus.COMPLETED)
            bound_log.info("Workflow completed", total_tasks=len(final_state.completed))

        await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    """Load workflow or raise ExecutionError if not found."""
    from agentmesh.persistence.repository import get_workflow
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        raise ExecutionError(f"Workflow {workflow_id} not found.")
    return workflow


# Avoid import cycle: 'Any' used in bound_log type above
from typing import Any  # noqa: E402
