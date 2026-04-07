"""CLI bridge endpoints — spawn forge commands as subprocesses."""

from __future__ import annotations

import asyncio
import os
import sys

from fastapi import APIRouter

router = APIRouter()

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@router.post("/api/scout")
async def api_run_scout(body: dict = {}):
    dry_run = body.get("dry_run", False)
    cmd = [sys.executable, "-m", "forge", "scout"]
    if dry_run:
        cmd.append("--dry-run")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=_PROJECT_DIR,
    )
    return {"ok": True, "pid": proc.pid, "message": "Scout started in background"}


@router.post("/api/hackathon/{hackathon_id}/run")
async def api_run_hackathon(hackathon_id: str, body: dict = {}):
    from_phase = body.get("from_phase")
    restart = body.get("restart", False)
    cmd = [sys.executable, "-m", "forge", "run", "--id", hackathon_id]
    if restart:
        cmd.append("--restart")
    if from_phase:
        cmd.extend(["--from-phase", from_phase])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=_PROJECT_DIR,
    )
    return {"ok": True, "pid": proc.pid}


@router.post("/api/test")
async def api_test():
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "forge", "test",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_PROJECT_DIR,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        return {"ok": proc.returncode == 0, "stdout": stdout.decode(), "stderr": stderr.decode()}
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": "Test timed out after 60s"}
