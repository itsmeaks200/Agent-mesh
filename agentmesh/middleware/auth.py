"""Optional API-key authentication.

Disabled entirely when ``settings.api_key`` is unset (the default) — local
dev, tests, and the bundled dashboard keep working with zero config. Set
``API_KEY`` (in the environment or ``.env``) to require every request to
present a matching ``X-API-Key`` header.

Implemented as plain ASGI (not ``BaseHTTPMiddleware``) for the same reason as
``CorrelationIdMiddleware`` — see that module's docstring.
"""

from __future__ import annotations

import structlog
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agentmesh.config import get_settings

log = structlog.get_logger(__name__)

API_KEY_HEADER = "X-API-Key"

# Always reachable without a key: health/docs so uptime checks and the
# OpenAPI UI work before anyone's configured a client, plus the websocket
# stream, which browsers cannot attach custom headers to.
EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}
EXEMPT_PREFIXES = ("/api/v1/ws/",)


class APIKeyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.api_key:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        provided = headers.get(API_KEY_HEADER)
        if provided != settings.api_key:
            log.warning("Rejected request with missing/invalid API key", path=path)
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "Missing or invalid API key.",
                    "detail": f"Provide a valid '{API_KEY_HEADER}' header.",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
