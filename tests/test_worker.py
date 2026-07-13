"""Tests for WorkerProcess — job execution against fakeredis + the test DB."""

from __future__ import annotations

import fakeredis
import pytest
from sqlalchemy import select

import agentmesh.worker.worker as worker_module
from agentmesh.models.task import Task, TaskResult, TaskStatus
from agentmesh.persistence.repository import create_workflow, get_workflow_tasks
from agentmesh.queue.consumer import JobConsumer
from agentmesh.queue.producer import JobProducer
from agentmesh.queue.streams import JobMessage
from agentmesh.schemas.workflow import TaskSpec
from agentmesh.worker.health import WorkerHealth
from agentmesh.worker.worker import WorkerProcess
from tests.conftest import test_session_factory as _test_session_factory


@pytest.fixture
async def redis():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def _patch_worker_session_factory(monkeypatch):
    """WorkerProcess opens its own DB sessions — point it at the test database."""
    monkeypatch.setattr(worker_module, "async_session_factory", _test_session_factory)


async def _create_task(db_session, tool_name: str = "echo", params: dict | None = None) -> Task:
    """Persist a single-task workflow and return its Task row."""
    spec = TaskSpec(id="step_1", tool=tool_name, params=params or {}, depends_on=[])
    workflow = await create_workflow(db_session, [spec])
    await db_session.commit()
    tasks = await get_workflow_tasks(db_session, workflow.id)
    return tasks[0]


def _job_for(task: Task, **overrides) -> JobMessage:
    defaults = dict(
        workflow_id=str(task.workflow_id),
        task_key=task.task_key,
        tool_name=task.tool_name,
        params=task.params or {},
        depends_on=[],
        dependency_results={},
        max_retries=task.max_retries,
        attempt=0,
        timeout_seconds=task.timeout_seconds,
        task_id=str(task.id),
    )
    defaults.update(overrides)
    return JobMessage(**defaults)


# ── End-to-end job execution ─────────────────────────────────────────────────


class TestWorkerExecutesJobs:
    async def test_successful_job_persists_result_and_publishes_success(self, redis, db_session):
        task = await _create_task(db_session, tool_name="echo", params={"message": "hello"})

        producer = JobProducer(redis)
        await producer.ensure_consumer_group()
        await producer.publish(_job_for(task))

        worker = WorkerProcess(worker_id="test-worker-1", redis=redis)
        await worker.run(max_iterations=1)

        # Result was published back to the coordinator's stream.
        consumer = JobConsumer(redis, consumer_id="test-observer")
        results = await consumer.read_results(str(task.workflow_id))
        assert len(results) == 1
        _, result_msg = results[0]
        assert result_msg.status == "SUCCESS"
        assert result_msg.task_key == "step_1"

        # TaskResult row was persisted to the DB by the worker.
        async with _test_session_factory() as check_db:
            row = await check_db.execute(
                select(TaskResult).where(TaskResult.task_id == task.id)
            )
            task_result = row.scalar_one_or_none()
            assert task_result is not None
            assert task_result.status == "SUCCESS"

    async def test_unknown_tool_reports_error_result(self, redis, db_session):
        task = await _create_task(db_session, tool_name="echo")

        producer = JobProducer(redis)
        await producer.ensure_consumer_group()
        await producer.publish(_job_for(task, tool_name="does_not_exist"))

        worker = WorkerProcess(worker_id="test-worker-2", redis=redis)
        await worker.run(max_iterations=1)

        consumer = JobConsumer(redis, consumer_id="test-observer")
        results = await consumer.read_results(str(task.workflow_id))
        assert len(results) == 1
        _, result_msg = results[0]
        assert result_msg.status == "ERROR"
        assert "not registered" in (result_msg.error or "").lower()

    async def test_job_marks_task_running_before_execution(self, redis, db_session):
        """Even without inspecting mid-flight state, the RUNNING transition must not error out."""
        task = await _create_task(db_session, tool_name="echo")

        producer = JobProducer(redis)
        await producer.ensure_consumer_group()
        await producer.publish(_job_for(task))

        worker = WorkerProcess(worker_id="test-worker-3", redis=redis)
        await worker.run(max_iterations=1)

        async with _test_session_factory() as check_db:
            row = await check_db.execute(select(Task).where(Task.id == task.id))
            refreshed = row.scalar_one()
            # Worker only sets RUNNING; COMPLETED is the coordinator's responsibility.
            assert refreshed.status == TaskStatus.RUNNING

    async def test_job_acknowledged_after_processing(self, redis, db_session):
        task = await _create_task(db_session, tool_name="echo")

        producer = JobProducer(redis)
        await producer.ensure_consumer_group()
        await producer.publish(_job_for(task))

        worker = WorkerProcess(worker_id="test-worker-4", redis=redis)
        await worker.run(max_iterations=1)

        consumer = JobConsumer(redis, consumer_id="test-observer")
        claimed = await consumer.claim_pending(min_idle_ms=0)
        assert claimed == []  # nothing left pending — the message was acked


# ── Worker heartbeats ─────────────────────────────────────────────────────────


class TestWorkerHealth:
    async def test_worker_registers_and_deregisters_heartbeat(self, redis, db_session):
        task = await _create_task(db_session, tool_name="echo")

        producer = JobProducer(redis)
        await producer.ensure_consumer_group()
        await producer.publish(_job_for(task))

        worker = WorkerProcess(worker_id="heartbeat-worker", redis=redis)
        await worker.run(max_iterations=1)

        # Worker deregisters its heartbeat key on clean shutdown.
        workers = await WorkerHealth.list_workers(redis)
        assert workers == []

    async def test_list_workers_reports_active_heartbeat(self, redis):
        health = WorkerHealth(redis, worker_id="manual-worker")
        await health.heartbeat(status="idle", active_tasks=0)

        workers = await WorkerHealth.list_workers(redis)
        assert len(workers) == 1
        assert workers[0]["worker_id"] == "manual-worker"
        assert workers[0]["status"] == "idle"
