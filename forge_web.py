#!/usr/bin/env python3
"""
forge_web — Lightweight web dashboard for remote Forge approval & monitoring.

Start:
    forge web                      # defaults to 0.0.0.0:9090
    forge web --port 8888
    uvicorn forge_web:app --host 0.0.0.0 --port 9090

Point sentinelhive.dev (or any domain) at this server.
Access from phone/laptop to approve checkpoints without SSH.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from config.redis_client import get_redis

app = FastAPI(title="Forge Dashboard", docs_url=None, redoc_url=None)

# Basic auth — set FORGE_WEB_TOKEN in .env/forge.secrets (or auto-generate)
WEB_TOKEN = os.environ.get("FORGE_WEB_TOKEN", "")

# ─── Auth middleware ──────────────────────────────────────────────────────────

def _check_auth(request: Request) -> bool:
    if not WEB_TOKEN:
        return True
    token = request.query_params.get("token") or request.cookies.get("forge_token")
    return token == WEB_TOKEN


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ("/login", "/health"):
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path == "/":
        if not _check_auth(request):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login")
    return await call_next(request)


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_hackathons(redis) -> list[dict]:
    keys = await redis.keys("hackathon:*:brief")
    hacks = []
    for key in sorted(keys):
        hid = key.split(":")[1]
        brief_raw = await redis.get(key)
        brief = json.loads(brief_raw) if brief_raw else {}
        phase = await redis.get(f"hackathon:{hid}:phase") or "unknown"
        hacks.append({"id": hid, "brief": brief, "phase": phase})
    return hacks


async def _get_checkpoints(redis) -> list[dict]:
    keys = await redis.keys("checkpoint:*:*")
    checkpoints = []
    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) < 3:
            continue
        hid, cp_name = parts[1], parts[2]
        raw = await redis.get(key)
        is_pending = raw == "pending"
        data = {}
        if raw and raw != "pending":
            try:
                data = json.loads(raw)
            except Exception:
                pass
        checkpoints.append({
            "hackathon_id": hid,
            "checkpoint": cp_name,
            "pending": is_pending,
            "data": data,
        })
    return checkpoints


CHECKPOINT_LABELS = {
    "concept_approval": "Concept Approval",
    "design_approval": "Design Approval",
    "quality_review": "Quality Review",
    "submission_approval": "Submission Approval",
}


# ─── HTML templates ───────────────────────────────────────────────────────────

def _base(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Forge</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --dim: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --radius: 12px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; padding: 16px;
    -webkit-font-smoothing: antialiased;
  }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
  h2 {{ font-size: 1.1rem; color: var(--dim); margin-bottom: 16px; font-weight: 400; }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 16px; margin-bottom: 12px;
    transition: border-color 0.2s;
  }}
  .card:hover {{ border-color: var(--accent); }}
  .card-title {{ font-weight: 600; font-size: 1rem; margin-bottom: 6px; }}
  .card-meta {{ color: var(--dim); font-size: 0.85rem; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
  }}
  .badge-pending {{ background: rgba(210,153,34,0.15); color: var(--yellow); }}
  .badge-approved {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .badge-phase {{ background: rgba(88,166,255,0.15); color: var(--accent); }}
  .btn {{
    display: inline-block; padding: 12px 24px; border-radius: var(--radius);
    font-size: 1rem; font-weight: 600; text-decoration: none; cursor: pointer;
    border: none; text-align: center; width: 100%; margin-top: 12px;
    transition: opacity 0.2s;
  }}
  .btn:hover {{ opacity: 0.85; }}
  .btn-primary {{ background: var(--accent); color: #fff; }}
  .btn-green {{ background: var(--green); color: #fff; }}
  .btn-red {{ background: var(--red); color: #fff; }}
  .btn-outline {{
    background: transparent; color: var(--accent);
    border: 1px solid var(--accent);
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .concept {{
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px; margin-bottom: 8px;
    cursor: pointer; transition: border-color 0.2s;
  }}
  .concept:hover, .concept.selected {{ border-color: var(--green); }}
  .concept-rank {{ color: var(--accent); font-weight: 700; }}
  .concept-name {{ font-weight: 600; }}
  .concept-score {{ color: var(--dim); float: right; }}
  .concept-tagline {{ color: var(--dim); font-size: 0.85rem; margin-top: 4px; }}
  .empty {{ text-align: center; padding: 40px 16px; color: var(--dim); }}
  .topbar {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 20px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
  }}
  .topbar-logo {{ font-weight: 700; font-size: 1.2rem; }}
  input[type=text], input[type=password] {{
    width: 100%; padding: 12px; background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px; font-size: 1rem;
    margin-bottom: 12px;
  }}
  .flash {{
    padding: 12px 16px; border-radius: 8px; margin-bottom: 16px;
    font-weight: 500;
  }}
  .flash-ok {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .flash-err {{ background: rgba(248,81,73,0.15); color: var(--red); }}
</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <a href="/" class="topbar-logo">Forge</a>
    <span style="color:var(--dim);font-size:0.85rem">{datetime.now(timezone.utc).strftime('%H:%M UTC')}</span>
  </div>
  {body}
</div>
</body>
</html>"""


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not WEB_TOKEN:
        return RedirectResponse("/")
    body = """
    <h1>Forge Dashboard</h1>
    <h2>Enter access token</h2>
    <form method="get" action="/">
      <input type="password" name="token" placeholder="Access token" autofocus>
      <button type="submit" class="btn btn-primary">Login</button>
    </form>
    """
    return HTMLResponse(_base("Login", body))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, token: str | None = None):
    response = HTMLResponse("")
    if token and token == WEB_TOKEN:
        response = RedirectResponse("/")
        response.set_cookie("forge_token", token, httponly=True, max_age=86400 * 30)
        return response

    redis = get_redis()
    try:
        checkpoints = await _get_checkpoints(redis)
        hackathons = await _get_hackathons(redis)
    finally:
        await redis.aclose()

    pending = [c for c in checkpoints if c["pending"]]
    approved = [c for c in checkpoints if not c["pending"] and c["data"].get("approved")]

    body = "<h1>Dashboard</h1>"

    if pending:
        body += f'<h2>{len(pending)} pending approval{"s" if len(pending) != 1 else ""}</h2>'
        for cp in pending:
            label = CHECKPOINT_LABELS.get(cp["checkpoint"], cp["checkpoint"])
            token_param = f"?token={WEB_TOKEN}" if WEB_TOKEN else ""
            body += f"""
            <a href="/approve/{cp['hackathon_id']}/{cp['checkpoint']}{token_param}" style="text-decoration:none;color:inherit">
              <div class="card">
                <div class="card-title">{label} <span class="badge badge-pending">pending</span></div>
                <div class="card-meta">{cp['hackathon_id']}</div>
              </div>
            </a>"""
    else:
        body += '<div class="empty">No pending approvals</div>'

    if approved:
        body += "<h2 style='margin-top:20px'>Recent approvals</h2>"
        for cp in approved[-5:]:
            label = CHECKPOINT_LABELS.get(cp["checkpoint"], cp["checkpoint"])
            at = cp["data"].get("approved_at", "")[:16]
            body += f"""
            <div class="card" style="opacity:0.6">
              <div class="card-title">{label} <span class="badge badge-approved">approved</span></div>
              <div class="card-meta">{cp['hackathon_id']} &middot; {at}</div>
            </div>"""

    if hackathons:
        body += f"<h2 style='margin-top:20px'>{len(hackathons)} hackathons</h2>"
        for h in hackathons[:10]:
            name = h["brief"].get("name", h["id"])[:60]
            score = h["brief"].get("score", "?")
            body += f"""
            <div class="card">
              <div class="card-title">{name}</div>
              <div class="card-meta">
                <span class="badge badge-phase">{h['phase']}</span>
                score: {score}
              </div>
            </div>"""

    return HTMLResponse(_base("Dashboard", body))


