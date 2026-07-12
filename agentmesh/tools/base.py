"""Core interfaces for the AgentMesh tool runtime.

Every tool implements BaseTool and receives a ToolContext, returning a ToolResult.
This interface is intentionally minimal — adding a new tool never changes the scheduler.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ToolResult:
    """The output of a tool execution.

    Attributes:
        status:      "SUCCESS" or "ERROR".
        data:        Output payload (arbitrary JSON-serializable dict).
        error:       Human-readable error message when status == "ERROR".
        duration_ms: Wall-clock execution time in milliseconds.
    """

    status: Literal["SUCCESS", "ERROR"]
    data: dict | None = None
    error: str | None = None
    duration_ms: int = 0

    @classmethod
    def success(cls, data: dict, duration_ms: int = 0) -> ToolResult:
        """Convenience constructor for a successful result."""
        return cls(status="SUCCESS", data=data, duration_ms=duration_ms)

    @classmethod
    def failure(cls, error: str, duration_ms: int = 0) -> ToolResult:
        """Convenience constructor for a failed result."""
        return cls(status="ERROR", error=error, duration_ms=duration_ms)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ToolContext:
    """Runtime context passed to every tool execution.

    Attributes:
        params:       Tool-specific parameters from the task spec.
        dependencies: Results from upstream tasks, keyed by task_key.
        workflow_id:  ID of the parent workflow.
        task_key:     Key of the task being executed.
    """

    params: dict = field(default_factory=dict)
    dependencies: dict[str, ToolResult] = field(default_factory=dict)
    workflow_id: str = ""
    task_key: str = ""

    def get_dependency(self, task_key: str) -> ToolResult | None:
        """Return the result of an upstream task, or None if not found."""
        return self.dependencies.get(task_key)

    def require_param(self, key: str) -> object:
        """Return a required parameter, raising ValueError if missing."""
        if key not in self.params:
            raise ValueError(f"Missing required parameter: '{key}'")
        return self.params[key]


class BaseTool(ABC):
    """Abstract base class for all AgentMesh tools.

    Subclasses must define:
        - ``name``: str  — unique registry key (e.g. "http", "llm")
        - ``description``: str  — used by the LLM planner in Phase 6
        - ``execute(context)``: async method that performs the tool's work

    Usage::

        class EchoTool(BaseTool):
            name = "echo"
            description = "Returns its input parameters as output."

            async def execute(self, context: ToolContext) -> ToolResult:
                return ToolResult.success(data=context.params)
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult:
        """Execute the tool with the given context.

        Args:
            context: Runtime context containing params and upstream results.

        Returns:
            A ToolResult with status SUCCESS or ERROR.
            Must NEVER raise — all errors should be caught and returned
            as ToolResult.failure(...).
        """
        ...

    async def safe_execute(self, context: ToolContext) -> ToolResult:
        """Wrapper around execute() that catches unexpected exceptions.

        Tools should handle their own errors internally, but this provides
        a safety net for the scheduler.
        """
        start = time.monotonic()
        try:
            result = await self.execute(context)
            if result.duration_ms == 0:
                result.duration_ms = int((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult.failure(
                error=f"Unexpected error in tool '{self.name}': {exc}",
                duration_ms=duration_ms,
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
