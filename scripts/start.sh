#!/usr/bin/env bash
# start.sh -- Start all Forge infrastructure services
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[start]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info]${NC} $1"; }

# --- Activate venv if not already active ------------------------------------
# .venv may be a symlink to ~/.forge-venv when project lives on NTFS (/mnt/c/)
if [[ "${OSTYPE:-}" == "msys" || "${MSYSTEM:-}" == "MINGW64" || -n "${WINDIR:-}" ]]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
  VENV_PYTHON=".venv/Scripts/python"
else
  VENV_ACTIVATE=".venv/bin/activate"
  VENV_PYTHON=".venv/bin/python"
fi

# Fallback: check native WSL2 location directly (in case .venv symlink is missing)
if [ ! -f "$VENV_ACTIVATE" ] && [ -f "$HOME/.forge-venv/bin/activate" ]; then
  VENV_ACTIVATE="$HOME/.forge-venv/bin/activate"
  VENV_PYTHON="$HOME/.forge-venv/bin/python"
fi

if [ -f "$VENV_ACTIVATE" ]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
  log "Virtual environment activated"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  log "Using active virtual environment: ${VIRTUAL_ENV}"
else
  # No .venv yet -- try to find a working python (common on fresh Git Bash installs)
  FOUND_PYTHON=""
  for cmd in python python3 python3.12 python3.11; do
    if command -v "$cmd" &>/dev/null; then
      VER=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "0.0")
      MAJOR=$(echo "$VER" | cut -d. -f1)
      MINOR=$(echo "$VER" | cut -d. -f2)
      if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 ]]; then
        FOUND_PYTHON="$cmd"
        break
      fi
    fi
  done
  if [[ -n "$FOUND_PYTHON" ]]; then
    warn "No .venv found -- using system Python ($FOUND_PYTHON). Run scripts/setup.sh for a proper venv."
    VENV_PYTHON="$FOUND_PYTHON"
  else
    warn "No .venv found. Run scripts/setup.sh first."
    warn "Or: source .venv/bin/activate  (Linux/macOS)"
    warn "Or: source .venv/Scripts/activate  (Windows Git Bash)"
    VENV_PYTHON="python"
  fi
fi

PYTHON_CMD="${VENV_PYTHON:-python}"

# --- Load .env ---------------------------------------------------------------
[[ -f .env ]] || err ".env not found -- run scripts/setup.sh first"
# Strip Windows CRLF line endings (files on NTFS /mnt/c/ get \r\n from Windows editors/git)
sed -i 's/\r$//' .env 2>/dev/null || true
set -a; source .env; set +a

# --- Validate .env has real passwords ----------------------------------------
ENV_OK=true
for var in POSTGRES_PASSWORD REDIS_PASSWORD QDRANT_API_KEY; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == "change_me" || "$val" == "change_this_strong_password" || "$val" == "change_this_strong_key" ]]; then
    warn "$var is not set or still uses a placeholder. Edit .env."
    ENV_OK=false
  fi
done
[[ "$ENV_OK" == "true" ]] || err "Fix the above .env values, then re-run start.sh."

# Ensure FORGE_WEB_TOKEN is set (protects dashboard from unauthenticated access)
CURRENT_WEB_TOKEN="${FORGE_WEB_TOKEN:-}"
if [[ -z "$CURRENT_WEB_TOKEN" ]]; then
  gen_pw() { openssl rand -base64 18 | tr -d '=/+' | head -c 24; }
  WEB_TOKEN=$(gen_pw)
  if grep -q '^FORGE_WEB_TOKEN=' .env; then
    sed -i "s|^FORGE_WEB_TOKEN=.*|FORGE_WEB_TOKEN=${WEB_TOKEN}|" .env
  else
    echo "FORGE_WEB_TOKEN=${WEB_TOKEN}" >> .env
  fi
  export FORGE_WEB_TOKEN="$WEB_TOKEN"
  log "Generated FORGE_WEB_TOKEN=${WEB_TOKEN}"
  info "Dashboard login: https://sentinelhive.dev/?token=${WEB_TOKEN}"
fi