@app.get("/approve/{hackathon_id}/{checkpoint}", response_class=HTMLResponse)
async def approve_page(hackathon_id: str, checkpoint: str, request: Request):
    redis = get_redis()
    try:
        raw = await redis.get(f"checkpoint:{hackathon_id}:{checkpoint}")
        if not raw:
            raise HTTPException(404, "Checkpoint not found")

        if raw != "pending":
            data = json.loads(raw) if raw else {}
            if data.get("approved"):
                body = f"""
                <h1>Already Approved</h1>
                <div class="flash flash-ok">
                  {CHECKPOINT_LABELS.get(checkpoint, checkpoint)} was approved
                  {data.get('approved_at', '')[:16]} by {data.get('approved_by', 'unknown')}
                </div>
                <a href="/" class="btn btn-outline">Back to dashboard</a>
                """
                return HTMLResponse(_base("Approved", body))

        label = CHECKPOINT_LABELS.get(checkpoint, checkpoint)
        body = f"<h1>{label}</h1><h2>{hackathon_id}</h2>"

        if checkpoint == "concept_approval":
            concepts_raw = await redis.get(f"hackathon:{hackathon_id}:concepts")
            if concepts_raw:
                concepts_data = json.loads(concepts_raw)
                concepts = concepts_data.get("concepts", [])
                recommended = concepts_data.get("recommended_concept", 1)

                body += '<div id="concepts">'
                for i, c in enumerate(concepts):
                    rec = " (recommended)" if (i + 1) == recommended else ""
                    body += f"""
                    <div class="concept" onclick="selectConcept({i})" id="c-{i}">
                      <div>
                        <span class="concept-rank">#{c.get('rank', i+1)}</span>
                        <span class="concept-name">{c.get('project_name', 'Untitled')}</span>
                        <span class="concept-score">{c.get('total_score', '?')}/100{rec}</span>
                      </div>
                      <div class="concept-tagline">{c.get('tagline', '')}</div>
                    </div>"""
                body += "</div>"

                body += f"""
                <input type="hidden" id="selected-concept" value="{recommended - 1}">
                <button class="btn btn-green" onclick="approveConcept()">
                  Approve Selected Concept
                </button>
                <script>
                  let selected = {recommended - 1};
                  document.getElementById('c-' + selected).classList.add('selected');
                  function selectConcept(i) {{
                    document.querySelectorAll('.concept').forEach(el => el.classList.remove('selected'));
                    document.getElementById('c-' + i).classList.add('selected');
                    selected = i;
                  }}
                  async function approveConcept() {{
                    const resp = await fetch('/api/approve/{hackathon_id}/{checkpoint}', {{
                      method: 'POST',
                      headers: {{'Content-Type': 'application/json'}},
                      body: JSON.stringify({{concept_index: selected}})
                    }});
                    if (resp.ok) window.location.href = '/?approved=1';
                    else alert('Error: ' + (await resp.json()).error);
                  }}
                </script>"""
            else:
                body += '<div class="empty">No concepts data found</div>'

        else:
            body += f"""
            <button class="btn btn-green" onclick="approveCheckpoint()">Approve</button>
            <a href="/" class="btn btn-outline" style="margin-top:8px">Cancel</a>
            <script>
              async function approveCheckpoint() {{
                const resp = await fetch('/api/approve/{hackathon_id}/{checkpoint}', {{
                  method: 'POST',
                  headers: {{'Content-Type': 'application/json'}},
                  body: '{{}}'
                }});
                if (resp.ok) window.location.href = '/?approved=1';
                else alert('Error: ' + (await resp.json()).error);
              }}
            </script>"""

        body += '<a href="/" class="btn btn-outline" style="margin-top:8px">Back</a>'
    finally:
        await redis.aclose()

    return HTMLResponse(_base(label, body))


