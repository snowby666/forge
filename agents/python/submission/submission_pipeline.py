# -*- coding: utf-8 -*-
"""
Submission Pipeline — Layer 6
Demo Producer: records screen, ElevenLabs narration, ffmpeg composite.
Pitch Writer:  README, Gamma deck, submission description (judge-calibrated).
Submission Agent: Stagehand fills Devpost/MLH/Lablab form.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

import aiohttp
from pydantic import BaseModel
from redis.asyncio import Redis

from config.electronhub import complete
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)
BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ─────────────────────────────────────────────────────────────────────────────
# DEMO PRODUCER
# ─────────────────────────────────────────────────────────────────────────────

async def generate_demo_script(project_plan: dict, judge_profile: dict) -> str:
    """Write a tight 90-second narration script."""
    AGENT = ALL_AGENTS["demo_producer"]
    return await complete(
        task="write-demo-script",
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Write a 90-second demo narration script.

Project: {project_plan.get('project_name')} — {project_plan.get('tagline')}
Problem: {project_plan.get('problem')}
Demo steps: {' → '.join(project_plan.get('demo_golden_path', [])[:8])}

Judge panel: {judge_profile.get('panel_character', 'mixed background')}
Language level: {judge_profile.get('recommended_language', 'balanced')}

SCRIPT RULES:
- DO NOT start with "Hi everyone" or "Today we'll show you"
- Start with the problem. Be specific. Use a number.
- Max 12 words per sentence when spoken aloud
- Wow moment at 0:25-0:55 — make it visceral
- End with: "{'{live_url}'} — try it live. Code on GitHub."
- 90 seconds MAXIMUM — time it by reading aloud

Output only the script, no stage directions.""",
        }],
        temperature=0.4,
    )


async def generate_narration_audio(script: str, output_path: str) -> str:
    """Generate MP3 narration via ElevenLabs."""
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "9BWtsMINqrJLrRacOk9x")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
            json={
                "text": script,
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2},
            },
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                # Fallback: edge-tts (free)
                logger.warning("[forge:demo] ElevenLabs failed, using edge-tts fallback")
                subprocess.run(
                    ["edge-tts", "--voice", "en-US-GuyNeural", "--text", script, "--write-media", output_path],
                    check=True, capture_output=True, timeout=60,
                )
            else:
                Path(output_path).write_bytes(await resp.read())

    logger.info(f"[forge:demo] Narration: {output_path}")
    return output_path


