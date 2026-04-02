# -*- coding: utf-8 -*-
"""
config/web_search.py — ForgeSearch: Sophisticated Hybrid Search Engine
========================================================================

A research-grade agentic search pipeline built specifically for Forge.
Zero mandatory cost. Exa integration available for deep semantic queries.

ARCHITECTURE (4-stage pipeline)
────────────────────────────────

  Stage 1 — QUERY EXPANSION (RAG-Fusion pattern)
  ┌─────────────────────────────────────────────────────────────────┐
  │ Original query → LLM generates 3 diverse sub-queries           │
  │ Each sub-query targets a different angle of the same intent     │
  │ Based on: arXiv:2402.03367 (RAG-Fusion) + Raudaschl benchmark  │
  │ Result: +22% NDCG@5, +40% recall@10 vs single-query baseline   │
  └─────────────────────────────────────────────────────────────────┘

  Stage 2 — PARALLEL RETRIEVAL (6 independent sources, priority order)
  ┌─────────────────────────────────────────────────────────────────┐
  │ a) Serper  — Google results via REST. ~120ms. 2500 free.       │
  │ b) Tavily  — AI-optimized search. ~1.7s. 1k free/mo.         │
  │ c) Brave   — Independent 30B-page index. ~1k free/mo.         │
  │ d) ddgs    — DuckDuckGo metasearch. MIT. Free. (fallback)     │
  │ e) SearXNG — Self-hosted metasearch (Docker). Fully free.     │
  │ f) Exa     — Neural semantic search. $7/1k reqs. Optional.    │
  │ All sources run concurrently for each expanded sub-query       │
  └─────────────────────────────────────────────────────────────────┘

  Stage 3 — HYBRID FUSION (BM25 + dense + RRF)
  ┌─────────────────────────────────────────────────────────────────┐
  │ Local re-scoring: BM25 (keyword) + Qdrant (semantic embeddings)│
  │ Fusion: Reciprocal Rank Fusion (RRF, Cormack 2009 SIGIR)       │
  │ Formula: score(d) = Σ 1/(k + rank_i) across all ranked lists   │
  │ k=60 constant. Documents appearing in multiple lists bubble up  │
  │ No score normalisation needed — rank-based fusion is robust     │
  └─────────────────────────────────────────────────────────────────┘

  Stage 4 — NEURAL RERANKING (cross-encoder)
  ┌─────────────────────────────────────────────────────────────────┐
  │ Model: cross-encoder/ms-marco-MiniLM-L6-v2 (HuggingFace)      │
  │ Trained on MS MARCO 8.8M passage pairs. 22M params. Free.     │
  │ Scores each (query, passage) pair with full attention          │
  │ Runs on RTX 4060 (Forge's dedicated GPU) — ~10ms per 50 docs  │
  │ Final top-k selection for LLM context window injection         │
  └─────────────────────────────────────────────────────────────────┘

CONTENT EXTRACTION
  fetch_full_content() — extracts clean text from result URLs
  Used by Knowledge Updater for full-page context (not just snippets)
  Strips HTML, scripts, ads. Returns markdown-ready plain text.

SEARCH MODES
  search_and_synthesize(query)     — standard: Serper + Tavily + Brave + ddgs
  deep_search(query)               — full pipeline: expansion + all
                                     sources + BM25/RRF + reranking
  semantic_search(query)           — Exa neural only (needs API key)
  fetch_full_content(urls)         — extract full text from URLs

COST SUMMARY (per search)
  Standard search:  $0.000  (Serper free tier / ddgs fallback)
  Deep search:      $0.000  (+ local BM25 + reranker on GPU)
  With Serper key:  ~$0.001 (2500 free, then $0.30-$1/1k)
  With Tavily key:  ~$0.005 (1k free/mo, then $5/1k)
  With Brave key:   ~$0.000 (1k free/mo, then $0.005/req)
  With Exa:         $0.007  (neural semantic results)

SETUP
  Required:    pip install ddgs bm25s sentence-transformers aiohttp
  Recommended: SERPER_API_KEY in forge.secrets  (2500 free, fastest)
  Recommended: TAVILY_API_KEY in forge.secrets  (1k/mo free, AI-optimized)
  Optional:    BRAVE_SEARCH_API_KEY in forge.secrets  (free tier)
  Optional:    EXA_API_KEY in forge.secrets            ($7/1k)
  Optional:    SEARXNG_URL=http://localhost:8080       (Docker)

REFERENCES
  RAG-Fusion:    Rackauckas (2024) arXiv:2402.03367
  RRF:           Cormack et al. (2009) SIGIR
  SPLADE:        Formal et al. (2021) arXiv:2107.05720
  Hybrid eval:   Raudaschl (2025) github.com/Raudaschl/rag-fusion
                 Benchmark: +22% NDCG@5, +40% recall@10
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Ensure Playwright can find its browsers in the default cache location.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    _pw_default = os.path.expanduser("~/.cache/ms-playwright")
    if os.path.isdir(_pw_default):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_default

# Fix stale CWD after rsync --delete (WSL2: sync.sh recreates ~/forge, invalidating CWD).
# crawl4ai's model_loader.py calls os.getcwd() at import time and crashes if CWD is gone.
try:
    os.getcwd()
except (FileNotFoundError, OSError):
    os.chdir(os.path.expanduser("~"))

# ── Tavily key pool (round-robin rotation across multiple free keys) ──────────
# Supports both TAVILY_API_KEY (single) and TAVILY_API_KEYS (comma-separated).
# Each free key gets 1,000 credits/month. With N keys → N×1,000 credits/month.
_tavily_keys: list[str] = []
_tavily_idx = 0

def _get_tavily_key() -> str | None:
    """Round-robin across all available Tavily API keys."""
    global _tavily_keys, _tavily_idx
    if not _tavily_keys:
        raw = os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY", "")
        _tavily_keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not _tavily_keys:
        return None
    key = _tavily_keys[_tavily_idx % len(_tavily_keys)]
    _tavily_idx = (_tavily_idx + 1) % len(_tavily_keys)
    return key

def _mark_tavily_key_exhausted(key: str) -> None:
    """Remove a key that returned 429 or 401 from the pool."""
    global _tavily_keys
    if key in _tavily_keys:
        _tavily_keys.remove(key)
        logger.debug(f"[forge:search] Tavily key ...{key[-6:]} removed from pool ({len(_tavily_keys)} left)")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str           # "serper" | "tavily" | "brave" | "ddgs" | "exa" | "searxng" | "ddgs_news"
    score: float = 0.0    # final RRF + reranker score
    full_text: str = ""   # populated by fetch_full_content()
    published: str = ""   # ISO date if available

    def context_block(self, index: int, max_snippet: int = 500) -> str:
        text = (self.full_text or self.snippet)[:max_snippet].replace("\n", " ").strip()
        date_str = f"  Published: {self.published}\n" if self.published else ""
        return (
            f"[{index}] {self.title}\n"
            f"  Source: {self.url}\n"
            f"{date_str}"
            f"  {text}\n"
        )


@dataclass
class SearchStats:
    query: str
    expanded_queries: list[str] = field(default_factory=list)
    sources_used: set[str] = field(default_factory=set)
    total_raw: int = 0
    after_dedup: int = 0
    after_rerank: int = 0
    elapsed_ms: float = 0.0
    reranker_used: bool = False
    exa_used: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1: QUERY EXPANSION
# ═══════════════════════════════════════════════════════════════════════════════

_EXPANSION_PROMPT = """You are a search query expansion expert for a hackathon intelligence system.