# ─── API ──────────────────────────────────────────────────────────────────────

@app.get("/api/checkpoints")
async def api_checkpoints():
    redis = get_redis()
    try:
        return await _get_checkpoints(redis)
    finally:
        await redis.aclose()


@app.get("/api/hackathons")
async def api_hackathons():
    redis = get_redis()
    try:
        return await _get_hackathons(redis)
    finally:
        await redis.aclose()


@app.post("/api/approve/{hackathon_id}/{checkpoint}")
async def api_approve(hackathon_id: str, checkpoint: str, request: Request):
    redis = get_redis()
    try:
        key = f"checkpoint:{hackathon_id}:{checkpoint}"
        raw = await redis.get(key)
        if not raw:
            raise HTTPException(404, "Checkpoint not found")

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        approval = {
            "approved": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": "web",
        }

        if checkpoint == "concept_approval":
            approval["concept_index"] = body.get("concept_index", 0)

        await redis.set(key, json.dumps(approval), ex=86400)
        return {"ok": True, "hackathon_id": hackathon_id, "checkpoint": checkpoint}
    finally:
        await redis.aclose()


# ─── Standalone run ───────────────────────────────────────────────────────────

def start(host: str = "0.0.0.0", port: int = 3000):
    import uvicorn
    uvicorn.run("forge_web:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=3000)
    args = p.parse_args()
    start(args.host, args.port)
