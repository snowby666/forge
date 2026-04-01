# -*- coding: utf-8 -*-
"""
config/devpost.py — Forge Devpost Intelligence Client
======================================================

Mossad-grade hackathon intelligence. Zero external deps beyond aiohttp.

DATA SOURCES (in priority order):
  1. JSON API:  https://devpost.com/api/hackathons     → full listing with 20+ fields
  2. HTML:      https://{slug}.devpost.com/rules        → rules, eligibility
  3. HTML:      https://{slug}.devpost.com/details/faq   → FAQs
  4. HTML:      https://{slug}.devpost.com               → description, judges, sponsors, community
  5. HTML:      https://{slug}.devpost.com/project-gallery → past projects / winners
  6. HTML:      https://devpost.com/software/{slug}      → individual project detail
  7. JSON API:  https://api.github.com/repos/{owner}/{repo} → GitHub enrichment

DEVPOST API FIELDS (reverse-engineered, all captured):
  id, title, url, open_state, themes[], prize_amount (HTML-encoded),
  prizes_counts {cash, other}, registrations_count, featured,
  organization_name, winners_announced, submission_gallery_url,
  start_a_submission_url, invite_only, eligibility_requirement_invite_only_description,
  submission_period_dates, displayed_location, thumbnail_url,
  time_left_to_submission, analytics_identifier, managed_by_devpost_badge

API QUERY PARAMETERS (reverse-engineered):
  page=N                     pagination (9 per page)
  status[]=open|ended|upcoming  filter by state
  order_by=prize-amount|submission-count|recently-added
  themes[]=Machine Learning/AI  filter by theme name
  search=keyword              full-text search

THEME IDS (for reference):
  1=Blockchain, 3=Fintech, 6=Machine Learning/AI, 11=Productivity,
  13=Social Good, 16=Health, 17=Low/No Code, 19=Education,
  21=Enterprise, 22=Open Ended, 23=Beginner Friendly
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import aiohttp

logger = logging.getLogger(__name__)

DEVPOST_HACKATHONS_API = "https://devpost.com/api/hackathons"
DEVPOST_SOFTWARE_API = "https://api.devpost.com/software"
GITHUB_REPO_API = "https://api.github.com/repos/{owner}/{repo}"
USER_AGENT = "Forge/2.0 (hackathon-agent-swarm)"

MAX_RETRIES = 3
BACKOFF_BASE = 0.5
RETRY_STATUSES = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT = 20.0
MIN_REQUEST_INTERVAL = 0.12

# Themes Forge cares about most (for filtered queries)
AI_THEMES = ["Machine Learning/AI"]
RELEVANT_THEMES = ["Machine Learning/AI", "Productivity", "Enterprise", "Open Ended", "Fintech", "Health", "Education"]


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class DevpostHackathon:
    """Every field from the Devpost JSON API + detail page enrichment."""
    # From JSON API
    id: int
    title: str
    url: str
    open_state: str                     # "open" | "ended" | "upcoming"
    themes: list[str]
    prize_amount_raw: str               # e.g. "$<span data-currency-value>75,000</span>"
    prize_usd: float                    # parsed numeric
    registrations_count: int
    submission_period: str              # "Jun 01 - Jun 30, 2026"
    time_left: str                      # "6 days left", "about 1 month left"
    location: str
    thumbnail_url: str
    organization_name: str
    featured: bool
    invite_only: bool
    invite_description: str
    prizes_cash_count: int
    prizes_other_count: int
    winners_announced: bool
    submission_gallery_url: str
    start_submission_url: str
    managed_by_devpost: bool
    # From detail page scrape
    description: str = ""
    rules: str = ""
    eligibility: str = ""
    prizes: list[dict] = field(default_factory=list)
    judges: list[dict] = field(default_factory=list)
    tracks: list[dict] = field(default_factory=list)
    sponsors: list[dict] = field(default_factory=list)
    judging_criteria: list[str] = field(default_factory=list)
    community_links: list[dict] = field(default_factory=list)
    deadline_iso: str = ""
    team_size_min: int = 1
    team_size_max: int = 5
    faqs: list[str] = field(default_factory=list)
    allowed_techs: list[str] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)  # docs, starter kits, APIs


@dataclass
class DevpostProject:
    url: str
    slug: str
    name: str
    tagline: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    submitted_to: list[str] = field(default_factory=list)
    creators: list[str] = field(default_factory=list)
    github_urls: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    hero_image: str = ""
    github_repos: list[dict] = field(default_factory=list)


@dataclass
class WinnerAnalysis:
    hackathon_slug: str
    total_projects: int
    projects: list[DevpostProject]
    tech_stack_frequency: dict[str, int]
    common_themes: list[str]
    github_languages: dict[str, int]
    avg_github_stars: float


# ── Async HTTP Layer ──────────────────────────────────────────────────────────

class _AsyncHTTP:
    """Async HTTP with retry, rate limiting, proxy rotation, and response caching."""

    def __init__(self, github_token: str | None = None):
        self._session: aiohttp.ClientSession | None = None
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._cache_ttl = 180.0
        self._cache_max = 512
        self._github_token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self._use_proxy = True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_json(self, url: str, params: dict | None = None, github: bool = False) -> dict:
        text = await self._request(url, params, github=github, use_proxy=False)
        return json.loads(text)

    async def get_text(self, url: str, params: dict | None = None) -> str:
        return await self._request(url, params, use_proxy=self._use_proxy)

    async def _request(self, url: str, params: dict | None = None, github: bool = False, use_proxy: bool = False) -> str:
        if params:
            qs = urlencode(params, doseq=True)
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{qs}"

        cached = self._cache_get(url)
        if cached is not None:
            return cached

        session = await self._get_session()
        headers: dict[str, str] = {}
        if github:
            headers["Accept"] = "application/vnd.github+json"
            if self._github_token:
                headers["Authorization"] = f"Bearer {self._github_token}"

        for attempt in range(1, MAX_RETRIES + 1):
            async with self._lock:
                now = time.monotonic()
                wait = MIN_REQUEST_INTERVAL - (now - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()

            # Proxy rotation — different proxy per retry (only for HTML scraping)
            proxy = None
            if use_proxy and not github:
                try:
                    from config.proxy_manager import get_next_proxy
                    proxy = get_next_proxy()
                except ImportError:
                    pass

            try:
                async with session.get(url, headers=headers, proxy=proxy) as resp:
                    if resp.status in RETRY_STATUSES and attempt < MAX_RETRIES:
                        retry_after = float(resp.headers.get("Retry-After", BACKOFF_BASE * (2 ** attempt)))
                        logger.debug(f"[devpost] {resp.status} on {url[:80]}, retry in {retry_after:.1f}s")
                        await asyncio.sleep(min(retry_after, 10.0))
                        continue
                    resp.raise_for_status()
                    body = await resp.text()
                    self._cache_set(url, body)
                    return body
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                raise RuntimeError(f"[devpost] Failed after {MAX_RETRIES} retries: {url[:80]} — {e}") from e

        raise RuntimeError(f"[devpost] Exhausted retries for {url[:80]}")

    def _cache_get(self, key: str) -> str | None:
        entry = self._cache.get(key)
        if entry and entry[1] > time.monotonic():
            self._cache.move_to_end(key)
            return entry[0]
        if entry:
            self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, value: str):
        self._cache[key] = (value, time.monotonic() + self._cache_ttl)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)


# ── HTML Parsers ──────────────────────────────────────────────────────────────

class _ProjectPageParser(HTMLParser):
    """Extracts structured data from a Devpost project page."""

    GITHUB_RE = re.compile(r'href=["\']?(https?://github\.com/[^/\s"\'<>]+/[^"\s\'<>]+)["\']?')

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self.name = ""
        self.tagline = ""
        self.description = ""
        self.hero_image = ""
        self.tags: list[str] = []
        self.submitted_to: list[str] = []
        self.creators: list[str] = []
        self.links: list[dict] = []
        self.github_urls: list[str] = []

        self._in_h1 = False
        self._in_h3 = False
        self._links_depth = 0
        self._built_with_depth = 0
        self._submissions_depth = 0
        self._team_depth = 0
        self._active_link: dict[str, str] | None = None
        self._active_submission = False
        self._active_tag: str | None = None

    def handle_starttag(self, tag: str, attrs_list):
        attrs = {k: (v or "") for k, v in attrs_list}
        cls = attrs.get("class", "")
        eid = attrs.get("id", "")

        for depth_name in ("_links_depth", "_built_with_depth", "_submissions_depth", "_team_depth"):
            if getattr(self, depth_name):
                setattr(self, depth_name, getattr(self, depth_name) + 1)

        if tag == "meta":
            prop = attrs.get("property", "")
            content = attrs.get("content", "")
            if prop == "og:title" and content:
                self.name = content.removesuffix(" - Devpost")
            elif prop == "og:description" and content and not self.description:
                self.description = content
            elif prop == "og:image" and content:
                self.hero_image = self._abs(content)
            return

        if tag == "h1" and not self.name:
            self._in_h1 = True
        if tag == "h3" and not self.tagline:
            self._in_h3 = True
        if tag == "nav" and "app-links" in cls:
            self._links_depth = 1
        if eid == "built-with":
            self._built_with_depth = 1
        if eid == "submissions":
            self._submissions_depth = 1
        if eid == "app-team":
            self._team_depth = 1

        href = attrs.get("href", "")
        if tag == "a" and href:
            if self._links_depth:
                self._active_link = {"href": href, "text": ""}
            if self._submissions_depth:
                self._active_submission = True
            if self._built_with_depth:
                self._active_tag = ""
        elif tag == "span" and self._built_with_depth and "cp-tag" in cls:
            self._active_tag = ""

    def handle_endtag(self, tag: str):
        if tag == "h1":
            self._in_h1 = False
        if tag == "h3":
            self._in_h3 = False
        if tag == "a":
            if self._active_link:
                href = self._abs(self._active_link["href"])
                label = self._active_link["text"].strip()
                if href:
                    domain = urlparse(href).netloc.lower().replace("www.", "")
                    is_gh = "github.com" in domain
                    self.links.append({"url": href, "label": label, "domain": domain, "is_github": is_gh})
                    if is_gh and href not in self.github_urls:
                        self.github_urls.append(href)
                self._active_link = None
            self._active_submission = False
            self._finalize_tag()
        if tag == "span":
            self._finalize_tag()

        for depth_name in ("_links_depth", "_built_with_depth", "_submissions_depth", "_team_depth"):
            val = getattr(self, depth_name)
            if val:
                setattr(self, depth_name, val - 1)

    def handle_data(self, data: str):
        text = " ".join(data.split())
        if not text:
            return
        if self._in_h1 and not self.name:
            self.name = text
        elif self._in_h3 and not self.tagline:
            self.tagline = text
        if self._active_link:
            self._active_link["text"] = f"{self._active_link['text']} {text}".strip()
        if self._active_submission and text not in self.submitted_to:
            self.submitted_to.append(text)
        if self._active_tag is not None:
            self._active_tag = f"{self._active_tag} {text}".strip()
        if self._team_depth:
            clean = text.strip()
            if len(clean) > 1 and clean not in self.creators and "@" not in clean:
                self.creators.append(clean)

    def _finalize_tag(self):
        if self._active_tag is None:
            return
        t = self._active_tag.strip()
        skip = {"built with", "try it out", "created by"}
        if t and t.lower() not in skip and t not in self.tags:
            self.tags.append(t)
        self._active_tag = None

    def _abs(self, url: str) -> str:
        url = url.strip()
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http"):
            return url
        return urljoin(self._base, url) if url else ""

    def extract_github_from_html(self, html: str):
        for m in self.GITHUB_RE.finditer(html):
            url = m.group(1).rstrip(").,;")
            if url not in self.github_urls:
                self.github_urls.append(url)


# ── Utility ───────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags, returning plain text."""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _parse_prize_amount(text: str) -> float:
    """Parse prize strings including HTML-encoded ones from API.
    Handles: '$<span data-currency-value>75,000</span>', '$10,000', '50K', '€2,000'
    """
    text = _strip_html(text)
    text = text.replace(",", "").replace(" ", "").upper()
    # Handle non-USD currencies roughly (€, £, etc.)
    text = re.sub(r'[€£¥₹]', '$', text)
    m = re.search(r'\$?([\d.]+)\s*K', text)
    if m:
        return float(m.group(1)) * 1000
    m = re.search(r'\$?([\d.]+)\s*M', text)
    if m:
        return float(m.group(1)) * 1_000_000
    m = re.search(r'\$?([\d.]+)', text)
    if m:
        return float(m.group(1))
    return 0.0


