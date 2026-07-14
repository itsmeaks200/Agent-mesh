"""Shared structlog configuration for every AgentMesh process (API, worker).

Every process that imports this module and calls ``configure_logging()``
once at startup gets identical JSON log formatting, so a line emitted by the
API and a line emitted by a worker for the same workflow can be correlated
by ``workflow_id`` / ``task_id`` alone.

Correlation IDs are threaded through ``structlog.contextvars`` rather than
passed as explicit kwargs at every call site: ``bind_contextvars`` merges
into every log call made on the current asyncio task until
``clear_contextvars`` is called, including calls made deep inside helper
functions that have no reference to the original context.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, json_logs: bool = True, level: int = logging.INFO) -> None:
    """Configure stdlib logging + structlog. Call once per process, at startup."""
    logging.basicConfig(level=level, format="%(message)s")

    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def bind_workflow_context(workflow_id: object, **extra: object) -> None:
    """Bind ``workflow_id`` (and any extra fields) to every log call on this task."""
    structlog.contextvars.bind_contextvars(workflow_id=str(workflow_id), **extra)


def bind_task_context(task_key: str, **extra: object) -> None:
    """Bind ``task_key`` (and any extra fields) to every log call on this task."""
    structlog.contextvars.bind_contextvars(task_key=task_key, **extra)


def clear_context() -> None:
    """Clear all bound correlation fields. Call when a unit of work finishes."""
    structlog.contextvars.clear_contextvars()
