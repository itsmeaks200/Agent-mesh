"""Tests for WorkflowGraph DAG data structure."""

import pytest

from agentmesh.compiler.graph import WorkflowGraph


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _build_linear_graph() -> WorkflowGraph:
    """A → B → C"""
    g = WorkflowGraph()
    g.add_task("A", "echo")
    g.add_task("B", "echo")
    g.add_task("C", "echo")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    return g


def _build_diamond_graph() -> WorkflowGraph:
    """A → B, A → C, B+C → D"""
    g = WorkflowGraph()
    g.add_task("A", "echo")
    g.add_task("B", "http")
    g.add_task("C", "llm")
    g.add_task("D", "echo")
    g.add_edge("A", "B")
    g.add_edge("A", "C")
    g.add_edge("B", "D")
    g.add_edge("C", "D")
    return g


def _build_parallel_roots() -> WorkflowGraph:
    """A, B (independent) → C"""
    g = WorkflowGraph()
    g.add_task("A", "http")
    g.add_task("B", "http")
    g.add_task("C", "llm")
    g.add_edge("A", "C")
    g.add_edge("B", "C")
    return g


def _build_single_task() -> WorkflowGraph:
    g = WorkflowGraph()
    g.add_task("only", "echo")
    return g


# ── get_ready_tasks ──────────────────────────────────────────────────────────


class TestGetReadyTasks:
    def test_empty_completed_returns_roots(self):
        g = _build_diamond_graph()
        assert g.get_ready_tasks(set()) == ["A"]

    def test_after_root_completed(self):
        g = _build_diamond_graph()
        ready = g.get_ready_tasks({"A"})
        assert sorted(ready) == ["B", "C"]

    def test_after_one_branch_completed(self):
        g = _build_diamond_graph()
        # Only B is done — D still needs C
        ready = g.get_ready_tasks({"A", "B"})
        assert ready == ["C"]

    def test_after_both_branches_completed(self):
        g = _build_diamond_graph()
        ready = g.get_ready_tasks({"A", "B", "C"})
        assert ready == ["D"]

    def test_all_completed_returns_empty(self):
        g = _build_diamond_graph()
        assert g.get_ready_tasks({"A", "B", "C", "D"}) == []

    def test_parallel_roots(self):
        g = _build_parallel_roots()
        ready = g.get_ready_tasks(set())
        assert sorted(ready) == ["A", "B"]

    def test_single_task_ready(self):
        g = _build_single_task()
        assert g.get_ready_tasks(set()) == ["only"]

    def test_single_task_completed(self):
        g = _build_single_task()
        assert g.get_ready_tasks({"only"}) == []


# ── get_execution_order ──────────────────────────────────────────────────────


class TestGetExecutionOrder:
    def test_linear_order(self):
        g = _build_linear_graph()
        levels = g.get_execution_order()
        assert levels == [["A"], ["B"], ["C"]]

    def test_diamond_order(self):
        g = _build_diamond_graph()
        levels = g.get_execution_order()
        assert len(levels) == 3
        assert levels[0] == ["A"]
        assert sorted(levels[1]) == ["B", "C"]
        assert levels[2] == ["D"]

    def test_parallel_roots_order(self):
        g = _build_parallel_roots()
        levels = g.get_execution_order()
        assert len(levels) == 2
        assert sorted(levels[0]) == ["A", "B"]
        assert levels[1] == ["C"]

    def test_single_task_order(self):
        g = _build_single_task()
        levels = g.get_execution_order()
        assert levels == [["only"]]


# ── topological_sort ─────────────────────────────────────────────────────────


class TestTopologicalSort:
    def test_linear_sort(self):
        g = _build_linear_graph()
        assert g.topological_sort() == ["A", "B", "C"]

    def test_diamond_sort_valid_ordering(self):
        g = _build_diamond_graph()
        order = g.topological_sort()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_single_task_sort(self):
        g = _build_single_task()
        assert g.topological_sort() == ["only"]


# ── Serialization ────────────────────────────────────────────────────────────


class TestSerialization:
    def test_roundtrip(self):
        original = _build_diamond_graph()
        data = original.to_dict()
        restored = WorkflowGraph.from_dict(data)

        assert restored.node_count == original.node_count
        assert sorted(restored.task_keys) == sorted(original.task_keys)
        assert restored.get_execution_order() == original.get_execution_order()

    def test_to_dict_structure(self):
        g = _build_linear_graph()
        data = g.to_dict()
        assert "nodes" in data
        assert "edges" in data
        assert "A" in data["nodes"]
        assert data["nodes"]["A"]["tool_name"] == "echo"
        assert "B" in data["edges"]["A"]

    def test_params_preserved(self):
        g = WorkflowGraph()
        g.add_task("fetch", "http", params={"url": "https://example.com"})
        data = g.to_dict()
        restored = WorkflowGraph.from_dict(data)
        assert restored.get_node("fetch").params == {"url": "https://example.com"}


# ── Properties ───────────────────────────────────────────────────────────────


class TestProperties:
    def test_node_count(self):
        g = _build_diamond_graph()
        assert g.node_count == 4

    def test_task_keys(self):
        g = _build_diamond_graph()
        assert g.task_keys == ["A", "B", "C", "D"]

    def test_dependencies_of(self):
        g = _build_diamond_graph()
        assert g.dependencies_of("D") == ["B", "C"]
        assert g.dependencies_of("A") == []

    def test_dependents_of(self):
        g = _build_diamond_graph()
        assert sorted(g.dependents_of("A")) == ["B", "C"]
        assert g.dependents_of("D") == []

    def test_repr(self):
        g = _build_diamond_graph()
        r = repr(g)
        assert "nodes=4" in r
        assert "edges=4" in r
