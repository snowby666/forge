#!/usr/bin/env python3
"""
Download webshare proxies and embed them into SearXNG settings.yml.

Usage:
    python scripts/update_searxng_proxies.py          # default 30 proxies
    python scripts/update_searxng_proxies.py --count 50
    
After running, restart SearXNG:
    docker compose restart searxng
"""

import argparse
import random
import sys
from pathlib import Path
from urllib.request import urlopen

WEBSHARE_URL = (
    "https://proxy.webshare.io/api/v2/proxy/list/download/"
    "ieqahpqdemgttqvflbxkdbmwkhpkfygvrqyliyhq/-/any/username/direct/-/"
    "?plan_id=11737780"
)
SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "searxng" / "settings.yml"


def download_proxies(count: int) -> list[str]:
    print(f"Downloading proxies from webshare.io...")
    resp = urlopen(WEBSHARE_URL, timeout=15)
    raw = resp.read().decode("utf-8")
    proxies = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) == 4:
            ip, port, user, pw = parts
            proxies.append(f"http://{user}:{pw}@{ip}:{port}")
    print(f"  Downloaded {len(proxies)} total proxies")
    random.shuffle(proxies)
    selected = proxies[:count]
    print(f"  Selected {len(selected)} for SearXNG")
    return selected


def build_settings(proxies: list[str]) -> str:
    proxy_lines = "\n".join(f'      - "{p}"' for p in proxies)

    return f'''use_default_settings: true

general:
  instance_name: "Forge Search"
  debug: false

search:
  safe_search: 0
  default_lang: "en"
  formats:
    - html
    - json

server:
  secret_key: "forge-searxng-secret-key"
  limiter: false
  image_proxy: false
  public_instance: false
  method: "GET"

ui:
  static_use_hash: true

outgoing:
  request_timeout: 15.0
  max_request_timeout: 30.0
  useragent_suffix: ""
  pool_connections: 100
  pool_maxsize: 20
  proxies:
    "all://":
{proxy_lines}

enabled_plugins:
  - 'Hash plugin'
  - 'Self Information'
  - 'Tracker URL remover'
  - 'Hostname replace'

engines:
  # ── Disabled engines ──
  - name: duckduckgo
    engine: duckduckgo
    disabled: true
  - name: duckduckgo images
    engine: duckduckgo_extra
    disabled: true
  - name: duckduckgo videos
    engine: duckduckgo_extra
    disabled: true
  - name: duckduckgo news
    engine: duckduckgo_extra
    disabled: true
  - name: duckduckgo weather
    engine: duckduckgo_weather
    disabled: true
  - name: duckduckgo definitions
    engine: duckduckgo_definitions
    disabled: true
  - name: wikipedia
    engine: wikipedia
    disabled: true
  # ── Tuned engines ──
  - name: brave
    engine: brave
    disabled: false
    timeout: 15.0
    send_accept_language_header: true
  - name: google
    engine: google
    disabled: false
    timeout: 15.0
  - name: bing
    engine: bing
    disabled: false
    timeout: 15.0
  - name: startpage
    engine: startpage
    disabled: false
    timeout: 15.0
'''


def main():
    parser = argparse.ArgumentParser(description="Embed webshare proxies into SearXNG settings")
    parser.add_argument("--count", type=int, default=30, help="Number of proxies to embed (default: 30)")
    args = parser.parse_args()

    proxies = download_proxies(args.count)
    if not proxies:
        print("ERROR: No proxies downloaded")
        sys.exit(1)

    content = build_settings(proxies)
    SETTINGS_PATH.write_text(content, encoding="utf-8")
    print(f"\n  Written to {SETTINGS_PATH}")
    print(f"  Restart SearXNG: docker compose restart searxng")


if __name__ == "__main__":
    main()
