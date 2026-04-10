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
from config.forge_trace import trace_op, emit_log, register_artifact, set_agent_context
from config.redis_client import get_redis
from config.agents_config import ALL_AGENTS

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
    """Return an AsyncDaytona client configured from environment.

    Reads DAYTONA_API_URL and DAYTONA_API_KEY from environment.
    Self-hosted URL should include the /api suffix (e.g. http://localhost:3986/api).
    """
    _ensure_daytona()
    from daytona_sdk import AsyncDaytona, DaytonaConfig

    api_url = (
        os.environ.get("DAYTONA_API_URL")
        or os.environ.get("DAYTONA_SERVER_URL")
    )
    if api_url and not api_url.rstrip("/").endswith("/api"):
        api_url = api_url.rstrip("/") + "/api"

    api_key = os.environ.get("DAYTONA_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "DAYTONA_API_KEY is not set. Generate one from the Daytona dashboard "
            "(http://localhost:3986 → Settings → API Keys) and add it to .env"
        )

    return AsyncDaytona(DaytonaConfig(
        api_url=api_url or "http://localhost:3986/api",
        api_key=api_key,
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

    logger.info(f"[forge:frontend] Creating Daytona sandbox (node:20-alpine) for {repo_name}")
    await emit_log(hackathon_id, "frontend_engineer", "info", f"Creating Daytona sandbox for {repo_name}")
    async with trace_op("daytona", "frontend:create_sandbox") as span:
        span.input = {"image": "node:20-alpine", "language": "typescript", "repo_name": repo_name}
        sandbox = await daytona.create(CreateSandboxFromImageParams(
            language="typescript",
            image=Image.base("node:20-alpine"),
            env_vars={
                "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
                "NEXT_PUBLIC_DEMO_MODE": "true",
                "NEXT_PUBLIC_API_URL": api_contract.get("base_url", "http://localhost:8000") if api_contract else "http://localhost:8000",
            },
        ))
        span.output = {"sandbox_id": getattr(sandbox, "id", "unknown")}
    logger.info(f"[forge:frontend] Sandbox created: {getattr(sandbox, 'id', 'unknown')}")
    await emit_log(hackathon_id, "frontend_engineer", "info", f"Sandbox created: {getattr(sandbox, 'id', 'unknown')}")

    fe_system_prompt = AGENT.system_prompt

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

        await emit_log(hackathon_id, "frontend_engineer", "info", "Scaffold complete")

        # 2. Write design tokens
        logger.debug(f"[forge:frontend] Uploading design tokens ({len(design_tokens_content)} chars)")
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
                "system_prompt": fe_system_prompt,
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
        await emit_log(hackathon_id, "frontend_engineer", "info", f"Generating {len(component_tasks)} components via LLM")
        async with trace_op("llm", "frontend:generate_components") as span:
            span.input = {"component_count": len(component_tasks), "concurrency": 4}
            component_codes = await complete_batch(component_tasks, concurrency=4)
            span.output = {"component_count": len(component_codes), "total_chars": sum(len(c) for c in component_codes)}

        for spec, code in zip(components_to_build, component_codes):
            file_path = spec.get("file_path", f"components/{spec['name'].lower()}.tsx")
            full_path = f"{repo_path}/src/{file_path}"
            await sandbox.process.exec(f"mkdir -p {os.path.dirname(full_path)}")
            await sandbox.fs.upload_file(code.encode(), full_path)
            logger.debug(f"[forge:frontend] Uploaded {file_path} ({len(code)} chars)")
        await emit_log(hackathon_id, "frontend_engineer", "info", f"Uploaded {len(component_codes)} components to sandbox")

        # 6. Generate pages
        screens = design_spec.get("screens", [])
        for screen in screens:
            route = screen.get("route", "/").lstrip("/") or "."
            async with trace_op("llm", "frontend:generate_page") as span:
                page_code = await complete(
                    task="generate-page",
                    system_prompt=fe_system_prompt,
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
        await emit_log(hackathon_id, "frontend_engineer", "info", "Running quality gates (TypeScript, ESLint, Build)")
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
        span.output = {"passed": passed, "attempts": attempt if 'attempt' in dir() else 0}
        if passed:
            await emit_log(hackathon_id, "frontend_engineer", "info", "Quality gates passed — deploying to GitHub")
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
            await emit_log(hackathon_id, "frontend_engineer", "info", f"Deployed: {preview_url}")
            register_artifact(hackathon_id, "frontend_engineer", "preview_url", preview_url, {"repo": repo_name})
            return {"preview_url": preview_url, "repo_url": f"https://github.com/{GITHUB_ORG}/{repo_name}"}
        else:
            await emit_log(hackathon_id, "frontend_engineer", "error", f"Quality gates failed after 3 attempts: {errors[:2]}")
            raise RuntimeError(f"Quality gates failed after 3 attempts: {errors}")

    finally:
        logger.info(f"[forge:frontend] Cleaning up sandbox {getattr(sandbox, 'id', 'unknown')}")
        await emit_log(hackathon_id, "frontend_engineer", "info", "Deleting Daytona sandbox")
        async with trace_op("daytona", "frontend:delete_sandbox") as span:
            span.input = {"sandbox_id": getattr(sandbox, "id", "unknown")}
            await daytona.delete(sandbox)
        await daytona.close()


async def _get_vercel_preview(repo_name: str, *, max_wait: int = 180) -> str:
    """Poll Vercel deployments API until a READY deployment is found, or return fallback."""
    import aiohttp
    token = os.environ.get("VERCEL_TOKEN")
    org_id = os.environ.get("VERCEL_ORG_ID", "")
    if not token:
        return f"https://{repo_name}.vercel.app"

    headers = {"Authorization": f"Bearer {token}"}
    fallback = f"https://{repo_name}.vercel.app"
    polls = max_wait // 10

    async with aiohttp.ClientSession() as session:
        for attempt in range(polls):
            try:
                params: dict = {"app": repo_name, "limit": "1", "target": "production"}
                if org_id:
                    params["teamId"] = org_id
                async with session.get(
                    "https://api.vercel.com/v6/deployments",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    deps = data.get("deployments", [])
                    if deps:
                        dep = deps[0]
                        state = dep.get("state") or dep.get("readyState", "")
                        if state == "READY":
                            url = dep.get("url", "")
                            if url:
                                final_url = f"https://{url}"
                                logger.info(f"[forge:frontend] Vercel deployment ready: {final_url}")
                                return final_url
                        elif state in ("ERROR", "CANCELED"):
                            logger.warning(f"[forge:frontend] Vercel deployment {state}")
                            return fallback
                        logger.debug(f"[forge:frontend] Vercel deploy state={state} (poll {attempt+1}/{polls})")
            except Exception as e:
                logger.debug(f"[forge:frontend] Vercel poll error: {e}")
            await asyncio.sleep(10)
    return fallback


async def deploy_to_vercel(repo_name: str, github_org: str) -> str:
    """Create a Vercel project linked to a GitHub repo, trigger deploy, return preview URL."""
    import aiohttp
    token = os.environ.get("VERCEL_TOKEN")
    org_id = os.environ.get("VERCEL_ORG_ID", "")
    if not token:
        logger.warning("[forge:frontend] No VERCEL_TOKEN — skipping Vercel deployment")
        return f"https://{repo_name}.vercel.app"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        body: dict = {
            "name": repo_name,
            "framework": "nextjs",
            "gitRepository": {
                "type": "github",
                "repo": f"{github_org}/{repo_name}",
            },
            "environmentVariables": [
                {"key": "NEXT_PUBLIC_DEMO_MODE", "value": "true", "target": ["production", "preview"]},
            ],
        }
        if org_id:
            body["teamId"] = org_id

        try:
            async with session.post(
                "https://api.vercel.com/v13/projects",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                if resp.status in (200, 201):
                    logger.info(f"[forge:frontend] Vercel project created: {data.get('id')}")
                elif "already exists" in json.dumps(data).lower() or resp.status == 409:
                    logger.info("[forge:frontend] Vercel project already exists — OK")
                else:
                    logger.warning(f"[forge:frontend] Vercel project create {resp.status}: {data}")
        except Exception as e:
            logger.warning(f"[forge:frontend] Vercel project creation failed: {e}")

    return await _get_vercel_preview(repo_name, max_wait=180)


async def deploy_to_railway(repo_name: str, github_org: str) -> str:
    """Create a Railway project and service linked to a GitHub repo, return service URL."""
    import aiohttp
    token = os.environ.get("RAILWAY_TOKEN", "")
    if not token:
        logger.warning("[forge:backend] No RAILWAY_TOKEN — skipping Railway deployment")
        return ""

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    full_repo = f"{github_org}/{repo_name}"

    try:
        async with aiohttp.ClientSession() as session:
            create_mutation = """
            mutation($name: String!) {
                projectCreate(input: {
                    name: $name,
                    defaultEnvironmentName: "production"
                }) { id }
            }
            """
            async with session.post(
                "https://backboard.railway.com/graphql/v2",
                headers=headers,
                json={"query": create_mutation, "variables": {"name": repo_name}},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                project_id = data.get("data", {}).get("projectCreate", {}).get("id")
                if not project_id:
                    logger.warning(f"[forge:backend] Railway project create failed: {data}")
                    return ""

            service_mutation = """
            mutation($projectId: String!, $repo: String!) {
                serviceCreate(input: {
                    projectId: $projectId,
                    name: "api",
                    source: { repo: $repo }
                }) { id }
            }
            """
            async with session.post(
                "https://backboard.railway.com/graphql/v2",
                headers=headers,
                json={
                    "query": service_mutation,
                    "variables": {"projectId": project_id, "repo": full_repo},
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                service_id = data.get("data", {}).get("serviceCreate", {}).get("id")
                if service_id:
                    # Poll for service domain
                    for _ in range(12):
                        domain_query = """
                        query($serviceId: String!) {
                            service(id: $serviceId) {
                                serviceInstances { edges { node { domains { serviceDomains { domain } } } } }
                            }
                        }
                        """
                        async with session.post(
                            "https://backboard.railway.com/graphql/v2",
                            headers=headers,
                            json={"query": domain_query, "variables": {"serviceId": service_id}},
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as dresp:
                            ddata = await dresp.json()
                            edges = ddata.get("data", {}).get("service", {}).get("serviceInstances", {}).get("edges", [])
                            if edges:
                                domains = edges[0].get("node", {}).get("domains", {}).get("serviceDomains", [])
                                if domains:
                                    domain = domains[0].get("domain", "")
                                    if domain:
                                        logger.info(f"[forge:backend] Railway deployed: https://{domain}")
                                        return f"https://{domain}"
                        await asyncio.sleep(15)
                    logger.info(f"[forge:backend] Railway service {service_id} created, domain pending")
                    return f"https://{repo_name}.up.railway.app"
                else:
                    logger.warning(f"[forge:backend] Railway service create failed: {data}")
                    return ""
    except Exception as e:
        logger.warning(f"[forge:backend] Railway deployment failed: {e}")
        return ""


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

    logger.info(f"[forge:backend] Creating Daytona sandbox (python:3.11-slim) for {repo_name}")
    await emit_log(hackathon_id, "backend_engineer", "info", f"Creating Daytona sandbox for {repo_name}")
    async with trace_op("daytona", "backend:create_sandbox") as span:
        span.input = {"image": "python:3.11-slim", "language": "python", "repo_name": repo_name}
        sandbox = await daytona.create(CreateSandboxFromImageParams(
            language="python",
            image=Image.base("python:3.11-slim"),
            env_vars={"DATABASE_URL": os.environ.get("DATABASE_URL", ""), "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
        ))
        span.output = {"sandbox_id": getattr(sandbox, "id", "unknown")}
    logger.info(f"[forge:backend] Sandbox created: {getattr(sandbox, 'id', 'unknown')}")
    await emit_log(hackathon_id, "backend_engineer", "info", f"Sandbox created: {getattr(sandbox, 'id', 'unknown')}")

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
        await emit_log(hackathon_id, "backend_engineer", "info", "API contract published to Redis — frontend unblocked")
        register_artifact(hackathon_id, "backend_engineer", "api_contract", contract_clean[:500], {"full_length": len(contract_clean)})

        # Scaffold FastAPI project
        await emit_log(hackathon_id, "backend_engineer", "info", "Scaffolding FastAPI project in sandbox")
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
        logger.debug(f"[forge:backend] Uploaded models.py ({len(models_code)} chars)")

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
        await emit_log(hackathon_id, "backend_engineer", "info", "Running quality gates (pytest, startup check)")
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
        await emit_log(hackathon_id, "backend_engineer", "info", "Deploying backend to GitHub")
        async with trace_op("subprocess", "backend:git_push") as span:
            span.input = {"repo_name": repo_name, "org": GITHUB_ORG}
            await sandbox.process.exec(
                f"cd {repo_path} && git init "
                f"&& git remote add origin https://{os.environ.get('GITHUB_TOKEN')}@github.com/{GITHUB_ORG}/{repo_name}.git "
                f"&& git add . "
                f'&& git commit -m "feat: backend api" '
                f"&& git push -u origin main",
                timeout=120,
            )
            span.output = {"repo_url": f"https://github.com/{GITHUB_ORG}/{repo_name}"}

        repo_url = f"https://github.com/{GITHUB_ORG}/{repo_name}"
        logger.info(f"[forge:backend] ✓ Deployed: {repo_url}")
        await emit_log(hackathon_id, "backend_engineer", "info", f"Deployed: {repo_url}")
        register_artifact(hackathon_id, "backend_engineer", "repo_url", repo_url, {"endpoints": len(endpoints)})

        return {"repo_url": repo_url, "api_contract_stored": True}

    finally:
        logger.info(f"[forge:backend] Cleaning up sandbox {getattr(sandbox, 'id', 'unknown')}")
        await emit_log(hackathon_id, "backend_engineer", "info", "Deleting Daytona sandbox")
        async with trace_op("daytona", "backend:delete_sandbox") as span:
            span.input = {"sandbox_id": getattr(sandbox, "id", "unknown")}
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
                    await emit_log(hackathon_id, "frontend_engineer", "error", f"Frontend engineer failed: {e}")
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
            await emit_log(hackathon_id, "backend_engineer", "error", f"Backend engineer failed: {e}")
            await redis.set(f"task:{hackathon_id}:backend_engineer", json.dumps({"status": "failed", "error": str(e)}), ex=604800)

    await redis.aclose()