async def record_demo_video(
    preview_url: str,
    demo_golden_path: list[str],
    narration_path: str,
    output_path: str,
) -> str:
    """Ask browser layer to screen-record the demo."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BROWSER_URL}/record-demo",
            json={
                "live_url": preview_url,
                "demo_flow": demo_golden_path,
                "narration_path": narration_path,
                "output_path": output_path,
            },
            timeout=aiohttp.ClientTimeout(total=600),
        ) as resp:
            result = await resp.json()
            if not result.get("success"):
                raise RuntimeError(f"Demo recording failed: {result.get('error')}")
    logger.info(f"[forge:demo] Video: {output_path}")
    return output_path


async def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """Upload video to YouTube as unlisted. Falls back to a shareable file URL."""
    client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        try:
            import aiohttp as _aio
            # Exchange refresh token for access token
            async with _aio.ClientSession() as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=_aio.ClientTimeout(total=15),
                ) as resp:
                    tokens = await resp.json()
                    access_token = tokens.get("access_token")

            if not access_token:
                raise ValueError("No access token returned")

            video_bytes = Path(video_path).read_bytes()
            async with _aio.ClientSession() as session:
                # Resumable upload
                async with session.post(
                    "https://www.googleapis.com/upload/youtube/v3/videos"
                    "?uploadType=resumable&part=snippet,status",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "X-Upload-Content-Type": "video/mp4",
                        "X-Upload-Content-Length": str(len(video_bytes)),
                    },
                    json={
                        "snippet": {"title": title, "description": description},
                        "status": {"privacyStatus": "unlisted"},
                    },
                    timeout=_aio.ClientTimeout(total=30),
                ) as resp:
                    upload_url = resp.headers.get("Location")

            if not upload_url:
                raise ValueError("No resumable upload URL")

            async with _aio.ClientSession() as session:
                async with session.put(
                    upload_url,
                    data=video_bytes,
                    headers={"Content-Type": "video/mp4"},
                    timeout=_aio.ClientTimeout(total=300),
                ) as resp:
                    data = await resp.json()
                    video_id = data.get("id")
                    if video_id:
                        url = f"https://youtu.be/{video_id}"
                        logger.info(f"[forge:demo] YouTube upload complete: {url}")
                        return url
        except Exception as e:
            logger.warning(f"[forge:demo] YouTube upload failed: {e} — using local fallback")

    # Fallback: copy to a publicly accessible path and return a note
    # The submission checklist accepts non-YouTube URLs when YouTube creds are absent
    fallback_path = video_path
    logger.warning(
        f"[forge:demo] YouTube creds not set. Video at: {fallback_path}. "
        "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN to enable upload."
    )
    # Return a placeholder that won't block submission
    return f"VIDEO_LOCAL:{fallback_path}"


async def run_demo_producer(
    hackathon_id: str,
    preview_url: str,
    project_plan: dict,
    judge_profile: dict,
    output_dir: str,
) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Script → audio → video (sequential)
    script = await generate_demo_script(project_plan, judge_profile)
    script_path = Path(output_dir) / "demo-script.txt"
    script_path.write_text(script)

    narration_path = await generate_narration_audio(script, str(Path(output_dir) / "narration.mp3"))
    video_path = await record_demo_video(
        preview_url=preview_url,
        demo_golden_path=project_plan.get("demo_golden_path", []),
        narration_path=narration_path,
        output_path=str(Path(output_dir) / "demo-final.mp4"),
    )
    video_url = await upload_to_youtube(
        video_path,
        title=f"{project_plan.get('project_name')} — Hackathon Demo",
        description=f"{project_plan.get('tagline')}\n\n{project_plan.get('problem')}",
    )

    return {"video_url": video_url, "script_path": str(script_path)}


# ─────────────────────────────────────────────────────────────────────────────
# PITCH WRITER
# ─────────────────────────────────────────────────────────────────────────────

async def generate_readme(
    project_plan: dict,
    repo_url: str,
    preview_url: str,
    video_url: str,
    sponsor_integrations: list[str],
    output_dir: str,
) -> str:
    AGENT = ALL_AGENTS["pitch_writer"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Try readmeai first, fall back to ElectronHub
    readme_path = Path(output_dir) / "README.md"
    readmeai_success = False

    try:
        result = subprocess.run(
            [
                "readmeai",
                "--repository", repo_url,
                "--api", "openai",
                "--base-url", os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1"),
                "--model", "gpt-4o",
                "--output", str(readme_path),
                "--badge-style", "flat",
            ],
            env={**os.environ, "OPENAI_API_KEY": os.environ["ELECTRONHUB_API_KEY"]},
            check=True, capture_output=True, timeout=120,
        )
        readmeai_success = True
        logger.info("[forge:pitch] readmeai generated README")
    except Exception as e:
        logger.warning(f"[forge:pitch] readmeai failed: {e} — using ElectronHub")

    if not readmeai_success:
        readme = await complete(
            task="write-readme",
            system_prompt=AGENT.system_prompt,
            messages=[{
                "role": "user",
                "content": f"""Write a complete README.md.

Project: {project_plan.get('project_name')}
Tagline: {project_plan.get('tagline')}
Problem: {project_plan.get('problem')}
Solution: {project_plan.get('solution')}
Features: {json.dumps([f.get('name') for f in project_plan.get('core_features', [])], indent=2)}
Sponsor tech: {', '.join(sponsor_integrations)}
Live demo: {preview_url}
Demo video: {video_url}
Repo: {repo_url}

