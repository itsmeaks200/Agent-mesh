"""Tests for persistence.repository status-update helpers.

Covers ``Workflow.duration_ms`` and the metrics recording hooks fired from
``update_workflow_status`` / ``update_task_status``.
"""

from __future__ import annotations

import asyncio

from agentmesh.models.task import TaskStatus
from agentmesh.models.workflow import WorkflowStatus
from agentmesh.observability import metrics
from agentmesh.persistence.repository import (
    create_workflow,
    update_task_status,
    update_workflow_status,
)
from agentmesh.schemas.workflow import TaskSpec


def _spec(task_id: str) -> TaskSpec:
    return TaskSpec(id=task_id, tool="echo", params={}, depends_on=[])


async def test_workflow_duration_ms_none_before_start(db_session):
    workflow = await create_workflow(db_session, [_spec("a")])
    assert workflow.duration_ms is None


async def test_workflow_duration_ms_live_updates_while_running(db_session):
    workflow = await create_workflow(db_session, [_spec("a")])
    workflow = await update_workflow_status(db_session, workflow.id, WorkflowStatus.RUNNING)

    assert workflow.duration_ms is not None
    assert workflow.duration_ms >= 0


async def test_workflow_duration_ms_freezes_after_completion(db_session):
    workflow = await create_workflow(db_session, [_spec("a")])
    await update_workflow_status(db_session, workflow.id, WorkflowStatus.RUNNING)
    await asyncio.sleep(0.01)
    workflow = await update_workflow_status(db_session, workflow.id, WorkflowStatus.COMPLETED)

    first = workflow.duration_ms
    await asyncio.sleep(0.01)
    second = workflow.duration_ms

    assert first is not None
    assert first == second


async def test_workflow_terminal_status_records_metric(db_session):
    workflow = await create_workflow(db_session, [_spec("a")])
    before = metrics.WORKFLOWS_TOTAL.labels(status="COMPLETED")._value.get()

    await update_workflow_status(db_session, workflow.id, WorkflowStatus.RUNNING)
    await update_workflow_status(db_session, workflow.id, WorkflowStatus.COMPLETED)

    after = metrics.WORKFLOWS_TOTAL.labels(status="COMPLETED")._value.get()
    assert after == before + 1


async def test_task_terminal_status_records_metric(db_session):
    workflow = await create_workflow(db_session, [_spec("a")])
    task = workflow.tasks[0]
    before = metrics.TASKS_TOTAL.labels(tool="echo", status="COMPLETED")._value.get()

    await update_task_status(db_session, task.id, TaskStatus.RUNNING)
    await update_task_status(db_session, task.id, TaskStatus.COMPLETED)

    after = metrics.TASKS_TOTAL.labels(tool="echo", status="COMPLETED")._value.get()
    assert after == before + 1
