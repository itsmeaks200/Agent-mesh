"""JobConsumer — reads jobs and results from Redis Streams."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from agentmesh.config import get_settings
from agentmesh.queue.streams import (
    JobMessage,
    ResultMessage,
    deserialize_job,
    deserialize_result,
)

log = logging.getLogger(__name__)


class JobConsumer:
    """Reads jobs from the task stream and results from per-workflow result streams.

    Args:
        redis:       An async Redis client instance.
        consumer_id: Unique name for this consumer within the group (e.g. ``hostname-pid``).
    """

    def __init__(self, redis: Redis, consumer_id: str) -> None:
        self._redis = redis
        self._consumer_id = consumer_id
        self._settings = get_settings()

    async def read_jobs(
        self,
        count: int = 1,
        block_ms: int = 2000,
    ) -> list[tuple[str, JobMessage]]:
        """Read new jobs from the task stream using XREADGROUP.

        Args:
            count:    Max number of messages to read.
            block_ms: How long to block waiting for messages (0 = non-blocking).

        Returns:
            List of ``(message_id, JobMessage)`` tuples.
        """
        response = await self._redis.xreadgroup(
            groupname=self._settings.consumer_group,
            consumername=self._consumer_id,
            streams={self._settings.task_stream_key: ">"},
            count=count,
            block=block_ms,
        )
        if not response:
            return []

        results = []
        for _stream, messages in response:
            for msg_id, fields in messages:
                mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                try:
                    job = deserialize_job(fields)
                    results.append((mid, job))
                except Exception as exc:
                    log.error("Failed to deserialize job msg_id=%s: %s", mid, exc)
        return results

    async def ack(self, message_id: str) -> None:
        """Acknowledge a message — removes it from the pending entry list."""
        await self._redis.xack(
            self._settings.task_stream_key,
            self._settings.consumer_group,
            message_id,
        )

    async def read_results(
        self,
        workflow_id: str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int | None = None,
    ) -> list[tuple[str, ResultMessage]]:
        """Read result messages from the per-workflow result stream.

        Args:
            workflow_id: The workflow whose results to read.
            last_id:     Only return messages with ID > last_id. Use ``"0"`` for all.
            count:       Max messages to return.
            block_ms:    If set, block for up to this many ms waiting for new
                         messages (like ``XREAD BLOCK``). ``None`` returns immediately.

        Returns:
            List of ``(message_id, ResultMessage)`` tuples, ordered oldest-first.
            Callers should track the last returned ``message_id`` and pass it back
            in as ``last_id`` on the next call to avoid re-processing messages.
        """
        stream_key = self._settings.result_stream_prefix + workflow_id
        kwargs: dict = {"streams": {stream_key: last_id}, "count": count}
        if block_ms is not None:
            kwargs["block"] = block_ms
        try:
            response = await self._redis.xread(**kwargs)
        except Exception:
            return []

        if not response:
            return []

        results = []
        for _stream, messages in response:
            for msg_id, fields in messages:
                mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                try:
                    results.append((mid, deserialize_result(fields)))
                except Exception as exc:
                    log.error("Failed to deserialize result: %s", exc)
        return results

    async def claim_pending(
        self,
        min_idle_ms: int | None = None,
        count: int = 10,
    ) -> list[tuple[str, JobMessage]]:
        """Claim pending messages that have been idle too long (crash recovery).

        Uses XAUTOCLAIM to take ownership of messages from crashed consumers.

        Args:
            min_idle_ms: Minimum idle time before claiming. Uses settings default if None.
            count:       Max messages to claim.

        Returns:
            List of ``(message_id, JobMessage)`` tuples.
        """
        idle = min_idle_ms if min_idle_ms is not None else self._settings.pending_claim_idle_ms

        try:
            response = await self._redis.xautoclaim(
                name=self._settings.task_stream_key,
                groupname=self._settings.consumer_group,
                consumername=self._consumer_id,
                min_idle_time=idle,
                start_id="0-0",
                count=count,
            )
        except Exception as exc:
            log.debug("xautoclaim not available or failed: %s", exc)
            return []

        # xautoclaim returns (next_start_id, [(msg_id, fields), ...], [deleted_ids])
        if not response or len(response) < 2:
            return []

        claimed = []
        messages = response[1]
        for msg_id, fields in messages:
            if not fields:
                continue
            mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            try:
                job = deserialize_job(fields)
                claimed.append((mid, job))
            except Exception as exc:
                log.error("Failed to deserialize claimed job: %s", exc)

        if claimed:
            log.info("Claimed %d pending messages", len(claimed))
        return claimed