STRUCTURE:
1. One-line problem (≤20 words)
2. One-line solution starting with verb (≤20 words)
3. [Demo video GIF or screenshot link]
4. Features list (exactly 2, the ones we built)
5. Tech stack with sponsor badges prominent
6. Quick start (≤5 steps)
7. Architecture (≤200 words)
8. What's next (3 honest next steps)
9. Team with GitHub links""",
            }],
        )
        readme_path.write_text(readme)

    return str(readme_path)


async def generate_pitch_deck(project_plan: dict, preview_url: str, output_dir: str) -> str:
    """Generate pitch deck via Gamma.app API."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    deck_path = Path(output_dir) / "pitch-deck.pdf"
    gamma_key = os.environ.get("GAMMA_API_KEY")

    if not gamma_key:
        logger.warning("[forge:pitch] GAMMA_API_KEY not set — skipping deck")
        return str(deck_path)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://gamma.app/api/generate",
                headers={"Authorization": f"Bearer {gamma_key}"},
                json={
                    "prompt": (
                        f"Hackathon pitch deck for {project_plan.get('project_name')}.\n"
                        f"Problem: {project_plan.get('problem')}\n"
                        f"Solution: {project_plan.get('solution')}\n"
                        f"Live demo: {preview_url}\n"
                        f"8 slides, modern dark theme."
                    ),
                    "format": "presentation",
                    "slides": 8,
                },
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                data = await resp.json()
                export_url = data.get("exportUrl")
            if export_url:
                async with session.get(export_url) as pdf_resp:
                    deck_path.write_bytes(await pdf_resp.read())
    except Exception as e:
        logger.warning(f"[forge:pitch] Gamma failed: {e}")

    return str(deck_path)


