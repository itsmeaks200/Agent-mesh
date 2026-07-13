"""Tests for WorkflowCoordinator — distributed orchestration over Redis Streams.

These tests drive the coordinator against fakeredis with a lightweight "fake
worker" loop standing in for real ``WorkerProcess`` instances. This isolates
coordinator behaviour (dispatch, dependency propagation, retries, fail-fast)
from actual tool execution, which is already covered by test_worker.py.
"""

from __future__ import annotations

import asyncio
import contextlib

import fakeredis
import pytest

from agentmesh.models.workflow import WorkflowStatus
from agentmesh.persistence.repository import create_workflow, get_workflow, get_workflow_tasks
from agentmesh.queue.consumer import JobConsumer
from agentmesh.queue.producer import JobProducer
from agentmesh.queue.streams import JobMessage, ResultMessage
from agentmesh.scheduler.coordinator import WorkflowCoordinator
from agentmesh.scheduler.retry import RetryPolicy
from agentmesh.schemas.workflow import TaskSpec
from agentmesh.tools.base import ToolResult

_FAST_RETRY_POLICY = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.05, jitter=False)


@pytest.fixture
async def redis():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def _spec(task_id: str, tool: str = "echo", depends_on: list[str] | None = None) -> TaskSpec:
    return TaskSpec(id=task_id, tool=tool, params={}, depends_on=depends_on or [])


async def _run_fake_worker(redis, behavior=None) -> None:
    """Continuously execute jobs from the task stream using `behavior` overrides.

    `behavior` maps task_key -> callable(JobMessage) -> ToolResult. Tasks without
    an override just succeed with an echo of their params.
    """
    behavior = behavior or {}
    consumer = JobConsumer(redis, consumer_id="fake-worker")
    producer = JobProducer(redis)

    while True:
        jobs = await consumer.read_jobs(count=10, block_ms=50)
        for msg_id, job in jobs:
            fn = behavior.get(job.task_key)
            result = fn(job) if fn else ToolResult.success(data={"echo": job.params})
            await producer.publish_result(ResultMessage(
                workflow_id=job.workflow_id,
                task_key=job.task_key,
                task_id=job.task_id,
                status=result.status,
                data=result.data,
                error=result.error,
                duration_ms=0,
                attempt=job.attempt,
            ))
            await consumer.ack(msg_id)
        if not jobs:
            await asyncio.sleep(0.01)


async def _run_with_fake_worker(coro, redis, behavior=None):
    """Run `coro` (typically coordinator.execute(...)) alongside a fake worker loop."""
    await JobProducer(redis).ensure_consumer_group()
    worker_task = asyncio.create_task(_run_fake_worker(redis, behavior))
    try:
        await coro
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


# ── Happy path ────────────────────────────────────────────────────────────────


class TestCoordinatorHappyPath:
    async def test_linear_workflow_completes(self, redis, db_session):
        workflow = await create_workflow(db_session, [
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["B"]),
        ])
        await db_session.commit()

        coordinator = WorkflowCoordinator(redis)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
        )

        result = await get_workflow(db_session, workflow.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert result.completed_tasks == 3

        tasks = await get_workflow_tasks(db_session, workflow.id)
        assert all(t.status.value == "COMPLETED" for t in tasks)

    async def test_diamond_workflow_dispatches_and_completes(self, redis, db_session):
        workflow = await create_workflow(db_session, [
            _spec("start"),
            _spec("branch_a", depends_on=["start"]),
            _spec("branch_b", depends_on=["start"]),
            _spec("merge", depends_on=["branch_a", "branch_b"]),
        ])
        await db_session.commit()

        coordinator = WorkflowCoordinator(redis)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
        )

        result = await get_workflow(db_session, workflow.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert result.completed_tasks == 4

    async def test_dependency_results_propagate_to_downstream_task(self, redis, db_session):
        workflow = await create_workflow(db_session, [
            _spec("A"),
            _spec("B", depends_on=["A"]),
        ])
        await db_session.commit()

        seen_dependency_results = {}

        def b_behavior(job: JobMessage) -> ToolResult:
            seen_dependency_results.update(job.dependency_results)
            return ToolResult.success(data={"got": True})

        def a_behavior(job: JobMessage) -> ToolResult:
            return ToolResult.success(data={"msg": "from A"})

        coordinator = WorkflowCoordinator(redis)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
            behavior={"A": a_behavior, "B": b_behavior},
        )

        assert seen_dependency_results.get("A") == {"msg": "from A"}


# ── Failure handling ──────────────────────────────────────────────────────────


class TestCoordinatorFailureHandling:
    async def test_permanent_failure_marks_workflow_failed(self, redis, db_session):
        workflow = await create_workflow(db_session, [_spec("A")])
        await db_session.commit()

        tasks = await get_workflow_tasks(db_session, workflow.id)
        tasks[0].max_retries = 1  # only one retry — fail fast in the test
        await db_session.commit()

        def always_fails(job: JobMessage) -> ToolResult:
            return ToolResult.failure(error="boom")

        coordinator = WorkflowCoordinator(redis, retry_policy=_FAST_RETRY_POLICY)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
            behavior={"A": always_fails},
        )

        result = await get_workflow(db_session, workflow.id)
        assert result.status == WorkflowStatus.FAILED
        assert "boom" in (result.error_message or "")

    async def test_retry_then_success_completes_workflow(self, redis, db_session):
        workflow = await create_workflow(db_session, [_spec("A")])
        await db_session.commit()

        tasks = await get_workflow_tasks(db_session, workflow.id)
        tasks[0].max_retries = 3
        await db_session.commit()

        call_count = {"n": 0}

        def fails_once_then_succeeds(job: JobMessage) -> ToolResult:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ToolResult.failure(error="transient")
            return ToolResult.success(data={"ok": True})

        coordinator = WorkflowCoordinator(redis, retry_policy=_FAST_RETRY_POLICY)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
            behavior={"A": fails_once_then_succeeds},
        )

        result = await get_workflow(db_session, workflow.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert call_count["n"] == 2

    async def test_downstream_task_never_dispatched_after_upstream_failure(self, redis, db_session):
        workflow = await create_workflow(db_session, [
            _spec("A"),
            _spec("B", depends_on=["A"]),
        ])
        await db_session.commit()

        tasks = await get_workflow_tasks(db_session, workflow.id)
        for t in tasks:
            if t.task_key == "A":
                t.max_retries = 0
        await db_session.commit()

        b_called = {"called": False}

        def a_fails(job: JobMessage) -> ToolResult:
            return ToolResult.failure(error="A broke")

        def b_runner(job: JobMessage) -> ToolResult:
            b_called["called"] = True
            return ToolResult.success(data={})

        coordinator = WorkflowCoordinator(redis, retry_policy=_FAST_RETRY_POLICY)
        await _run_with_fake_worker(
            coordinator.execute(workflow.id, db_session), redis,
            behavior={"A": a_fails, "B": b_runner},
        )

        assert not b_called["called"]
        result = await get_workflow(db_session, workflow.id)
        assert result.status == WorkflowStatus.FAILED
