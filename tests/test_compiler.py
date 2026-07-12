"""Tests for WorkflowCompiler — validation pipeline and DAG construction."""

import pytest

from agentmesh.compiler import (
    CompilationError,
    CycleDetectedError,
    DuplicateTaskIdError,
    MissingDependencyError,
    MultipleCompilationErrors,
    SchemaValidationError,
    UnknownToolError,
    WorkflowCompiler,
)
from agentmesh.schemas.workflow import TaskSpec


# ── Helpers ──────────────────────────────────────────────────────────────────


def _spec(id: str, tool: str = "echo", depends_on: list[str] | None = None, **params) -> TaskSpec:
    return TaskSpec(id=id, tool=tool, params=params, depends_on=depends_on or [])


# ── Valid Workflows ──────────────────────────────────────────────────────────


class TestValidWorkflows:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_linear_dag(self):
        """A → B → C"""
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["B"]),
        ]
        graph = self.compiler.compile(tasks)
        assert graph.node_count == 3
        assert graph.topological_sort() == ["A", "B", "C"]

    def test_parallel_dag(self):
        """A → B, A → C, B+C → D"""
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["A"]),
            _spec("D", depends_on=["B", "C"]),
        ]
        graph = self.compiler.compile(tasks)
        assert graph.node_count == 4
        levels = graph.get_execution_order()
        assert len(levels) == 3
        assert sorted(levels[1]) == ["B", "C"]

    def test_diamond_dag(self):
        tasks = [
            _spec("fetch"),
            _spec("extract", depends_on=["fetch"]),
            _spec("transform", depends_on=["fetch"]),
            _spec("load", depends_on=["extract", "transform"]),
        ]
        graph = self.compiler.compile(tasks)
        ready = graph.get_ready_tasks(set())
        assert ready == ["fetch"]

    def test_single_task(self):
        tasks = [_spec("solo")]
        graph = self.compiler.compile(tasks)
        assert graph.node_count == 1
        assert graph.get_ready_tasks(set()) == ["solo"]

    def test_multiple_independent_tasks(self):
        tasks = [_spec("A"), _spec("B"), _spec("C")]
        graph = self.compiler.compile(tasks)
        levels = graph.get_execution_order()
        assert len(levels) == 1
        assert sorted(levels[0]) == ["A", "B", "C"]

    def test_complex_dag(self):
        """
        A → B → D → F
        A → C → E → F
        B → E
        """
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["A"]),
            _spec("D", depends_on=["B"]),
            _spec("E", depends_on=["C", "B"]),
            _spec("F", depends_on=["D", "E"]),
        ]
        graph = self.compiler.compile(tasks)
        order = graph.topological_sort()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("B") < order.index("E")
        assert order.index("C") < order.index("E")
        assert order.index("D") < order.index("F")
        assert order.index("E") < order.index("F")


# ── Cycle Detection ──────────────────────────────────────────────────────────


class TestCycleDetection:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_simple_cycle(self):
        """A → B → C → A"""
        tasks = [
            _spec("A", depends_on=["C"]),
            _spec("B", depends_on=["A"]),
            _spec("C", depends_on=["B"]),
        ]
        with pytest.raises(CycleDetectedError) as exc_info:
            self.compiler.compile(tasks)
        assert "Cycle detected" in str(exc_info.value)

    def test_two_node_cycle(self):
        """A ↔ B"""
        tasks = [
            _spec("A", depends_on=["B"]),
            _spec("B", depends_on=["A"]),
        ]
        with pytest.raises(CycleDetectedError):
            self.compiler.compile(tasks)

    def test_cycle_in_subgraph(self):
        """A (root) → B → C → B (cycle within subgraph)"""
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["A", "C"]),
            _spec("C", depends_on=["B"]),
        ]
        with pytest.raises(CycleDetectedError):
            self.compiler.compile(tasks)


# ── Missing Dependencies ─────────────────────────────────────────────────────


class TestMissingDependencies:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_missing_single_dep(self):
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["nonexistent"]),
        ]
        with pytest.raises(MissingDependencyError) as exc_info:
            self.compiler.compile(tasks)
        assert "nonexistent" in exc_info.value.message
        assert exc_info.value.task_id == "B"

    def test_missing_multiple_deps(self):
        tasks = [
            _spec("A", depends_on=["x"]),
            _spec("B", depends_on=["y"]),
        ]
        with pytest.raises((MissingDependencyError, MultipleCompilationErrors)):
            self.compiler.compile(tasks)


