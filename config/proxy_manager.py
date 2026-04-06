# -*- coding: utf-8 -*-
"""
config/proxy_manager.py — Centralized proxy manager for webshare.io
===================================================================

Loads 1000 premium rotating proxies once, provides them to all Forge subsystems:
  - config/devpost.py (async HTTP client)
  - config/web_search.py (Crawl4AI, aiohttp fetches)
  - Any future scrapers

Usage:
    from config.proxy_manager import get_random_proxy, get_next_proxy, get_aiohttp_proxy

    # For aiohttp
    proxy = get_aiohttp_proxy()  # "http://user:pass@ip:port"
    async with session.get(url, proxy=proxy) as resp: ...

    # For Crawl4AI BrowserConfig
    proxy = get_random_proxy()

    # Round-robin for high-volume sequential requests
    proxy = get_next_proxy()
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_PROXIES: list[str] = []
_PROXY_LOADED = False
_PROXY_LOCK = asyncio.Lock()
_PROXY_INDEX = 0

WEBSHARE_PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL", "")


async def load_proxies() -> None:
    """Fetch proxy list from webshare.io. Safe to call multiple times (idempotent)."""
    global _PROXIES, _PROXY_LOADED

    async with _PROXY_LOCK:
        if _PROXY_LOADED:
            return

        if not WEBSHARE_PROXY_URL:
            logger.debug("[proxy] WEBSHARE_PROXY_URL not set — proxies disabled")
            _PROXY_LOADED = True
            return

        for attempt in range(4):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(WEBSHARE_PROXY_URL) as resp:
                        if resp.status == 429:
                            delay = 2 ** (attempt + 1)
                            logger.warning(f"[proxy] Rate-limited, retry in {delay}s")
                            await asyncio.sleep(delay)
                            continue
                        resp.raise_for_status()
                        content = await resp.text()

                loaded: list[str] = []
                for line in content.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(":")
                    if len(parts) == 4:
                        ip, port, username, password = parts
                        loaded.append(f"http://{username}:{password}@{ip}:{port}")
                    elif len(parts) == 2:
                        loaded.append(f"http://{line}")

                random.shuffle(loaded)
                _PROXIES = loaded
                _PROXY_LOADED = True
                logger.info(f"[proxy] Loaded {len(_PROXIES)} proxies from webshare.io")
                return

            except Exception as e:
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                logger.error(f"[proxy] Failed to load proxies after 4 attempts: {e}")
                _PROXIES = []
                return


async def ensure_loaded() -> None:
    """Ensure proxies are loaded. Call at the start of any scraping pipeline."""
    if not _PROXY_LOADED:
        await load_proxies()


def get_proxies() -> list[str]:
    return _PROXIES.copy()


def get_random_proxy() -> Optional[str]:
    if not _PROXIES:
        return None
    return random.choice(_PROXIES)


def get_aiohttp_proxy() -> Optional[str]:
    """Returns a proxy URL string suitable for aiohttp's `proxy=` parameter."""
    return get_random_proxy()


def get_next_proxy() -> Optional[str]:
    """Round-robin proxy selection for sequential high-volume requests."""
    global _PROXY_INDEX
    if not _PROXIES:
        return None
    proxy = _PROXIES[_PROXY_INDEX % len(_PROXIES)]
    _PROXY_INDEX = (_PROXY_INDEX + 1) % len(_PROXIES)
    return proxy


def proxy_count() -> int:
    return len(_PROXIES)