def _parse_time_left(text: str) -> int:
    """Parse 'X days left' or 'about 1 month left' into days."""
    if not text:
        return 0
    text = text.lower().strip()
    m = re.search(r'(\d+)\s*day', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*month', text)
    if m:
        return int(m.group(1)) * 30
    m = re.search(r'(\d+)\s*hour', text)
    if m:
        return max(1, int(m.group(1)) // 24)
    if "about" in text and "month" in text:
        return 30
    return 0


def _extract_gallery_urls(html: str) -> tuple[list[str], int]:
    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'href=["\']?(https?://devpost\.com/software/[^"\s\'<>]+)["\']?', html):
        raw = m.group(1).rstrip(").,;")
        slug = urlparse(raw).path.removeprefix("/software/").strip("/").split("/")[0]
        if not slug:
            continue
        clean = f"https://devpost.com/software/{slug}"
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)
    pages = [int(m.group(1)) for m in re.finditer(r"project-gallery\?page=(\d+)", html)]
    return urls, max(pages) if pages else 1


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if not parsed.netloc or "github.com" not in parsed.netloc.lower():
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        owner = parts[0]
        repo = parts[1].removesuffix(".git")
        if owner and repo and repo not in ("issues", "pulls", "tree", "blob", "wiki", "releases", "actions"):
            return owner, repo
    return None


