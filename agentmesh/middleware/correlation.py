"""Correlation ID middleware — one request_id ties together every log line
and error response produced while handling a single HTTP request.

Accepts an inbound ``X-Request-ID`` (so a caller or reverse proxy can supply
its own trace ID), otherwise generates one. Echoes it back on the response
so clients can quote it when reporting an issue.

Implemented as plain ASGI (not ``BaseHTTPMiddleware``): ``BaseHTTPMiddleware``
runs the downstream app inside a spawned task via an anyio task group, which
breaks SQLAlchemy's async greenlet context and turns any lazy-loaded
relationship access into a ``MissingGreenlet`` error. Plain ASGI middleware
calls the app in the same task, so it doesn't have that problem.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentmesh.observability.logger import clear_context

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        scope["state"] = {**scope.get("state", {}), "request_id": request_id}

        clear_context()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        method = scope["method"]
        path = scope["path"]
        status_code = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        start = time.monotonic()
        log.info("Request started", method=method, path=path)
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.exception("Request failed", method=method, path=path, duration_ms=duration_ms)
            raise
        else:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "Request finished",
                method=method, path=path, status_code=status_code, duration_ms=duration_ms,
            )
        finally:
            clear_context()
