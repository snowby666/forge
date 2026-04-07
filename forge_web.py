#!/usr/bin/env python3
"""
forge_web — thin compatibility shim.

The real implementation lives in the forge_web/ package.
This file exists so that ``uvicorn forge_web:app`` and existing Docker/scripts
continue to work without changes.

Usage:
    uvicorn forge_web:app --host 0.0.0.0 --port 3001
    python forge_web.py [--host 0.0.0.0] [--port 3001]
"""

from forge_web import app  # noqa: F401


def start(host: str = "0.0.0.0", port: int = 3001):
    import uvicorn
    uvicorn.run("forge_web:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=3001)
    args = p.parse_args()
    start(args.host, args.port)
