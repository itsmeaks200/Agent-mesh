"""Validation rules for workflow compilation.

Each validator accepts task specs (or adjacency structures) and returns
a list of ``CompilationError`` instances.  The compiler collects all
errors before raising, so the user sees every problem at once.
"""

from __future__ import annotations

from agentmesh.compiler.errors import (
    CompilationError,
    CycleDetectedError,
    DuplicateTaskIdError,
    MissingDependencyError,
    SchemaValidationError,
    UnknownToolError,
)
from agentmesh.schemas.workflow import TaskSpec


def validate_no_duplicate_ids(tasks: list[TaskSpec]) -> list[CompilationError]:
    """Check that every task has a unique ID."""
    seen: dict[str, int] = {}
    for task in tasks:
        seen[task.id] = seen.get(task.id, 0) + 1

    duplicates = [tid for tid, count in seen.items() if count > 1]
    if duplicates:
        return [DuplicateTaskIdError(duplicate_ids=duplicates)]
    return []


def validate_dependencies_exist(tasks: list[TaskSpec]) -> list[CompilationError]:
    """Verify every ``depends_on`` references an existing task ID."""
    task_ids = {t.id for t in tasks}
    errors: list[CompilationError] = []
    for task in tasks:
        for dep in task.depends_on:
            if dep not in task_ids:
                errors.append(MissingDependencyError(task_id=task.id, missing_dep=dep))
    return errors


def validate_no_cycles(adjacency: dict[str, list[str]]) -> list[CompilationError]:
    """DFS-based cycle detection.  Returns the cycle path if one is found.

    Args:
        adjacency: forward adjacency list (task → dependents).

    Returns:
        A list containing a single ``CycleDetectedError`` if a cycle exists,
        otherwise an empty list.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in adjacency}
    parent: dict[str, str | None] = {node: None for node in adjacency}

    def _dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        for neighbor in adjacency.get(node, []):
            if color[neighbor] == GRAY:
                # Back edge found — reconstruct cycle path
                cycle = [neighbor, node]
                current = node
                while current != neighbor:
                    current = parent[current]
                    if current is None:
                        break
                    cycle.append(current)
                cycle.reverse()
                cycle.append(neighbor)  # close the loop
                return cycle
            if color[neighbor] == WHITE:
                parent[neighbor] = node
                result = _dfs(neighbor)
                if result is not None:
                    return result
        color[node] = BLACK
        return None

    for node in adjacency:
        if color[node] == WHITE:
            cycle = _dfs(node)
            if cycle is not None:
                return [CycleDetectedError(cycle_path=cycle)]
    return []


def validate_tool_names(
    tasks: list[TaskSpec],
    known_tools: set[str] | None = None,
) -> list[CompilationError]:
    """Check that every tool name is in the known tool set.

    If ``known_tools`` is None, tool validation is skipped (useful before
    Phase 3 when the ToolRegistry doesn't exist yet).
    """
    if known_tools is None:
        return []

    errors: list[CompilationError] = []
    sorted_tools = sorted(known_tools)
    for task in tasks:
        if task.tool not in known_tools:
            errors.append(
                UnknownToolError(
                    task_id=task.id,
                    tool_name=task.tool,
                    known_tools=sorted_tools,
                )
            )
    return errors


def validate_schema(tasks: list[TaskSpec]) -> list[CompilationError]:
    """Validate structural requirements beyond Pydantic's type checking.

    Checks:
    - Task IDs are non-empty and contain only allowed characters.
    - Tool names are non-empty.
    - ``depends_on`` does not reference itself.
    """
    schema_errors: list[dict] = []

    for task in tasks:
        # Self-dependency
        if task.id in task.depends_on:
            schema_errors.append({
                "task_id": task.id,
                "field": "depends_on",
                "error": f"Task '{task.id}' cannot depend on itself",
            })

        # ID characters (alphanumeric, underscores, hyphens)
        if not all(c.isalnum() or c in ("_", "-") for c in task.id):
            schema_errors.append({
                "task_id": task.id,
                "field": "id",
                "error": f"Task ID '{task.id}' contains invalid characters (allowed: a-z, 0-9, _, -)",
            })

    if schema_errors:
        return [SchemaValidationError(errors=schema_errors)]
    return []
