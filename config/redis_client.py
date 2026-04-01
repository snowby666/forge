# -*- coding: utf-8 -*-
"""Centralized Redis client factory for Forge.

Every module should use `get_redis()` from here instead of calling
`Redis.from_url()` directly. This ensures consistent connection settings
(keepalive, retry, health checks) across the entire codebase.
"""

from __future__ import annotations

import os

from redis.asyncio import Redis


def get_redis() -> Redis:
    """Create a resilient async Redis client.

    Settings:
    - socket_keepalive: prevents idle TCP connections from being silently dropped
    - health_check_interval: auto-pings every 30s to keep connection alive during
      long LLM calls that leave Redis idle for minutes
    - retry_on_timeout: automatically retries on transient timeouts
    - socket_timeout: 30s per operation (prevents infinite hangs)
    """
    return Redis.from_url(
        os.environ["REDIS_URL"],
        decode_responses=True,
        socket_timeout=30,
        socket_connect_timeout=10,
        socket_keepalive=True,
        retry_on_timeout=True,
        health_check_interval=30,
    )
