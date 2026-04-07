# -*- coding: utf-8 -*-
"""
Frontend Engineer + Backend Engineer — Layer 3: Build
Both run in parallel after design approval checkpoint.
Backend publishes ApiContract immediately so frontend can start.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel

from config.electronhub import complete, complete_batch
from config.forge_trace import trace_op, register_artifact, set_agent_context
from config.redis_client import get_redis
from config.agents_config import ALL_AGENTS
from config.design_constitution import SYSTEM_PROMPT_FRONTEND_AGENT

logger = logging.getLogger(__name__)
GITHUB_ORG = os.environ.get("GITHUB_ORG", "hackathon-agent")

_daytona_available: bool | None = None


def _ensure_daytona():
    """Lazy-check that daytona_sdk is importable; raises clear error if not."""
    global _daytona_available
    if _daytona_available is None:
        try:
            import daytona_sdk  # noqa: F401
            _daytona_available = True
        except ImportError:
            _daytona_available = False
    if not _daytona_available:
        raise RuntimeError(
            "daytona-sdk is required for build agents. "
            "Install it with: pip install -e \".[daytona]\" or pip install daytona-sdk"
        )


def get_daytona():
    """Return an AsyncDaytona client configured from environment."""
    _ensure_daytona()
    from daytona_sdk import AsyncDaytona, DaytonaConfig
    return AsyncDaytona(DaytonaConfig(
        api_url=os.environ.get("DAYTONA_API_URL", os.environ.get("DAYTONA_SERVER_URL", "http://localhost:3986")),
        api_key=os.environ.get("DAYTONA_API_KEY", ""),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# SHARED: QUALITY GATE RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_fe_quality_gates(sandbox, repo_path: str) -> tuple[bool, list[str]]:
    errors = []
    checks = [
        ("TypeScript", f"cd {repo_path} && npx tsc --noEmit 2>&1"),
        ("ESLint",     f"cd {repo_path} && npx eslint . --ext .ts,.tsx --max-warnings 0 2>&1"),
        ("Build",      f"cd {repo_path} && npm run build 2>&1"),
    ]
    for name, cmd in checks:
        result = await sandbox.process.exec(cmd, timeout=120)
        if result.exit_code != 0:
            errors.append(f"{name}: {(result.result or '')[-800:]}")
            logger.warning(f"[forge:frontend] {name} gate failed")
        else:
            logger.info(f"[forge:frontend] ✓ {name}")
    return len(errors) == 0, errors


async def run_be_quality_gates(sandbox, repo_path: str) -> tuple[bool, list[str]]:
    errors = []
    checks = [
        ("pytest",  f"cd {repo_path} && python -m pytest -x -q --timeout=30 2>&1"),
        ("startup", f"cd {repo_path} && timeout 8 uvicorn app.main:app --host 0.0.0.0 --port 8001 &>/dev/null & sleep 6 && curl -sf http://localhost:8001/health || echo FAILED"),
    ]
    for name, cmd in checks:
        result = await sandbox.process.exec(cmd, timeout=90)
        output = result.result or ""
        if result.exit_code != 0 or "FAILED" in output:
            errors.append(f"{name}: {output[-500:]}")
        else:
            logger.info(f"[forge:backend] ✓ {name}")
    return len(errors) == 0, errors


# ─────────────────────────────────────────────────────────────────────────────
# FRONTEND ENGINEER
# ─────────────────────────────────────────────────────────────────────────────

async def run_frontend_engineer(
    hackathon_id: str,
    project_plan: dict,
    design_spec: dict,
    design_tokens_content: str,
    component_specs: list[dict],
    design_md_content: str,
    api_contract: dict | None,
    simplify: bool = False,
) -> dict:
    set_agent_context(hackathon_id, "frontend_engineer")
    from daytona_sdk import CreateSandboxFromImageParams, Image
    AGENT = ALL_AGENTS["frontend_engineer"]
    daytona = get_daytona()
    repo_name = f"hack-{hackathon_id[:8]}-frontend"
    repo_path = f"/workspace/{repo_name}"

    sandbox = await daytona.create(CreateSandboxFromImageParams(
        language="typescript",
        image=Image.base("node:20-alpine"),
        env_vars={
            "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
            "NEXT_PUBLIC_DEMO_MODE": "true",
            "NEXT_PUBLIC_API_URL": api_contract.get("base_url", "http://localhost:8000") if api_contract else "http://localhost:8000",
        },
    ))

    try:
        # 1. Scaffold with exact stack
        logger.info(f"[forge:frontend] Scaffolding {repo_name}...")
        async with trace_op("subprocess", "frontend:scaffold") as span:
            await sandbox.process.exec(
                f"npx create-next-app@latest {repo_name} "
                f"--typescript --tailwind --app --yes "
                f"--import-alias '@/*' "
                f"--use-npm",
                timeout=180,
            )
            await sandbox.process.exec(
                f"cd {repo_path} && npx shadcn@latest init --yes --defaults",
                timeout=120,
            )
            await sandbox.process.exec(
                f"cd {repo_path} && npm install @tanstack/react-query zod clsx tailwind-merge class-variance-authority lucide-react",
                timeout=60,
            )

        # 2. Write design tokens
        await sandbox.fs.upload_file(design_tokens_content.encode(), f"{repo_path}/src/lib/tokens.ts")

        # 3. Write tailwind config with design tokens
        tailwind_extension = design_spec.get("tokens", {}).get("tailwind_config_extension", "")
        if tailwind_extension:
            tailwind_config = await complete(
                task="fix-typescript-error",
                messages=[{"role": "user", "content": f"""Generate a complete tailwind.config.ts file 
