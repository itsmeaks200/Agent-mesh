"""WorkflowCompiler — validates a task specification and builds an executable DAG.

Usage:
    compiler = WorkflowCompiler(known_tools={"http", "llm", "echo"})
    graph = compiler.compile(task_specs)
    order = graph.get_execution_order()
"""

from __future__ import annotations

from agentmesh.compiler.errors import CompilationError, MultipleCompilationErrors
from agentmesh.compiler.graph import WorkflowGraph
from agentmesh.compiler.validator import (
    validate_dependencies_exist,
    validate_no_cycles,
    validate_no_duplicate_ids,
    validate_schema,
    validate_tool_names,
)
from agentmesh.schemas.workflow import TaskSpec


class WorkflowCompiler:
    """Compiles a list of ``TaskSpec`` into a ``WorkflowGraph``.

    Validation pipeline (run in order, all errors collected):
    1. Schema validation (field constraints, self-dependency).
    2. Duplicate task ID check.
    3. Missing dependency references.
    4. Unknown tool names (optional — requires known_tools).
    5. Cycle detection (DFS on the constructed adjacency list).

    Args:
        known_tools: Optional set of tool names for validation.
            When ``None``, tool-name validation is skipped.
            Will be wired to ``ToolRegistry`` in Phase 3.
    """

    def __init__(self, known_tools: set[str] | None = None) -> None:
        self._known_tools = known_tools

    def compile(self, tasks: list[TaskSpec]) -> WorkflowGraph:
        """Validate the task specs and build an executable DAG.

        Args:
            tasks: List of task specifications from the API request.

        Returns:
            A ``WorkflowGraph`` instance ready for scheduling.

        Raises:
            CompilationError: If a single validation error is found.
            MultipleCompilationErrors: If multiple validation errors are found.
        """
        errors: list[CompilationError] = []

        # 1. Schema validation
        errors.extend(validate_schema(tasks))

        # 2. Duplicate IDs
        errors.extend(validate_no_duplicate_ids(tasks))

        # 3. Missing dependencies
        errors.extend(validate_dependencies_exist(tasks))

        # 4. Tool names
        errors.extend(validate_tool_names(tasks, self._known_tools))

        # Build adjacency list for cycle detection
        # Edge: dependency → dependent (from_task must finish before to_task)
        task_ids = {t.id for t in tasks}
        adjacency: dict[str, list[str]] = {t.id: [] for t in tasks}
        for task in tasks:
            for dep in task.depends_on:
                if dep in task_ids:  # Only add edges for valid deps
                    adjacency[dep].append(task.id)

        # 5. Cycle detection
        errors.extend(validate_no_cycles(adjacency))

        # Raise collected errors
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise MultipleCompilationErrors(errors)

        # Build the graph
        graph = WorkflowGraph()
        for task in tasks:
            graph.add_task(task_key=task.id, tool_name=task.tool, params=task.params)

        for task in tasks:
            for dep in task.depends_on:
                # Edge: dep → task.id (dep must complete before task runs)
                graph.add_edge(from_task=dep, to_task=task.id)

        return graph
