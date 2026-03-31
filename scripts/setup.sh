#!/usr/bin/env bash
# setup.sh -- Bootstrap Forge (30 agents)
# Works on: Linux, macOS, WSL2, Git Bash (Windows)
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info]${NC} $1"; }

log "Forge -- 30-agent autonomous hackathon swarm"

# --- Detect OS / shell environment -------------------------------------------
IS_WINDOWS=false
IS_WSL=false
IS_MACOS=false

if [[ "${OSTYPE:-}" == "msys" || "${OSTYPE:-}" == "cygwin" || \
      "${MSYSTEM:-}" == "MINGW64" || "${MSYSTEM:-}" == "MINGW32" || \
      -n "${WINDIR:-}" ]]; then
  IS_WINDOWS=true
  warn "Detected: Windows (Git Bash / MINGW)"
  info "For best experience, use WSL2: https://docs.microsoft.com/windows/wsl/install"
  echo ""
elif grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then
  IS_WSL=true
  log "Detected: WSL2"
elif [[ "$(uname)" == "Darwin" ]]; then
  IS_MACOS=true
  log "Detected: macOS"
else
  log "Detected: Linux"
fi

# --- Find Python 3.11+ -------------------------------------------------------
PYTHON_CMD=""
for cmd in python3 python3.12 python3.11 python; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "0.0")
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 ]]; then
      PYTHON_CMD="$cmd"
      break
    fi
  fi
done

if [[ -z "$PYTHON_CMD" ]]; then
  echo ""
  if $IS_WINDOWS; then
    err "Python 3.11+ not found.
  Download from https://www.python.org/downloads/windows/
  Check 'Add Python to PATH' during install, then restart Git Bash."
  elif $IS_MACOS; then
    err "Python 3.11+ not found. Run: brew install python@3.12"
  else
    err "Python 3.11+ not found. Run: sudo apt install python3.12 python3.12-venv"
  fi
fi

log "Python: $($PYTHON_CMD --version)"
PIP_CMD="$PYTHON_CMD -m pip"

# --- Docker ------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
  if $IS_WINDOWS; then
    err "Docker not installed.
  Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  Enable WSL2 backend in Docker Desktop settings."
  elif $IS_MACOS; then
    err "Docker not installed. Run: brew install --cask docker"
  else
    err "Docker not installed. See: https://docs.docker.com/engine/install/"
  fi
fi
log "Docker: $(docker --version | cut -d' ' -f3 | tr -d ',')"

# --- Node.js -----------------------------------------------------------------
if ! command -v node &>/dev/null; then
  if $IS_WINDOWS; then
    err "Node.js not installed.
  Download LTS from https://nodejs.org/
  Or: winget install OpenJS.NodeJS.LTS"
  elif $IS_MACOS; then
    err "Node.js not installed. Run: brew install node@20"
  else
    err "Node.js not installed. Run:
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs"
  fi
fi
log "Node.js: $(node --version)"

# --- ffmpeg (optional) -------------------------------------------------------
if ! command -v ffmpeg &>/dev/null; then
  if $IS_WINDOWS; then
    warn "ffmpeg not found.
  Install: winget install Gyan.FFmpeg
  Or download: https://ffmpeg.org/download.html#build-windows
  (Only needed for demo video generation)"
  elif $IS_MACOS; then
    warn "ffmpeg not found -- run: brew install ffmpeg"
  else
    warn "ffmpeg not found -- run: sudo apt install ffmpeg"
  fi
fi

# --- .env and forge.secrets --------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env created -- fill in ELECTRONHUB_API_KEY"
fi
if [ ! -f forge.secrets ]; then
  cp forge.secrets.example forge.secrets
  warn "forge.secrets created -- add your API keys (gitignored)"
fi

# --- Infrastructure directories ----------------------------------------------
log "Creating infra directories..."
mkdir -p infra/postgres/data infra/redis/data infra/qdrant/data infra/temporal infra/n8n/data infra/searxng

cat > infra/qdrant/config.yaml << 'EOCONF'
service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
log_level: INFO
EOCONF