Generate {n} diverse search queries that together cover all important angles of this topic.
Each query must target a DIFFERENT aspect — not just rephrasings of the same query.

Original query: {query}

Rules:
- Each query should retrieve documents the original query might miss
- Include: synonyms, related concepts, specific sub-topics, question forms
- Keep each query under 10 words
- Do NOT include the word "hackathon" unless it was in the original query
- Return ONLY a JSON array of strings, nothing else

Example output: ["query one here", "query two here", "query three here"]"""


async def expand_query(query: str, n: int = 3) -> list[str]:
    """
    RAG-Fusion style query expansion.
    Uses gpt-5-nano (fast/cheap) to generate n diverse sub-queries.
    Returns original query + expanded queries (total n+1).
    Based on Rackauckas (2024) arXiv:2402.03367 — Hybrid+Diverse variant
    showed +22% NDCG@5, +40% recall@10 over baseline in benchmark.
    Falls back gracefully to original query on any failure.
    """
    try:
        from config.electronhub import complete
        raw = await complete(
            task="score-hackathon",   # FAST tier (gpt-5-nano) — cheap and sufficient
            messages=[{
                "role": "user",
                "content": _EXPANSION_PROMPT.format(query=query, n=n),
            }],
            temperature=0.6,   # high diversity, low coherence cost
        )
        # Parse JSON array from response
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        expanded: list[str] = __import__("json").loads(cleaned)
        if isinstance(expanded, list) and all(isinstance(q, str) for q in expanded):
            unique = [q.strip() for q in expanded if q.strip() and q.strip() != query]
            logger.debug(f"[forge:search] Expanded '{query[:40]}' → {len(unique)} sub-queries")
            return [query] + unique[:n]
    except Exception as e:
        logger.debug(f"[forge:search] Query expansion failed (using original): {e}")
    return [query]


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2: PARALLEL RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════════════

# ── 2a. ddgs (free, no API key) ───────────────────────────────────────────────

async def _search_ddgs(
    query: str,
    max_results: int = 8,
    timelimit: str | None = "y",
) -> list[SearchResult]:
    """
    DuckDuckGo/Bing/Google metasearch via ddgs.
    MIT licence. No API key. No rate-limit hard cap. ~200ms/query.
    """
    try:
        from ddgs import DDGS  # type: ignore[import]
    except ImportError:
        logger.warning("[forge:search] ddgs not installed. Run: pip install ddgs")
        return []

    def _sync() -> list[dict]:
        try:
            return DDGS().text(
                query,
                region="us-en",
                safesearch="off",
                timelimit=timelimit,
                max_results=max_results,
                backend="auto",
            ) or []
        except Exception as e:
            logger.debug(f"[forge:search] ddgs error: {e}")
            return []

    raw = await asyncio.to_thread(_sync)
    return [
        SearchResult(title=r.get("title", ""), url=r.get("href", ""),
                     snippet=r.get("body", ""), source="ddgs")
        for r in raw if r.get("title") and r.get("href")
    ]


async def _search_ddgs_news(query: str, max_results: int = 5) -> list[SearchResult]:
    """Recent tech news — ddgs news endpoint."""
    try:
        from ddgs import DDGS  # type: ignore[import]
    except ImportError:
        return []

    def _sync() -> list[dict]:
        try:
            return DDGS().news(
                query, region="us-en", safesearch="off",
                timelimit="m", max_results=max_results,
            ) or []
        except Exception as e:
            logger.debug(f"[forge:search] ddgs_news error: {e}")
            return []

    raw = await asyncio.to_thread(_sync)
    return [
        SearchResult(
            title=r.get("title", ""), url=r.get("url", ""),
            snippet=r.get("body", r.get("excerpt", "")),
            source="ddgs_news", published=r.get("date", ""),
        )
        for r in raw if r.get("title") and r.get("url")
    ]


# ── 2b. Brave Search API (optional, ~1k free/mo) ────────────────────────────

async def _search_brave(query: str, max_results: int = 8) -> list[SearchResult]:
    """
    Brave Search: independent 30B-page index, best tech freshness.
    Set BRAVE_SEARCH_API_KEY in forge.secrets. ~1k free queries/month.
    Leads AIMultiple agentic search benchmark (14.89/20).
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
                params={
                    "q": query,
                    "count": min(max_results, 20),
                    "search_lang": "en",
                    "freshness": "pm",
                    "text_decorations": "0",
                    "result_filter": "web",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 429:
                    logger.warning("[forge:search] Brave rate limit")
                    return []
                if resp.status != 200:
                    logger.debug(f"[forge:search] Brave HTTP {resp.status}")
                    return []
                data = await resp.json()

        return [
            SearchResult(
                title=r.get("title", ""), url=r.get("url", ""),
                snippet=r.get("description", ""), source="brave",
                published=r.get("age", ""),
            )
            for r in data.get("web", {}).get("results", [])
            if r.get("title") and r.get("url")
        ]
    except Exception as e:
        logger.debug(f"[forge:search] Brave error: {e}")
        return []


# ── 2c. Serper.dev (Google results, ~120ms, 2500 free credits) ────────────────

async def _search_serper(query: str, max_results: int = 8) -> list[SearchResult]:
    """
    Serper.dev — real Google results via REST API.
    Fastest SERP API (~120ms avg). 2,500 free one-time credits, no CC required.
    Then $0.30-$1.00 per 1k queries.  Signup: https://serper.dev
    Set SERPER_API_KEY in forge.secrets.
    """
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": max_results},
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.debug(f"[forge:search] Serper HTTP {resp.status}: {text[:120]}")
                    return []
                data = await resp.json()

        return [
            SearchResult(
                title=r.get("title", ""), url=r.get("link", ""),
                snippet=r.get("snippet", ""), source="serper",
            )
            for r in data.get("organic", [])[:max_results]
            if r.get("title") and r.get("link")
        ]
    except Exception as e:
        logger.debug(f"[forge:search] Serper error: {e}")
        return []


# ── 2d. Tavily Search (AI-optimized, ~1.7s, 1000/mo free) ───────────────────

async def _search_tavily(query: str, max_results: int = 8) -> list[SearchResult]:
    """
    Tavily — AI-optimized search API with built-in relevance scoring.
    Rotates across all keys in TAVILY_API_KEYS (comma-separated) or TAVILY_API_KEY.
    Each free key = 1,000 credits/month. Dev keys: 100 RPM, prod keys: 1,000 RPM.
    On 429/401, removes the exhausted key and retries with the next one.
    """
    max_attempts = min(len(_tavily_keys) if _tavily_keys else 3, 5)
    for _attempt in range(max_attempts):
        api_key = _get_tavily_key()
        if not api_key:
            return []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.tavily.com/search",
                    json={
                        "query": query,
                        "max_results": min(max_results, 20),
                        "search_depth": "basic",
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (429, 401, 403):
                        _mark_tavily_key_exhausted(api_key)
                        continue
                    if resp.status != 200:
                        text = await resp.text()
                        logger.debug(f"[forge:search] Tavily HTTP {resp.status}: {text[:120]}")
                        return []
                    data = await resp.json()

            return [
                SearchResult(
                    title=r.get("title", ""), url=r.get("url", ""),
                    snippet=r.get("content", ""), source="tavily",
                    score=r.get("score", 0.0),
                )
                for r in data.get("results", [])[:max_results]
                if r.get("title") and r.get("url")
            ]
        except Exception as e:
            logger.debug(f"[forge:search] Tavily error: {e}")
            return []
    return []


# ── 2e. Exa neural search (optional, $7/1k requests with content) ───────────

async def _search_exa(
    query: str,
    max_results: int = 8,
    search_type: str = "auto",   # "neural" | "keyword" | "auto" | "deep"
    category: str | None = None, # "company" | "people" | "news" | None
) -> list[SearchResult]:
    """
    Exa neural search — embeddings-based semantic retrieval.
    Trained on link-prediction: finds conceptually related content
    even without keyword overlap. 81% multi-hop accuracy vs Tavily 71%.
    $7/1k requests (content included) as of March 2026.
    Set EXA_API_KEY in forge.secrets.
    """
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        async with aiohttp.ClientSession() as session:
            body: dict[str, Any] = {
                "query": query,
                "numResults": max_results,
                "type": search_type,
                "contents": {
                    "text": {"maxCharacters": 600},
                    "highlights": {"numSentences": 2, "highlightsPerUrl": 1},
                },
            }
            if category:
                body["category"] = category

            async with session.post(
                "https://api.exa.ai/search",
                json=body,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.debug(f"[forge:search] Exa HTTP {resp.status}: {text[:100]}")
                    return []
                data = await resp.json()

        results = []
        for r in data.get("results", []):
            snippet = ""
            # Prefer highlights over raw text for snippet quality
            highlights = r.get("highlights", [])
            if highlights:
                snippet = " … ".join(highlights[:2])
            else:
                text_obj = r.get("text", "")
                snippet = text_obj[:600] if isinstance(text_obj, str) else ""

            results.append(SearchResult(
                title=r.get("title", r.get("url", "")),
                url=r.get("url", ""),
                snippet=snippet,
                source="exa",
                published=r.get("publishedDate", "")[:10] if r.get("publishedDate") else "",
            ))
        return results

    except Exception as e:
        logger.debug(f"[forge:search] Exa error: {e}")
        return []


async def _search_exa_people(query: str, max_results: int = 5) -> list[SearchResult]:
    """Exa people index — 1B+ LinkedIn profiles. For judge/speaker research."""
    return await _search_exa(query, max_results, search_type="neural", category="people")


async def _search_exa_company(query: str, max_results: int = 5) -> list[SearchResult]:
    """Exa company index — 70M entities. For sponsor research."""
    return await _search_exa(query, max_results, search_type="neural", category="company")


# ── 2f. SearXNG (self-hosted metasearch, fully free) ────────────────────────

async def _search_searxng(query: str, max_results: int = 8) -> list[SearchResult]:
    """
    SearXNG self-hosted instance — queries 70+ engines simultaneously
    (Google, Bing, DDG, Startpage, etc.) without tracking.
    Set SEARXNG_URL in forge.secrets (e.g., http://localhost:8081).
    Completely free. Add to docker-compose to enable.
    """
    base_url = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not base_url:
        return []

    urls_to_try = [base_url]
    if "localhost" in base_url or "127.0.0.1" in base_url:
        port = base_url.rsplit(":", 1)[-1] if ":" in base_url.split("//", 1)[-1] else "8081"
        urls_to_try = list(dict.fromkeys([
            base_url,
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]))

    for url in urls_to_try:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "engines": "google,bing,brave,startpage",
                        "language": "en",
                        "time_range": "year",
                        "safesearch": "0",
                    },
                    headers={"Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        logger.debug(f"[forge:search] SearXNG {url} returned {resp.status}")
                        continue
                    data = await resp.json()

            results = [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source="searxng",
                    published=r.get("publishedDate", ""),
                )
                for r in data.get("results", [])[:max_results]
                if r.get("title") and r.get("url")
            ]
            if results:
                return results
        except Exception as e:
            logger.debug(f"[forge:search] SearXNG {url} error: {e}")
            continue
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# CONTENT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

_CONTENT_SKIP_PATTERNS = re.compile(
    r"(cookie|subscribe|newsletter|sign.?up|login|paywall|advertisement)",
    re.IGNORECASE,
)
_HTML_STRIP = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


# ── Crawl4AI singleton browser ────────────────────────────────────────────────
# Crawl4AI AsyncWebCrawler with a persistent browser pool.
# One warm instance shared across all fetch_full_content() calls.
# Handles JS rendering, anti-bot, Shadow DOM — everything the old regex stripper missed.

_c4a_crawler: Any = None
_c4a_lock = asyncio.Lock()


async def _get_c4a_crawler():
    """
    Return a warmed AsyncWebCrawler instance (singleton).
    Lazy-init on first call. Thread-safe via asyncio lock.
    Uses headless Chromium via Playwright. Free. No API key.
    """
    global _c4a_crawler
    async with _c4a_lock:
        if _c4a_crawler is None:
            try:
                try:
                    os.getcwd()
                except (FileNotFoundError, OSError):
                    os.chdir(os.path.expanduser("~"))
                from crawl4ai import AsyncWebCrawler, BrowserConfig  # type: ignore[import]
                browser_cfg = BrowserConfig(
                    browser_type="chromium",
                    chrome_channel="chromium",
                    headless=True,
                    verbose=False,
                    user_agent_mode="random",
                    java_script_enabled=True,
                )
                _c4a_crawler = AsyncWebCrawler(config=browser_cfg)
                await _c4a_crawler.__aenter__()
                logger.info("[forge:search] Crawl4AI browser pool initialised")
            except Exception as e:
                logger.warning(f"[forge:search] Crawl4AI unavailable: {e} — using fallback extractor")
                _c4a_crawler = None
    return _c4a_crawler


async def _fetch_with_c4a(url: str, max_chars: int = 4000) -> str:
    """
    Extract clean LLM-ready markdown from a URL using Crawl4AI.
    Uses PruningContentFilter to strip ads/nav/boilerplate automatically.
    Falls back to the regex extractor if Crawl4AI is unavailable or errors.
    """
    try:
        try:
            os.getcwd()
        except (FileNotFoundError, OSError):
            os.chdir(os.path.expanduser("~"))
        from crawl4ai import CrawlerRunConfig, CacheMode  # type: ignore[import]
        from crawl4ai.content_filter_strategy import PruningContentFilter  # type: ignore[import]
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator  # type: ignore[import]

        crawler = await _get_c4a_crawler()
        if crawler is None:
            return ""

        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.ENABLED,          # Cache results — same URL not re-fetched in a run
            word_count_threshold=15,                # Skip micro-fragments
            exclude_external_links=True,
            remove_overlay_elements=True,           # Kill cookie banners / consent popups
            process_iframes=False,
            wait_until="networkidle",
            page_timeout=20000,                     # 20s timeout
            markdown_generator=DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(
                    threshold=0.45,
                    threshold_type="fixed",
                    min_word_threshold=15,
                )
            ),
        )
        result = await crawler.arun(url=url, config=run_cfg)

        if result.success and result.markdown:
            md = result.markdown.fit_markdown or result.markdown.raw_markdown or ""
            return md[:max_chars]
        return ""

    except Exception as e:
        logger.debug(f"[forge:search] Crawl4AI fetch failed for {url}: {e}")
        return ""