that uses these theme extensions:
{tailwind_extension}

Output ONLY the complete TypeScript file, starting with: import type {{ Config }} from 'tailwindcss'"""}],
            )
            await sandbox.fs.upload_file(tailwind_config.encode(), f"{repo_path}/tailwind.config.ts")

        # 4. Write CSS variables
        css_vars = design_spec.get("tokens", {}).get("css_variables", "")
        if css_vars:
            globals_css = f"@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n{css_vars}"
            await sandbox.fs.upload_file(globals_css.encode(), f"{repo_path}/src/app/globals.css")

        # 5. Generate components from specs
        components_to_build = component_specs
        if simplify:
            components_to_build = [c for c in component_specs if c.get("is_demo_critical", False)]
            logger.info(f"[forge:frontend] Simplify mode: {len(components_to_build)} critical components only")

        component_tasks = [
            {
                "task": "generate-component",
                "system_prompt": SYSTEM_PROMPT_FRONTEND_AGENT,
                "messages": [{
                    "role": "user",
                    "content": f"""Generate a complete React component.

Component spec from DESIGN.md:
{json.dumps(c, indent=2)}

Rules:
- Use design tokens from @/lib/tokens (never hardcode hex values)
- Use CVA for variants
- Implement ALL states from the spec
- Use the exact real_copy values (no placeholders)
- shadcn/ui base: {c.get('shadcn_base', 'custom')}
- TypeScript strict (no any types)

Output the complete .tsx file only.""",
                }],
                "temperature": 0.1,
            }
            for c in components_to_build
        ]

        logger.info(f"[forge:frontend] Generating {len(component_tasks)} components...")
        async with trace_op("llm", "frontend:generate_components") as span:
            component_codes = await complete_batch(component_tasks, concurrency=4)
            span.output = {"component_count": len(component_codes)}

        for spec, code in zip(components_to_build, component_codes):
            file_path = spec.get("file_path", f"components/{spec['name'].lower()}.tsx")
            full_path = f"{repo_path}/src/{file_path}"
            await sandbox.process.exec(f"mkdir -p {os.path.dirname(full_path)}")
            await sandbox.fs.upload_file(code.encode(), full_path)

        # 6. Generate pages
        screens = design_spec.get("screens", [])
        for screen in screens:
            route = screen.get("route", "/").lstrip("/") or "."
            async with trace_op("llm", "frontend:generate_page") as span:
                page_code = await complete(
                    task="generate-page",
                    system_prompt=SYSTEM_PROMPT_FRONTEND_AGENT,
                    messages=[{
                        "role": "user",
                        "content": f"""Generate a Next.js 14 App Router page.

Screen: {json.dumps(screen, indent=2)}

API endpoints on this page's demo path:
{json.dumps([e for e in (api_contract or {}).get("endpoints", []) if e.get("is_demo_path")], indent=2)[:800]}

DESIGN.md context (for this screen):
{design_md_content[:1500]}

Output files needed:
1. app/{route}/page.tsx — server component with TanStack Query
2. Include loading.tsx and error.tsx as brief stubs

