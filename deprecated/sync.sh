#!/usr/bin/env bash
# sync.sh — Hot-reload code changes to ~/forge without rebuilding anything.
# Usage: bash sync.sh
#
# What it does:
#   1. Copies only source files (Python, config, scripts) to ~/forge
#   2. Skips venv, node_modules, Docker volumes, .git
#   3. Takes ~1 second
#
# What it does NOT do:
#   - Reinstall pip packages (run: cd ~/forge && pip install -e ".[dev]")
#   - Restart Docker (run: cd ~/forge && bash scripts/start.sh)

set -euo pipefail

GREEN='\033[0;32m'; DIM='\033[2m'; NC='\033[0m'
log() { echo -e "${GREEN}[sync]${NC} $1"; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$HOME/forge"

if [[ ! -d "$DST/.venv" ]]; then
  echo "Error: $DST/.venv not found. Run forge-deploy.sh first."
  exit 1
fi

log "Syncing $SRC → $DST"

# Avoid "getcwd: cannot access parent directories" when rsync --delete
# recreates dirs under the shell's cwd
cd "$HOME"

rsync -a --delete \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='*.egg-info/' \
  --exclude='.env' \
  "$SRC/" "$DST/"

# Fix line endings on anything that might have CRLF
find "$DST" -maxdepth 1 -name "*.py" -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find "$DST/agents" "$DST/config" "$DST/scripts" -type f \( -name "*.py" -o -name "*.sh" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find "$DST/docker" -type f \( -name "*.yaml" -o -name "*.yml" -o -name "*.env" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
sed -i 's/\r$//' "$DST/docker-compose.yml" "$DST/docker-compose.daytona.yml" 2>/dev/null || true

# Re-install in editable mode (picks up new deps in pyproject.toml, ~2s if nothing changed)
cd "$DST"
source .venv/bin/activate
pip install -e ".[dev,calendar,stitch,daytona]" --quiet 2>&1 | tail -1

# Ensure Playwright Chromium is installed (Crawl4AI needs it)
log "Installing Playwright system deps..."
python -m playwright install-deps chromium 2>&1 | tail -3 || true
log "Downloading Playwright Chromium browser..."
python -m playwright install chromium 2>&1
if [ $? -ne 0 ]; then
  log "Playwright install failed, trying with sudo..."
  sudo "$(which python)" -m playwright install chromium 2>&1 || true
fi
# Verify Chromium is accessible
CHROMIUM_BIN=$(python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()" 2>/dev/null || echo "NOT_FOUND")
if [[ "$CHROMIUM_BIN" != "NOT_FOUND" && -f "$CHROMIUM_BIN" ]]; then
  log "Playwright Chromium OK: $CHROMIUM_BIN"
else
  log "WARNING: Chromium binary not found at expected path. Trying crawl4ai setup..."
  python -c "import subprocess; subprocess.run(['crawl4ai-setup'], check=False)" 2>&1 || true
  python -c "
import subprocess, sys
try:
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
except Exception as e:
    print(f'Final playwright install attempt failed: {e}')
" 2>&1 || true
fi

log "Done. $(date +%H:%M:%S)"

# --- Ensure FORGE_WEB_TOKEN is set (auth for dashboard) ----------------------
cd "$DST"
if [ -f .env ]; then
  CURRENT_WEB_TOKEN=$(grep '^FORGE_WEB_TOKEN=' .env | cut -d= -f2- || echo "")
  if [[ -z "$CURRENT_WEB_TOKEN" ]]; then
    WEB_TOKEN=$(openssl rand -base64 18 | tr -d '=/+' | head -c 24)
    if grep -q '^FORGE_WEB_TOKEN=' .env; then
      sed -i "s|^FORGE_WEB_TOKEN=.*|FORGE_WEB_TOKEN=${WEB_TOKEN}|" .env
    else
      echo "FORGE_WEB_TOKEN=${WEB_TOKEN}" >> .env
    fi
    log "Generated FORGE_WEB_TOKEN=${WEB_TOKEN} (required for dashboard login)"
  fi
fi

# --- Rebuild & restart Forge web dashboard (sentinelhive.dev) ----------------
FORGE_WEB_PORT="${FORGE_WEB_PORT:-3000}"
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
  log "Rebuilding forge-api + forge-web containers..."
  docker compose up -d --build --no-deps api web 2>&1 | tail -5
  sleep 5
  if curl -sf "http://localhost:${FORGE_WEB_PORT}/" &>/dev/null 2>&1; then
    log "Web dashboard running on port ${FORGE_WEB_PORT}"
  else
    log "${DIM}Web dashboard may still be starting (check: docker logs forge-web)${NC}"
  fi
  # Ensure Daytona stack is running (start if down, restart if already up)
  if [ -f "$DST/docker-compose.daytona.yml" ]; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
      log "Restarting Daytona sandbox stack..."
    else
      log "Starting Daytona sandbox stack..."
    fi
    docker compose -f "$DST/docker-compose.daytona.yml" up -d 2>&1 | tail -3
  fi

  # Verify forge-api Docker DNS health (qdrant + daytona-api)
  NEED_API_RESTART=false

  if ! docker exec forge-api python -c "
import socket
socket.getaddrinfo('qdrant', 6333)
" &>/dev/null 2>&1; then
    log "forge-api cannot resolve qdrant — fixing network..."
    docker network connect forge-network forge-qdrant 2>/dev/null || true
    NEED_API_RESTART=true
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
    if ! docker exec forge-api python -c "
import socket
socket.getaddrinfo('daytona-api', 3000)
" &>/dev/null 2>&1; then
      log "forge-api cannot resolve daytona-api — fixing network..."
      docker network connect forge-network daytona-api 2>/dev/null || true
      NEED_API_RESTART=true
    fi
  fi

  if [[ "$NEED_API_RESTART" == "true" ]]; then
    docker restart forge-api 2>/dev/null || true
    sleep 5
    log "Restarted forge-api with network fix"
  fi
else
  log "${DIM}Docker not available — skipping container rebuild${NC}"
  log "${DIM}Run manually: docker compose up -d --build api web${NC}"
fi

# --- Ensure browser layer is running (host process, not Docker) ---------------
BROWSER_PORT="${BROWSER_SERVER_PORT:-3100}"
if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
  log "Browser layer already running (port ${BROWSER_PORT})"
else
  if [ -d "$DST/agents/browser" ] && [ -f "$DST/agents/browser/package.json" ]; then
    log "Starting browser layer (port ${BROWSER_PORT})..."
    fuser -k "${BROWSER_PORT}/tcp" 2>/dev/null || true
    cd "$DST/agents/browser"
    nohup npm start > /tmp/forge-browser.log 2>&1 &
    BROWSER_PID=$!
    cd "$DST"
    sleep 4
    if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
      log "Browser layer ready (PID ${BROWSER_PID}, port ${BROWSER_PORT})"
    else
      log "${DIM}Browser layer failed to start — check /tmp/forge-browser.log${NC}"
      log "${DIM}Agents will skip browser-dependent tasks (scraping, screenshots)${NC}"
    fi
  fi
fi

# Auto-run forge if arguments were passed (e.g. bash sync.sh scout --shallow)
if [[ $# -gt 0 ]]; then
  log "Running: forge $*"
  "$DST/.venv/bin/forge" "$@"
else
  log "${DIM}Now run:${NC}"
  echo ""
  echo "  source ~/forge/.venv/bin/activate && forge scout"
  echo ""
  echo "  Or:  bash sync.sh scout"
  echo ""
fi