# Force UTF-8 on Windows to prevent UnicodeDecodeError with non-ASCII chars
export PYTHONUTF8=1

log "Starting Docker services..."
docker compose up -d

log "Waiting for services..."
MAX_WAIT=60
WAITED=0

until docker exec forge-postgres pg_isready -U "${POSTGRES_USER:-backbone}" &>/dev/null 2>&1; do
  sleep 1; WAITED=$((WAITED+1))
  [[ $WAITED -ge $MAX_WAIT ]] && err "PostgreSQL did not start in ${MAX_WAIT}s"
done
log "PostgreSQL ready"
WAITED=0

until docker exec forge-redis redis-cli -a "${REDIS_PASSWORD}" ping &>/dev/null 2>&1; do
  sleep 1; WAITED=$((WAITED+1))
  [[ $WAITED -ge $MAX_WAIT ]] && { warn "Redis health check timed out -- continuing"; break; }
done
log "Redis ready"
WAITED=0

until curl -sf http://localhost:6333/readyz &>/dev/null 2>&1; do
  sleep 2; WAITED=$((WAITED+2))
  [[ $WAITED -ge $MAX_WAIT ]] && { warn "Qdrant health check timed out -- continuing"; break; }
done
log "Qdrant ready"

log "Initializing Qdrant collections..."
$PYTHON_CMD -c "
import asyncio, sys
sys.path.insert(0, '.')
async def main():
    from agents.python.infra.memory_keeper import ensure_collections
    await ensure_collections()
    print('Collections ready')
asyncio.run(main())
" || warn "Qdrant collection init failed (may already exist)"

# Ensure Playwright Chromium is installed (Crawl4AI needs it)
log "Installing Playwright system deps..."
$PYTHON_CMD -m playwright install-deps chromium 2>&1 | tail -3 || true
log "Downloading Playwright Chromium browser..."
$PYTHON_CMD -m playwright install chromium 2>&1
if [ $? -ne 0 ]; then
  log "Playwright install failed, trying with sudo..."
  sudo "$PYTHON_CMD" -m playwright install chromium 2>&1 || true
fi
CHROMIUM_BIN=$($PYTHON_CMD -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()" 2>/dev/null || echo "NOT_FOUND")
if [[ "$CHROMIUM_BIN" != "NOT_FOUND" && -f "$CHROMIUM_BIN" ]]; then
  log "Playwright Chromium OK: $CHROMIUM_BIN"
else
  warn "Chromium binary not found — Crawl4AI scraping will use HTTP fallback"
fi

log "Starting browser layer..."
cd agents/browser && npm start &
BROWSER_PID=$!
cd ../..
sleep 3

BROWSER_PORT="${BROWSER_SERVER_PORT:-3100}"
if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
  log "Browser layer ready (port ${BROWSER_PORT})"
else
  warn "Browser layer health check failed (PID ${BROWSER_PID})"
fi

# --- Forge web dashboard (sentinelhive.dev) ----------------------------------
# The web dashboard runs as the forge-web Docker container (see docker-compose.yml).
# 'docker compose up -d' above already started it; verify it's healthy.
FORGE_WEB_PORT="${FORGE_WEB_PORT:-3000}"
WAITED=0
until curl -sf "http://localhost:${FORGE_WEB_PORT}/" &>/dev/null 2>&1; do
  sleep 2; WAITED=$((WAITED+2))
  [[ $WAITED -ge 30 ]] && { warn "Web dashboard health check timed out — check: docker logs forge-web"; break; }
done
[[ $WAITED -lt 30 ]] && log "Web dashboard ready (port ${FORGE_WEB_PORT})"

echo ""
log "All services running:"
info "  Qdrant:    http://localhost:6333"
info "  Browser:   http://localhost:${BROWSER_PORT}"
info "  n8n:       http://localhost:5678"
info "  Temporal:  http://localhost:8080"
info "  SearXNG:   http://localhost:8081"
info "  Dashboard: http://localhost:${FORGE_WEB_PORT}  (sentinelhive.dev)"
echo ""
log "Run: python scripts/test_run.py --dry-run"