Start your response with --- FILE: app/{route}/page.tsx ---""",
                    }],
                    temperature=0.1,
                )

            page_dir = f"{repo_path}/src/app/{route}"
            await sandbox.process.exec(f"mkdir -p {page_dir}")
            await sandbox.fs.upload_file(page_code.encode(), f"{page_dir}/page.tsx")

        # 7. Quality gates with auto-fix
        async with trace_op("subprocess", "frontend:quality_gates") as span:
            for attempt in range(1, 4):
                passed, errors = await run_fe_quality_gates(sandbox, repo_path)
                if passed:
                    break
                logger.warning(f"[forge:frontend] Gates failed (attempt {attempt}/3), auto-fixing...")
                fix_tasks = [
                    {
                        "task": "fix-typescript-error" if "TypeScript" in e else "fix-lint-error",
                        "messages": [{"role": "user", "content": f"Fix this error:\n{e}\n\nRespond with FILE: path\\ncode"}],
                    }
                    for e in errors[:3]
                ]
                fixes = await complete_batch(fix_tasks, concurrency=3)
                for fix in fixes:
                    lines = fix.strip().split("\n")
                    if lines and lines[0].startswith("FILE:"):
                        fp = lines[0].replace("FILE:", "").strip()
                        code = "\n".join(lines[1:])
                        await sandbox.fs.upload_file(code.encode(), f"{repo_path}/src/{fp}")

        # 8. Deploy
        if passed:
            await sandbox.process.exec(
                f"cd {repo_path} && git init "
                f"&& git remote add origin https://{os.environ.get('GITHUB_TOKEN')}@github.com/{GITHUB_ORG}/{repo_name}.git "
                f"&& git add . "
                f'&& git commit -m "feat: hackathon project" '
                f"&& git push -u origin main",
                timeout=120,
            )
            preview_url = await _get_vercel_preview(repo_name)
            logger.info(f"[forge:frontend] ✓ Deployed: {preview_url}")
            return {"preview_url": preview_url, "repo_url": f"https://github.com/{GITHUB_ORG}/{repo_name}"}
        else:
            raise RuntimeError(f"Quality gates failed after 3 attempts: {errors}")

    finally:
        await daytona.delete(sandbox)
        await daytona.close()


async def _get_vercel_preview(repo_name: str) -> str:
    import aiohttp
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        return f"https://{repo_name}.vercel.app"
    async with aiohttp.ClientSession() as session:
        for _ in range(12):
            async with session.get(
                f"https://api.vercel.com/v6/deployments?app={repo_name}&limit=1",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                data = await resp.json()
                deps = data.get("deployments", [])
                if deps and deps[0].get("state") == "READY":
                    return f"https://{deps[0]['url']}"
            await asyncio.sleep(10)
    return f"https://{repo_name}.vercel.app"


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND ENGINEER
# ─────────────────────────────────────────────────────────────────────────────

async def run_backend_engineer(
    hackathon_id: str,
    project_plan: dict,
    db_schema: dict,
    simplify: bool = False,
) -> dict:
    set_agent_context(hackathon_id, "backend_engineer")
    from daytona_sdk import CreateSandboxFromImageParams, Image
    AGENT = ALL_AGENTS["backend_engineer"]
    daytona = get_daytona()
    repo_name = f"hack-{hackathon_id[:8]}-backend"
    repo_path = f"/workspace/{repo_name}"
    redis = get_redis()

    sandbox = await daytona.create(CreateSandboxFromImageParams(
        language="python",
        image=Image.base("python:3.11-slim"),
        env_vars={"DATABASE_URL": os.environ.get("DATABASE_URL", ""), "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
    ))

    try:
        # IMMEDIATE: design and publish API contract
        logger.info(f"[forge:backend] Designing API contract for immediate publish...")
        async with trace_op("llm", "backend:design_api_contract") as span:
            api_contract_raw = await complete(
                task="design-api-contract",
                system_prompt=AGENT.system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"""Design the FastAPI API contract for this project.

Project: {project_plan.get('project_name')}
Features: {json.dumps([f.get('name') for f in project_plan.get('core_features', [])], indent=2)}
DB Schema: {json.dumps(db_schema.get('tables', [])[:3], indent=2)}
Demo path: {json.dumps(project_plan.get('demo_golden_path', [])[:6], indent=2)}

