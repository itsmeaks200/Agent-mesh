"""Redis Stream key constants, message dataclasses, and serialization helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


# ── Stream Keys (defaults — overridden by Settings in production) ─────────────

TASK_STREAM = "agentmesh:tasks"
RESULT_STREAM_PREFIX = "agentmesh:results:"
DEAD_LETTER_STREAM = "agentmesh:dead-letter"
CONSUMER_GROUP = "workers"


# ── Message Dataclasses ───────────────────────────────────────────────────────


@dataclass
class JobMessage:
    """A task dispatched to a worker via the Redis task stream.

    All fields are required so a worker can execute the task entirely
    from this message without querying the database.
    """

    workflow_id: str
    task_key: str
    tool_name: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    dependency_results: dict = field(default_factory=dict)  # task_key → ToolResult.data
    max_retries: int = 3
    attempt: int = 0
    timeout_seconds: int = 300
    task_id: str = ""  # DB UUID, for status updates


@dataclass
class ResultMessage:
    """A task result published by a worker back to the coordinator."""

    workflow_id: str
    task_key: str
    task_id: str
    status: str          # "SUCCESS" or "ERROR"
    data: dict | None = None
    error: str | None = None
    duration_ms: int = 0
    attempt: int = 0


# ── Serialization ─────────────────────────────────────────────────────────────
# Redis Streams store values as flat string→string dicts.
# We JSON-encode nested structures (params, data, etc.)


def serialize_job(job: JobMessage) -> dict[str, str]:
    """Serialize a JobMessage to a flat Redis field dict."""
    return {
        "workflow_id": job.workflow_id,
        "task_key": job.task_key,
        "tool_name": job.tool_name,
        "params": json.dumps(job.params),
        "depends_on": json.dumps(job.depends_on),
        "dependency_results": json.dumps(job.dependency_results),
        "max_retries": str(job.max_retries),
        "attempt": str(job.attempt),
        "timeout_seconds": str(job.timeout_seconds),
        "task_id": job.task_id,
    }


def deserialize_job(fields: dict) -> JobMessage:
    """Deserialize a Redis field dict back to a JobMessage."""
    # Redis may return bytes or strings depending on decode_responses setting
    def s(v): return v.decode() if isinstance(v, bytes) else v
    def i(v): return int(s(v))
    def j(v): return json.loads(s(v))

    return JobMessage(
        workflow_id=s(fields[b"workflow_id" if b"workflow_id" in fields else "workflow_id"]),
        task_key=s(fields.get(b"task_key", fields.get("task_key", ""))),
        tool_name=s(fields.get(b"tool_name", fields.get("tool_name", ""))),
        params=j(fields.get(b"params", fields.get("params", "{}"))),
        depends_on=j(fields.get(b"depends_on", fields.get("depends_on", "[]"))),
        dependency_results=j(fields.get(b"dependency_results", fields.get("dependency_results", "{}"))),
        max_retries=i(fields.get(b"max_retries", fields.get("max_retries", "3"))),
        attempt=i(fields.get(b"attempt", fields.get("attempt", "0"))),
        timeout_seconds=i(fields.get(b"timeout_seconds", fields.get("timeout_seconds", "300"))),
        task_id=s(fields.get(b"task_id", fields.get("task_id", ""))),
    )


def serialize_result(result: ResultMessage) -> dict[str, str]:
    """Serialize a ResultMessage to a flat Redis field dict."""
    return {
        "workflow_id": result.workflow_id,
        "task_key": result.task_key,
        "task_id": result.task_id,
        "status": result.status,
        "data": json.dumps(result.data) if result.data is not None else "null",
        "error": result.error or "",
        "duration_ms": str(result.duration_ms),
        "attempt": str(result.attempt),
    }


def deserialize_result(fields: dict) -> ResultMessage:
    """Deserialize a Redis field dict back to a ResultMessage."""
    def s(v): return v.decode() if isinstance(v, bytes) else v
    def i(v): return int(s(v))
    def j(v):
        raw = s(v)
        return json.loads(raw) if raw and raw != "null" else None

    return ResultMessage(
        workflow_id=s(fields.get(b"workflow_id", fields.get("workflow_id", ""))),
        task_key=s(fields.get(b"task_key", fields.get("task_key", ""))),
        task_id=s(fields.get(b"task_id", fields.get("task_id", ""))),
        status=s(fields.get(b"status", fields.get("status", "ERROR"))),
        data=j(fields.get(b"data", fields.get("data", "null"))),
        error=s(fields.get(b"error", fields.get("error", ""))) or None,
        duration_ms=i(fields.get(b"duration_ms", fields.get("duration_ms", "0"))),
        attempt=i(fields.get(b"attempt", fields.get("attempt", "0"))),
    )
