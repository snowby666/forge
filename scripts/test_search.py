#!/usr/bin/env python3
"""Diagnose search provider hangs — run each provider in isolation with timing."""

import asyncio
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(encoding="utf-8-sig")

QUERY = '"Hack&Chill3.0" discord OR reddit OR slack OR github'


async def test_provider(name, coro, timeout=8.0):
    print(f"\n--- {name} (timeout={timeout}s) ---")
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(asyncio.shield(coro), timeout=timeout)
        ms = (time.monotonic() - t0) * 1000
        n = len(result) if result else 0
        print(f"  {n} results in {ms:.0f}ms")
        for r in (result or [])[:3]:
            t = r.title if hasattr(r, 'title') else r.get('title', '')
            u = r.url if hasattr(r, 'url') else r.get('url', '')
            print(f"    {t[:55]} | {u[:55]}")
    except asyncio.TimeoutError:
        print(f"  TIMEOUT after {(time.monotonic()-t0)*1000:.0f}ms")
    except asyncio.CancelledError:
        print(f"  CANCELLED after {(time.monotonic()-t0)*1000:.0f}ms")
    except Exception as e:
        print(f"  ERROR after {(time.monotonic()-t0)*1000:.0f}ms: {type(e).__name__}: {e}")


async def main():
    print(f"Python {sys.version}")
    print(f"Query: {QUERY}\n")

    keys = {
        "SERPER":  bool(os.environ.get("SERPER_API_KEY", "").strip()),
        "TAVILY":  bool(os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY", "").strip()),
        "BRAVE":   bool(os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()),
        "SEARXNG": bool(os.environ.get("SEARXNG_URL", "").strip()),
    }
    for k, v in keys.items():
        print(f"  {k}: {'YES' if v else 'no'}")

    from config.web_search import (
        _search_serper, _search_tavily, _search_brave,
        _search_searxng, _search_ddgs,
    )

    # --- Individual providers ---
    if keys["SERPER"]:
        await test_provider("serper", _search_serper(QUERY, 10))
    if keys["TAVILY"]:
        await test_provider("tavily", _search_tavily(QUERY, 10))
    if keys["BRAVE"]:
        await test_provider("brave", _search_brave(QUERY, 10))
    if keys["SEARXNG"]:
        await test_provider("searxng", _search_searxng(QUERY, 10))
    await test_provider("ddgs", _search_ddgs(QUERY, 10))

    # --- Full race ---
    print(f"\n{'='*50}")
    print("_fast_search (full race)")
    print(f"{'='*50}")
    from agents.python.intelligence.hackathon_scout import _fast_search
    t0 = time.monotonic()
    try:
        r = await asyncio.wait_for(_fast_search(QUERY, 10), timeout=15.0)
        print(f"  {len(r)} results in {(time.monotonic()-t0)*1000:.0f}ms")
    except asyncio.TimeoutError:
        print(f"  TIMEOUT at {(time.monotonic()-t0)*1000:.0f}ms -- STILL HANGING")

    # --- 5 concurrent (Phase 3 simulation) ---
    print(f"\n{'='*50}")
    print("5 concurrent _fast_search (Phase 3 sim)")
    print(f"{'='*50}")
    qs = [
        '"Ideathon 2026" discord OR reddit',
        '"HackNSU Season 6" discord OR reddit',
        '"GenZ Can Hack" discord OR reddit',
        '"Hack&Chill3.0" discord OR reddit',
        '"Athernex" discord OR reddit',
    ]
    t0 = time.monotonic()
    tasks = [asyncio.wait_for(_fast_search(q, 10), timeout=12.0) for q in qs]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=30.0,
        )
        ms = (time.monotonic() - t0) * 1000
        print(f"  Completed in {ms:.0f}ms")
        for i, r in enumerate(results):
            if isinstance(r, list):
                print(f"    [{i}] {len(r)} results")
            else:
                print(f"    [{i}] {type(r).__name__}: {r}")
    except asyncio.TimeoutError:
        print(f"  GLOBAL TIMEOUT at {(time.monotonic()-t0)*1000:.0f}ms -- DEADLOCK")

    # --- Deadlock regression test ---
    print(f"\n{'='*50}")
    print("wait_for + to_thread deadlock test (must not hang)")
    print(f"{'='*50}")
    def _block():
        import time as t; t.sleep(30); return []
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(asyncio.shield(asyncio.to_thread(_block)), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        ms = (time.monotonic() - t0) * 1000
        print(f"  Timeout in {ms:.0f}ms (expected ~2000) -- OK")

    print(f"\n  Threads alive: {threading.active_count()}")
    print("DONE")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
