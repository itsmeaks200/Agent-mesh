"""Tests for HttpTool — uses pytest-httpx to mock requests."""

import pytest
import pytest_asyncio

from agentmesh.tools.base import ToolContext
from agentmesh.tools.http_tool import HttpTool


@pytest.fixture
def tool():
    return HttpTool()


def _ctx(**params) -> ToolContext:
    return ToolContext(params=params)


class TestHttpTool:
    def test_name(self, tool):
        assert tool.name == "http"

    async def test_missing_url_returns_error(self, tool):
        ctx = ToolContext(params={})
        result = await tool.execute(ctx)
        assert result.status == "ERROR"
        assert "url" in result.error.lower()

    async def test_get_request(self, tool, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/api",
            json={"key": "value"},
            status_code=200,
        )
        ctx = _ctx(url="https://example.com/api", method="GET")
        result = await tool.execute(ctx)
        assert result.status == "SUCCESS"
        assert result.data["status_code"] == 200
        assert result.data["body"] == {"key": "value"}

    async def test_post_request(self, tool, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/post",
            json={"created": True},
            status_code=201,
        )
        ctx = _ctx(url="https://example.com/post", method="POST", body={"x": 1})
        result = await tool.execute(ctx)
        assert result.status == "SUCCESS"
        assert result.data["status_code"] == 201

    async def test_non_json_response(self, tool, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/text",
            text="plain text response",
            status_code=200,
        )
        ctx = _ctx(url="https://example.com/text")
        result = await tool.execute(ctx)
        assert result.status == "SUCCESS"
        assert result.data["body"] == "plain text response"

    async def test_connection_error(self, tool, httpx_mock):
        import httpx
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        ctx = _ctx(url="https://unreachable.example.com")
        result = await tool.execute(ctx)
        assert result.status == "ERROR"
        assert "connection" in result.error.lower()

    async def test_timeout_error(self, tool, httpx_mock):
        import httpx
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        ctx = _ctx(url="https://slow.example.com", timeout=1)
        result = await tool.execute(ctx)
        assert result.status == "ERROR"
        assert "timed out" in result.error.lower()

    async def test_duration_set(self, tool, httpx_mock):
        httpx_mock.add_response(url="https://example.com", json={}, status_code=200)
        ctx = _ctx(url="https://example.com")
        result = await tool.execute(ctx)
        assert result.duration_ms >= 0
