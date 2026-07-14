"""WorkflowCoordinator — orchestrates distributed workflow execution via Redis Streams.

Unlike ``WorkflowExecutor`` (Phase 4, in-process asyncio scheduling), the
coordinator never runs a tool itself. Instead it:

    1. Loads + compiles the workflow, exactly like the in-process executor.
    2. Publishes a ``JobMessage`` to the shared task stream for every
       initially-ready task.
    3. Reads the per-workflow result stream for ``ResultMessage`` replies
       published by worker processes.
    4. On success: persists the status transition, then dispatches any
       newly-ready downstream tasks.
    5. On failure: retries (re-publishes with an incremented attempt count
       after a backoff delay) or marks the task permanently failed —
       matching the same fail-fast semantics as ``WorkflowScheduler``
       (no *new* tasks are dispatched once a permanent failure occurs, but
       tasks already in flight are allowed to finish).
    6. Transitions the workflow to COMPLETED or FAILED once all dispatched
       tasks have reached a terminal state.

This class owns no tool execution logic at all — that lives in
``agentmesh.worker.worker.WorkerProcess``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from agentmesh.compiler.compiler import WorkflowCompiler
from agentmesh.compiler.errors import CompilationError, MultipleCompilationErrors
from agentmesh.events import publish_event_nowait
from agentmesh.models.task import Task, TaskStatus
from agentmesh.models.workflow import Workflow, WorkflowStatus
from agentmesh.persistence.repository import (
    get_workflow,
    get_workflow_tasks,
    update_task_status,
    update_workflow_status,
)
from agentmesh.queue.producer import JobProducer
from agentmesh.queue.consumer import JobConsumer
from agentmesh.queue.streams import JobMessage, ResultMessage
from agentmesh.scheduler.retry import DEFAULT_RETRY_POLICY, RetryPolicy, compute_backoff
from agentmesh.schemas.workflow import TaskSpec
from agentmesh.tools.base import ToolResult

log = structlog.get_logger(__name__)

# How long to wait (non-blocking-ish) per poll cycle when no results are ready.
_EMPTY_POLL_SLEEP_SECONDS = 0.05
_RESULT_BLOCK_MS = 1000


class CoordinationError(Exception):
    """Raised when the coordinator cannot start or complete a workflow."""


class WorkflowCoordinator:
    """Drives end-to-end workflow execution across distributed worker processes.

    Args:
        redis:        An async Redis client instance.
        retry_policy:  Controls backoff delays between retry attempts.
    """

    def __init__(self, redis: Redis, retry_policy: RetryPolicy | None = None) -> None:
        self._redis = redis
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._producer = JobProducer(redis)

    async def execute(self, workflow_id: uuid.UUID, db: AsyncSession) -> None:
        """Execute the workflow identified by ``workflow_id`` via distributed workers.

        Designed to be run as a background asyncio task. All exceptions are
        caught and persisted as workflow failures.
        """
        bound_log = log.bind(workflow_id=str(workflow_id))
        try:
            await self._execute_inner(workflow_id, db, bound_log)
        except Exception as exc:
            bound_log.exception("Unhandled error in coordinator", error=str(exc))
            await update_workflow_status(
                db, workflow_id, WorkflowStatus.FAILED,
                error_message=f"Internal coordinator error: {exc}",
            )
            await db.commit()

    async def _execute_inner(
        self,
        workflow_id: uuid.UUID,
        db: AsyncSession,
        bound_log: Any,
    ) -> None:
        # ── 1. Load + compile (identical to WorkflowExecutor) ──────────────
        workflow = await _load_workflow(db, workflow_id)
        tasks = await get_workflow_tasks(db, workflow_id)

        if not tasks:
            raise CoordinationError("Workflow has no tasks.")

        task_specs = [
            TaskSpec(id=t.task_key, tool=t.tool_name, params=t.params or {}, depends_on=[])
            for t in tasks
        ]
        spec_tasks_by_key = {
            s["id"]: s for s in (workflow.workflow_spec or {}).get("tasks", [])
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

        workflow.compiled_graph = graph.to_dict()
        await db.flush()

        await update_workflow_status(db, workflow_id, WorkflowStatus.RUNNING)
        await db.commit()
        bound_log.info("Workflow started (distributed mode)")

        # Fire-and-forget: these must never be awaited inline. This loop also
        # issues blocking XREADGROUP reads on `self._redis`, and interleaving
        # an awaited PUBLISH with an in-flight blocking read on the same
        # client can wedge some Redis client implementations. Tasks are
        # tracked here and drained (best-effort) once the workflow finishes.
        bg_publish_tasks: set[asyncio.Task] = set()

        def publish_task(task_key: str, status: TaskStatus, **extra: Any) -> None:
            bg_publish_tasks.add(publish_event_nowait(self._redis, workflow_id, {
                "type": "task_update", "workflow_id": str(workflow_id),
                "task_key": task_key, "status": status.value, **extra,
            }))

        def publish_workflow(status: WorkflowStatus, **extra: Any) -> None:
            bg_publish_tasks.add(publish_event_nowait(self._redis, workflow_id, {
                "type": "workflow_update", "workflow_id": str(workflow_id),
                "status": status.value, **extra,
            }))

        publish_workflow(
            WorkflowStatus.RUNNING,
            total_tasks=workflow.total_tasks, completed_tasks=workflow.completed_tasks,
        )

        await self._producer.ensure_consumer_group()

        # ── 2. Local orchestration state ────────────────────────────────────
        task_db_map: dict[str, Task] = {t.task_key: t for t in tasks}
        depends_on_map: dict[str, list[str]] = {
            t.task_key: spec_tasks_by_key.get(t.task_key, {}).get("depends_on", [])
            for t in tasks
        }

        dispatched: set[str] = set()
        completed: set[str] = set()
        failed: set[str] = set()
        results: dict[str, ToolResult] = {}
        errors: dict[str, str] = {}
        db_lock = asyncio.Lock()

        async def dispatch(task_key: str, attempt: int) -> None:
            task = task_db_map[task_key]
            dependency_results = {
                dep: (results[dep].data or {})
                for dep in depends_on_map.get(task_key, [])
                if dep in results
            }
            job = JobMessage(
                workflow_id=str(workflow_id),
                task_key=task_key,
                tool_name=task.tool_name,
                params=task.params or {},
                depends_on=depends_on_map.get(task_key, []),
                dependency_results=dependency_results,
                max_retries=task.max_retries,
                attempt=attempt,
                timeout_seconds=task.timeout_seconds,
                task_id=str(task.id),
            )
            await self._producer.publish(job)
            async with db_lock:
                await update_task_status(db, task.id, TaskStatus.QUEUED)
                await db.commit()
            publish_task(task_key, TaskStatus.QUEUED)
            bound_log.debug("Dispatched task", task_key=task_key, attempt=attempt)

        async def dispatch_ready() -> None:
            """Dispatch every currently-ready, not-yet-dispatched task.

            Fail-fast: once a permanent failure has occurred, no new tasks
            are dispatched (mirrors WorkflowScheduler's behaviour), though
            tasks already in flight are still allowed to finish.
            """
            if failed:
                return
            for task_key in graph.get_ready_tasks(completed):
                if task_key in dispatched:
                    continue
                dispatched.add(task_key)
                await dispatch(task_key, 0)

        async def redispatch_after_delay(task_key: str, attempt: int, delay: float) -> None:
            await asyncio.sleep(delay)
            if failed:
                # A sibling task failed permanently while we were waiting — fail-fast
                # means we won't dispatch a new attempt. Mark this task failed too,
                # otherwise it would stay stuck in `dispatched` forever and the
                # coordinator's main loop would never terminate.
                failed.add(task_key)
                errors[task_key] = "Skipped retry: workflow already failed"
                task = task_db_map[task_key]
                async with db_lock:
                    await update_task_status(
                        db, task.id, TaskStatus.FAILED,
                        error_message=errors[task_key],
                    )
                    await db.commit()
                publish_task(task_key, TaskStatus.FAILED, error_message=errors[task_key])
                return
            await dispatch(task_key, attempt)

        # ── 3. Initial dispatch ─────────────────────────────────────────────
        await dispatch_ready()

        consumer = JobConsumer(self._redis, consumer_id=f"coordinator-{workflow_id}")
        last_id = "0"
        retry_tasks: set[asyncio.Task] = set()

        # ── 4. Drive execution from result stream ───────────────────────────
        while dispatched - completed - failed:
            messages = await consumer.read_results(
                str(workflow_id), last_id=last_id, count=50, block_ms=_RESULT_BLOCK_MS,
            )
            if not messages:
                await asyncio.sleep(_EMPTY_POLL_SLEEP_SECONDS)
                retry_tasks = {t for t in retry_tasks if not t.done()}
                continue

            for msg_id, result_msg in messages:
                last_id = msg_id
                task_key = result_msg.task_key
                task = task_db_map.get(task_key)
                if task is None or task_key in completed or task_key in failed:
                    continue

                if result_msg.status == "SUCCESS":
                    tool_result = ToolResult.success(
                        data=result_msg.data or {}, duration_ms=result_msg.duration_ms,
                    )
                    results[task_key] = tool_result
                    completed.add(task_key)
                    async with db_lock:
                        await update_task_status(db, task.id, TaskStatus.COMPLETED)
                        await db.commit()
                    publish_task(task_key, TaskStatus.COMPLETED, duration_ms=result_msg.duration_ms)
                    bound_log.info("Task completed", task_key=task_key)
                    await dispatch_ready()
                else:
                    attempt = result_msg.attempt
                    max_retries = task.max_retries
                    if attempt < max_retries:
                        delay = compute_backoff(attempt, self._retry_policy)
                        async with db_lock:
                            await update_task_status(
                                db, task.id, TaskStatus.RETRYING, error_message=result_msg.error,
                            )
                            await db.commit()
                        publish_task(task_key, TaskStatus.RETRYING, error_message=result_msg.error)
                        bound_log.warning(
                            "Task failed, scheduling retry",
                            task_key=task_key, attempt=attempt + 1, max_retries=max_retries,
                            delay=round(delay, 2), error=result_msg.error,
                        )
                        retry_tasks.add(asyncio.create_task(
                            redispatch_after_delay(task_key, attempt + 1, delay)
                        ))
                    else:
                        failed.add(task_key)
                        errors[task_key] = result_msg.error or "Unknown error"
                        async with db_lock:
                            await update_task_status(
                                db, task.id, TaskStatus.FAILED, error_message=result_msg.error,
                            )
                            await db.commit()
                        publish_task(task_key, TaskStatus.FAILED, error_message=result_msg.error)
                        bound_log.error(
                            "Task failed permanently",
                            task_key=task_key, attempts=attempt + 1, error=result_msg.error,
                        )

        # Let any in-flight retry timers settle before finishing up.
        if retry_tasks:
            await asyncio.gather(*retry_tasks, return_exceptions=True)

        # ── 5. Transition workflow to terminal state ────────────────────────
        if failed:
            error_summary = "; ".join(f"{k}: {v}" for k, v in errors.items())
            await update_workflow_status(
                db, workflow_id, WorkflowStatus.FAILED, error_message=error_summary,
            )
            bound_log.error("Workflow failed", failed_tasks=list(failed))
            await db.commit()
            publish_workflow(
                WorkflowStatus.FAILED, total_tasks=workflow.total_tasks,
                completed_tasks=len(completed), error_message=error_summary,
            )
        else:
            workflow_obj = await _load_workflow(db, workflow_id)
            workflow_obj.completed_tasks = len(completed)
            await update_workflow_status(db, workflow_id, WorkflowStatus.COMPLETED)
            bound_log.info("Workflow completed", total_tasks=len(completed))
            await db.commit()
            publish_workflow(
                WorkflowStatus.COMPLETED, total_tasks=workflow.total_tasks,
                completed_tasks=len(completed), error_message=None,
            )

        # Best-effort: give in-flight publishes a chance to land before we return.
        if bg_publish_tasks:
            await asyncio.gather(*bg_publish_tasks, return_exceptions=True)


async def _load_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    """Load workflow or raise CoordinationError if not found."""
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        raise CoordinationError(f"Workflow {workflow_id} not found.")
    return workflow
