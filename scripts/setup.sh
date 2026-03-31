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

# Force UTF-8 everywhere — prevents UnicodeDecodeError on Windows with non-ASCII files
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# --- Detect OS / shell environment -------------------------------------------
OS_TYPE="linux"

if [[ "${OSTYPE:-}" == "msys" || "${OSTYPE:-}" == "cygwin" ||
      "${MSYSTEM:-}" == "MINGW64" || "${MSYSTEM:-}" == "MINGW32" ||
      -n "${WINDIR:-}" ]]; then
  OS_TYPE="windows"
  warn "Detected: Windows (Git Bash / MINGW)"
  info "For best experience, use WSL2: https://docs.microsoft.com/windows/wsl/install"
  echo ""
elif grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then
  OS_TYPE="wsl"
  log "Detected: WSL2"
elif [[ "$(uname)" == "Darwin" ]]; then
  OS_TYPE="macos"
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
  if [[ "$OS_TYPE" == "windows" ]]; then
    err "Python 3.11+ not found.
  Download from https://www.python.org/downloads/windows/
  Check 'Add Python to PATH' during install, then restart Git Bash."
  elif [[ "$OS_TYPE" == "macos" ]]; then
    err "Python 3.11+ not found. Run: brew install python@3.12"
  else
    err "Python 3.11+ not found. Run: sudo apt install python3.12 python3.12-venv"
  fi
fi

log "Python: $($PYTHON_CMD --version)"

# --- Docker ------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
  if [[ "$OS_TYPE" == "windows" ]]; then
    err "Docker not installed.
  Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  Enable WSL2 backend in Docker Desktop settings."
  elif [[ "$OS_TYPE" == "macos" ]]; then
    err "Docker not installed. Run: brew install --cask docker"
  else
    err "Docker not installed. See: https://docs.docker.com/engine/install/"
  fi
fi
DOCKER_VER=$(docker --version 2>/dev/null | head -1 | grep -oP 'Docker version \K[^,]+' || echo "installed")
log "Docker: ${DOCKER_VER}"

# --- Node.js -----------------------------------------------------------------
if ! command -v node &>/dev/null; then
  if [[ "$OS_TYPE" == "windows" ]]; then
    err "Node.js not installed. Download LTS from https://nodejs.org/
  Or: winget install OpenJS.NodeJS.LTS"
  elif [[ "$OS_TYPE" == "macos" ]]; then
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
  if [[ "$OS_TYPE" == "windows" ]]; then
    warn "ffmpeg not found (optional -- only needed for demo video generation).
  Install: winget install Gyan.FFmpeg"
  elif [[ "$OS_TYPE" == "macos" ]]; then
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
mkdir -p infra/postgres/data infra/redis/data infra/qdrant/data \
         infra/temporal infra/n8n/data infra/searxng

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
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
  platform TEXT, theme TEXT, deadline TIMESTAMPTZ, score INTEGER,
  status TEXT DEFAULT 'discovered', concept_json JSONB,
  project_url TEXT, submission_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  agent_id TEXT NOT NULL, status TEXT DEFAULT 'pending',
  input_json JSONB, output_json JSONB, error TEXT,
  iterations INTEGER DEFAULT 0, started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ux_audit_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  preview_url TEXT, overall_score FLOAT, approved BOOLEAN,
  report_json JSONB, created_at TIMESTAMPTZ DEFAULT NOW()
);
EOSQL

# --- Python version warning for 3.13+ ----------------------------------------
PY_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")
PY_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
if [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -ge 13 ]]; then
  warn "Python 3.${PY_MINOR} detected. Some wheels (torch, temporalio, daytona-sdk)
  may not have pre-built binaries for Python 3.${PY_MINOR} yet.
  Forge core will work. For maximum compatibility use Python 3.11 or 3.12."
fi