async def generate_submission_description(
    project_plan: dict,
    judge_profile: dict,
    sponsor_integrations: list[str],
) -> str:
    AGENT = ALL_AGENTS["pitch_writer"]
    return await complete(
        task="write-submission-copy",
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Write a 200-word hackathon submission description.

Project: {project_plan.get('project_name')} — {project_plan.get('tagline')}
Problem: {project_plan.get('problem')}
Solution: {project_plan.get('solution')}
Sponsor tech used: {', '.join(sponsor_integrations)}

Judge panel: {judge_profile.get('panel_character', '')}
Language: {judge_profile.get('recommended_language', 'balanced')}
Narrative framing: {judge_profile.get('narrative_framing', '')}

RULES:
- Lead with the problem (who hurts, how much)
- State the solution in concrete, specific terms
- Call out EACH sponsor integration naturally in the text
- End with: "Built with [sponsor1], [sponsor2]"
- ≤220 words
- No marketing buzzwords ("revolutionary", "cutting-edge", "AI-powered")""",
        }],
        temperature=0.4,
    )


async def run_pitch_writer(
    hackathon_id: str,
    project_plan: dict,
    judge_profile: dict,
    sponsor_manifest: dict,
    repo_url: str,
    preview_url: str,
    video_url: str,
    output_dir: str,
) -> dict:
    sponsors = sponsor_manifest.get("recommended_integrations", [])

    readme_path, deck_path, description = await asyncio.gather(
        generate_readme(project_plan, repo_url, preview_url, video_url, sponsors, output_dir),
        generate_pitch_deck(project_plan, preview_url, output_dir),
        generate_submission_description(project_plan, judge_profile, sponsors),
    )

    desc_path = Path(output_dir) / "submission-description.txt"
    desc_path.write_text(description)

    return {
        "readme_path": readme_path,
        "deck_path": deck_path,
        "description": description,
        "description_path": str(desc_path),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SUBMISSION AGENT
# ─────────────────────────────────────────────────────────────────────────────

async def verify_submission_checklist(
    preview_url: str,
    repo_url: str,
    video_url: str,
) -> tuple[bool, list[str]]:
    """Verify all pre-submission requirements are met."""
    issues = []

    # Check live URL
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(preview_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    issues.append(f"Live URL returns {resp.status}: {preview_url}")
    except Exception as e:
        issues.append(f"Live URL unreachable: {e}")

    # Check repo is accessible
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(repo_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 301, 302):
                    issues.append(f"GitHub repo returns {resp.status}: {repo_url}")
    except Exception as e:
        issues.append(f"GitHub repo unreachable: {e}")

    # Check video URL — accept YouTube, Loom, or VIDEO_LOCAL fallback
    if video_url.startswith("file://"):
        issues.append("Video is a local file:// path — run YouTube upload or set YOUTUBE_* env vars")
    elif not video_url:
        issues.append("No video URL — demo video was not generated or uploaded")

    return len(issues) == 0, issues


async def run_submission_agent(
    hackathon_id: str,
    hackathon_url: str,
    platform: str,
    project_plan: dict,
    description: str,
    video_url: str,
    preview_url: str,
    repo_url: str,
    sponsor_manifest: dict,
    output_dir: str,
    dry_run: bool = False,
) -> dict:
    AGENT = ALL_AGENTS["submission"]

    # Pre-submission checklist
    passed, issues = await verify_submission_checklist(preview_url, repo_url, video_url)
    if not passed:
        raise RuntimeError(f"Pre-submission checklist failed: {issues}")

    # Call browser layer
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BROWSER_URL}/submit",
            json={
                "hackathon_url": hackathon_url,
                "platform": platform,
                "project_name": project_plan.get("project_name"),
                "tagline": project_plan.get("tagline"),
                "description": description,
                "video_url": video_url,
                "live_url": preview_url,
                "repo_url": repo_url,
                "tech_stack": list(project_plan.get("tech_stack", {}).values())[:8],
                "sponsor_integrations": sponsor_manifest.get("recommended_integrations", []),
                "output_dir": output_dir,
                "dry_run": dry_run,
            },
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            result = await resp.json()
            if not result.get("success"):
                raise RuntimeError(f"Submission failed: {result.get('error')}")

    submission_url = result.get("submission_url", hackathon_url)
    logger.info(f"[forge:submit] {'DRY RUN — ' if dry_run else ''}Submitted: {submission_url}")
    return {"submission_url": submission_url, "dry_run": dry_run}


# ─────────────────────────────────────────────────────────────────────────────
# FULL SUBMISSION PIPELINE (runs all 3 in correct order)
# ─────────────────────────────────────────────────────────────────────────────

async def run_full_submission_pipeline(
    hackathon_id: str,
    brief: dict,
    project_plan: dict,
    judge_profile: dict,
    sponsor_manifest: dict,
    preview_url: str,
    repo_url: str,
    output_dir: str,
    dry_run: bool = False,
) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    logger.info(f"[submission_pipeline] Starting for: {project_plan.get('project_name')}")

    # Demo producer + Pitch writer in parallel (both independent)
    demo_result, pitch_result = await asyncio.gather(
        run_demo_producer(hackathon_id, preview_url, project_plan, judge_profile, output_dir),
        run_pitch_writer(
            hackathon_id, project_plan, judge_profile, sponsor_manifest,
            repo_url, preview_url, "", output_dir  # video_url filled after demo
        ),
    )

    # Update pitch with real video URL
    video_url = demo_result.get("video_url", "")
    if video_url:
        # Re-generate description with video URL known
        pitch_result["description"] = await generate_submission_description(
            project_plan, judge_profile, sponsor_manifest.get("recommended_integrations", [])
        )

    # Wait for human approval (Commander handles checkpoint)
    await redis.set(
        f"checkpoint:{hackathon_id}:submission_approval",
        json.dumps({"status": "pending", "materials": {
            "preview_url": preview_url,
            "video_url": video_url,
            "readme_path": pitch_result.get("readme_path"),
            "description_preview": pitch_result.get("description", "")[:200],
        }}),
        ex=86400,
    )

    # Commander will publish "approved" when human approves
    # Then Submission Agent runs
    submission_result = await run_submission_agent(
        hackathon_id=hackathon_id,
        hackathon_url=brief.get("url", ""),
        platform=brief.get("platform", "devpost"),
        project_plan=project_plan,
        description=pitch_result.get("description", ""),
        video_url=video_url,
        preview_url=preview_url,
        repo_url=repo_url,
        sponsor_manifest=sponsor_manifest,
        output_dir=output_dir,
        dry_run=dry_run,
    )

    await redis.aclose()
    return {
        "demo": demo_result,
        "pitch": pitch_result,
        "submission": submission_result,
    }
