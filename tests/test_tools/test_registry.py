"""Tests for ToolRegistry."""

import pytest

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult
from agentmesh.tools.registry import ToolNotFoundError, ToolRegistry

# ── Fixtures ─────────────────────────────────────────────────────────────────


class FakeTool(BaseTool):
    name = "fake"
    description = "A fake tool for testing."

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult.success(data={"ok": True})


class AnotherTool(BaseTool):
    name = "another"
    description = "Another fake tool."

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult.success(data={"another": True})


class UnnamedTool(BaseTool):
    name = ""
    description = "Has no name."

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult.success(data={})


# ── Registration ──────────────────────────────────────────────────────────────


class TestRegistration:
    def test_register_and_get(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        tool = registry.get("fake")
        assert isinstance(tool, FakeTool)

    def test_register_overwrites(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        registry.register(FakeTool())  # second registration
        assert len(registry) == 1

    def test_register_unnamed_raises(self):
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="no name"):
            registry.register(UnnamedTool())

    def test_get_unknown_raises(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        with pytest.raises(ToolNotFoundError) as exc_info:
            registry.get("nonexistent")
        assert "nonexistent" in str(exc_info.value)
        assert "fake" in exc_info.value.known_tools

    def test_contains(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        assert "fake" in registry
        assert "other" not in registry

    def test_len(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(FakeTool())
        registry.register(AnotherTool())
        assert len(registry) == 2


# ── Listing ───────────────────────────────────────────────────────────────────


class TestListing:
    def test_list_tools_sorted(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        registry.register(AnotherTool())
        tools = registry.list_tools()
        assert [t.name for t in tools] == ["another", "fake"]

    def test_tool_names(self):
        registry = ToolRegistry()
        registry.register(FakeTool())
        registry.register(AnotherTool())
        assert registry.tool_names() == {"fake", "another"}

    def test_empty_registry(self):
        registry = ToolRegistry()
        assert registry.list_tools() == []
        assert registry.tool_names() == set()


# ── Default Registry ──────────────────────────────────────────────────────────


class TestDefaultRegistry:
    def test_default_registry_has_builtin_tools(self):
        from agentmesh.tools.registry import default_registry
        names = default_registry.tool_names()
        assert "echo" in names
        assert "http" in names
        assert "filesystem" in names
        assert "shell" in names
        assert "llm" in names

    def test_default_registry_get_echo(self):
        from agentmesh.tools.echo import EchoTool
        from agentmesh.tools.registry import default_registry
        tool = default_registry.get("echo")
        assert isinstance(tool, EchoTool)