cat > infra/temporal/dynamicconfig.yaml << 'EOCONF'
system.forceSearchAttributesCacheRefreshOnRead:
  - value: true
    constraints: {}
EOCONF

cat > infra/postgres/init.sql << 'EOSQL'
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO backbone;
\c backbone;

CREATE TABLE IF NOT EXISTS hackathons (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  platform TEXT,
  theme TEXT,
  deadline TIMESTAMPTZ,
  score INTEGER,
  status TEXT DEFAULT 'discovered',
  concept_json JSONB,
  project_url TEXT,
  submission_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  agent_id TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  input_json JSONB,
  output_json JSONB,
  error TEXT,
  iterations INTEGER DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ux_audit_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  preview_url TEXT,
  overall_score FLOAT,
  approved BOOLEAN,
  report_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
EOSQL

# --- Python dependencies -----------------------------------------------------
log "Installing Python dependencies..."
if command -v uv &>/dev/null; then
  uv pip install -e ".[dev]"
else
  $PIP_CMD install -e ".[dev]" --quiet
fi

# --- Playwright browsers -----------------------------------------------------
log "Installing Playwright (Chromium)..."
if $IS_WINDOWS; then
  # --with-deps requires apt/winget and may need elevation; install browser only
  $PYTHON_CMD -m playwright install chromium || \
    warn "Playwright browser install failed.
  Try in an elevated terminal: python -m playwright install chromium --with-deps"
else
  $PYTHON_CMD -m playwright install chromium --with-deps
fi

# --- Browser layer (Node.js) -------------------------------------------------
log "Installing browser layer..."
cd agents/browser && npm install --silent && cd ../..

# --- Docker images -----------------------------------------------------------
log "Pulling Docker images..."
docker compose -f config/docker-compose.yml pull 2>&1 | grep -E "Pull|pulled|up to date|error" || true

# --- Daytona CLI -------------------------------------------------------------
if ! command -v daytona &>/dev/null; then
  if $IS_WINDOWS && ! $IS_WSL; then
    warn "Daytona CLI: not available for native Windows Git Bash.
  Options:
    a) Use WSL2 -- run setup.sh inside WSL2 (recommended)
    b) Manual install: https://www.daytona.io/docs/installation/installation/"
  elif command -v sudo &>/dev/null; then
    log "Installing Daytona CLI..."
    curl -sf -L https://download.daytona.io/daytona/install.sh | sudo bash
  else
    warn "Daytona CLI not installed and sudo unavailable.
  Manual install: https://www.daytona.io/docs/installation/installation/"
  fi
fi

# --- Lighthouse CLI ----------------------------------------------------------
log "Installing Lighthouse CLI..."
npm install -g lighthouse 2>/dev/null || warn "Lighthouse install failed (non-critical -- performance audit will use fallback)"

# --- Crawl4AI first-run setup ------------------------------------------------
log "Setting up Crawl4AI..."
$PYTHON_CMD -c "
import asyncio, sys
async def setup():
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as _: pass
        print('[setup] Crawl4AI: OK')
    except Exception as e:
        print(f'[warn] Crawl4AI first-run: {e}', file=sys.stderr)
asyncio.run(setup())
" || warn "Crawl4AI first-run setup had errors (non-critical -- will retry on first use)"

# --- Done --------------------------------------------------------------------
echo ""
log "Setup complete!"
echo ""
info "Next steps:"
info "  1. Edit forge.secrets -- add your ELECTRONHUB_API_KEY"
if $IS_WINDOWS && ! $IS_WSL; then
  info "  2. Ensure Docker Desktop is running"
fi
info "  2. Start services: bash scripts/start.sh"
info "  3. Test: $PYTHON_CMD scripts/test_run.py --dry-run"
echo ""
if $IS_WINDOWS && ! $IS_WSL; then
  warn "Windows note: For GPU access, Daytona, and full Linux tooling,"
  warn "run Forge inside WSL2. Core pipeline works in Git Bash."
fi