# --- Virtual environment -----------------------------------------------------
# Ubuntu 24.04+ (PEP 668) blocks system-wide pip installs.
# All other Linux distros benefit too. Always use a venv.
VENV_DIR=".venv"

# On Ubuntu/Debian, python3-venv is a separate package that must be installed
# BEFORE attempting venv creation — the venv module may exist but ensurepip fails
# without python3-full / python3-venv. Install proactively, not just as a fallback.
if [[ "$OS_TYPE" == "linux" || "$OS_TYPE" == "wsl" ]]; then
  if command -v apt-get &>/dev/null; then
    # Check if venv can actually bootstrap pip (not just if the module exists)
    if ! $PYTHON_CMD -m venv --without-pip /tmp/forge-venv-test &>/dev/null 2>&1 ||        [ ! -f /tmp/forge-venv-test/bin/python ]; then
      log "Installing python3-venv and python3-full..."
      sudo apt-get install -y python3-venv python3-full 2>/dev/null         || warn "apt-get failed -- will try anyway"
    fi
    rm -rf /tmp/forge-venv-test 2>/dev/null || true
    # Always ensure python3-venv is present on Debian/Ubuntu to avoid ensurepip failures
    sudo apt-get install -y python3-venv python3-full --no-upgrade -qq 2>/dev/null || true
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  log "Creating virtual environment (.venv)..."
  $PYTHON_CMD -m venv "$VENV_DIR"     || $PYTHON_CMD -m venv --without-pip "$VENV_DIR"     || err "Failed to create venv.
  Run manually: sudo apt install python3.12-venv python3-full
  Then re-run: bash scripts/setup.sh"
  log "Virtual environment created at .venv/"
else
  log "Virtual environment already exists (.venv/)"
fi

# Activate venv and update PYTHON_CMD / PIP_CMD to point inside it
if [[ "$OS_TYPE" == "windows" ]]; then
  VENV_PYTHON="$VENV_DIR/Scripts/python"
  VENV_PIP="$VENV_DIR/Scripts/pip"
else
  VENV_PYTHON="$VENV_DIR/bin/python"
  VENV_PIP="$VENV_DIR/bin/pip"
fi
PYTHON_CMD="$VENV_PYTHON"
PIP_CMD="$VENV_PYTHON -m pip"

# Upgrade pip inside venv (no PEP 668 restriction inside a venv)
$PIP_CMD install --upgrade pip --quiet 2>/dev/null || true
log "pip: $($PIP_CMD --version | cut -d' ' -f2)"
# Persist UTF-8 setting for all python calls in this session
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# --- Python core dependencies ------------------------------------------------
log "Installing Python core dependencies..."
if command -v uv &>/dev/null; then
  uv pip install --python "$VENV_PYTHON" -e ".[dev]" \
    || { uv pip install --python "$VENV_PYTHON" -e "."; uv pip install --python "$VENV_PYTHON" pytest pytest-asyncio; }
else
  $PIP_CMD install -e ".[dev]" --quiet 2>&1 | grep -v "^WARNING\|^NOTICE\|^notice" || {
    warn "Full install failed -- trying core only"
    $PIP_CMD install -e "." --quiet 2>&1 | grep -v "^WARNING\|^NOTICE\|^notice"
    $PIP_CMD install pytest pytest-asyncio --quiet
  }
fi
log "Core dependencies installed"

# --- Optional: crawl4ai (JS rendering, adaptive crawl) ----------------------
log "Installing crawl4ai..."
$PIP_CMD install "crawl4ai>=0.4.0" --quiet 2>/dev/null \
  || warn "crawl4ai install failed -- web crawling will use the lightweight HTTP fallback"

# --- Optional: sentence-transformers (semantic reranking) -------------------
log "Installing sentence-transformers..."
$PIP_CMD install "sentence-transformers>=3.0.0" --quiet 2>/dev/null \
  || warn "sentence-transformers install failed -- BM25 keyword ranking will be used instead"

