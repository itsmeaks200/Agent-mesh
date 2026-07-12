"""FilesystemTool — read and write files within a sandboxed workspace directory.

All paths are resolved relative to ./workspace/ and validated to prevent
path traversal attacks (e.g. ../../etc/passwd).
"""

from __future__ import annotations

import time
from pathlib import Path

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult

# Sandbox root — all file operations are contained here
WORKSPACE_DIR = Path("workspace").resolve()


class FilesystemTool(BaseTool):
    """Read or write files within the sandboxed workspace directory.

    Required params:
        operation (str): "read" or "write".
        path (str):      File path relative to the workspace root.

    Optional params:
        content (str):   File content for write operations.
        encoding (str):  File encoding. Default: "utf-8".

    Output (read)::

        {"path": "report.md", "content": "...", "size_bytes": 1234}

    Output (write)::

        {"path": "report.md", "bytes_written": 1234}
    """

    name = "filesystem"
    description = (
        "Read or write files within the sandboxed workspace directory. "
        "Supports text files. All paths are relative to ./workspace/."
    )

    def _safe_path(self, relative_path: str) -> Path | None:
        """Resolve the path and verify it stays inside WORKSPACE_DIR."""
        try:
            resolved = (WORKSPACE_DIR / relative_path).resolve()
            # Ensure the resolved path is inside the workspace
            resolved.relative_to(WORKSPACE_DIR)
            return resolved
        except ValueError:
            return None

    async def execute(self, context: ToolContext) -> ToolResult:
        start = time.monotonic()

        operation = context.params.get("operation", "").lower()
        relative_path = context.params.get("path", "")
        encoding = context.params.get("encoding", "utf-8")

        if not operation:
            return ToolResult.failure(
                error="FilesystemTool requires an 'operation' parameter ('read' or 'write').",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        if not relative_path:
            return ToolResult.failure(
                error="FilesystemTool requires a 'path' parameter.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        safe = self._safe_path(relative_path)
        if safe is None:
            return ToolResult.failure(
                error=f"Path '{relative_path}' is outside the workspace sandbox.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            if operation == "read":
                if not safe.exists():
                    return ToolResult.failure(
                        error=f"File not found: '{relative_path}'",
                        duration_ms=int((time.monotonic() - start) * 1000),
                    )
                content = safe.read_text(encoding=encoding)
                return ToolResult.success(
                    data={
                        "path": relative_path,
                        "content": content,
                        "size_bytes": len(content.encode(encoding)),
                    },
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            elif operation == "write":
                content = context.params.get("content", "")
                # Create parent directories if they don't exist
                safe.parent.mkdir(parents=True, exist_ok=True)
                safe.write_text(content, encoding=encoding)
                return ToolResult.success(
                    data={
                        "path": relative_path,
                        "bytes_written": len(content.encode(encoding)),
                    },
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            else:
                return ToolResult.failure(
                    error=f"Unknown operation '{operation}'. Use 'read' or 'write'.",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

        except PermissionError:
            return ToolResult.failure(
                error=f"Permission denied: '{relative_path}'",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return ToolResult.failure(
                error=f"Filesystem error: {exc}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