Output as JSON with: base_url, endpoints (with method, path, request_body, response_schema, is_demo_path), schemas.
Include /health and /demo/seed endpoints.""",
                }],
                temperature=0.1,
            )

        # Clean and store contract immediately
        contract_clean = api_contract_raw.strip()
        if contract_clean.startswith("```"):
            contract_clean = contract_clean.split("\n", 1)[1].rsplit("```", 1)[0]
        await redis.set(f"hackathon:{hackathon_id}:api_contract", contract_clean, ex=604800)
        await redis.publish("agent:api_contract_ready", json.dumps({
            "hackathon_id": hackathon_id,
            "api_contract": json.loads(contract_clean),
        }))
        logger.info(f"[forge:backend] ✓ API contract published — frontend can now start")

        # Scaffold FastAPI project
        await sandbox.process.exec(
            f"mkdir -p {repo_path}/app/routers {repo_path}/tests "
            f"&& cd {repo_path} "
            f"&& pip install fastapi uvicorn sqlalchemy asyncpg pydantic pydantic-settings "
            f"pytest pytest-asyncio httpx alembic python-jose 2>&1 | tail -5",
            timeout=120,
        )

        # Generate models, routers, main.py
        async with trace_op("llm", "backend:generate_models") as span:
            models_code = await complete(
                task="design-db-schema",
                system_prompt=AGENT.system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"""Generate SQLAlchemy 2.0 async models for:
{json.dumps(db_schema.get('tables', []), indent=2)}

Complete app/models.py file. AsyncAttrs mixin, UUID PKs, timestamps, relationships.""",
                }],
                temperature=0.0,
            )
        await sandbox.fs.upload_file(models_code.encode(), f"{repo_path}/app/models.py")

        # Parse contract and generate routers
        try:
            contract = json.loads(contract_clean)
            endpoints = contract.get("endpoints", [])
        except Exception:
            endpoints = []

        if endpoints:
            router_code = await complete(
                task="generate-api-route",
                system_prompt=AGENT.system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"""Generate FastAPI router for these endpoints:
{json.dumps(endpoints[:10], indent=2)}

Include the /demo/seed endpoint that creates realistic demo data (idempotent).
Output complete app/routers/main.py""",
                }],
                temperature=0.1,
            )
            await sandbox.fs.upload_file(router_code.encode(), f"{repo_path}/app/routers/main.py")

        # main.py
        main_py = f'''"""FastAPI app — {project_plan.get('project_name')}"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.main import router