# ── Duplicate IDs ────────────────────────────────────────────────────────────


class TestDuplicateIds:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_duplicate_ids(self):
        tasks = [
            _spec("A"),
            _spec("A"),
        ]
        with pytest.raises(DuplicateTaskIdError) as exc_info:
            self.compiler.compile(tasks)
        assert "A" in exc_info.value.duplicate_ids


# ── Unknown Tools ────────────────────────────────────────────────────────────


class TestUnknownTools:
    def test_unknown_tool_with_whitelist(self):
        compiler = WorkflowCompiler(known_tools={"echo", "http"})
        tasks = [_spec("A", tool="unknown_tool")]
        with pytest.raises(UnknownToolError) as exc_info:
            compiler.compile(tasks)
        assert exc_info.value.tool_name == "unknown_tool"

    def test_valid_tool_with_whitelist(self):
        compiler = WorkflowCompiler(known_tools={"echo", "http"})
        tasks = [_spec("A", tool="echo")]
        graph = compiler.compile(tasks)
        assert graph.node_count == 1

    def test_explicit_none_skips_tool_validation(self):
        """Passing known_tools=None explicitly skips tool validation."""
        compiler = WorkflowCompiler(known_tools=None)
        tasks = [_spec("A", tool="anything_goes")]
        graph = compiler.compile(tasks)
        assert graph.node_count == 1

    def test_default_validates_against_registry(self):
        """Default compiler rejects tools not in the registry."""
        compiler = WorkflowCompiler()  # uses default_registry
        tasks = [_spec("A", tool="anything_goes")]
        with pytest.raises(UnknownToolError):
            compiler.compile(tasks)

    def test_default_accepts_builtin_tools(self):
        """Default compiler accepts all built-in tool names."""
        compiler = WorkflowCompiler()
        tasks = [_spec("A", tool="echo"), _spec("B", tool="http", depends_on=["A"])]
        graph = compiler.compile(tasks)
        assert graph.node_count == 2


# ── Schema Validation ────────────────────────────────────────────────────────


class TestSchemaValidation:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_self_dependency(self):
        tasks = [_spec("A", depends_on=["A"])]
        with pytest.raises((SchemaValidationError, MultipleCompilationErrors)) as exc_info:
            self.compiler.compile(tasks)
        err = exc_info.value
        # Self-dependency triggers both schema validation AND cycle detection.
        # The schema error about self-dep should be present in either case.
        if isinstance(err, MultipleCompilationErrors):
            codes = [e.code for e in err.errors]
            assert "SCHEMA_VALIDATION_ERROR" in codes
        else:
            assert err.code == "SCHEMA_VALIDATION_ERROR"

    def test_invalid_id_characters(self):
        tasks = [TaskSpec(id="bad id!", tool="echo")]
        with pytest.raises(SchemaValidationError):
            self.compiler.compile(tasks)


# ── Multiple Errors ──────────────────────────────────────────────────────────


class TestMultipleErrors:
    def test_collects_multiple_errors(self):
        compiler = WorkflowCompiler(known_tools={"echo"})
        tasks = [
            _spec("A", tool="bad_tool"),
            _spec("A", tool="echo"),  # duplicate
        ]
        with pytest.raises((DuplicateTaskIdError, UnknownToolError, MultipleCompilationErrors)):
            compiler.compile(tasks)


# ── Compiled Graph Integrity ─────────────────────────────────────────────────


class TestCompiledGraphIntegrity:
    def setup_method(self):
        self.compiler = WorkflowCompiler()

    def test_graph_stores_tool_names(self):
        tasks = [
            _spec("fetch", tool="http"),
            _spec("process", tool="llm", depends_on=["fetch"]),
        ]
        graph = self.compiler.compile(tasks)
        assert graph.get_node("fetch").tool_name == "http"
        assert graph.get_node("process").tool_name == "llm"

    def test_graph_stores_params(self):
        tasks = [TaskSpec(id="fetch", tool="http", params={"url": "https://example.com"})]
        graph = self.compiler.compile(tasks)
        assert graph.get_node("fetch").params == {"url": "https://example.com"}

    def test_compiled_graph_serializable(self):
        tasks = [
            _spec("A"),
            _spec("B", depends_on=["A"]),
        ]
        graph = self.compiler.compile(tasks)
        data = graph.to_dict()
        assert isinstance(data, dict)
        assert "nodes" in data
        assert "edges" in data