async def _fetch_fallback(url: str, max_chars: int = 4000) -> str:
    """
    Fallback extractor: basic aiohttp + regex HTML cleaner.
    Used when Crawl4AI is unavailable or the URL blocks headless browsers.
    Does NOT handle JS-rendered content.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
                "Gecko/20100101 Firefox/125.0"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return ""
                content_type = resp.headers.get("Content-Type", "")
                if "html" not in content_type and "text" not in content_type:
                    return ""
                html = await resp.text(errors="ignore")

        for tag in ("script", "style", "nav", "header", "footer",
                    "aside", "form", "iframe", "noscript"):
            html = re.sub(f"<{tag}[^>]*>.*?</{tag}>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)
        text = _HTML_STRIP.sub(" ", html)
        text = _WHITESPACE.sub(" ", text).strip()
        lines = [ln.strip() for ln in text.split(".")
                 if len(ln.strip()) > 40 and not _CONTENT_SKIP_PATTERNS.search(ln)]
        return ". ".join(lines)[:max_chars]

    except Exception as e:
        logger.debug(f"[forge:search] fallback fetch failed for {url}: {e}")
        return ""


async def fetch_full_content(url: str, max_chars: int = 4000) -> str:
    """
    Fetch a URL and return clean LLM-ready text / markdown.

    Priority:
      1. Crawl4AI — full Playwright JS rendering, anti-bot, PruningContentFilter
         Returns fit_markdown (boilerplate stripped) or raw_markdown.
      2. Fallback — aiohttp + regex stripper (no JS, but instant)

    Used by Knowledge Updater and deep_search content enrichment.
    """
    # Try Crawl4AI first (handles SPA/JS pages like Devpost, Lablab)
    text = await _fetch_with_c4a(url, max_chars)
    if text and len(text) > 100:
        return text

    # Fallback for plain HTML pages or when Crawl4AI is unavailable
    return await _fetch_fallback(url, max_chars)


async def enrich_results_with_content(
    results: list[SearchResult],
    top_n: int = 3,
    max_chars: int = 3000,
) -> list[SearchResult]:
    """
    Fetch full page content for the top_n results in parallel.
    Only called by deep_search or Knowledge Updater — not standard search.
    Uses Crawl4AI for JS-rendered pages, fallback regex for static pages.
    """
    async def _fetch(r: SearchResult, fetch: bool) -> str:
        return await fetch_full_content(r.url, max_chars) if fetch else ""

    tasks = [_fetch(r, i < top_n) for i, r in enumerate(results)]
    contents = await asyncio.gather(*tasks, return_exceptions=True)
    for r, content in zip(results, contents):
        if isinstance(content, str) and content:
            r.full_text = content
    return results



# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3: HYBRID FUSION (BM25 + RRF)
# ═══════════════════════════════════════════════════════════════════════════════

def _bm25_score(query: str, results: list[SearchResult]) -> list[tuple[SearchResult, float]]:
    """
    BM25 scoring over snippet text.
    Uses bm25s library (pure Python, benchmarks near Elasticsearch speed).
    Falls back to simple TF if bm25s unavailable.
    k1=1.5, b=0.75 — standard Okapi BM25 parameters.
    """
    corpus = [f"{r.title} {r.snippet}" for r in results]
    if not corpus:
        return []

    try:
        import bm25s  # type: ignore[import]
        tokenized = bm25s.tokenize(corpus)
        retriever = bm25s.BM25(k1=1.5, b=0.75)
        retriever.index(tokenized)
        query_tokens = bm25s.tokenize([query])
        scores, _ = retriever.retrieve(query_tokens, k=len(corpus))
        scored = list(zip(results, scores[0].tolist()))
    except (ImportError, ModuleNotFoundError, Exception):
        # Fallback: simple TF scoring (also handles Windows where bm25s
        # may fail due to missing 'resource' module in some versions)
        query_terms = set(query.lower().split())
        scored = []
        for r in results:
            text = f"{r.title} {r.snippet}".lower()
            tf_score = sum(text.count(term) for term in query_terms)
            scored.append((r, float(tf_score)))

    return scored


def _reciprocal_rank_fusion(
    ranked_lists: list[list[SearchResult]],
    k: int = 60,
) -> list[SearchResult]:
    """
    Reciprocal Rank Fusion (Cormack et al., 2009 SIGIR).
    Formula: RRF(d) = Σ 1 / (k + rank_i)  for each ranked list i

    k=60 is the original paper's recommended constant.
    Rank-based (not score-based) — robust to score distribution differences
    between providers. Documents appearing high in multiple lists bubble up.

    All ranked_lists are deduplicated by URL before fusion.
    """
    fused_scores: dict[str, float] = {}
    url_to_result: dict[str, SearchResult] = {}

    for ranked_list in ranked_lists:
        for rank, result in enumerate(ranked_list, start=1):
            url = result.url
            if not url:
                continue
            if url not in url_to_result:
                url_to_result[url] = result
            fused_scores[url] = fused_scores.get(url, 0.0) + 1.0 / (k + rank)

    sorted_urls = sorted(fused_scores, key=lambda u: fused_scores[u], reverse=True)
    final = []
    for url in sorted_urls:
        result = url_to_result[url]
        result.score = fused_scores[url]
        final.append(result)
    return final


def _dedup_by_url(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate results by URL, keeping the one with the most content."""
    seen: dict[str, SearchResult] = {}
    for r in results:
        url = r.url.rstrip("/")
        if url not in seen or len(r.snippet) > len(seen[url].snippet):
            seen[url] = r
    return list(seen.values())