app = FastAPI(title="{project_plan.get('project_name')}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health() -> dict:
    return {{"status": "ok", "version": "1.0.0"}}
'''
        await sandbox.fs.upload_file(main_py.encode(), f"{repo_path}/app/main.py")

        # Quality gates
        for attempt in range(1, 4):
            passed, errors = await run_be_quality_gates(sandbox, repo_path)
            if passed:
                break
            for error in errors[:2]:
                fix = await complete(
                    task="fix-python-error",
                    messages=[{"role": "user", "content": f"Fix:\n{error}\n\nRespond with FILE: path\\ncode"}],
                )
                lines = fix.strip().split("\n")
                if lines and lines[0].startswith("FILE:"):
                    fp = lines[0].replace("FILE:", "").strip()
                    code = "\n".join(lines[1:])
                    await sandbox.fs.upload_file(code.encode(), f"{repo_path}/{fp}")

        # Feature 5: Publish contract delta so Frontend can re-generate affected API clients.
        # If router generation added or modified endpoints vs the initial contract, notify frontend.
        try:
            if endpoints:
                await redis.publish("agent:api_contract_delta", json.dumps({
                    "hackathon_id": hackathon_id,
                    "message": "Backend implementation complete — API contract finalised",
                    "endpoints_implemented": [
                        {"method": e.get("method"), "path": e.get("path")}
                        for e in endpoints[:20]
                    ],
                }))
                logger.info(f"[forge:backend] Published contract delta — {len(endpoints)} endpoints finalised")
        except Exception as e:
            logger.debug(f"[forge:backend] Contract delta publish failed (non-critical): {e}")

        # Deploy
        await sandbox.process.exec(
            f"cd {repo_path} && git init "
            f"&& git remote add origin https://{os.environ.get('GITHUB_TOKEN')}@github.com/{GITHUB_ORG}/{repo_name}.git "
            f"&& git add . "
            f'&& git commit -m "feat: backend api" '
            f"&& git push -u origin main",
            timeout=120,
        )

        return {
            "repo_url": f"https://github.com/{GITHUB_ORG}/{repo_name}",
            "api_contract_stored": True,
        }

    finally:
        await daytona.delete(sandbox)
        await daytona.close()
        await redis.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# REDIS WORKERS
# ─────────────────────────────────────────────────────────────────────────────

async def run_frontend_worker() -> None:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger", "agent:api_contract_ready", "agent:api_contract_delta")
    logger.info("[forge:frontend] Worker ready — waiting for API contract to start")

    pending: dict[str, dict] = {}
    active_workspaces: dict[str, str] = {}  # hackathon_id → repo_path

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])

        # Queue frontend trigger
        if payload.get("agent") == "frontend_engineer":
            hackathon_id = payload["hackathon_id"]
            pending[hackathon_id] = payload

        # Unblock when API contract arrives
        elif "api_contract" in payload and payload.get("hackathon_id") in pending:
            hackathon_id = payload.get("hackathon_id")
            if hackathon_id and hackathon_id in pending:
                set_agent_context(hackathon_id, "frontend_engineer")
                inp = pending.pop(hackathon_id)["input"]
                inp["api_contract"] = payload["api_contract"]
                await redis.set(f"task:{hackathon_id}:frontend_engineer", json.dumps({"status": "in-progress"}), ex=604800)
                try:
                    result = await run_frontend_engineer(hackathon_id=hackathon_id, **{k: inp[k] for k in [
                        "project_plan", "design_spec", "design_tokens_content",
                        "component_specs", "design_md_content", "api_contract",
                    ] if k in inp})
                    active_workspaces[hackathon_id] = result.get("repo_path", "")
                    await redis.set(f"task:{hackathon_id}:frontend_engineer", json.dumps({"status": "done", "data": result}), ex=604800)
                except Exception as e:
                    logger.error(f"[forge:frontend] Failed: {e}")
                    await redis.set(f"task:{hackathon_id}:frontend_engineer", json.dumps({"status": "failed", "error": str(e)}), ex=604800)

        # Feature 5: Backend finalised contract — regenerate only the API client layer
        elif message["channel"] == "agent:api_contract_delta":
            hackathon_id = payload.get("hackathon_id", "")
            endpoints = payload.get("endpoints_implemented", [])
            if not hackathon_id or not endpoints:
                continue
            logger.info(
                f"[forge:frontend] Received contract delta for {hackathon_id} "
                f"({len(endpoints)} endpoints) — regenerating API client"
            )
            try:
                # Re-fetch the final contract from Redis and regenerate just the API client
                api_contract_raw = await redis.get(f"hackathon:{hackathon_id}:api_contract")
                if not api_contract_raw:
                    continue

                api_contract = json.loads(api_contract_raw)
                from config.electronhub import complete as llm_complete
                client_code = await llm_complete(
                    task="generate-component",
                    messages=[{
                        "role": "user",
                        "content": f"""Regenerate the TypeScript API client (src/lib/api.ts) 
based on the finalised backend contract.

Endpoints:
{json.dumps(api_contract.get('endpoints', [])[:15], indent=2)}

Requirements:
- Async functions per endpoint, typed request/response
- Base URL from NEXT_PUBLIC_API_URL env var
- Demo mode: if NEXT_PUBLIC_DEMO_MODE='true', return mock data
- All functions return {{data, error}} not throw

Output only the complete src/lib/api.ts file.""",
                    }],
                    temperature=0.0,
                )

                # Store for Polish Agent to pick up if needed
                await redis.set(
                    f"hackathon:{hackathon_id}:api_client_v2",
                    client_code,
                    ex=604800,
                )
                logger.info(f"[forge:frontend] API client regenerated from delta for {hackathon_id}")
            except Exception as e:
                logger.warning(f"[forge:frontend] Delta regeneration failed (non-critical): {e}")

    await redis.aclose()


async def run_backend_worker() -> None:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")
    logger.info("[forge:backend] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "backend_engineer":
            continue

        hackathon_id = payload["hackathon_id"]
        set_agent_context(hackathon_id, "backend_engineer")
        inp = payload["input"]
        await redis.set(f"task:{hackathon_id}:backend_engineer", json.dumps({"status": "in-progress"}), ex=604800)
        try:
            result = await run_backend_engineer(
                hackathon_id=hackathon_id,
                project_plan=inp["project_plan"],
                db_schema=inp.get("db_schema", {}),
                simplify=inp.get("simplify", False),
            )
            await redis.set(f"task:{hackathon_id}:backend_engineer", json.dumps({"status": "done", "data": result}), ex=604800)
        except Exception as e:
            logger.error(f"[forge:backend] Failed: {e}")
            await redis.set(f"task:{hackathon_id}:backend_engineer", json.dumps({"status": "failed", "error": str(e)}), ex=604800)

    await redis.aclose()
