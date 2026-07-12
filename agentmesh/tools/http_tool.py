"""HttpTool — makes async HTTP requests using httpx.

Supports GET, POST, PUT, PATCH, DELETE with configurable headers,
body, and timeout. Returns status code, response body, and headers.
"""

from __future__ import annotations

import time

import httpx

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult

# Hard upper limit — prevents runaway requests
MAX_TIMEOUT_SECONDS = 120
DEFAULT_TIMEOUT_SECONDS = 30


class HttpTool(BaseTool):
    """Makes an HTTP request and returns the response.

    Required params:
        url (str): The URL to request.

    Optional params:
        method (str):   HTTP method. Default: "GET".
        headers (dict): Request headers. Default: {}.
        body (dict):    Request body (sent as JSON). Default: None.
        timeout (int):  Timeout in seconds. Default: 30, max: 120.

    Output::

        {
          "status_code": 200,
          "url": "https://...",
          "body": {...},          # parsed JSON or raw text
          "headers": {...},
          "content_type": "application/json"
        }
    """

    name = "http"
    description = (
        "Makes an HTTP request (GET, POST, etc.) to a URL and returns "
        "the response status code, headers, and body."
    )

    async def execute(self, context: ToolContext) -> ToolResult:
        start = time.monotonic()

        # Validate required params
        url = context.params.get("url")
        if not url:
            return ToolResult.failure(
                error="HttpTool requires a 'url' parameter.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        method = str(context.params.get("method", "GET")).upper()
        headers = context.params.get("headers") or {}
        body = context.params.get("body")
        raw_timeout = context.params.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        try:
            timeout = min(int(raw_timeout), MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if body is not None else None,
                )

            # Try to parse JSON body, fall back to raw text
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body_data = response.json()
                except Exception:
                    body_data = response.text
            else:
                body_data = response.text

            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult.success(
                data={
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "body": body_data,
                    "headers": dict(response.headers),
                    "content_type": content_type,
                },
                duration_ms=duration_ms,
            )

        except httpx.TimeoutException:
            return ToolResult.failure(
                error=f"Request to '{url}' timed out after {timeout}s.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except httpx.ConnectError as exc:
            return ToolResult.failure(
                error=f"Connection error for '{url}': {exc}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return ToolResult.failure(
                error=f"HTTP request failed: {exc}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