def _qdrant_semantic_score(
    query: str,
    results: list[SearchResult],
) -> list[tuple[SearchResult, float]]:
    """
    Semantic scoring via Qdrant + local embedding model.
    Uses all-MiniLM-L6-v2 (384-dim, free, fast on CPU).
    If Qdrant is unavailable, returns empty — caller falls back to BM25 only.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]
        import numpy as np  # type: ignore[import]

        model = _get_embedding_model()
        texts = [f"{r.title}. {r.snippet[:300]}" for r in results]
        query_emb = model.encode([query], normalize_embeddings=True)[0]
        doc_embs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        scores = (doc_embs @ query_emb).tolist()
        return list(zip(results, scores))
    except Exception as e:
        logger.debug(f"[forge:search] Semantic scoring failed: {e}")
        return []


@lru_cache(maxsize=1)
def _get_embedding_model():
    """Load all-MiniLM-L6-v2 once and cache it. ~23MB download, free."""
    from sentence_transformers import SentenceTransformer  # type: ignore[import]
    return SentenceTransformer("all-MiniLM-L6-v2")


def _hybrid_score_and_rank(
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    """
    Combine BM25 keyword scores + semantic vector scores via RRF.
    This is the "free lunch" from Raudaschl benchmark:
    No extra API calls, notable improvement in MRR vs either alone.
    """
    bm25_scored = _bm25_score(query, results)
    semantic_scored = _qdrant_semantic_score(query, results)

    # Build ranked lists for RRF
    bm25_ranked = [r for r, _ in sorted(bm25_scored, key=lambda x: x[1], reverse=True)]
    
    if semantic_scored:
        sem_ranked = [r for r, _ in sorted(semantic_scored, key=lambda x: x[1], reverse=True)]
        fused = _reciprocal_rank_fusion([bm25_ranked, sem_ranked])
    else:
        # Semantic unavailable — BM25 rank only, still better than raw source order
        for i, r in enumerate(bm25_ranked):
            r.score = 1.0 / (60 + i + 1)
        fused = bm25_ranked

    return fused


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4: NEURAL RERANKING (cross-encoder)
# ═══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def _get_reranker():
    """
    Load cross-encoder/ms-marco-MiniLM-L6-v2 once and cache it.
    Trained on 8.8M MS MARCO passage pairs. 22M params.
    NDCG@10 of 39.0 on TREC DL 2019, MRR@10 of 39.8 on MS MARCO Dev.
    ~30MB download from HuggingFace. Free, runs on RTX 4060.
    """
    from sentence_transformers import CrossEncoder  # type: ignore[import]
    logger.info("[forge:search] Loading cross-encoder reranker (first time — ~30MB)...")
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2")


def _neural_rerank(
    query: str,
    results: list[SearchResult],
    top_k: int = 10,
) -> list[SearchResult]:
    """
    Cross-encoder reranking — scores each (query, passage) pair
    with full bidirectional attention. More accurate than bi-encoder
    but not feasible for large candidate sets.
    Typical pattern: RRF retrieves top-50 → reranker picks top-10.
    Runs on GPU if available (RTX 4060 → ~5ms for 50 pairs).
    Falls back to RRF-ordered results if model unavailable.
    """
    if not results:
        return results

    # Only rerank top candidates — reranker is slower on large sets
    candidates = results[:50]
    rest = results[50:]

    try:
        reranker = _get_reranker()
        pairs = [(query, f"{r.title}. {r.snippet[:400]}") for r in candidates]
        scores = reranker.predict(pairs)
        ranked = sorted(
            zip(candidates, scores.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )
        reranked = [r for r, s in ranked[:top_k]]
        for r, s in ranked:
            r.score = float(s)
        logger.debug(
            f"[forge:search] Reranker: {len(candidates)} → {len(reranked)} "
            f"(top score: {ranked[0][1]:.3f})"
        )
        return reranked + rest
    except Exception as e:
        logger.debug(f"[forge:search] Reranker unavailable: {e}")
        return results[:top_k] + rest


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

async def web_search(
    query: str,
    max_results: int = 8,
    include_news: bool = False,
    timelimit: str | None = "y",
) -> list[SearchResult]:
    """
    Standard web search — Serper → Tavily → Brave → ddgs (priority order).
    No query expansion. No reranking. Fast (~200ms with Serper).
    Suitable for: quick inline lookups during build phase.
    """
    tasks: list[Any] = []

    has_tavily = bool(os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY"))

    # Fast cloud APIs first (Serper ~120ms, Tavily ~1.7s, Brave ~500ms)
    if os.environ.get("SERPER_API_KEY"):
        tasks.append(_search_serper(query, max_results))
    if has_tavily:
        tasks.append(_search_tavily(query, max_results))
    if os.environ.get("BRAVE_SEARCH_API_KEY"):
        tasks.append(_search_brave(query, max_results))

    # Fallback: ddgs (slow, rate-limited) + self-hosted SearXNG
    tasks.append(_search_ddgs(query, max_results, timelimit=timelimit))
    if os.environ.get("SEARXNG_URL"):
        tasks.append(_search_searxng(query, max_results))

    if include_news:
        tasks.append(_search_ddgs_news(query, max_results=5))

    all_batches = await asyncio.gather(*tasks, return_exceptions=True)
    all_results: list[SearchResult] = []
    for batch in all_batches:
        if isinstance(batch, list):
            all_results.extend(batch)

    deduped = _dedup_by_url(all_results)
    return deduped[:max_results]


async def deep_search(
    query: str,
    max_results: int = 10,
    use_exa: bool = True,
    expand_queries: bool = True,
    rerank: bool = True,
    fetch_content: bool = False,
    exa_category: str | None = None,
) -> tuple[list[SearchResult], SearchStats]:
    """
    Full 4-stage pipeline search.
    Stages: query expansion → parallel retrieval → BM25+RRF → cross-encoder rerank.

    Args:
        query:          Original search query
        max_results:    Final top-k results to return
        use_exa:        Include Exa neural search (requires EXA_API_KEY)
        expand_queries: Run RAG-Fusion query expansion (recommended)
        rerank:         Run cross-encoder reranking (recommended, ~50ms on GPU)
        fetch_content:  Fetch full page text for top 3 results (slow, ~2s)
        exa_category:   "people" | "company" | None — special Exa indexes

    Returns:
        (results, stats) — results ranked by final score, stats for debugging
    """
    t0 = time.monotonic()
    stats = SearchStats(query=query)
    has_exa = bool(os.environ.get("EXA_API_KEY")) and use_exa
    has_tavily = bool(os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY"))

    # ── Stage 1: Query Expansion ──────────────────────────────────────────────
    if expand_queries:
        expanded = await expand_query(query, n=3)
    else:
        expanded = [query]
    stats.expanded_queries = expanded[1:]   # only the generated ones

    # ── Stage 2: Parallel Retrieval across all queries × all providers ────────
    retrieval_tasks = []
    for q in expanded:
        # Fast cloud APIs first
        if os.environ.get("SERPER_API_KEY"):
            retrieval_tasks.append(_search_serper(q, max_results=8))
        if has_tavily:
            retrieval_tasks.append(_search_tavily(q, max_results=8))
        if os.environ.get("BRAVE_SEARCH_API_KEY"):
            retrieval_tasks.append(_search_brave(q, max_results=8))
        # Fallbacks
        retrieval_tasks.append(_search_ddgs(q, max_results=8))
        if os.environ.get("SEARXNG_URL"):
            retrieval_tasks.append(_search_searxng(q, max_results=8))
        if has_exa:
            if exa_category:
                retrieval_tasks.append(
                    _search_exa(q, max_results=6, category=exa_category)
                )
            else:
                retrieval_tasks.append(_search_exa(q, max_results=6))

    all_batches = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

    all_raw: list[SearchResult] = []
    for batch in all_batches:
        if isinstance(batch, list):
            all_raw.extend(batch)
            for r in batch:
                stats.sources_used.add(r.source)

    stats.total_raw = len(all_raw)

    # ── Stage 3: Dedup + BM25/Semantic hybrid fusion (RRF) ───────────────────
    deduped = _dedup_by_url(all_raw)
    stats.after_dedup = len(deduped)

    if len(deduped) > 1:
        fused = _hybrid_score_and_rank(query, deduped)
    else:
        fused = deduped

    # ── Stage 4: Cross-encoder reranking ─────────────────────────────────────
    if rerank and len(fused) > 3:
        try:
            final = _neural_rerank(query, fused, top_k=max_results)
            stats.reranker_used = True
        except Exception:
            final = fused[:max_results]
    else:
        final = fused[:max_results]

    stats.after_rerank = len(final)
    stats.exa_used = has_exa

    # ── Optional: content enrichment (for Knowledge Updater) ─────────────────
    if fetch_content:
        final = await enrich_results_with_content(final, top_n=3)

    stats.elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        f"[forge:search] deep_search '{query[:50]}': "
        f"{stats.total_raw} raw → {stats.after_dedup} deduped → {stats.after_rerank} final | "
        f"{stats.elapsed_ms:.0f}ms | sources={stats.sources_used} | "
        f"reranked={stats.reranker_used} exa={stats.exa_used}"
    )
    return final, stats


async def semantic_search(
    query: str,
    max_results: int = 8,
    category: str | None = None,
) -> list[SearchResult]:
    """
    Exa-only neural semantic search.
    Best for: judge research (category="people"), sponsor research (category="company"),
    finding conceptually related projects without exact keyword matches.
    Requires EXA_API_KEY. $7/1k requests (content included).
    """
    if not os.environ.get("EXA_API_KEY"):
        logger.warning("[forge:search] semantic_search: EXA_API_KEY not set")
        return await web_search(query, max_results)

    results = await _search_exa(query, max_results, search_type="neural", category=category)
    if results and len(results) > 3:
        results = _neural_rerank(query, results, top_k=max_results)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def format_results_for_llm(
    results: list[SearchResult],
    max_chars_per_snippet: int = 400,
    include_scores: bool = False,
) -> str:
    """
    Format search results as a numbered context block for LLM injection.
    The LLM synthesises this — it never calls search itself.
    """
    if not results:
        return "(no web search results available — using training knowledge)"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        score_str = f" [score={r.score:.3f}]" if include_scores and r.score else ""
        text = (r.full_text or r.snippet)[:max_chars_per_snippet].replace("\n", " ").strip()
        date_str = f"  Published: {r.published}\n" if r.published else ""
        lines.append(f"[{i}] {r.title}{score_str}")
        lines.append(f"    Source: {r.url}")
        if date_str:
            lines.append(f"    {date_str.strip()}")
        if text:
            lines.append(f"    {text}")
        lines.append("")

    return "\n".join(lines)


# ── Primary convenience functions (replace the old search_and_synthesize) ────

async def search_and_synthesize(
    query: str,
    max_results: int = 8,
    include_news: bool = False,
    deep: bool = False,
) -> str:
    """
    Main entry point for agent search — returns formatted string for LLM context.

    deep=False (default): fast standard search, no expansion, no reranking.
                          ~300ms. Suitable for build-phase agent lookups.
    deep=True:            full pipeline — expansion + all sources + RRF + reranking.
                          ~800ms–2s. For Knowledge Updater, Competitor Analyst.

    Usage:
        raw = await search_and_synthesize("winning hackathon concepts 2026", deep=True)
        result = await complete_json(
            task="analyze-competitors",
            messages=[{"role": "user", "content": f"Research:\n{raw}\n\nExtract..."}],
            response_model=WinningConcepts,
        )
    """
    if deep:
        results, stats = await deep_search(
            query,
            max_results=max_results,
            use_exa=True,
            expand_queries=True,
            rerank=True,
        )
        logger.info(f"[forge:search] deep search stats: {stats}")
    else:
        results = await web_search(
            query,
            max_results=max_results,
            include_news=include_news,
        )

    return format_results_for_llm(results)


async def research_people(query: str, max_results: int = 8) -> str:
    """
    Semantic people search — for judge and speaker background research.
    Uses Exa people index (1B+ LinkedIn profiles) when EXA_API_KEY is set.
    Falls back to standard web search if key unavailable.
    """
    results = await semantic_search(query, max_results, category="people")
    return format_results_for_llm(results)


async def research_companies(query: str, max_results: int = 8) -> str:
    """
    Semantic company search — for sponsor discovery and API research.
    Uses Exa company index (70M entities) when EXA_API_KEY is set.
    Falls back to standard web search if key unavailable.
    """
    results = await semantic_search(query, max_results, category="company")
    return format_results_for_llm(results)


# ═══════════════════════════════════════════════════════════════════════════════
# CRAWL4AI ADAPTIVE CRAWLER
# ═══════════════════════════════════════════════════════════════════════════════

async def adaptive_crawl(
    start_url: str,
    query: str,
    max_pages: int = 20,
    confidence_threshold: float = 0.75,
    strategy: str = "statistical",
) -> list[dict]:
    """
    Adaptive web crawl — crawls a site until it has "enough" information
    to answer the query, then stops. Uses information foraging theory.

    Powered by Crawl4AI's AdaptiveCrawler with three-layer scoring:
      - Coverage:    how well collected pages cover the query terms
      - Consistency: coherence of information across pages
      - Saturation:  detecting when new pages add no new information

    strategy="statistical" — fast, no extra deps, good for exact terms
    strategy="embedding"   — semantic, uses all-MiniLM-L6-v2 locally

    Perfect for:
      - Knowledge Updater: crawl sponsor/library docs until sufficient
      - Competitor Analyst: crawl devpost category until enough winners found
      - Judge Profiler: crawl speaker bios until all judges covered

    Returns list of dicts: [{url, score, content}] sorted by relevance.
    """
    try:
        try:
            os.getcwd()
        except (FileNotFoundError, OSError):
            os.chdir(os.path.expanduser("~"))
        from crawl4ai import AsyncWebCrawler, AdaptiveCrawler, AdaptiveConfig, BrowserConfig  # type: ignore[import]

        browser_cfg = BrowserConfig(browser_type="chromium", chrome_channel="chromium", headless=True, verbose=False)
        config = AdaptiveConfig(
            strategy=strategy,
            confidence_threshold=confidence_threshold,
            max_pages=max_pages,
            top_k_links=4,
            min_gain_threshold=0.05,
        )

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            adaptive = AdaptiveCrawler(crawler, config)
            await adaptive.digest(start_url=start_url, query=query)
            pages = adaptive.get_relevant_content(top_k=max_pages)

        logger.info(
            f"[forge:search] adaptive_crawl '{query[:50]}' from {start_url}: "
            f"{len(pages)} pages retrieved"
        )
        return pages

    except ImportError:
        logger.warning("[forge:search] Crawl4AI not installed — adaptive_crawl unavailable")
        return []
    except Exception as e:
        logger.warning(f"[forge:search] adaptive_crawl failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# HACKATHON PLATFORM EXTRACTOR (replaces Stagehand for listing scrapes)
# ═══════════════════════════════════════════════════════════════════════════════

# Lablab and Devfolio are React SPAs — CSS selectors don't work.
# Crawl4AI fetches the page, we extract markdown, then parse with regex.
# Devpost uses its own JSON API (ForgeDevpostClient) and doesn't need Crawl4AI.

async def _fetch_devfolio_api(limit: int = 20) -> list[dict]:
    """Fetch hackathons from Devfolio's real JSON API. No browser needed."""
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            page = 1
            while len(results) < limit:
                async with session.get(
                    "https://api.devfolio.co/api/hackathons",
                    params={"filter": "application_open", "page": page},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.debug(f"[forge:search] Devfolio API HTTP {resp.status}")
                        break
                    data = await resp.json()

                if "result" not in data or not data["result"]:
                    break

                for item in data["result"]:
                    title = item.get("name", "")
                    slug = item.get("slug", "")
                    if not title or not slug:
                        continue

                    url = f"https://{slug}.devfolio.co/"
                    starts = item.get("starts_at", "")
                    ends = item.get("ends_at", "")

                    results.append({
                        "title": title,
                        "url": url,
                        "platform": "devfolio",
                        "deadline": ends[:10] if ends else "",
                        "starts_at": starts[:10] if starts else "",
                        "mode": "Online" if item.get("is_online") else "Offline",
                        "participants": str(item.get("participant_count", "")),
                        "team_size_min": item.get("team_min", 1),
                        "team_size_max": item.get("team_size", 4),
                        "location": item.get("location", ""),
                        "cover_img": item.get("cover_img", ""),
                    })

                    if len(results) >= limit:
                        break
                page += 1

        logger.info(f"[forge:search] Devfolio API: {len(results)} hackathons")
    except Exception as e:
        logger.warning(f"[forge:search] Devfolio API error: {e}")
    return results


async def _fetch_lablab_aiohttp(limit: int = 20) -> list[dict]:
    """Fetch hackathons from lablab.ai by parsing the event page HTML."""
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "text/html",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://lablab.ai/event",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"[forge:search] Lablab HTTP {resp.status}")
                    return []
                html = await resp.text()

        hackathon_pattern = re.compile(
            r'href="(/ai-hackathons/[^"]+)"[^>]*>.*?'
            r'(?:<h[23][^>]*>([^<]+)</h[23]>)?',
            re.DOTALL,
        )

        link_pattern = re.compile(
            r'href="(https://lablab\.ai/ai-hackathons/([^"]+))"',
        )

        seen_slugs: set[str] = set()
        for match in link_pattern.finditer(html):
            url, slug = match.groups()
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            title = slug.replace("-", " ").title()

            prize = ""
            context_start = max(0, match.start() - 2000)
            context = html[context_start:match.end() + 500]
            prize_match = re.search(r'\$[\d,]+(?:,\d{3})*', context)
            if prize_match:
                prize = prize_match.group(0)

            results.append({
                "title": title,
                "url": url,
                "platform": "lablab",
                "prize_amount_raw": prize,
            })
            if len(results) >= limit:
                break

        logger.info(f"[forge:search] Lablab: {len(results)} hackathons from HTML links")
    except Exception as e:
        logger.warning(f"[forge:search] Lablab fetch error: {e}")
    return results


async def scrape_hackathon_listings(
    platforms: list[str] | None = None,
    limit_per_platform: int = 20,
) -> list[dict]:
    """
    Scrape hackathon listings from Lablab and Devfolio.
    Devfolio: uses their real JSON API (https://api.devfolio.co/api/hackathons).
    Lablab: parses event page HTML links (no public API).
    No browser/Crawl4AI needed — pure aiohttp.
    """
    platforms = platforms or ["devpost", "lablab", "devfolio"]
    all_listings: list[dict] = []

    tasks = []
    if "devfolio" in platforms:
        tasks.append(("devfolio", _fetch_devfolio_api(limit_per_platform)))
    if "lablab" in platforms:
        tasks.append(("lablab", _fetch_lablab_aiohttp(limit_per_platform)))

    if not tasks:
        return []

    results = await asyncio.gather(
        *[t[1] for t in tasks],
        return_exceptions=True,
    )

    for (platform, _), result in zip(tasks, results):
        if isinstance(result, list):
            all_listings.extend(result)
            for item in result[:3]:
                logger.info(
                    f"[forge:search]   {platform}: {item.get('title', '?')[:55]} "
                    f"| {item.get('url', '')[:50]}"
                )
        elif isinstance(result, Exception):
            logger.warning(f"[forge:search] {platform} error: {result}")

    logger.info(f"[forge:search] scrape_hackathon_listings: {len(all_listings)} total from {[t[0] for t in tasks]}")
    return all_listings
