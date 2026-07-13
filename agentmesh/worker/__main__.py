"""Entry point for running a standalone worker process.

Usage::

    python -m agentmesh.worker

Run multiple instances (e.g. via ``docker compose up --scale worker=3``) to
scale task throughput horizontally. Each instance registers as an independent
consumer within the shared ``workers`` consumer group.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import structlog

from agentmesh.worker.worker import WorkerProcess


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )


async def _main() -> None:
    worker = WorkerProcess()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except (AttributeError, NotImplementedError):
            # add_signal_handler doesn't exist on Windows event loops (ProactorEventLoop).
            pass

    await worker.run()


def main() -> None:
    _configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
