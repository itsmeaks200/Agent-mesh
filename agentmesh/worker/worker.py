"""WorkerProcess — standalone consumer that executes tasks from the Redis task stream.

A worker's responsibilities are intentionally narrow:
    1. Pull a job off the task stream (or reclaim one abandoned by a crashed peer).
    2. Look up the tool in the registry and execute it.
    3. Persist the successful TaskResult to PostgreSQL.
    4. Publish a ResultMessage back to the coordinator.
    5. Acknowledge the message.

Retry decisions, downstream dispatch, and workflow/task status transitions are
owned entirely by ``WorkflowCoordinator`` — the worker never re-publishes a
failed job itself. This keeps orchestration logic in one place and makes
workers safe to add/remove/restart at will.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid

import redis.asyncio as aioredis
import structlog
from redis.asyncio import Redis

from agentmesh.config import get_settings
from agentmesh.events import publish_event_nowait
from agentmesh.models.task import TaskStatus
from agentmesh.persistence import async_session_factory
from agentmesh.persistence.repository import save_task_result, update_task_status
from agentmesh.queue.consumer import JobConsumer
from agentmesh.queue.producer import JobProducer
from agentmesh.queue.streams import JobMessage, ResultMessage
from agentmesh.tools.base import ToolContext, ToolResult
from agentmesh.tools.registry import ToolRegistry, default_registry
from agentmesh.worker.health import WorkerHealth

log = structlog.get_logger(__name__)


def _default_worker_id() -> str:
    """Build a reasonably unique worker identifier: hostname-pid-random."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


