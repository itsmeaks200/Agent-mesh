"""WorkflowScheduler — dependency-aware asyncio task executor.

The scheduler is intentionally decoupled from the database and API layers.
It accepts:
  - A WorkflowGraph (compiled DAG)
  - A dict of async runner callables: task_key → async (ToolContext) → ToolResult
  - Optional lifecycle callbacks for external state persistence

This makes it trivially unit-testable with mock runners.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from agentmesh.compiler.graph import WorkflowGraph
from agentmesh.scheduler.retry import RetryPolicy, compute_backoff
from agentmesh.scheduler.state import ExecutionState, TaskRun
from agentmesh.tools.base import ToolContext, ToolResult

log = logging.getLogger(__name__)

# Type alias for a task runner
TaskRunner = Callable[[ToolContext], Awaitable[ToolResult]]

# Type alias for lifecycle callbacks
OnTaskStarted = Callable[[str], Awaitable[None]]
OnTaskCompleted = Callable[[str, ToolResult], Awaitable[None]]
OnTaskFailed = Callable[[str, str, bool], Awaitable[None]]  # key, error, will_retry


class WorkflowScheduler:
    """Executes a compiled WorkflowGraph concurrently using asyncio.

    Algorithm:
        1. Call ``graph.get_ready_tasks(state.completed)`` to find runnable tasks.
        2. For each ready task, create an asyncio task (concurrent dispatch).
        3. Await all running tasks with ``asyncio.gather``.
        4. For each result:
           - SUCCESS → mark completed, store result.
           - ERROR + retries remaining → sleep (backoff), re-queue.
           - ERROR + no retries left → mark failed (fail-fast: stop workflow).
        5. Repeat from step 1 until all tasks complete or a fatal failure occurs.

    Args:
        retry_policy:      Controls retry behaviour for all tasks.
        workflow_id:       Used for logging and ToolContext.
        on_task_started:   Async callback fired when a task begins.
        on_task_completed: Async callback fired on task success.
        on_task_failed:    Async callback fired on task failure (will_retry flag).
    """

    def __init__(
        self,
        retry_policy: RetryPolicy | None = None,
        workflow_id: str = "",
        on_task_started: OnTaskStarted | None = None,
        on_task_completed: OnTaskCompleted | None = None,
        on_task_failed: OnTaskFailed | None = None,
    ) -> None:
        from agentmesh.scheduler.retry import DEFAULT_RETRY_POLICY
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._workflow_id = workflow_id
        self._on_task_started = on_task_started or _noop_started
        self._on_task_completed = on_task_completed or _noop_completed
        self._on_task_failed = on_task_failed or _noop_failed

    async def run(
        self,
        graph: WorkflowGraph,
        runners: dict[str, TaskRunner],
        task_configs: dict[str, TaskRun] | None = None,
    ) -> ExecutionState:
        """Execute all tasks in the graph, respecting dependencies.

        Args:
            graph:        Compiled DAG.
            runners:      Mapping of task_key → async callable.
            task_configs: Optional per-task retry / timeout overrides.

        Returns:
            Final ExecutionState with results and any errors.
        """
        state = ExecutionState()
        # Retry queues: task_key → (attempt_number, delay_seconds)
        retry_queue: dict[str, tuple[int, float]] = {}
        configs = task_configs or {}

        while True:
            # --- Fire ready tasks ---
            ready = graph.get_ready_tasks(state.completed)

            # Remove tasks that are already failed (fail-fast)
            if state.has_failures:
                break

            # Filter out any tasks blocked by failed dependencies
            ready = [
                t for t in ready
                if not any(dep in state.failed for dep in graph.dependencies_of(t))
            ]

            # Include retry candidates whose backoff has elapsed
            retry_ready = list(retry_queue.keys())

            if not ready and not retry_ready:
                # No more work to dispatch — check if we're done
                if len(state.completed) + len(state.failed) == graph.node_count:
                    break
                # Deadlock guard: no tasks to run but not all done
                log.error(
                    "Scheduler deadlock detected: %d/%d tasks done, failures=%s",
                    len(state.completed) + len(state.failed),
                    graph.node_count,
                    state.failed,
                )
                break

            # Build async tasks for all ready tasks
            async_tasks: list[asyncio.Task] = []
            task_key_map: dict[asyncio.Task, str] = {}

            for task_key in ready:
                if task_key in state.finished:
                    continue
                cfg = configs.get(task_key, TaskRun(task_key=task_key, tool_name=""))
                attempt = 0
                coro = self._run_single(task_key, attempt, cfg, state, runners)
                t = asyncio.create_task(coro, name=f"task:{task_key}")
                async_tasks.append(t)
                task_key_map[t] = task_key

            for task_key in retry_ready:
                attempt, delay = retry_queue.pop(task_key)
                cfg = configs.get(task_key, TaskRun(task_key=task_key, tool_name=""))
                coro = self._run_with_delay(task_key, attempt, delay, cfg, state, runners)
                t = asyncio.create_task(coro, name=f"retry:{task_key}:{attempt}")
                async_tasks.append(t)
                task_key_map[t] = task_key

            if not async_tasks:
                break

            # Wait for ALL concurrent tasks to finish
            results: list[tuple[str, ToolResult, int]] = await asyncio.gather(*async_tasks)

            for task_key, result, attempt in results:
                if result.status == "SUCCESS":
                    state.mark_completed(task_key, result)
                    await self._on_task_completed(task_key, result)
                else:
                    cfg = configs.get(task_key, TaskRun(task_key=task_key, tool_name=""))
                    effective_max = cfg.max_retries
                    if attempt < effective_max:
                        delay = compute_backoff(attempt, self._retry_policy)
                        retry_queue[task_key] = (attempt + 1, delay)
                        will_retry = True
                        log.warning(
                            "Task '%s' failed (attempt %d/%d), retrying in %.1fs: %s",
                            task_key, attempt + 1, effective_max, delay, result.error,
                        )
                    else:
                        state.mark_failed(task_key, result.error or "Unknown error")
                        will_retry = False
                        log.error(
                            "Task '%s' failed permanently after %d attempts: %s",
                            task_key, attempt + 1, result.error,
                        )
                    await self._on_task_failed(task_key, result.error or "", will_retry)

        return state

    async def _run_single(
        self,
        task_key: str,
        attempt: int,
        cfg: TaskRun,
        state: ExecutionState,
        runners: dict[str, TaskRunner],
    ) -> tuple[str, ToolResult, int]:
        """Execute a single task with timeout, returning (task_key, result, attempt)."""
        await self._on_task_started(task_key)
        log.debug("Starting task '%s' (attempt %d)", task_key, attempt + 1)

        runner = runners.get(task_key)
        if runner is None:
            return task_key, ToolResult.failure(
                error=f"No runner registered for task '{task_key}'"
            ), attempt

        # Build context — inject upstream results as dependencies
        dependencies = {
            dep_key: state.results[dep_key]
            for dep_key in cfg.depends_on
            if dep_key in state.results
        }
        context = ToolContext(
            params=cfg.params,
            dependencies=dependencies,
            workflow_id=self._workflow_id,
            task_key=task_key,
        )

        try:
            result = await asyncio.wait_for(
                runner(context),
                timeout=cfg.timeout_seconds or None,
            )
        except TimeoutError:
            result = ToolResult.failure(
                error=f"Task '{task_key}' timed out after {cfg.timeout_seconds}s"
            )
        except Exception as exc:
            result = ToolResult.failure(error=f"Unexpected error: {exc}")

        return task_key, result, attempt

    async def _run_with_delay(
        self,
        task_key: str,
        attempt: int,
        delay: float,
        cfg: TaskRun,
        state: ExecutionState,
        runners: dict[str, TaskRunner],
    ) -> tuple[str, ToolResult, int]:
        """Sleep for backoff delay then execute the task."""
        await asyncio.sleep(delay)
        return await self._run_single(task_key, attempt, cfg, state, runners)


# ── No-op callbacks ───────────────────────────────────────────────────────────

async def _noop_started(task_key: str) -> None:
    pass

async def _noop_completed(task_key: str, result: ToolResult) -> None:
    pass

async def _noop_failed(task_key: str, error: str, will_retry: bool) -> None:
    pass
