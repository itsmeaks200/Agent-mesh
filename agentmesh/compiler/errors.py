"""Compilation error types with actionable messages."""

from __future__ import annotations


class CompilationError(Exception):
    """Base error raised when workflow compilation fails.

    Attributes:
        code: Machine-readable error code.
        message: Human-readable description.
        details: Structured data about the error (paths, ids, etc.).
    """

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}

    def __repr__(self) -> str:
        return f"CompilationError(code={self.code!r}, message={self.message!r})"


class CycleDetectedError(CompilationError):
    """Raised when the workflow graph contains a cycle.

    The cycle path is included in details, e.g. ["A", "B", "C", "A"].
    """

    def __init__(self, cycle_path: list[str]) -> None:
        path_str = " → ".join(cycle_path)
        super().__init__(
            code="CYCLE_DETECTED",
            message=f"Cycle detected: {path_str}",
            details={"cycle_path": cycle_path},
        )
        self.cycle_path = cycle_path


class MissingDependencyError(CompilationError):
    """Raised when a task references a dependency that does not exist."""

    def __init__(self, task_id: str, missing_dep: str) -> None:
        super().__init__(
            code="MISSING_DEPENDENCY",
            message=f"Task '{task_id}' depends on '{missing_dep}' which does not exist",
            details={"task_id": task_id, "missing_dependency": missing_dep},
        )
        self.task_id = task_id
        self.missing_dep = missing_dep


class DuplicateTaskIdError(CompilationError):
    """Raised when two or more tasks share the same ID."""

    def __init__(self, duplicate_ids: list[str]) -> None:
        ids_str = ", ".join(f"'{d}'" for d in duplicate_ids)
        super().__init__(
            code="DUPLICATE_TASK_ID",
            message=f"Duplicate task IDs found: {ids_str}",
            details={"duplicate_ids": duplicate_ids},
        )
        self.duplicate_ids = duplicate_ids


class UnknownToolError(CompilationError):
    """Raised when a task references a tool that is not registered."""

    def __init__(self, task_id: str, tool_name: str, known_tools: list[str]) -> None:
        super().__init__(
            code="UNKNOWN_TOOL",
            message=f"Task '{task_id}' uses unknown tool '{tool_name}'",
            details={
                "task_id": task_id,
                "tool_name": tool_name,
                "known_tools": known_tools,
            },
        )
        self.task_id = task_id
        self.tool_name = tool_name


class SchemaValidationError(CompilationError):
    """Raised when task specifications fail schema-level validation."""

    def __init__(self, errors: list[dict]) -> None:
        count = len(errors)
        super().__init__(
            code="SCHEMA_VALIDATION_ERROR",
            message=f"{count} schema validation error(s) found",
            details={"errors": errors},
        )
        self.errors = errors


class MultipleCompilationErrors(CompilationError):
    """Container for multiple compilation errors collected during validation."""

    def __init__(self, errors: list[CompilationError]) -> None:
        messages = "; ".join(e.message for e in errors)
        super().__init__(
            code="MULTIPLE_ERRORS",
            message=f"{len(errors)} compilation error(s): {messages}",
            details={"errors": [e.to_dict() for e in errors]},
        )
        self.errors = errors
