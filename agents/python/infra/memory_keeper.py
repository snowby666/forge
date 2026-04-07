# -*- coding: utf-8 -*-
"""
Memory Keeper — Layer 7: Infrastructure
Persistent memory across all hackathons.
Mem0 for episodic memory, Qdrant for vector search.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import warnings
from datetime import datetime, timezone
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams, Filter, FieldCondition, MatchValue

from config.electronhub import embed
from config.forge_trace import trace_op

logger = logging.getLogger(__name__)

COLLECTIONS = {
    "code":     "code-artifacts",
    "design":   "design-patterns",
    "copy":     "submission-copy",
    "briefs":   "hackathon-briefs",
    "judges":   "judge-profiles",
}
VECTOR_SIZE = 1536  # text-embedding-3-small

# Qdrant REST default client timeout is very low (~5s); create_collection / first
# startup often exceeds that and raises httpx.ReadTimeout.
_DEFAULT_QDRANT_TIMEOUT_S = 120


def get_qdrant() -> AsyncQdrantClient:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    timeout_raw = os.environ.get("QDRANT_CLIENT_TIMEOUT", str(_DEFAULT_QDRANT_TIMEOUT_S))
    try:
        timeout_s = max(10, int(timeout_raw))
    except ValueError:
        timeout_s = _DEFAULT_QDRANT_TIMEOUT_S
    api_key = os.environ.get("QDRANT_API_KEY") or None
    # API key over plain HTTP triggers a UserWarning; expected for self-hosted compose.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*[Aa]pi key is used with an insecure connection.*",
            category=UserWarning,
        )
        return AsyncQdrantClient(
            url=url,
            api_key=api_key,
            timeout=timeout_s,
        )


def get_mem0() -> Any:
    # Lazy import so `ensure_collections` / deploy hooks work with only qdrant-client installed.
    from mem0 import Memory

    return Memory.from_config({
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "url": os.environ.get("QDRANT_URL", "http://localhost:6333"),
                "api_key": os.environ.get("QDRANT_API_KEY", ""),
                "collection_name": "mem0-agent-memory",
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "api_key": os.environ["ELECTRONHUB_API_KEY"],
                "openai_base_url": os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1"),
                "model": "claude-haiku-4-5",
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": os.environ["ELECTRONHUB_API_KEY"],
                "openai_base_url": os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1"),
                "model": "text-embedding-3-small",
            },
        },
    })


class MemoryKeeper:
    USER_ID = "hackathon-agent"

    def __init__(self) -> None:
        self._qdrant: AsyncQdrantClient | None = None
        self._mem0: Any = None
        self._collections_ready = False

    @property
    def qdrant(self) -> AsyncQdrantClient:
        if self._qdrant is None:
            self._qdrant = get_qdrant()
        return self._qdrant

    @property
    def mem0(self) -> Any:
        if self._mem0 is None:
            self._mem0 = get_mem0()
        return self._mem0

    async def ensure_collections(self) -> None:
        if self._collections_ready:
            return
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                existing = {c.name for c in (await self.qdrant.get_collections()).collections}
                created = []
                for name in COLLECTIONS.values():
                    if name not in existing:
                        await self.qdrant.create_collection(
                            collection_name=name,
                            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                        )
                        created.append(name)
                if created:
                    logger.info(f"[forge:memory] Created {len(created)} collections: {', '.join(created)}")
                self._collections_ready = True
                return
            except Exception as e:
                last_err = e
                logger.warning(
                    "[forge:memory] ensure_collections attempt %s/3 failed: %s",
                    attempt,
                    e,
                )
                if attempt < 3:
                    await asyncio.sleep(2.0 * attempt)
        logger.error(
            "[forge:memory] Failed to ensure collections after retries (Qdrant may be down): %s",
            last_err,
        )
        if last_err:
            raise last_err
        raise RuntimeError("ensure_collections failed with no exception detail")

    # ── Hackathon briefs ───────────────────────────────────────────────────────

    async def store_hackathon_brief(self, hackathon_id: str, brief: dict) -> None:
        await self.ensure_collections()
        text = f"{brief.get('name', '')} {brief.get('theme', '')} {brief.get('description', '')[:200]}"
        async with trace_op("http", "memory:store_brief") as span:
            span.input = {"hackathon_id": hackathon_id}
            vector = await embed(text)
            point_id = int(hashlib.md5(hackathon_id.encode()).hexdigest()[:8], 16)
            await self.qdrant.upsert(
                collection_name=COLLECTIONS["briefs"],
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "hackathon_id": hackathon_id,
                        "name": brief.get("name"),
                        "theme": brief.get("theme"),
                        "platform": brief.get("platform"),
                        "score": brief.get("score"),
                        "stored_at": datetime.now(timezone.utc).isoformat(),
                    },
                )],
            )
            span.output = {"stored": True}

    async def find_similar_hackathons(self, theme: str, limit: int = 3) -> list[dict]:
        await self.ensure_collections()
        async with trace_op("http", "memory:find_similar") as span:
            vector = await embed(theme)
            results = await self.qdrant.search(
                collection_name=COLLECTIONS["briefs"],
                query_vector=vector,
                limit=limit,
                score_threshold=0.7,
            )
            span.output = {"results": len(results)}
        return [r.payload for r in results if r.payload]

    # ── Outcomes ──────────────────────────────────────────────────────────────

    async def store_outcome(self, hackathon_id: str, hackathon_name: str, outcome: dict) -> None:
        async with trace_op("http", "memory:store_outcome") as span:
            span.input = {"hackathon_id": hackathon_id}
            self.mem0.add(
                messages=[
                    {"role": "user", "content": f"Hackathon: {hackathon_name}"},
                    {"role": "assistant", "content": (
                        f"Result: {outcome.get('result')}. "
                        f"Concept: {outcome.get('concept')}. "
                        f"What worked: {'; '.join(outcome.get('what_worked', []))}. "
                        f"What failed: {'; '.join(outcome.get('what_failed', []))}. "
                        f"Prize: {outcome.get('prize_won', 'none')}. "
                        f"UX audit score: {outcome.get('ux_audit_score', 'unknown')}."
                    )},
                ],
                user_id=self.USER_ID,
                metadata={"hackathon_id": hackathon_id, "result": outcome.get("result")},
            )
        logger.info(f"[forge:memory] Stored outcome for {hackathon_name}: {outcome.get('result')}")

    async def get_relevant_past(self, query: str, limit: int = 5) -> list[dict]:
        async with trace_op("http", "memory:search_past") as span:
            results = self.mem0.search(query=query, user_id=self.USER_ID, limit=limit)
            span.output = {"results": len(results.get("results", []))}
        return results.get("results", [])

    # ── Code artifacts ─────────────────────────────────────────────────────────

    async def store_code_artifact(
        self, hackathon_id: str, artifact_type: str, name: str, code: str, description: str,
    ) -> None:
        await self.ensure_collections()
        text = f"{name} {description} {code[:300]}"
        async with trace_op("http", "memory:store_artifact") as span:
            vector = await embed(text)
            point_id = int(hashlib.md5(f"{name}{code[:100]}".encode()).hexdigest()[:8], 16)
            await self.qdrant.upsert(
                collection_name=COLLECTIONS["code"],
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "hackathon_id": hackathon_id,
                        "type": artifact_type,
                        "name": name,
                        "description": description,
                        "code": code,
                        "stored_at": datetime.now(timezone.utc).isoformat(),
                    },
                )],
            )

    async def find_similar_component(
        self, spec: str, artifact_type: str, threshold: float = 0.85,
    ) -> dict | None:
        await self.ensure_collections()
        vector = await embed(spec)
        results = await self.qdrant.search(
            collection_name=COLLECTIONS["code"],
            query_vector=vector,
            query_filter=Filter(must=[FieldCondition(key="type", match=MatchValue(value=artifact_type))]),
            limit=1,
            score_threshold=threshold,
        )
        return results[0].payload if results else None

    # ── Judge profiles ─────────────────────────────────────────────────────────

    async def store_judge_profile(self, hackathon_id: str, profile: dict) -> None:
        await self.ensure_collections()
        panel_desc = profile.get("panel_character", "")
        async with trace_op("http", "memory:store_judge") as span:
            vector = await embed(panel_desc)
            point_id = int(hashlib.md5(hackathon_id.encode()).hexdigest()[:8], 16) + 1
            await self.qdrant.upsert(
                collection_name=COLLECTIONS["judges"],
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={"hackathon_id": hackathon_id, "profile": profile},
                )],
            )

    async def find_similar_judge_profile(self, panel_description: str) -> dict | None:
        await self.ensure_collections()
        vector = await embed(panel_description)
        results = await self.qdrant.search(
            collection_name=COLLECTIONS["judges"],
            query_vector=vector,
            limit=1,
            score_threshold=0.8,
        )
        return results[0].payload if results else None


# ── Module-level convenience ──────────────────────────────────────────────────

_keeper: MemoryKeeper | None = None

def get_memory_keeper() -> MemoryKeeper:
    global _keeper
    if _keeper is None:
        _keeper = MemoryKeeper()
    return _keeper


async def ensure_collections() -> None:
    await get_memory_keeper().ensure_collections()
