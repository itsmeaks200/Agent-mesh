"""Prometheus metrics for workflow and task execution.

Recording hooks are called from ``persistence.repository.update_task_status``
and ``update_workflow_status`` — the single choke point both the in-process
executor and the distributed coordinator/worker/recovery paths go through —
so every execution mode is covered without per-caller instrumentation.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

WORKFLOWS_TOTAL = Counter(
    "agentmesh_workflows_total",
    "Workflows reaching a terminal state, by status",
    ["status"],
)
TASKS_TOTAL = Counter(
    "agentmesh_tasks_total",
    "Tasks reaching a terminal state, by tool and status",
    ["tool", "status"],
)
WORKFLOW_DURATION_SECONDS = Histogram(
    "agentmesh_workflow_duration_seconds",
    "Workflow execution duration from start to terminal state",
)
TASK_DURATION_SECONDS = Histogram(
    "agentmesh_task_duration_seconds",
    "Task execution duration from start to terminal state, by tool",
    ["tool"],
)


def record_workflow_terminal(status: str, duration_ms: int | None) -> None:
    WORKFLOWS_TOTAL.labels(status=status).inc()
    if duration_ms is not None:
        WORKFLOW_DURATION_SECONDS.observe(duration_ms / 1000)


def record_task_terminal(tool_name: str, status: str, duration_ms: int | None) -> None:
    TASKS_TOTAL.labels(tool=tool_name, status=status).inc()
    if duration_ms is not None:
        TASK_DURATION_SECONDS.labels(tool=tool_name).observe(duration_ms / 1000)


def render_latest() -> tuple[bytes, str]:
    """Return (body, content_type) for a ``/metrics`` scrape response."""
    return generate_latest(), CONTENT_TYPE_LATEST
