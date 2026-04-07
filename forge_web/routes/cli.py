"""CLI bridge endpoints — spawn forge commands as subprocesses."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

from fastapi import APIRouter

from config.redis_client import get_redis

router = APIRouter()
logger = logging.getLogger("forge.cli_bridge")

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_ACTIVE_PROCS: dict[str, asyncio.subprocess.Process] = {}


async def _is_run_active(hackathon_id: str) -> tuple[bool, str]:
    """Check if a pipeline run is already active for this hackathon.

    Returns (is_active, reason).
    """
    proc = _ACTIVE_PROCS.get(hackathon_id)
    if proc and proc.returncode is None:
        return True, f"Pipeline already running (pid={proc.pid})"

    if proc and proc.returncode is not None:
        _ACTIVE_PROCS.pop(hackathon_id, None)

    redis = get_redis()
    try:
        lock_val = await redis.get(f"hackathon:{hackathon_id}:run_lock")
        if lock_val:
            return True, f"Pipeline already running (started by another instance)"
    finally:
        await redis.aclose()
    return False, ""


async def _set_run_lock(hackathon_id: str, pid: int) -> None:
    redis = get_redis()
    try:
        await redis.set(
            f"hackathon:{hackathon_id}:run_lock",
            f"{pid}:{int(time.time())}",
            ex=7200,  # 2h max — safety net
        )
    finally:
        await redis.aclose()


async def _clear_run_lock(hackathon_id: str) -> None:
    redis = get_redis()
    try:
        await redis.delete(f"hackathon:{hackathon_id}:run_lock")
    finally:
        await redis.aclose()


async def _monitor_proc(hackathon_id: str, proc: asyncio.subprocess.Process, log_path: str) -> None:
    """Wait for subprocess to finish, clear run lock, log exit code."""
    try:
        code = await proc.wait()
        logger.info(f"[forge:cli] Pipeline for {hackathon_id} exited with code {code} (pid={proc.pid})")
        if code != 0:
            logger.warning(f"[forge:cli] Check log: {log_path}")
    except Exception as e:
        logger.error(f"[forge:cli] Monitor error for {hackathon_id}: {e}")
    finally:
        _ACTIVE_PROCS.pop(hackathon_id, None)
        await _clear_run_lock(hackathon_id)


_SCOUT_LOG: str | None = None
_SCOUT_PROC: asyncio.subprocess.Process | None = None
_SCOUT_STARTED: float = 0


def _scout_is_running() -> bool:
    return _SCOUT_PROC is not None and _SCOUT_PROC.returncode is None


@router.post("/api/scout")
async def api_run_scout(body: dict = {}):
    global _SCOUT_LOG, _SCOUT_PROC, _SCOUT_STARTED
    if _scout_is_running():
        elapsed = int(time.time() - _SCOUT_STARTED) if _SCOUT_STARTED else 0
        return {
            "ok": False,
            "error": f"Scout is already running ({elapsed}s elapsed, pid={_SCOUT_PROC.pid})",
            "already_running": True,
            "pid": _SCOUT_PROC.pid,
        }

    dry_run = body.get("dry_run", False)
    cmd = [sys.executable, "-m", "forge", "scout"]
    if dry_run:
        cmd.append("--dry-run")

    log_path = os.path.join(_LOG_DIR, f"scout-{int(time.time())}.log")
    log_file = open(log_path, "w")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
        cwd=_PROJECT_DIR,
    )
    _SCOUT_LOG = log_path
    _SCOUT_PROC = proc
    _SCOUT_STARTED = time.time()
    logger.info(f"[forge:cli] Scout started (pid={proc.pid}, log={log_path})")
    return {"ok": True, "pid": proc.pid, "message": "Scout started in background", "log": log_path}


@router.get("/api/scout/status")
async def api_scout_status():
    """Get scout process status and recent log output."""
    running = _scout_is_running()
    pid = _SCOUT_PROC.pid if running and _SCOUT_PROC else None
    exit_code = _SCOUT_PROC.returncode if _SCOUT_PROC and not running else None
    elapsed = int(time.time() - _SCOUT_STARTED) if running and _SCOUT_STARTED else None

    lines: list[str] = []
    if _SCOUT_LOG and os.path.isfile(_SCOUT_LOG):
        try:
            with open(_SCOUT_LOG, "r", errors="replace") as f:
                all_lines = f.readlines()
                lines = [l.rstrip() for l in all_lines[-200:]]
        except Exception:
            pass

    return {"running": running, "pid": pid, "exit_code": exit_code, "elapsed_s": elapsed, "log_lines": lines}


@router.post("/api/scout/abort")
async def api_abort_scout():
    """Kill the running scout subprocess."""
    global _SCOUT_PROC
    if not _scout_is_running():
        return {"ok": False, "error": "Scout is not running"}
    pid = _SCOUT_PROC.pid
    _SCOUT_PROC.kill()
    await _SCOUT_PROC.wait()
    _SCOUT_PROC = None
    logger.info(f"[forge:cli] Scout aborted (pid={pid})")
    return {"ok": True, "killed_pid": pid}


@router.post("/api/hackathon/{hackathon_id}/run")
async def api_run_hackathon(hackathon_id: str, body: dict = {}):
    from_phase = body.get("from_phase")
    restart = body.get("restart", False)

    active, reason = await _is_run_active(hackathon_id)
    if active and not restart:
        return {"ok": False, "error": reason, "already_running": True}

    if active and restart:
        old_proc = _ACTIVE_PROCS.get(hackathon_id)
        if old_proc and old_proc.returncode is None:
            logger.info(f"[forge:cli] Killing existing run (pid={old_proc.pid}) for restart")
            old_proc.kill()
            await old_proc.wait()
            _ACTIVE_PROCS.pop(hackathon_id, None)
        await _clear_run_lock(hackathon_id)

    cmd = [sys.executable, "-m", "forge", "run", "--id", hackathon_id]
    if restart:
        cmd.append("--restart")
    if from_phase:
        cmd.extend(["--from-phase", from_phase])

    log_path = os.path.join(_LOG_DIR, f"run-{hackathon_id[:12]}-{int(time.time())}.log")
    log_file = open(log_path, "w")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
        cwd=_PROJECT_DIR,
    )

    _ACTIVE_PROCS[hackathon_id] = proc
    await _set_run_lock(hackathon_id, proc.pid)
    asyncio.create_task(_monitor_proc(hackathon_id, proc, log_path))

    mode = "restart" if restart else (f"from {from_phase}" if from_phase else "resume")
    logger.info(f"[forge:cli] Pipeline started: {hackathon_id} ({mode}, pid={proc.pid}, log={log_path})")
    return {"ok": True, "pid": proc.pid, "mode": mode, "log": log_path}


@router.get("/api/hackathon/{hackathon_id}/run/status")
async def api_run_status(hackathon_id: str):
    """Check whether a pipeline subprocess is currently running."""
    active, reason = await _is_run_active(hackathon_id)
    proc = _ACTIVE_PROCS.get(hackathon_id)
    pid = proc.pid if proc and proc.returncode is None else None
    redis = get_redis()
    try:
        paused = await redis.get(f"hackathon:{hackathon_id}:paused")
    finally:
        await redis.aclose()
    return {
        "running": active,
        "pid": pid,
        "paused": paused == "1",
        "reason": reason if active else None,
    }


@router.post("/api/hackathon/{hackathon_id}/abort")
async def api_abort_pipeline(hackathon_id: str):
    """Kill the running pipeline subprocess and mark all in-progress agents as cancelled."""
    proc = _ACTIVE_PROCS.get(hackathon_id)
    killed_pid = None
    if proc and proc.returncode is None:
        killed_pid = proc.pid
        proc.kill()
        await proc.wait()
        _ACTIVE_PROCS.pop(hackathon_id, None)
    await _clear_run_lock(hackathon_id)

    redis = get_redis()
    try:
        await redis.delete(f"hackathon:{hackathon_id}:paused")
        keys = await redis.keys(f"task:{hackathon_id}:*")
        cancelled_agents = []
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                import json
                task = json.loads(raw)
                if task.get("status") in ("in-progress", "pending"):
                    agent_id = key.split(":")[-1]
                    task["status"] = "cancelled"
                    await redis.set(key, json.dumps(task), ex=604800)
                    cancelled_agents.append(agent_id)
            except Exception:
                pass
    finally:
        await redis.aclose()

    logger.info(f"[forge:cli] Aborted pipeline for {hackathon_id} (pid={killed_pid}, cancelled={cancelled_agents})")
    return {"ok": True, "killed_pid": killed_pid, "cancelled_agents": cancelled_agents}


@router.post("/api/hackathon/{hackathon_id}/agent/{agent_id}/cancel")
async def api_cancel_agent(hackathon_id: str, agent_id: str):
    """Cancel a single agent — sets its task status to 'cancelled'."""
    redis = get_redis()
    try:
        import json
        raw = await redis.get(f"task:{hackathon_id}:{agent_id}")
        if not raw:
            return {"ok": False, "error": "Agent task not found"}
        task = json.loads(raw)
        prev_status = task.get("status", "unknown")
        if prev_status in ("done", "cancelled"):
            return {"ok": False, "error": f"Agent already {prev_status}"}
        task["status"] = "cancelled"
        await redis.set(f"task:{hackathon_id}:{agent_id}", json.dumps(task), ex=604800)
    finally:
        await redis.aclose()
    logger.info(f"[forge:cli] Cancelled agent {agent_id} for {hackathon_id} (was {prev_status})")
    return {"ok": True, "agent_id": agent_id, "previous_status": prev_status}


@router.post("/api/hackathon/{hackathon_id}/pause")
async def api_pause_pipeline(hackathon_id: str):
    """Toggle pause for the pipeline. Paused pipelines skip new agent triggers."""
    redis = get_redis()
    try:
        current = await redis.get(f"hackathon:{hackathon_id}:paused")
        if current == "1":
            await redis.delete(f"hackathon:{hackathon_id}:paused")
            paused = False
        else:
            await redis.set(f"hackathon:{hackathon_id}:paused", "1", ex=7200)
            paused = True
    finally:
        await redis.aclose()
    logger.info(f"[forge:cli] Pipeline {'paused' if paused else 'unpaused'} for {hackathon_id}")
    return {"ok": True, "paused": paused}


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