class WorkerProcess:
    """Long-running process that pulls jobs from the Redis task stream and executes them.

    Usage::

        worker = WorkerProcess()
        asyncio.run(worker.run())

    Args:
        worker_id: Unique consumer name within the ``workers`` group. Auto-generated if omitted.
        redis:     An existing async Redis client to reuse (mainly for tests with fakeredis).
                   If omitted, a client is created from ``settings.redis_url`` and closed on exit.
        registry:  ToolRegistry to resolve tool names against. Defaults to the global registry.
    """

    def __init__(
        self,
        worker_id: str | None = None,
        redis: Redis | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self._settings = get_settings()
        self._worker_id = worker_id or _default_worker_id()
        self._redis = redis
        self._owns_redis = redis is None
        self._registry = registry or default_registry
        self._semaphore = asyncio.Semaphore(self._settings.worker_concurrency)
        self._active_tasks = 0
        self._stopping = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def stop(self) -> None:
        """Signal the worker to stop after the current poll cycle."""
        self._stopping = True

    async def run(self, *, max_iterations: int | None = None) -> None:
        """Main loop: connect, register the consumer group, and process jobs until stopped.

        Args:
            max_iterations: If set, stop after this many poll cycles. Used by tests
                             to run a bounded number of iterations instead of forever.
        """
        if self._redis is None:
            self._redis = aioredis.from_url(self._settings.redis_url, decode_responses=True)

        producer = JobProducer(self._redis)
        consumer = JobConsumer(self._redis, consumer_id=self._worker_id)
        health = WorkerHealth(self._redis, self._worker_id)

        await producer.ensure_consumer_group()
        log.info("Worker starting", worker_id=self._worker_id)

        in_flight: set[asyncio.Task] = set()
        last_claim_check = 0.0
        last_heartbeat = 0.0
        iterations = 0

        try:
            while not self._stopping:
                now = time.monotonic()

                if now - last_heartbeat >= 1.0:
                    await health.heartbeat(
                        status="busy" if self._active_tasks else "idle",
                        active_tasks=self._active_tasks,
                    )
                    last_heartbeat = now

                # Reclaim jobs abandoned by crashed/stalled consumers.
                if now - last_claim_check >= self._settings.worker_heartbeat_interval:
                    claimed = await consumer.claim_pending()
                    for msg_id, job in claimed:
                        in_flight.add(asyncio.create_task(
                            self._handle_job(msg_id, job, consumer, producer, health)
                        ))
                    last_claim_check = now

                jobs = await consumer.read_jobs(count=self._settings.worker_concurrency, block_ms=1000)
                for msg_id, job in jobs:
                    in_flight.add(asyncio.create_task(
                        self._handle_job(msg_id, job, consumer, producer, health)
                    ))

                if in_flight:
                    done = {t for t in in_flight if t.done()}
                    for t in done:
                        exc = t.exception()
                        if exc:
                            log.error("In-flight job task raised", error=str(exc))
                    in_flight -= done

                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break

            # Drain any still-running jobs before shutting down.
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
        finally:
            await health.deregister()
            if self._owns_redis:
                await self._redis.close()
            log.info("Worker stopped", worker_id=self._worker_id)

    async def _handle_job(
        self,
        msg_id: str,
        job: JobMessage,
        consumer: JobConsumer,
        producer: JobProducer,
        health: WorkerHealth,
    ) -> None:
        """Execute a single job end-to-end: run tool → persist → publish result → ack."""
        async with self._semaphore:
            self._active_tasks += 1
            try:
                await self._mark_running(job)
                result = await self._execute(job)

                if result.status == "SUCCESS":
                    await self._persist_success(job, result)

                await producer.publish_result(ResultMessage(
                    workflow_id=job.workflow_id,
                    task_key=job.task_key,
                    task_id=job.task_id,
                    status=result.status,
                    data=result.data,
                    error=result.error,
                    duration_ms=result.duration_ms,
                    attempt=job.attempt,
                ))
                await consumer.ack(msg_id)
                health.record_task_processed()
            except Exception as exc:
                log.exception("Worker failed to process job", task_key=job.task_key, error=str(exc))
                try:
                    await producer.publish_result(ResultMessage(
                        workflow_id=job.workflow_id,
                        task_key=job.task_key,
                        task_id=job.task_id,
                        status="ERROR",
                        error=f"Worker error: {exc}",
                        attempt=job.attempt,
                    ))
                    await consumer.ack(msg_id)
                except Exception:
                    log.exception("Failed to report worker error", task_key=job.task_key)
            finally:
                self._active_tasks -= 1

    async def _execute(self, job: JobMessage) -> ToolResult:
        """Resolve the tool and run it with a timeout, returning a ToolResult."""
        try:
            tool = self._registry.get(job.tool_name)
        except Exception as exc:
            return ToolResult.failure(error=str(exc))

        dependencies = {
            dep_key: ToolResult.success(data=data)
            for dep_key, data in job.dependency_results.items()
        }
        context = ToolContext(
            params=job.params,
            dependencies=dependencies,
            workflow_id=job.workflow_id,
            task_key=job.task_key,
        )

        try:
            return await asyncio.wait_for(
                tool.safe_execute(context),
                timeout=job.timeout_seconds or None,
            )
        except asyncio.TimeoutError:
            return ToolResult.failure(
                error=f"Task '{job.task_key}' timed out after {job.timeout_seconds}s"
            )

    async def _mark_running(self, job: JobMessage) -> None:
        """Flag the task as RUNNING in PostgreSQL once execution actually starts."""
        task_uuid = _parse_task_id(job.task_id)
        if task_uuid is None:
            return
        async with async_session_factory() as db:
            await update_task_status(db, task_uuid, TaskStatus.RUNNING)
            await db.commit()
        if self._redis is not None:
            # Fire-and-forget — see agentmesh.events.publish_event_nowait. This
            # runs concurrently with the main loop's blocking XREADGROUP reads
            # on the same client, so it must not be awaited inline.
            publish_event_nowait(self._redis, job.workflow_id, {
                "type": "task_update", "workflow_id": job.workflow_id,
                "task_key": job.task_key, "status": TaskStatus.RUNNING.value,
            })

    async def _persist_success(self, job: JobMessage, result: ToolResult) -> None:
        """Persist the TaskResult row for a successful execution."""
        task_uuid = _parse_task_id(job.task_id)
        if task_uuid is None:
            return
        async with async_session_factory() as db:
            await save_task_result(db, task_uuid, result)
            await db.commit()


def _parse_task_id(task_id: str) -> uuid.UUID | None:
    if not task_id:
        return None
    try:
        return uuid.UUID(task_id)
    except ValueError:
        return None
