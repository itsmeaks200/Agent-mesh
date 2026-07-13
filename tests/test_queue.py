"""Tests for the Redis Streams job queue (JobProducer / JobConsumer) using fakeredis."""

from __future__ import annotations

import fakeredis
import pytest

from agentmesh.queue.consumer import JobConsumer
from agentmesh.queue.producer import JobProducer
from agentmesh.queue.streams import JobMessage, ResultMessage


@pytest.fixture
async def redis():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def producer(redis):
    return JobProducer(redis)


def _job(task_key: str = "step_1", **overrides) -> JobMessage:
    defaults = dict(
        workflow_id="wf-1",
        task_key=task_key,
        tool_name="echo",
        params={"message": "hi"},
        depends_on=[],
        dependency_results={},
        max_retries=3,
        attempt=0,
        timeout_seconds=300,
        task_id="11111111-1111-1111-1111-111111111111",
    )
    defaults.update(overrides)
    return JobMessage(**defaults)


# ── Producer / Consumer round trip ───────────────────────────────────────────


class TestJobRoundTrip:
    async def test_publish_and_read_job(self, redis, producer):
        await producer.ensure_consumer_group()
        await producer.publish(_job())

        consumer = JobConsumer(redis, consumer_id="worker-1")
        jobs = await consumer.read_jobs(count=10)

        assert len(jobs) == 1
        msg_id, job = jobs[0]
        assert job.task_key == "step_1"
        assert job.tool_name == "echo"
        assert job.params == {"message": "hi"}
        assert job.workflow_id == "wf-1"

    async def test_ensure_consumer_group_is_idempotent(self, redis, producer):
        await producer.ensure_consumer_group()
        # Calling it again should not raise (BUSYGROUP is swallowed).
        await producer.ensure_consumer_group()

    async def test_read_jobs_only_delivers_once_per_consumer_group(self, redis, producer):
        await producer.ensure_consumer_group()
        await producer.publish(_job())

        consumer = JobConsumer(redis, consumer_id="worker-1")
        first = await consumer.read_jobs(count=10)
        second = await consumer.read_jobs(count=10)

        assert len(first) == 1
        assert second == []  # already delivered — XREADGROUP with ">" won't redeliver

    async def test_ack_removes_from_pending(self, redis, producer):
        await producer.ensure_consumer_group()
        await producer.publish(_job())

        consumer = JobConsumer(redis, consumer_id="worker-1")
        [(msg_id, _job_msg)] = await consumer.read_jobs(count=10)
        await consumer.ack(msg_id)

        # Nothing pending to reclaim after ack, even with zero idle time.
        claimed = await consumer.claim_pending(min_idle_ms=0)
        assert claimed == []


# ── Crash recovery via XAUTOCLAIM ────────────────────────────────────────────


class TestPendingReclaim:
    async def test_claim_pending_reclaims_unacked_message(self, redis, producer):
        await producer.ensure_consumer_group()
        await producer.publish(_job(task_key="crashed_task"))

        crashed_consumer = JobConsumer(redis, consumer_id="worker-crashed")
        delivered = await crashed_consumer.read_jobs(count=10)
        assert len(delivered) == 1  # picked up, then the worker "crashes" (never acks)

        healthy_consumer = JobConsumer(redis, consumer_id="worker-healthy")
        claimed = await healthy_consumer.claim_pending(min_idle_ms=0)

        assert len(claimed) == 1
        _, job = claimed[0]
        assert job.task_key == "crashed_task"

    async def test_claim_pending_empty_when_nothing_pending(self, redis, producer):
        await producer.ensure_consumer_group()
        consumer = JobConsumer(redis, consumer_id="worker-1")
        claimed = await consumer.claim_pending(min_idle_ms=0)
        assert claimed == []


# ── Results stream ────────────────────────────────────────────────────────────


class TestResultRoundTrip:
    async def test_publish_and_read_result(self, redis, producer):
        result = ResultMessage(
            workflow_id="wf-1",
            task_key="step_1",
            task_id="11111111-1111-1111-1111-111111111111",
            status="SUCCESS",
            data={"output": 42},
            duration_ms=15,
            attempt=0,
        )
        await producer.publish_result(result)

        consumer = JobConsumer(redis, consumer_id="coordinator")
        messages = await consumer.read_results("wf-1")

        assert len(messages) == 1
        _, msg = messages[0]
        assert msg.task_key == "step_1"
        assert msg.status == "SUCCESS"
        assert msg.data == {"output": 42}
        assert msg.duration_ms == 15

    async def test_cursor_avoids_reprocessing_results(self, redis, producer):
        consumer = JobConsumer(redis, consumer_id="coordinator")

        await producer.publish_result(ResultMessage(
            workflow_id="wf-2", task_key="a", task_id="t1", status="SUCCESS", data={},
        ))
        first_batch = await consumer.read_results("wf-2")
        assert len(first_batch) == 1
        last_id = first_batch[-1][0]

        # No new messages yet — same cursor should return nothing.
        assert await consumer.read_results("wf-2", last_id=last_id) == []

        await producer.publish_result(ResultMessage(
            workflow_id="wf-2", task_key="b", task_id="t2", status="ERROR", error="boom",
        ))
        second_batch = await consumer.read_results("wf-2", last_id=last_id)

        assert len(second_batch) == 1
        assert second_batch[0][1].task_key == "b"
        assert second_batch[0][1].error == "boom"

    async def test_read_results_for_unknown_workflow_returns_empty(self, redis):
        consumer = JobConsumer(redis, consumer_id="coordinator")
        assert await consumer.read_results("does-not-exist") == []


# ── Dead letter ───────────────────────────────────────────────────────────────


class TestDeadLetter:
    async def test_publish_dead_letter(self, redis, producer):
        await producer.publish_dead_letter(_job(task_key="doomed"), error="exhausted retries")

        raw = await redis.xrange("agentmesh:dead-letter")
        assert len(raw) == 1
        _msg_id, fields = raw[0]
        assert fields["task_key"] == "doomed"
        assert fields["final_error"] == "exhausted retries"
