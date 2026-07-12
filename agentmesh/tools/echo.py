"""EchoTool — returns its input parameters as output.

Useful for:
- Testing pipeline wiring without side effects
- Passing static data to downstream tasks
- Debugging workflow execution
"""

from __future__ import annotations

import time

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult


class EchoTool(BaseTool):
    """Returns the task's params as output data unchanged.

    Params:
        Any key-value pairs. At least one key is required.

    Example::

        {
          "id": "greet",
          "tool": "echo",
          "params": {"message": "hello", "value": 42}
        }

    Output::

        {"message": "hello", "value": 42}
    """

    name = "echo"
    description = (
        "Returns its input parameters as output. "
        "Useful for passing static data to downstream tasks or testing."
    )

    async def execute(self, context: ToolContext) -> ToolResult:
        start = time.monotonic()

        if not context.params:
            return ToolResult.failure(
                error="EchoTool requires at least one parameter.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        return ToolResult.success(
            data=dict(context.params),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
