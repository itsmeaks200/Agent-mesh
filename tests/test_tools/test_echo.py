"""Tests for EchoTool."""

import pytest

from agentmesh.tools.base import ToolContext
from agentmesh.tools.echo import EchoTool


@pytest.fixture
def tool():
    return EchoTool()


def _ctx(**params) -> ToolContext:
    return ToolContext(params=params)


class TestEchoTool:
    def test_name(self, tool):
        assert tool.name == "echo"

    async def test_returns_params(self, tool):
        ctx = _ctx(message="hello", value=42)
        result = await tool.execute(ctx)
        assert result.status == "SUCCESS"
        assert result.data == {"message": "hello", "value": 42}

    async def test_empty_params_returns_error(self, tool):
        ctx = ToolContext(params={})
        result = await tool.execute(ctx)
        assert result.status == "ERROR"
        assert "parameter" in result.error.lower()

    async def test_duration_set(self, tool):
        ctx = _ctx(x=1)
        result = await tool.execute(ctx)
        assert result.duration_ms >= 0

    async def test_safe_execute_does_not_raise(self, tool):
        ctx = ToolContext(params={})
        result = await tool.safe_execute(ctx)
        assert result.status == "ERROR"  # empty params, but no exception
