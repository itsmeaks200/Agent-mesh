"""JobProducer — publishes jobs and results to Redis Streams."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from agentmesh.config import get_settings
from agentmesh.queue.streams import (
    JobMessage,
    ResultMessage,
    serialize_job,
    serialize_result,
)

log = logging.getLogger(__name__)


class JobProducer:
    """Publishes jobs and results to Redis Streams.

    Args:
        redis: An async Redis client instance.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._settings = get_settings()

    async def ensure_consumer_group(self) -> None:
        """Create the consumer group if it does not already exist.

        Uses ``XGROUP CREATE ... $ MKSTREAM`` so the stream is created
        automatically if Redis doesn't have it yet.
        """
        try:
            await self._redis.xgroup_create(
                name=self._settings.task_stream_key,
                groupname=self._settings.consumer_group,
                id="0",       # start from beginning — workers will see all pending
                mkstream=True,
            )
            log.info("Created consumer group '%s'", self._settings.consumer_group)
        except Exception as exc:
            # BUSYGROUP error means the group already exists — that's fine
            if "BUSYGROUP" in str(exc):
                log.debug("Consumer group already exists")
            else:
                raise

    async def publish(self, job: JobMessage) -> str:
        """Publish a job to the task stream.

        Returns:
            The Redis message ID (e.g. ``"1234567890123-0"``).
        """
        fields = serialize_job(job)
        msg_id = await self._redis.xadd(
            name=self._settings.task_stream_key,
            fields=fields,
            maxlen=self._settings.task_stream_max_len,
            approximate=True,
        )
        log.debug(
            "Published job task_key=%s workflow_id=%s msg_id=%s",
            job.task_key, job.workflow_id, msg_id,
        )
        return msg_id if isinstance(msg_id, str) else msg_id.decode()

    async def publish_result(self, result: ResultMessage) -> str:
        """Publish a task result to the per-workflow result stream.

        Stream key: ``agentmesh:results:{workflow_id}``
        """
        stream_key = self._settings.result_stream_prefix + result.workflow_id
        fields = serialize_result(result)
        msg_id = await self._redis.xadd(name=stream_key, fields=fields)
        log.debug(
            "Published result task_key=%s status=%s msg_id=%s",
            result.task_key, result.status, msg_id,
        )
        return msg_id if isinstance(msg_id, str) else msg_id.decode()

    async def publish_dead_letter(self, job: JobMessage, error: str) -> str:
        """Move a permanently failed job to the dead-letter stream."""
        fields = serialize_job(job)
        fields["final_error"] = error
        msg_id = await self._redis.xadd(
            name=self._settings.dead_letter_stream_key,
            fields=fields,
        )
        log.warning(
            "Dead-lettered task_key=%s workflow_id=%s error=%s",
            job.task_key, job.workflow_id, error,
        )
        return msg_id if isinstance(msg_id, str) else msg_id.decode()