# ── Main Client ───────────────────────────────────────────────────────────────

class ForgeDevpostClient:
    """
    Mossad-grade async Devpost intelligence client.

    Usage:
        async with ForgeDevpostClient() as client:
            hackathons = await client.list_open_hackathons()
            for h in hackathons:
                h = await client.enrich_hackathon(h)
            winners = await client.get_past_winners("treehacks-2025", pages=2)
    """

    def __init__(self, github_token: str | None = None):
        self._http = _AsyncHTTP(github_token=github_token)

    async def __aenter__(self):
        try:
            from config.proxy_manager import ensure_loaded
            await ensure_loaded()
        except ImportError:
            pass
        return self

    async def __aexit__(self, *args):
        await self._http.close()

    # ── 1. List hackathons (JSON API) ────────────────────────────────────────

    async def list_hackathons(
        self,
        status: str = "open",
        pages: int = 8,
        order_by: str = "prize-amount",
        themes: list[str] | None = None,
        search: str | None = None,
    ) -> list[DevpostHackathon]:
        """
        Fetch ALL hackathons from Devpost's JSON API.
        9 per page, ~64 open at any time → 8 pages gets everything.
        Supports filtering by theme and full-text search.
        """
        all_hackathons: list[DevpostHackathon] = []
        total_api = 0

        for page in range(1, pages + 1):
            try:
                params: dict[str, Any] = {"page": page}
                if status:
                    params["status[]"] = status
                if order_by:
                    params["order_by"] = order_by
                if themes:
                    params["themes[]"] = themes
                if search:
                    params["search"] = search

                data = await self._http.get_json(DEVPOST_HACKATHONS_API, params=params)
                items = data.get("hackathons", [])
                meta = data.get("meta", {})
                total_api = meta.get("total_count", total_api)

                if not items:
                    break

                for item in items:
                    try:
                        all_hackathons.append(self._parse_api_hackathon(item))
                    except Exception as e:
                        logger.debug(f"[devpost] Failed to parse hackathon: {e}")

                logger.info(
                    f"[devpost] Page {page}: +{len(items)} "
                    f"(total {len(all_hackathons)}/{total_api})"
                )

                if len(all_hackathons) >= total_api:
                    break

            except Exception as e:
                logger.warning(f"[devpost] Page {page} failed: {e}")
                break

        logger.info(
            f"[devpost] Listed {len(all_hackathons)}/{total_api} "
            f"{status} hackathons (ordered by {order_by})"
        )
        return all_hackathons

    def _parse_api_hackathon(self, item: dict) -> DevpostHackathon:
        """Parse a single hackathon from the JSON API response."""
        themes = []
        for t in item.get("themes", []):
            if isinstance(t, dict) and t.get("name"):
                themes.append(t["name"])

        location = ""
        loc = item.get("displayed_location")
        if isinstance(loc, dict):
            location = loc.get("location", "")

        prize_raw = item.get("prize_amount", "") or ""
        prizes_counts = item.get("prizes_counts", {})

        return DevpostHackathon(
            id=int(item.get("id", 0)),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            open_state=str(item.get("open_state", "")),
            themes=themes,
            prize_amount_raw=prize_raw,
            prize_usd=_parse_prize_amount(prize_raw),
            registrations_count=int(item.get("registrations_count", 0) or 0),
            submission_period=str(item.get("submission_period_dates", "")),
            time_left=str(item.get("time_left_to_submission", "")),
            location=location,
            thumbnail_url=str(item.get("thumbnail_url", "")),
            organization_name=str(item.get("organization_name", "")),
            featured=bool(item.get("featured", False)),
            invite_only=bool(item.get("invite_only", False)),
            invite_description=str(item.get("eligibility_requirement_invite_only_description", "") or ""),
            prizes_cash_count=int(prizes_counts.get("cash", 0)),
            prizes_other_count=int(prizes_counts.get("other", 0)),
            winners_announced=bool(item.get("winners_announced", False)),
            submission_gallery_url=str(item.get("submission_gallery_url", "")),
            start_submission_url=str(item.get("start_a_submission_url", "")),
            managed_by_devpost=bool(item.get("managed_by_devpost_badge", False)),
        )

    # ── 2. Enrich hackathon detail (multi-page scrape) ───────────────────────

    async def enrich_hackathon(self, h: DevpostHackathon) -> DevpostHackathon:
        """
        Deep-scrape a hackathon by visiting multiple sub-pages in parallel:
          - Main page (description, judges, sponsors, community links)
          - /rules (rules, eligibility)
          - /details/faq (FAQs)
        Then LLM-extracts structured data from combined content.
        """
        if not h.url:
            return h

        base = h.url.rstrip("/")
        urls = {
            "main": base,
            "rules": f"{base}/rules",
            "faq": f"{base}/details/faq",
            "judges": f"{base}/details/judges",
        }

        # Fetch all pages in parallel
        pages: dict[str, str] = {}
        tasks = {name: self._http.get_text(url) for name, url in urls.items()}

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, str) and len(result) > 100:
                pages[name] = result

        if not pages:
            return h

        # Extract community links from HTML (Discord, Slack, GitHub, etc.)
        combined_html = " ".join(pages.values())
        link_patterns = {
            "discord": r'href=["\']?(https?://discord\.(gg|com)/[^"\s\'<>]+)',
            "slack": r'href=["\']?(https?://[^"\s\'<>]*slack\.(com|to)/[^"\s\'<>]+)',
            "telegram": r'href=["\']?(https?://t\.me/[^"\s\'<>]+)',
            "twitter": r'href=["\']?(https?://(twitter|x)\.com/[^"\s\'<>]+)',
            "youtube": r'href=["\']?(https?://(youtube\.com|youtu\.be)/[^"\s\'<>]+)',
            "github": r'href=["\']?(https?://github\.com/[^"\s\'<>]+)',
            "linkedin": r'href=["\']?(https?://(www\.)?linkedin\.com/[^"\s\'<>]+)',
        }
        seen_urls = set()
        for platform, pattern in link_patterns.items():
            for m in re.finditer(pattern, combined_html, re.I):
                url = m.group(1).rstrip('"\')')
                if url not in seen_urls:
                    h.community_links.append({"platform": platform, "url": url})
                    seen_urls.add(url)

        # Extract resource links (docs, APIs, starter kits)
        for m in re.finditer(r'href=["\']?(https?://[^"\s\'<>]+(?:docs|api|github|starter|boilerplate|template)[^"\s\'<>]*)["\']?', combined_html, re.I):
            url = m.group(1).rstrip('"\')')
            if url not in seen_urls:
                h.resources.append({"url": url, "type": "resource"})
                seen_urls.add(url)

        # Smart HTML → text: extract key sections instead of blind truncation
        def _html_to_focused_text(html: str, max_chars: int = 8000) -> str:
            """Strip scripts/styles, but prioritize sections with judges/prizes/sponsors."""
            cleaned = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
            cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.S)
            cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.S)
            cleaned = re.sub(r'<nav[^>]*>.*?</nav>', '', cleaned, flags=re.S)
            cleaned = re.sub(r'<footer[^>]*>.*?</footer>', '', cleaned, flags=re.S)
            text = re.sub(r'<[^>]+>', ' ', cleaned)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]

        def _extract_section(html: str, markers: list[str], max_chars: int = 3000) -> str:
            """Extract text around HTML sections containing specific keywords."""
            lower = html.lower()
            chunks = []
            for marker in markers:
                idx = lower.find(marker)
                while idx != -1 and len(chunks) < 5:
                    start = max(0, idx - 200)
                    end = min(len(html), idx + max_chars)
                    chunk = html[start:end]
                    chunk = re.sub(r'<[^>]+>', ' ', chunk)
                    chunk = re.sub(r'\s+', ' ', chunk).strip()
                    if len(chunk) > 20:
                        chunks.append(chunk)
                    idx = lower.find(marker, idx + len(marker))
            return "\n".join(chunks)

        # Build focused text for LLM — main page sections + subpages
        try:
            from config.electronhub import complete

            combined_text = ""

            if "main" in pages:
                main_general = _html_to_focused_text(pages["main"], max_chars=4000)
                main_judges = _extract_section(pages["main"], ["judge", "mentor", "evaluator", "jury"], max_chars=2000)
                main_prizes = _extract_section(pages["main"], ["prize", "reward", "bounty", "award", "track"], max_chars=2000)
                main_sponsors = _extract_section(pages["main"], ["sponsor", "partner", "powered by", "built with"], max_chars=1500)
                combined_text += f"=== MAIN PAGE ===\n{main_general}\n\n"
                if main_judges:
                    combined_text += f"=== JUDGES SECTION (from main) ===\n{main_judges}\n\n"
                if main_prizes:
                    combined_text += f"=== PRIZES SECTION (from main) ===\n{main_prizes}\n\n"
                if main_sponsors:
                    combined_text += f"=== SPONSORS (from main) ===\n{main_sponsors}\n\n"

            if "judges" in pages:
                combined_text += f"=== JUDGES PAGE ===\n{_html_to_focused_text(pages['judges'], max_chars=4000)}\n\n"

            if "rules" in pages:
                combined_text += f"=== RULES PAGE ===\n{_html_to_focused_text(pages['rules'], max_chars=3000)}\n\n"

            if "faq" in pages:
                combined_text += f"=== FAQ PAGE ===\n{_html_to_focused_text(pages['faq'], max_chars=2000)}\n\n"

            prompt = (
                f"Extract ALL hackathon details. Return ONLY valid JSON.\n\n"
                f"{combined_text[:12000]}\n\n"
                f"Return JSON:\n"
                f'{{"description": "full description",'
                f'"rules": "rules summary",'
                f'"eligibility": "who can participate",'
                f'"deadline": "ISO 8601 date or empty",'
                f'"prizes": [{{"name": "...", "amount": 0, "sponsor": "", "requirements": ""}}],'
                f'"judges": [{{"name": "...", "title": "...", "company": "", "expertise": []}}],'
                f'"tracks": [{{"name": "...", "description": "", "sponsor": "", "prize_amount": 0}}],'
                f'"judging_criteria": ["criterion1", "criterion2"],'
                f'"sponsors": [{{"name": "...", "api_name": "", "docs_url": "", "prize_amount": 0}}],'
                f'"faqs": ["Q: ... A: ..."],'
                f'"allowed_techs": ["tech1"],'
                f'"team_size_min": 1, "team_size_max": 5}}'
            )

            raw = await complete(task="scout-hackathons", messages=[{"role": "user", "content": prompt}], temperature=0.1)
            cleaned = raw.strip()
            # Strip markdown fences: ```json ... ```, ``` ... ```, etc.
            if cleaned.startswith("```"):
                first_newline = cleaned.find("\n")
                if first_newline != -1:
                    cleaned = cleaned[first_newline + 1:]
                cleaned = cleaned.rsplit("```", 1)[0].strip()
            # Also handle case where LLM wraps in { } with extra text
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                cleaned = cleaned[brace_start:brace_end + 1]
            extracted = json.loads(cleaned)

            if extracted.get("description"):
                h.description = extracted["description"]
            if extracted.get("rules"):
                h.rules = extracted["rules"]
            if extracted.get("eligibility"):
                h.eligibility = extracted["eligibility"]
            if extracted.get("deadline"):
                h.deadline_iso = extracted["deadline"]
            if extracted.get("prizes"):
                h.prizes = extracted["prizes"]
            if extracted.get("judges"):
                h.judges = extracted["judges"]
            if extracted.get("tracks"):
                h.tracks = extracted["tracks"]
            if extracted.get("judging_criteria"):
                h.judging_criteria = extracted["judging_criteria"]
            if extracted.get("sponsors"):
                h.sponsors = extracted["sponsors"]
            if extracted.get("faqs"):
                h.faqs = extracted["faqs"]
            if extracted.get("allowed_techs"):
                h.allowed_techs = extracted["allowed_techs"]
            h.team_size_min = extracted.get("team_size_min", 1)
            h.team_size_max = extracted.get("team_size_max", 5)

            logger.info(
                f"[devpost] Enriched '{h.title[:45]}': "
                f"{len(h.prizes)} prizes, {len(h.judges)} judges, "
                f"{len(h.tracks)} tracks, {len(h.sponsors)} sponsors, "
                f"{len(h.community_links)} community, {len(h.resources)} resources"
            )

        except Exception as e:
            logger.warning(f"[devpost] LLM extraction failed for {h.title[:40]}: {e}")

        return h

    # ── 3. Past winner analysis ──────────────────────────────────────────────

    async def get_past_winners(
        self,
        hackathon_slug_or_url: str,
        pages: int = 2,
        include_github: bool = True,
    ) -> WinnerAnalysis:
        """Scrape project gallery → project details → GitHub enrichment."""
        base_url = self._normalize_hackathon_url(hackathon_slug_or_url)
        all_urls: list[str] = []
        total_pages = 1

        for page in range(1, pages + 1):
            if page > total_pages:
                break
            gallery_url = f"{base_url}/project-gallery" + (f"?page={page}" if page > 1 else "")
            try:
                html = await self._http.get_text(gallery_url)
                urls, total_pages = _extract_gallery_urls(html)
                all_urls.extend(u for u in urls if u not in all_urls)
                logger.info(f"[devpost] Gallery page {page}/{total_pages}: {len(urls)} projects")
            except Exception as e:
                logger.warning(f"[devpost] Gallery page {page} failed: {e}")
                break

        sem = asyncio.Semaphore(8)
        projects: list[DevpostProject] = []

        async def fetch_project(url: str) -> DevpostProject | None:
            async with sem:
                return await self.get_project_detail(url)

        results = await asyncio.gather(*[fetch_project(u) for u in all_urls], return_exceptions=True)
        for r in results:
            if isinstance(r, DevpostProject) and r.name:
                projects.append(r)

        if include_github:
            gh_tasks = []
            for p in projects:
                for gh_url in p.github_urls[:2]:
                    gh_tasks.append(self._enrich_github(gh_url))
            gh_results = await asyncio.gather(*gh_tasks, return_exceptions=True)
            gh_idx = 0
            for p in projects:
                for _ in p.github_urls[:2]:
                    if gh_idx < len(gh_results) and isinstance(gh_results[gh_idx], dict) and gh_results[gh_idx]:
                        p.github_repos.append(gh_results[gh_idx])
                    gh_idx += 1

        tech_freq: dict[str, int] = {}
        gh_languages: dict[str, int] = {}
        stars: list[int] = []
        for p in projects:
            for tag in p.tags:
                tech_freq[tag] = tech_freq.get(tag, 0) + 1
            for repo in p.github_repos:
                lang = repo.get("language", "")
                if lang:
                    gh_languages[lang] = gh_languages.get(lang, 0) + 1
                s = repo.get("stargazers_count", 0)
                if isinstance(s, int):
                    stars.append(s)

        tech_freq = dict(sorted(tech_freq.items(), key=lambda x: x[1], reverse=True))

        analysis = WinnerAnalysis(
            hackathon_slug=hackathon_slug_or_url,
            total_projects=len(all_urls),
            projects=projects,
            tech_stack_frequency=tech_freq,
            common_themes=list(tech_freq.keys())[:15],
            github_languages=gh_languages,
            avg_github_stars=sum(stars) / len(stars) if stars else 0,
        )

        logger.info(
            f"[devpost] Winners '{hackathon_slug_or_url}': "
            f"{len(projects)} projects, "
            f"top: {', '.join(list(tech_freq.keys())[:5])}"
        )
        return analysis

    # ── 4. Project detail ────────────────────────────────────────────────────

    async def get_project_detail(self, slug_or_url: str) -> DevpostProject:
        url = slug_or_url if slug_or_url.startswith("http") else f"https://devpost.com/software/{slug_or_url}"
        try:
            html = await self._http.get_text(url)
            parser = _ProjectPageParser(url)
            parser.feed(html)
            parser.close()
            parser.extract_github_from_html(html)
            slug = urlparse(url).path.removeprefix("/software/").strip("/").split("/")[0]
            return DevpostProject(
                url=url, slug=slug, name=parser.name,
                tagline=parser.tagline, description=parser.description,
                tags=parser.tags, submitted_to=parser.submitted_to,
                creators=parser.creators, github_urls=parser.github_urls,
                links=parser.links, hero_image=parser.hero_image,
            )
        except Exception as e:
            logger.debug(f"[devpost] Parse failed for {url[:60]}: {e}")
            return DevpostProject(url=url, slug="", name="")

    # ── 5. GitHub enrichment ─────────────────────────────────────────────────

    async def _enrich_github(self, url: str) -> dict:
        parsed = _github_owner_repo(url)
        if not parsed:
            return {}
        owner, repo = parsed
        try:
            data = await self._http.get_json(
                GITHUB_REPO_API.format(owner=owner, repo=repo), github=True,
            )
            return {
                "full_name": data.get("full_name", ""),
                "html_url": data.get("html_url", ""),
                "description": data.get("description", ""),
                "stargazers_count": data.get("stargazers_count", 0),
                "forks_count": data.get("forks_count", 0),
                "language": data.get("language", ""),
                "license": (data.get("license") or {}).get("name", ""),
                "updated_at": data.get("updated_at", ""),
                "topics": data.get("topics", []),
            }
        except Exception as e:
            logger.debug(f"[devpost] GitHub failed for {owner}/{repo}: {e}")
            return {}

    # ── 6. Search projects ───────────────────────────────────────────────────

    async def search_projects(self, query: str, pages: int = 2) -> list[DevpostProject]:
        results: list[DevpostProject] = []
        for page in range(1, pages + 1):
            try:
                data = await self._http.get_json(
                    DEVPOST_SOFTWARE_API, params={"page": page, "query": query},
                )
                items = data.get("software", [])
                if not items:
                    break
                for item in items:
                    results.append(DevpostProject(
                        url=str(item.get("url", "")),
                        slug=str(item.get("slug", "")),
                        name=str(item.get("name", "")),
                        tagline=str(item.get("tagline", "")),
                        description=str(item.get("description", "")),
                    ))
            except Exception as e:
                logger.warning(f"[devpost] Search page {page} failed: {e}")
                break
        return results

    # ── 7. Ended hackathons (for competitive analysis) ───────────────────────

    async def list_recent_ended(self, pages: int = 3, themes: list[str] | None = None) -> list[DevpostHackathon]:
        """Fetch recently ended hackathons for competitive intelligence."""
        return await self.list_hackathons(status="ended", pages=pages, themes=themes)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_hackathon_url(slug_or_url: str) -> str:
        value = slug_or_url.strip().strip("/")
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        if value.endswith(".devpost.com"):
            return f"https://{value}"
        if "." not in value:
            return f"https://{value}.devpost.com"
        return f"https://{value}"
