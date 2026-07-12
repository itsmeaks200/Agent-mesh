"""ShellTool — execute shell commands in a subprocess with timeout enforcement."""

from __future__ import annotations

import asyncio
import time

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300
# Truncate very long output to avoid storing huge strings in the DB
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB


class ShellTool(BaseTool):
    """Execute a shell command and return stdout, stderr, and exit code.

    Required params:
        command (str): The shell command to execute.

    Optional params:
        timeout (int): Timeout in seconds. Default: 30, max: 300.
        cwd (str):     Working directory. Default: current directory.

    Output::

        {
          "command": "echo hello",
          "stdout": "hello\\n",
          "stderr": "",
          "returncode": 0,
          "timed_out": false
        }

    Security notes:
        - Commands run in a subprocess, not the host shell directly.
        - Timeout is always enforced — stuck processes are killed.
        - Output is truncated at 64 KB to prevent DB bloat.
    """

    name = "shell"
    description = (
        "Execute a shell command and return stdout, stderr, and exit code. "
        "Timeout is enforced (max 300s). Output truncated at 64 KB."
    )

    async def execute(self, context: ToolContext) -> ToolResult:
        start = time.monotonic()

        command = context.params.get("command", "").strip()
        if not command:
            return ToolResult.failure(
                error="ShellTool requires a 'command' parameter.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        raw_timeout = context.params.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout = min(int(raw_timeout), MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS

        cwd = context.params.get("cwd") or None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                timed_out = True
                stdout_bytes, stderr_bytes = b"", b""

            stdout = _truncate(stdout_bytes)
            stderr = _truncate(stderr_bytes)
            returncode = proc.returncode if proc.returncode is not None else -1
            duration_ms = int((time.monotonic() - start) * 1000)

            if timed_out:
                return ToolResult.failure(
                    error=f"Command timed out after {timeout}s: {command!r}",
                    duration_ms=duration_ms,
                )

            return ToolResult.success(
                data={
                    "command": command,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                    "timed_out": False,
                },
                duration_ms=duration_ms,
            )

        except FileNotFoundError:
            return ToolResult.failure(
                error=f"Shell not found. Cannot execute: {command!r}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return ToolResult.failure(
                error=f"Shell execution error: {exc}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )


def _truncate(raw: bytes, limit: int = MAX_OUTPUT_BYTES) -> str:
    """Decode bytes and truncate if over the limit."""
    text = raw.decode("utf-8", errors="replace")
    if len(raw) > limit:
        text = text[:limit] + f"\n... [truncated at {limit // 1024} KB]"
    return text
