"""WorkflowGraph — DAG data structure for compiled workflows.

Stores tasks and their dependency edges as an adjacency list.
Provides topological sorting, execution-order leveling, and
ready-task queries used by the scheduler.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class TaskNode:
    """Metadata for a single task within the graph."""

    task_key: str
    tool_name: str
    params: dict = field(default_factory=dict)


class WorkflowGraph:
    """Directed Acyclic Graph representing a compiled workflow.

    Internal representation:
        - ``_nodes``:   dict[task_key → TaskNode]
        - ``_adj``:     dict[task_key → list[task_key]]   (forward edges)
        - ``_rev_adj``: dict[task_key → list[task_key]]   (reverse edges / dependencies)
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._adj: dict[str, list[str]] = {}        # task → list of dependents
        self._rev_adj: dict[str, list[str]] = {}     # task → list of dependencies

    # ── Construction ─────────────────────────────────────────────────────

    def add_task(self, task_key: str, tool_name: str, params: dict | None = None) -> None:
        """Register a task node in the graph."""
        node = TaskNode(task_key=task_key, tool_name=tool_name, params=params or {})
        self._nodes[task_key] = node
        self._adj.setdefault(task_key, [])
        self._rev_adj.setdefault(task_key, [])

    def add_edge(self, from_task: str, to_task: str) -> None:
        """Add a dependency edge: ``to_task`` depends on ``from_task``.

        This means ``from_task`` must complete before ``to_task`` can start.
        """
        self._adj[from_task].append(to_task)
        self._rev_adj[to_task].append(from_task)

    # ── Queries ──────────────────────────────────────────────────────────

    @property
    def task_keys(self) -> list[str]:
        """Return all task keys in insertion order."""
        return list(self._nodes.keys())

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def get_node(self, task_key: str) -> TaskNode:
        return self._nodes[task_key]

    def dependencies_of(self, task_key: str) -> list[str]:
        """Return the list of task keys that ``task_key`` depends on."""
        return list(self._rev_adj.get(task_key, []))

    def dependents_of(self, task_key: str) -> list[str]:
        """Return the list of task keys that depend on ``task_key``."""
        return list(self._adj.get(task_key, []))

    # ── Scheduling Helpers ───────────────────────────────────────────────

    def get_ready_tasks(self, completed: set[str]) -> list[str]:
        """Return task keys whose dependencies are all satisfied.

        A task is ready if:
        1. It is not yet completed.
        2. All of its dependencies are in the ``completed`` set.
        """
        ready = []
        for key in self._nodes:
            if key in completed:
                continue
            deps = self._rev_adj.get(key, [])
            if all(dep in completed for dep in deps):
                ready.append(key)
        return ready

    def get_execution_order(self) -> list[list[str]]:
        """Return tasks grouped by topological level (parallel batches).

        Level 0 = root tasks (no dependencies).
        Level N = tasks whose latest dependency is at level N-1.

        Uses Kahn's algorithm (BFS-based topological sort).
        """
        in_degree: dict[str, int] = {k: len(self._rev_adj.get(k, [])) for k in self._nodes}
        queue: deque[str] = deque(k for k, d in in_degree.items() if d == 0)
        levels: list[list[str]] = []

        while queue:
            # All tasks currently in the queue belong to the same level
            level: list[str] = []
            for _ in range(len(queue)):
                task = queue.popleft()
                level.append(task)
                for dependent in self._adj.get(task, []):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)
            levels.append(level)

        return levels

    def topological_sort(self) -> list[str]:
        """Return a full linear topological ordering of all tasks."""
        result: list[str] = []
        for level in self.get_execution_order():
            result.extend(level)
        return result

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the graph to a dict (suitable for JSONB storage)."""
        return {
            "nodes": {
                key: {
                    "task_key": node.task_key,
                    "tool_name": node.tool_name,
                    "params": node.params,
                }
                for key, node in self._nodes.items()
            },
            "edges": {
                key: list(deps) for key, deps in self._adj.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowGraph:
        """Reconstruct a WorkflowGraph from a serialized dict."""
        graph = cls()
        for key, node_data in data["nodes"].items():
            graph.add_task(
                task_key=node_data["task_key"],
                tool_name=node_data["tool_name"],
                params=node_data.get("params", {}),
            )
        for from_task, dependents in data["edges"].items():
            for to_task in dependents:
                graph.add_edge(from_task, to_task)
        return graph

    def __repr__(self) -> str:
        edge_count = sum(len(v) for v in self._adj.values())
        return f"<WorkflowGraph nodes={self.node_count} edges={edge_count}>"