# --- Optional: PyTorch (CPU build) ------------------------------------------
if ! $PYTHON_CMD -c "import torch" &>/dev/null 2>&1; then
  log "Installing PyTorch (CPU build)..."
  $PIP_CMD install torch --index-url https://download.pytorch.org/whl/cpu --quiet 2>/dev/null \
    || warn "PyTorch CPU install failed.
  GPU (CUDA 12.x): .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu121
  CPU only:        .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu"
fi

# --- Playwright browsers -----------------------------------------------------
log "Installing Playwright (Chromium)..."
if [[ "$OS_TYPE" == "windows" ]]; then
  $PYTHON_CMD -m playwright install chromium \
    || warn "Playwright install had errors. Try: .venv/Scripts/python -m playwright install chromium --with-deps"
else
  $PYTHON_CMD -m playwright install chromium --with-deps
fi

# --- Browser layer (Node.js) -------------------------------------------------
log "Installing browser layer..."
cd agents/browser && npm install --silent && cd ../..

# --- Docker images -----------------------------------------------------------
log "Pulling Docker images..."
# Load .env so docker-compose variable substitution works
set -a; source .env 2>/dev/null || true; set +a
docker compose -f config/docker-compose.yml pull 2>&1 \
  | grep -E "^(Pulling|pulled|up to date|Error)" \
  || true

# --- Daytona CLI -------------------------------------------------------------
if ! command -v daytona &>/dev/null; then
  if [[ "$OS_TYPE" == "windows" ]]; then
    warn "Daytona CLI: not available for native Windows Git Bash.
  Use WSL2 or install manually: https://www.daytona.io/docs/installation/installation/"
  elif command -v sudo &>/dev/null; then
    log "Installing Daytona CLI..."
    curl -sf -L https://download.daytona.io/daytona/install.sh | sudo bash
  else
    warn "Daytona CLI: sudo not available. Manual install: https://www.daytona.io/docs/installation/installation/"
  fi
fi

# --- Lighthouse CLI ----------------------------------------------------------
log "Installing Lighthouse CLI..."
npm install -g lighthouse 2>/dev/null \
  || warn "Lighthouse install failed (non-critical -- performance audit will use fallback)"

# --- Crawl4AI first-run ------------------------------------------------------
log "Verifying Crawl4AI..."
$PYTHON_CMD -c "
import asyncio, sys
async def s():
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as _: pass
        print('[setup] Crawl4AI: OK')
    except ImportError:
        print('[warn] Crawl4AI not installed -- using lightweight HTTP fallback', file=sys.stderr)
    except Exception as e:
        print(f'[warn] Crawl4AI: {e}', file=sys.stderr)
asyncio.run(s())
" 2>&1 || true

# --- Activate hint -----------------------------------------------------------
echo ""
log "Setup complete!"
echo ""
info "IMPORTANT: Activate the virtual environment before running Forge:"
if [[ "$OS_TYPE" == "windows" ]]; then
  info "  source .venv/Scripts/activate   (Git Bash)"
  info "  .venv\\Scripts\\activate          (cmd / PowerShell)"
else
  info "  source .venv/bin/activate"
fi
echo ""
info "Next steps:"
if [[ "$OS_TYPE" == "windows" ]]; then
  info "  1. source .venv/Scripts/activate"
  info "  2. Edit forge.secrets -- add your ELECTRONHUB_API_KEY"
  info "  3. Ensure Docker Desktop is running"
  info "  4. bash scripts/start.sh"
  info "  5. python scripts/test_run.py --dry-run"
  echo ""
  warn "Windows: For GPU access, Daytona, and full Linux tooling, use WSL2."
else
  info "  1. source .venv/bin/activate"
  info "  2. Edit forge.secrets -- add your ELECTRONHUB_API_KEY"
  info "  3. bash scripts/start.sh"
  info "  4. python scripts/test_run.py --dry-run"
fi
echo ""
