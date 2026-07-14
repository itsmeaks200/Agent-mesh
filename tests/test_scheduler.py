"""Tests for WorkflowScheduler — pure unit tests with mock runners, no DB."""

from __future__ import annotations

import asyncio

from agentmesh.compiler.compiler import WorkflowCompiler
from agentmesh.scheduler.retry import NO_RETRY_POLICY, RetryPolicy
from agentmesh.scheduler.scheduler import WorkflowScheduler
from agentmesh.scheduler.state import TaskRun
from agentmesh.schemas.workflow import TaskSpec
from agentmesh.tools.base import ToolContext, ToolResult

# ── Helpers ───────────────────────────────────────────────────────────────────


def _spec(task_id: str, tool: str = "echo", depends_on: list[str] | None = None) -> TaskSpec:
    return TaskSpec(id=task_id, tool=tool, params={}, depends_on=depends_on or [])


def _compile(*specs: TaskSpec):
    """Compile specs to a graph using known_tools=None to skip tool validation."""
    compiler = WorkflowCompiler(known_tools=None)
    return compiler.compile(list(specs))


def _success_runner(data: dict | None = None):
    """Returns a runner that always succeeds."""
    async def runner(ctx: ToolContext) -> ToolResult:
        return ToolResult.success(data=data or {"ok": True})
    return runner


def _fail_runner(error: str = "simulated failure"):
    """Returns a runner that always fails."""
    async def runner(ctx: ToolContext) -> ToolResult:
        return ToolResult.failure(error=error)
    return runner


def _fail_n_times_runner(n: int, then_data: dict | None = None):
    """Returns a runner that fails N times then succeeds."""
    call_count = [0]
    async def runner(ctx: ToolContext) -> ToolResult:
        call_count[0] += 1
        if call_count[0] <= n:
            return ToolResult.failure(error=f"failure #{call_count[0]}")
        return ToolResult.success(data=then_data or {"recovered": True})
    return runner


def _slow_runner(delay: float = 10.0):
    """Returns a runner that sleeps (simulates slow task)."""
    async def runner(ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(delay)
        return ToolResult.success(data={"done": True})
    return runner


def _build_scheduler(retry_policy=None) -> WorkflowScheduler:
    return WorkflowScheduler(
        retry_policy=retry_policy or NO_RETRY_POLICY,
        workflow_id="test-workflow",
    )


# ── Linear DAG ────────────────────────────────────────────────────────────────


class TestLinearDAG:
    async def test_linear_three_tasks(self):
        graph = _compile(
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["B"]),
        )
        configs = {
            "A": TaskRun(task_key="A", tool_name="echo"),
            "B": TaskRun(task_key="B", tool_name="echo"),
            "C": TaskRun(task_key="C", tool_name="echo"),
        }
        runners = {k: _success_runner() for k in ["A", "B", "C"]}

        state = await _build_scheduler().run(graph, runners, configs)

        assert state.completed == {"A", "B", "C"}
        assert state.failed == set()

    async def test_single_task(self):
        graph = _compile(_spec("A"))
        configs = {"A": TaskRun(task_key="A", tool_name="echo")}
        runners = {"A": _success_runner(data={"x": 1})}

        state = await _build_scheduler().run(graph, runners, configs)

        assert "A" in state.completed
        assert state.results["A"].data == {"x": 1}


# ── Parallel DAG ──────────────────────────────────────────────────────────────


class TestParallelDAG:
    async def test_diamond_concurrent_branches(self):
        """B and C should run concurrently — both must complete before D starts."""
        start_times: dict[str, float] = {}
        import time

        async def timed_runner(key: str) -> ToolResult:
            start_times[key] = time.monotonic()
            await asyncio.sleep(0.05)
            return ToolResult.success(data={"key": key})

        graph = _compile(
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["A"]),
            _spec("D", depends_on=["B", "C"]),
        )
        configs = {k: TaskRun(task_key=k, tool_name="echo") for k in "ABCD"}
        runners = {k: (lambda k=k: lambda ctx: timed_runner(k))() for k in "ABCD"}

        state = await _build_scheduler().run(graph, runners, configs)

        assert state.completed == {"A", "B", "C", "D"}
        # B and C should start at nearly the same time (both dispatched after A)
        assert abs(start_times["B"] - start_times["C"]) < 0.1

    async def test_independent_tasks_run_concurrently(self):
        graph = _compile(_spec("X"), _spec("Y"), _spec("Z"))
        configs = {k: TaskRun(task_key=k, tool_name="echo") for k in "XYZ"}
        runners = {k: _success_runner() for k in "XYZ"}

        state = await _build_scheduler().run(graph, runners, configs)

        assert state.completed == {"X", "Y", "Z"}


