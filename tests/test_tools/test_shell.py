"""Tests for ShellTool."""

import sys

import pytest

from agentmesh.tools.base import ToolContext
from agentmesh.tools.shell import ShellTool


@pytest.fixture
def tool():
    return ShellTool()


def _ctx(**params) -> ToolContext:
    return ToolContext(params=params)


# Use platform-appropriate echo command
ECHO_CMD = "echo hello"
PYTHON_CMD = f'"{sys.executable}"'


class TestShellTool:
    def test_name(self, tool):
        assert tool.name == "shell"

    async def test_missing_command_returns_error(self, tool):
        result = await tool.execute(ToolContext(params={}))
        assert result.status == "ERROR"
        assert "command" in result.error.lower()

    async def test_echo_command(self, tool):
        result = await tool.execute(_ctx(command=ECHO_CMD))
        assert result.status == "SUCCESS"
        assert "hello" in result.data["stdout"]
        assert result.data["returncode"] == 0

    async def test_nonzero_exit_code(self, tool):
        # Python exit with non-zero code
        result = await tool.execute(_ctx(
            command=f"{PYTHON_CMD} -c \"import sys; sys.exit(1)\""
        ))
        assert result.status == "SUCCESS"  # tool succeeds even if command fails
        assert result.data["returncode"] == 1

    async def test_stderr_captured(self, tool):
        result = await tool.execute(_ctx(
            command=f"{PYTHON_CMD} -c \"import sys; sys.stderr.write('err\\n')\""
        ))
        assert result.status == "SUCCESS"
        assert "err" in result.data["stderr"]

    async def test_timeout_enforced(self, tool):
        result = await tool.execute(_ctx(
            command=f"{PYTHON_CMD} -c \"import time; time.sleep(10)\"",
            timeout=1,
        ))
        assert result.status == "ERROR"
        assert "timed out" in result.error.lower()

    async def test_duration_set(self, tool):
        result = await tool.execute(_ctx(command=ECHO_CMD))
        assert result.duration_ms >= 0
