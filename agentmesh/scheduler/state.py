"""In-memory state representations for a workflow execution run.

These are pure dataclasses — no DB, no I/O. The scheduler uses them
to track which tasks are pending, running, or done without coupling
to SQLAlchemy models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentmesh.tools.base import ToolResult


@dataclass
class TaskRun:
    """In-memory representation of a task during execution.

    Mirrors the DB Task model but is decoupled from SQLAlchemy
    so the scheduler can be tested without a database.
    """

    task_key: str
    tool_name: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300


@dataclass
class ExecutionState:
    """Tracks the live state of all tasks during a scheduler run.

    Attributes:
        completed:  task_keys that finished successfully.
        failed:     task_keys that exhausted retries and failed.
        results:    ToolResult for every completed task (keyed by task_key).
        errors:     Final error message for every failed task.
    """

    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    results: dict[str, ToolResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def finished(self) -> set[str]:
        """All task_keys that are no longer runnable (completed or failed)."""
        return self.completed | self.failed

    def mark_completed(self, task_key: str, result: ToolResult) -> None:
        self.completed.add(task_key)
        self.results[task_key] = result

    def mark_failed(self, task_key: str, error: str) -> None:
        self.failed.add(task_key)
        self.errors[task_key] = error

    @property
    def has_failures(self) -> bool:
        return len(self.failed) > 0
