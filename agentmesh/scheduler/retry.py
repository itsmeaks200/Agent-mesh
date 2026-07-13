"""Retry policy with exponential backoff and jitter."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class RetryPolicy:
    """Configuration for task retry behaviour.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay:  Initial backoff delay in seconds.
        max_delay:   Upper bound for backoff delay in seconds.
        jitter:      If True, add random jitter to avoid thundering herd.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True


# Sensible default used by the executor when none is specified
DEFAULT_RETRY_POLICY = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0)
NO_RETRY_POLICY = RetryPolicy(max_retries=0)


def compute_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Compute the delay (seconds) before the next retry attempt.

    Uses exponential backoff: ``base_delay * 2^attempt``, capped at
    ``max_delay``.  When ``jitter`` is enabled, the result is multiplied
    by a random factor in [0.5, 1.0] to spread retries across workers.

    Args:
        attempt:  The current attempt number (0-indexed).
                  attempt=0 → first retry, attempt=1 → second retry, etc.
        policy:   The retry policy governing delays.

    Returns:
        Seconds to sleep before the next attempt.
    """
    delay = min(policy.base_delay * (2 ** attempt), policy.max_delay)
    if policy.jitter:
        delay *= random.uniform(0.5, 1.0)
    return delay
