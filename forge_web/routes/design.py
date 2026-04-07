"""Design and artifacts endpoints."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter

from forge_web.services import redis_conn

router = APIRouter()

_EMPTY_DESIGN = {
    "design_md": "",
    "screenshots": [],
    "tokens": {},
    "components": [],
    "screens": [],
    "personality": None,
    "critique": None,
    "figma_file_id": None,
}


@router.get("/api/hackathon/{hackathon_id}/design")
async def api_design(hackathon_id: str):
    async with redis_conn() as redis:
        raw = await redis.get(f"hackathon:{hackathon_id}:design_spec")
        if raw:
            try:
                data = json.loads(raw)
                return {
                    "design_md": data.get("design_md", data.get("markdown", "")),
                    "screenshots": data.get("screenshots", []),
                    "tokens": data.get("tokens") or {},
                    "components": data.get("components", []),
                    "screens": data.get("screens", []),
                    "personality": data.get("personality"),
                    "critique": data.get("critique") or data.get("self_critique"),
                    "figma_file_id": data.get("figma_file_id"),
                }
            except Exception:
                return {**_EMPTY_DESIGN, "design_md": raw}

        task_raw = await redis.get(f"task:{hackathon_id}:ui_ux_designer")
        if not task_raw:
            return dict(_EMPTY_DESIGN)

        try:
            task = json.loads(task_raw)
        except Exception:
            return dict(_EMPTY_DESIGN)

        data = task.get("data") or {}

        design_md = ""
        md_path = data.get("design_md_path")
        if md_path and os.path.isfile(md_path):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    design_md = f.read()
            except Exception:
                pass
        if not design_md:
            spec = data.get("design_spec") or {}
            parts = []
            if spec.get("app_name"):
                parts.append(f"# {spec['app_name']}")
            if spec.get("description"):
                parts.append(spec["description"])
            for screen in spec.get("screens", []):
                parts.append(f"## {screen.get('name', 'Screen')}")
                if screen.get("purpose"):
                    parts.append(screen["purpose"])
            design_md = "\n\n".join(parts)

        screenshots = []
        for ss in data.get("stitch_screens", []):
            if ss.get("image_url"):
                screenshots.append(ss["image_url"])
        spec = data.get("design_spec") or {}
        for screen in spec.get("screens", []):
            if screen.get("image_url"):
                screenshots.append(screen["image_url"])

        tokens = data.get("tokens") or {}

        components = []
        for comp in (spec.get("components") or []):
            components.append({
                "name": comp.get("name", ""),
                "description": comp.get("description", ""),
                "is_demo_critical": comp.get("is_demo_critical", False),
                "file_path": comp.get("file_path", ""),
                "shadcn_base": comp.get("shadcn_base", ""),
                "purpose": comp.get("purpose", ""),
            })

        screens = []
        for scr in (spec.get("screens") or []):
            screens.append({
                "route": scr.get("route", ""),
                "name": scr.get("name", ""),
                "purpose": scr.get("purpose", ""),
                "primary_action": scr.get("primary_action", ""),
            })

        return {
            "design_md": design_md,
            "screenshots": screenshots,
            "tokens": tokens,
            "components": components,
            "screens": screens,
            "personality": data.get("personality"),
            "critique": data.get("self_critique") or data.get("critique"),
            "figma_file_id": data.get("figma_file_id"),
        }


@router.get("/api/hackathon/{hackathon_id}/artifacts")
async def api_artifacts(hackathon_id: str):
    async with redis_conn() as redis:
        keys = await redis.keys(f"hackathon:{hackathon_id}:*")
        artifacts = []
        for key in sorted(keys):
            if key.endswith(":brief"):
                continue
            raw = await redis.get(key)
            data: Any = None
            if raw:
                try:
                    data = json.loads(raw)
                except Exception:
                    data = raw
            artifacts.append({"key": key, "data": data})
        return artifacts
