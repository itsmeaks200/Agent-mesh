"""Tests for POST /api/v1/agent/run — natural language → planned & scheduled workflow.

The planner and background execution are stubbed out here; planner retry/
validation logic itself is covered by tests/test_planner.py. This file only
verifies the endpoint's plumbing: plan → persist → schedule → respond.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

import agentmesh.api.agent as agent_module
from agentmesh.persistence.repository import get_workflow_tasks
from agentmesh.planner.planner import PlannerError
from agentmesh.schemas.workflow import TaskSpec


class _FakePlanner:
    """Stand-in for WorkflowPlanner that returns a fixed plan without calling Gemini."""

    def __init__(self, task_specs: list[TaskSpec] | None = None, error: str | None = None):
        self._task_specs = task_specs
        self._error = error

    async def plan(self, request_text: str) -> list[TaskSpec]:
        if self._error:
            raise PlannerError(self._error)
        return self._task_specs or [
            TaskSpec(id="step_1", tool="echo", params={"message": "hi"}, depends_on=[]),
        ]


@pytest.fixture(autouse=True)
def _stub_background_execution(monkeypatch):
    """Prevent the endpoint from trying to reach Redis/Postgres in a fire-and-forget task."""
    async def _noop(workflow_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(agent_module, "_run_in_background", _noop)


def _use_fake_planner(monkeypatch, **kwargs) -> None:
    fake = _FakePlanner(**kwargs)
    monkeypatch.setattr(agent_module, "WorkflowPlanner", lambda *a, **kw: fake)


class TestAgentRunEndpoint:
    async def test_plans_persists_and_schedules_workflow(
        self, client: AsyncClient, db_session, monkeypatch,
    ):
        _use_fake_planner(monkeypatch)

        resp = await client.post("/api/v1/agent/run", json={"request": "Say hi to me"})

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "SCHEDULED"
        assert data["tasks_planned"] == 1
        assert "workflow_id" in data

        workflow_id = uuid.UUID(data["workflow_id"])
        tasks = await get_workflow_tasks(db_session, workflow_id)
        assert len(tasks) == 1
        assert tasks[0].task_key == "step_1"
        assert tasks[0].tool_name == "echo"

    async def test_multi_task_plan_is_persisted_with_dependencies(
        self, client: AsyncClient, db_session, monkeypatch,
    ):
        _use_fake_planner(monkeypatch, task_specs=[
            TaskSpec(id="fetch", tool="http", params={"url": "https://x.test"}, depends_on=[]),
            TaskSpec(id="summarize", tool="llm", params={"prompt": "sum"}, depends_on=["fetch"]),
        ])

        resp = await client.post("/api/v1/agent/run", json={"request": "Fetch then summarize"})

        assert resp.status_code == 202
        assert resp.json()["tasks_planned"] == 2

        workflow_id = uuid.UUID(resp.json()["workflow_id"])
        tasks = await get_workflow_tasks(db_session, workflow_id)
        by_key = {t.task_key: t for t in tasks}
        assert by_key["summarize"].tool_name == "llm"

    async def test_planning_failure_returns_422(self, client: AsyncClient, monkeypatch):
        _use_fake_planner(monkeypatch, error="model returned garbage")

        resp = await client.post("/api/v1/agent/run", json={"request": "Do something impossible"})

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "PLANNING_FAILED"
        assert "garbage" in detail["message"]

    async def test_empty_request_text_is_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v1/agent/run", json={"request": ""})
        assert resp.status_code == 422
