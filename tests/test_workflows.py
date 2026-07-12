"""Tests for workflow CRUD API endpoints."""

import pytest
from httpx import AsyncClient


# ── Sample payloads ──────────────────────────────────────────────────────────

SIMPLE_WORKFLOW = {
    "tasks": [
        {
            "id": "step_1",
            "tool": "echo",
            "params": {"message": "hello"},
            "depends_on": [],
        }
    ]
}

LINEAR_WORKFLOW = {
    "tasks": [
        {
            "id": "fetch",
            "tool": "http",
            "params": {"url": "https://example.com"},
            "depends_on": [],
        },
        {
            "id": "process",
            "tool": "llm",
            "params": {"prompt": "summarize"},
            "depends_on": ["fetch"],
        },
        {
            "id": "save",
            "tool": "filesystem",
            "params": {"path": "output.md"},
            "depends_on": ["process"],
        },
    ]
}

DIAMOND_WORKFLOW = {
    "tasks": [
        {"id": "start", "tool": "echo", "params": {}, "depends_on": []},
        {"id": "branch_a", "tool": "echo", "params": {}, "depends_on": ["start"]},
        {"id": "branch_b", "tool": "echo", "params": {}, "depends_on": ["start"]},
        {"id": "merge", "tool": "echo", "params": {}, "depends_on": ["branch_a", "branch_b"]},
    ]
}


# ── Create Workflow ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_simple_workflow(client: AsyncClient):
    """Creating a single-task workflow should return 201 with correct data."""
    resp = await client.post("/api/v1/workflows", json=SIMPLE_WORKFLOW)
    assert resp.status_code == 201

    data = resp.json()
    assert data["status"] == "CREATED"
    assert data["total_tasks"] == 1
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_key"] == "step_1"
    assert data["tasks"][0]["tool_name"] == "echo"
    assert data["tasks"][0]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_create_linear_workflow(client: AsyncClient):
    """A 3-task linear workflow should be created with dependencies preserved."""
    resp = await client.post("/api/v1/workflows", json=LINEAR_WORKFLOW)
    assert resp.status_code == 201

    data = resp.json()
    assert data["total_tasks"] == 3

    # Verify dependency chains
    tasks = {t["task_key"]: t for t in data["tasks"]}
    assert tasks["fetch"]["depends_on_keys"] == []
    assert tasks["process"]["depends_on_keys"] == ["fetch"]
    assert tasks["save"]["depends_on_keys"] == ["process"]


@pytest.mark.asyncio
async def test_create_diamond_workflow(client: AsyncClient):
    """A diamond DAG should have correct branching dependencies."""
    resp = await client.post("/api/v1/workflows", json=DIAMOND_WORKFLOW)
    assert resp.status_code == 201

    data = resp.json()
    assert data["total_tasks"] == 4

    tasks = {t["task_key"]: t for t in data["tasks"]}
    assert sorted(tasks["merge"]["depends_on_keys"]) == ["branch_a", "branch_b"]


@pytest.mark.asyncio
async def test_create_workflow_invalid_dependency(client: AsyncClient):
    """Referencing a non-existent dependency should return 422."""
    payload = {
        "tasks": [
            {
                "id": "step_1",
                "tool": "echo",
                "params": {},
                "depends_on": ["does_not_exist"],
            }
        ]
    }
    resp = await client.post("/api/v1/workflows", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_workflow_duplicate_task_ids(client: AsyncClient):
    """Duplicate task IDs should return 422."""
    payload = {
        "tasks": [
            {"id": "dup", "tool": "echo", "params": {}, "depends_on": []},
            {"id": "dup", "tool": "echo", "params": {}, "depends_on": []},
        ]
    }
    resp = await client.post("/api/v1/workflows", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_workflow_empty_tasks(client: AsyncClient):
    """An empty task list should return 422."""
    payload = {"tasks": []}
    resp = await client.post("/api/v1/workflows", json=payload)
    assert resp.status_code == 422


# ── Get Workflow ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_workflow(client: AsyncClient):
    """Should return a previously created workflow with full task details."""
    create_resp = await client.post("/api/v1/workflows", json=LINEAR_WORKFLOW)
    workflow_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["id"] == workflow_id
    assert data["total_tasks"] == 3
    assert len(data["tasks"]) == 3


@pytest.mark.asyncio
async def test_get_workflow_not_found(client: AsyncClient):
    """Getting a non-existent workflow should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"/api/v1/workflows/{fake_id}")
    assert resp.status_code == 404


# ── List Workflows ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_workflows_empty(client: AsyncClient):
    """Listing workflows when none exist should return empty list."""
    resp = await client.get("/api/v1/workflows")
    assert resp.status_code == 200

    data = resp.json()
    assert data["workflows"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_workflows(client: AsyncClient):
    """Listing workflows should return all created workflows."""
    await client.post("/api/v1/workflows", json=SIMPLE_WORKFLOW)
    await client.post("/api/v1/workflows", json=LINEAR_WORKFLOW)

    resp = await client.get("/api/v1/workflows")
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 2
    assert len(data["workflows"]) == 2


@pytest.mark.asyncio
async def test_list_workflows_pagination(client: AsyncClient):
    """Pagination should limit results correctly."""
    for _ in range(5):
        await client.post("/api/v1/workflows", json=SIMPLE_WORKFLOW)

    resp = await client.get("/api/v1/workflows?limit=2&offset=0")
    data = resp.json()
    assert len(data["workflows"]) == 2
    assert data["total"] == 5


# ── Delete Workflow ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_workflow(client: AsyncClient):
    """Deleting a workflow should return 204 and remove it."""
    create_resp = await client.post("/api/v1/workflows", json=SIMPLE_WORKFLOW)
    workflow_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/workflows/{workflow_id}")
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_workflow_not_found(client: AsyncClient):
    """Deleting a non-existent workflow should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.delete(f"/api/v1/workflows/{fake_id}")
    assert resp.status_code == 404


# ── Health Check ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Health endpoint should return 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
