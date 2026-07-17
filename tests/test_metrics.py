"""Tests for Prometheus metrics recording helpers."""

from __future__ import annotations

from agentmesh.observability import metrics


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_record_workflow_terminal_increments_counter():
    before = _counter_value(metrics.WORKFLOWS_TOTAL, status="COMPLETED")
    metrics.record_workflow_terminal("COMPLETED", 1500)
    after = _counter_value(metrics.WORKFLOWS_TOTAL, status="COMPLETED")
    assert after == before + 1


def test_record_workflow_terminal_without_duration_skips_histogram():
    """duration_ms=None (e.g. a workflow that never started) must not raise."""
    before = _counter_value(metrics.WORKFLOWS_TOTAL, status="CANCELLED")
    metrics.record_workflow_terminal("CANCELLED", None)
    after = _counter_value(metrics.WORKFLOWS_TOTAL, status="CANCELLED")
    assert after == before + 1


def test_record_task_terminal_increments_counter_by_tool():
    before = _counter_value(metrics.TASKS_TOTAL, tool="echo", status="COMPLETED")
    metrics.record_task_terminal("echo", "COMPLETED", 42)
    after = _counter_value(metrics.TASKS_TOTAL, tool="echo", status="COMPLETED")
    assert after == before + 1


def test_render_latest_returns_prometheus_text_exposition():
    metrics.record_workflow_terminal("COMPLETED", 100)
    metrics.record_task_terminal("echo", "COMPLETED", 10)

    body, content_type = metrics.render_latest()

    assert b"agentmesh_workflows_total" in body
    assert b"agentmesh_tasks_total" in body
    assert b"agentmesh_workflow_duration_seconds" in body
    assert "text/plain" in content_type
