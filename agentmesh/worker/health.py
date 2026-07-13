"""WorkerHealth — publishes and queries worker heartbeats via Redis hashes.

Each worker process writes its status to a Redis hash key on a timer. A TTL
(slightly longer than the heartbeat interval) is set on every write, so a
crashed worker's key disappears from Redis on its own — no separate staleness
bookkeeping is required. ``GET /api/v1/workers`` simply scans for live keys.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

from agentmesh.config import get_settings

WORKER_KEY_PREFIX = "agentmesh:worker:"


class WorkerHealth:
    """Reports and reads worker status stored in Redis hashes.

    Args:
        redis:     An async Redis client instance.
        worker_id: Unique identifier for this worker (e.g. ``hostname-pid``).
    """

    def __init__(self, redis: Redis, worker_id: str) -> None:
        self._redis = redis
        self._worker_id = worker_id
        self._settings = get_settings()
        self._started_at = time.time()
        self._tasks_processed = 0

    @property
    def key(self) -> str:
        return f"{WORKER_KEY_PREFIX}{self._worker_id}"

    def record_task_processed(self) -> None:
        """Increment the lifetime task counter (reflected on the next heartbeat)."""
        self._tasks_processed += 1

    async def heartbeat(self, status: str = "idle", active_tasks: int = 0) -> None:
        """Write current status to Redis with a TTL so crashed workers vanish automatically."""
        fields = {
            "worker_id": self._worker_id,
            "status": status,
            "active_tasks": str(active_tasks),
            "tasks_processed": str(self._tasks_processed),
            "started_at": str(self._started_at),
            "last_heartbeat": str(time.time()),
        }
        await self._redis.hset(self.key, mapping=fields)
        await self._redis.expire(self.key, self._settings.worker_heartbeat_interval * 3)

    async def deregister(self) -> None:
        """Remove this worker's status key (called on graceful shutdown)."""
        await self._redis.delete(self.key)

    @staticmethod
    async def list_workers(redis: Redis) -> list[dict]:
        """Return status dicts for every worker currently reporting a heartbeat."""
        keys: list[str] = []
        async for key in redis.scan_iter(match=f"{WORKER_KEY_PREFIX}*"):
            keys.append(key.decode() if isinstance(key, bytes) else key)

        now = time.time()
        workers: list[dict] = []
        for key in keys:
            data = await redis.hgetall(key)
            if not data:
                continue

            def g(field: str, default: str = "") -> str:
                raw = data.get(field, data.get(field.encode(), default))
                return raw.decode() if isinstance(raw, bytes) else raw

            last_heartbeat = float(g("last_heartbeat", "0") or 0)
            workers.append({
                "worker_id": g("worker_id", key.removeprefix(WORKER_KEY_PREFIX)),
                "status": g("status", "unknown"),
                "active_tasks": int(g("active_tasks", "0") or 0),
                "tasks_processed": int(g("tasks_processed", "0") or 0),
                "started_at": float(g("started_at", "0") or 0),
                "last_heartbeat": last_heartbeat,
                "seconds_since_heartbeat": round(now - last_heartbeat, 1) if last_heartbeat else None,
            })

        workers.sort(key=lambda w: w["worker_id"])
        return workers