# ── Failure & Retry ───────────────────────────────────────────────────────────


class TestFailureHandling:
    async def test_task_failure_fails_workflow(self):
        graph = _compile(_spec("A"), _spec("B", depends_on=["A"]))
        configs = {k: TaskRun(task_key=k, tool_name="echo") for k in "AB"}
        runners = {"A": _fail_runner("A broke"), "B": _success_runner()}

        state = await _build_scheduler().run(graph, runners, configs)

        assert "A" in state.failed
        assert state.errors["A"] == "A broke"

    async def test_downstream_not_run_after_failure(self):
        """If A fails, B should never run."""
        b_called = [False]

        async def b_runner(ctx: ToolContext) -> ToolResult:
            b_called[0] = True
            return ToolResult.success(data={})

        graph = _compile(_spec("A"), _spec("B", depends_on=["A"]))
        configs = {k: TaskRun(task_key=k, tool_name="echo") for k in "AB"}
        runners = {"A": _fail_runner(), "B": b_runner}

        await _build_scheduler().run(graph, runners, configs)

        assert not b_called[0]

    async def test_retry_succeeds_after_failures(self):
        graph = _compile(_spec("A"))
        configs = {"A": TaskRun(task_key="A", tool_name="echo", max_retries=3)}
        runners = {"A": _fail_n_times_runner(2)}

        policy = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.05, jitter=False)
        scheduler = WorkflowScheduler(retry_policy=policy, workflow_id="test")
        state = await scheduler.run(graph, runners, configs)

        assert "A" in state.completed

    async def test_retry_exhausted_marks_failed(self):
        graph = _compile(_spec("A"))
        configs = {"A": TaskRun(task_key="A", tool_name="echo", max_retries=2)}
        runners = {"A": _fail_runner("always fails")}

        policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05, jitter=False)
        scheduler = WorkflowScheduler(retry_policy=policy, workflow_id="test")
        state = await scheduler.run(graph, runners, configs)

        assert "A" in state.failed


# ── Timeout ───────────────────────────────────────────────────────────────────


class TestTimeout:
    async def test_task_timeout_returns_error(self):
        graph = _compile(_spec("A"))
        configs = {"A": TaskRun(task_key="A", tool_name="echo", timeout_seconds=1, max_retries=0)}
        runners = {"A": _slow_runner(delay=10.0)}

        state = await _build_scheduler().run(graph, runners, configs)

        assert "A" in state.failed
        assert "timed out" in state.errors["A"].lower()


# ── Dependency Injection ──────────────────────────────────────────────────────


class TestDependencyInjection:
    async def test_upstream_result_in_context(self):
        """B's runner should receive A's result in ctx.dependencies."""
        received_deps: dict = {}

        async def b_runner(ctx: ToolContext) -> ToolResult:
            received_deps.update(ctx.dependencies)
            return ToolResult.success(data={"got_dep": True})

        graph = _compile(_spec("A"), _spec("B", depends_on=["A"]))
        configs = {
            "A": TaskRun(task_key="A", tool_name="echo", depends_on=[]),
            "B": TaskRun(task_key="B", tool_name="echo", depends_on=["A"]),
        }
        runners = {"A": _success_runner(data={"msg": "from A"}), "B": b_runner}

        await _build_scheduler().run(graph, runners, configs)

        assert "A" in received_deps
        assert received_deps["A"].data == {"msg": "from A"}


# ── Callbacks ─────────────────────────────────────────────────────────────────


class TestLifecycleCallbacks:
    async def test_callbacks_fired(self):
        started = []
        completed = []
        failed_list = []

        async def on_started(key): started.append(key)
        async def on_completed(key, result): completed.append(key)
        async def on_failed(key, error, will_retry): failed_list.append(key)

        graph = _compile(_spec("A"), _spec("B", depends_on=["A"]))
        configs = {k: TaskRun(task_key=k, tool_name="echo") for k in "AB"}
        runners = {"A": _success_runner(), "B": _success_runner()}

        scheduler = WorkflowScheduler(
            retry_policy=NO_RETRY_POLICY,
            on_task_started=on_started,
            on_task_completed=on_completed,
            on_task_failed=on_failed,
        )
        await scheduler.run(graph, runners, configs)

        assert set(started) == {"A", "B"}
        assert set(completed) == {"A", "B"}
        assert failed_list == []
