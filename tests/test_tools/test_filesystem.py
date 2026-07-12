"""Tests for FilesystemTool — uses tmp_path fixture for isolation."""

import pytest

from agentmesh.tools.base import ToolContext
from agentmesh.tools.filesystem import WORKSPACE_DIR, FilesystemTool


@pytest.fixture
def tool():
    return FilesystemTool()


@pytest.fixture(autouse=True)
def patch_workspace(monkeypatch, tmp_path):
    """Redirect WORKSPACE_DIR to a temporary directory for test isolation."""
    import agentmesh.tools.filesystem as fs_module
    monkeypatch.setattr(fs_module, "WORKSPACE_DIR", tmp_path)
    # Also patch it on the module so _safe_path uses tmp_path
    return tmp_path


def _ctx(**params) -> ToolContext:
    return ToolContext(params=params)


class TestFilesystemTool:
    def test_name(self, tool):
        assert tool.name == "filesystem"

    async def test_write_and_read(self, tool, tmp_path):
        # Write
        write_result = await tool.execute(_ctx(
            operation="write",
            path="hello.txt",
            content="Hello, AgentMesh!",
        ))
        assert write_result.status == "SUCCESS"
        assert write_result.data["bytes_written"] == len("Hello, AgentMesh!")

        # Read back
        read_result = await tool.execute(_ctx(operation="read", path="hello.txt"))
        assert read_result.status == "SUCCESS"
        assert read_result.data["content"] == "Hello, AgentMesh!"

    async def test_read_nonexistent_file(self, tool):
        result = await tool.execute(_ctx(operation="read", path="nope.txt"))
        assert result.status == "ERROR"
        assert "not found" in result.error.lower()

    async def test_write_creates_parent_dirs(self, tool):
        result = await tool.execute(_ctx(
            operation="write",
            path="subdir/nested/file.txt",
            content="nested",
        ))
        assert result.status == "SUCCESS"

    async def test_path_traversal_rejected(self, tool):
        result = await tool.execute(_ctx(
            operation="read",
            path="../../etc/passwd",
        ))
        assert result.status == "ERROR"
        assert "sandbox" in result.error.lower()

    async def test_missing_operation(self, tool):
        result = await tool.execute(_ctx(path="file.txt"))
        assert result.status == "ERROR"
        assert "operation" in result.error.lower()

    async def test_missing_path(self, tool):
        result = await tool.execute(_ctx(operation="read"))
        assert result.status == "ERROR"
        assert "path" in result.error.lower()

    async def test_unknown_operation(self, tool):
        result = await tool.execute(_ctx(operation="delete", path="x.txt"))
        assert result.status == "ERROR"
        assert "unknown operation" in result.error.lower()

    async def test_write_empty_content(self, tool):
        result = await tool.execute(_ctx(operation="write", path="empty.txt"))
        assert result.status == "SUCCESS"
        assert result.data["bytes_written"] == 0

    async def test_read_returns_size(self, tool):
        content = "size test"
        await tool.execute(_ctx(operation="write", path="size.txt", content=content))
        result = await tool.execute(_ctx(operation="read", path="size.txt"))
        assert result.data["size_bytes"] == len(content.encode("utf-8"))
