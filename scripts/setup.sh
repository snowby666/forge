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

# --- .env -------------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env created -- fill in ELECTRONHUB_API_KEY and other keys"
fi
# Strip Windows CRLF from config files (NTFS /mnt/c/ + git autocrlf cause \r\n)
sed -i 's/\r$//' .env 2>/dev/null || true

# --- Infrastructure config files (inside config/ -- no separate infra/ dir) ----
# Data volumes are Docker-managed named volumes (see docker-compose.yml).
# Only config files needed: init.sql and dynamicconfig.yaml, stored in config/.
log "Creating infrastructure config files..."

if [ ! -f config/postgres-init.sql ]; then
cat > config/postgres-init.sql << 'EOSQL'
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
  log "Created config/postgres-init.sql"
fi

if [ ! -f config/temporal-dynamicconfig.yaml ]; then
cat > config/temporal-dynamicconfig.yaml << 'EOCONF'
system.forceSearchAttributesCacheRefreshOnRead:
  - value: true
    constraints: {}
EOCONF
  log "Created config/temporal-dynamicconfig.yaml"
fi

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
# --- Virtual environment location -------------------------------------------
# CRITICAL: On WSL2, the project may live on a mounted Windows drive (/mnt/c/...).
# NTFS mounts don't support Unix permissions or symlinks that Python venv needs.
# Solution: always create the venv in the WSL2 native filesystem (~/.forge-venv),
# then symlink .venv back to it so relative paths still work.

FORGE_DIR="$(pwd)"
VENV_DIR=".venv"
NATIVE_VENV_DIR="$HOME/.forge-venv"

# Detect if we're on a Windows NTFS mount (WSL2 running forge from /mnt/...)
ON_NTFS=false
if [[ "$OS_TYPE" == "wsl" ]] && [[ "$FORGE_DIR" == /mnt/* ]]; then
  ON_NTFS=true
fi

# On Ubuntu/Debian ensure python3-venv is installed before attempting creation
if [[ "$OS_TYPE" == "linux" || "$OS_TYPE" == "wsl" ]]; then
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y python3-venv python3-full -qq 2>/dev/null || true
  fi
fi

if [[ "$ON_NTFS" == "true" ]]; then
  # Use native WSL2 filesystem for the venv to avoid NTFS permission errors
  if [ ! -d "$NATIVE_VENV_DIR" ]; then
    log "Creating virtual environment in WSL2 native filesystem (~/.forge-venv)..."
    log "(Project is on NTFS /mnt/c/ -- venv must be on native ext4 filesystem)"
    $PYTHON_CMD -m venv "$NATIVE_VENV_DIR"       || err "Failed to create venv at $NATIVE_VENV_DIR.
  Run: sudo apt install python3.12-venv python3-full && bash scripts/setup.sh"
    log "Virtual environment created at ~/.forge-venv"
  else
    log "Virtual environment already exists (~/.forge-venv)"
  fi
  # Create/update .venv symlink in project dir pointing to native venv
  rm -f "$VENV_DIR" 2>/dev/null || true
  ln -sfn "$NATIVE_VENV_DIR" "$VENV_DIR" 2>/dev/null     || { rm -rf "$VENV_DIR"; ln -s "$NATIVE_VENV_DIR" "$VENV_DIR"; }
  log "Symlinked .venv -> ~/.forge-venv"
else
  # Normal filesystem (Linux, macOS, native WSL2 path): create venv in place
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment (.venv)..."
    $PYTHON_CMD -m venv "$VENV_DIR"       || err "Failed to create venv.
  Run: sudo apt install python3.12-venv python3-full && bash scripts/setup.sh"
    log "Virtual environment created at .venv/"
  else
    log "Virtual environment already exists (.venv/)"
  fi
fi

# Activate venv and update PYTHON_CMD / PIP_CMD to point inside it
# CRITICAL: On NTFS mounts, use the native venv path directly for pip operations.
# The .venv symlink lives on NTFS and pip's temp-file operations fail through it.
if [[ "$OS_TYPE" == "windows" ]]; then
  VENV_PYTHON="$VENV_DIR/Scripts/python"
  VENV_PIP="$VENV_DIR/Scripts/pip"
elif [[ "$ON_NTFS" == "true" ]]; then
  VENV_PYTHON="$NATIVE_VENV_DIR/bin/python"
  VENV_PIP="$NATIVE_VENV_DIR/bin/pip"
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
# On NTFS mounts, editable installs (-e) fail because pip/hatchling writes
# build metadata (.egg-info) to the project dir on NTFS. Use regular install.
if [[ "$ON_NTFS" == "true" ]]; then
  PIP_EDIT_FLAG=""
  info "NTFS detected -- using non-editable install (pip install . instead of -e .)"
else
  PIP_EDIT_FLAG="-e"
fi

log "Installing Python core dependencies (this takes 1-3 minutes)..."
if command -v uv &>/dev/null; then
  uv pip install --python "$VENV_PYTHON" $PIP_EDIT_FLAG ".[dev,stitch,daytona]" \
    || { uv pip install --python "$VENV_PYTHON" $PIP_EDIT_FLAG "."; uv pip install --python "$VENV_PYTHON" pytest pytest-asyncio; }
else
  $PIP_CMD install $PIP_EDIT_FLAG ".[dev,stitch,daytona]" 2>&1 || {
    warn "Full install failed -- trying core only"
    $PIP_CMD install $PIP_EDIT_FLAG "." 2>&1 || {
      err "pip install failed. Check errors above.
  If on WSL2/NTFS, try cloning the repo to your Linux home directory:
    cp -r /mnt/c/.../forge ~/forge && cd ~/forge && bash scripts/setup.sh"
    }
    $PIP_CMD install pytest pytest-asyncio || true
  }
fi
log "Core dependencies installed"

# --- Optional: crawl4ai (JS rendering, adaptive crawl) ----------------------
log "Installing crawl4ai..."
$PIP_CMD install "crawl4ai>=0.4.0" 2>&1 | tail -5 \
  || warn "crawl4ai install failed -- web crawling will use the lightweight HTTP fallback"

# --- Optional: sentence-transformers (semantic reranking) -------------------
# This pulls in PyTorch (~2GB) -- can take 5-10 min on slow connections
log "Installing sentence-transformers (large download, may take a few minutes)..."
$PIP_CMD install "sentence-transformers>=3.0.0" 2>&1 | tail -5 \
  || warn "sentence-transformers install failed -- BM25 keyword ranking will be used instead"

# --- Optional: PyTorch (CPU build) ------------------------------------------
if ! $PYTHON_CMD -c "import torch" &>/dev/null 2>&1; then
  log "Installing PyTorch (CPU build -- large download)..."
  $PIP_CMD install torch --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -5 \
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

# --- Daytona SDK (sandbox build environments) --------------------------------
log "Installing Daytona SDK..."
$PIP_CMD install "daytona-sdk>=0.100.0" 2>&1 | tail -3 \
  || warn "daytona-sdk install failed — build agents (frontend/backend engineer) will not work"

# --- Docker images -----------------------------------------------------------
log "Pulling Docker images..."
set -a; source .env 2>/dev/null || true; set +a
docker compose pull 2>&1 \
  | grep -E "^(Pulling|pulled|up to date|Error)" \
  || true

# --- Daytona self-hosted (sandbox infrastructure) ----------------------------
if [ -f docker-compose.daytona.yml ]; then
  log "Pulling Daytona sandbox infrastructure images..."
  docker compose -f docker-compose.daytona.yml pull 2>&1 \
    | grep -E "^(Pulling|pulled|up to date|Error)" \
    || true
  info "Daytona self-hosted stack available. Start with:"
  info "  docker compose -f docker-compose.daytona.yml up -d"
  info "  Then open http://localhost:3986 (login: dev@daytona.io / password)"
  info "  Generate an API key and set DAYTONA_API_KEY in .env"
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
elif [[ "$ON_NTFS" == "true" ]]; then
  info "  source ~/.forge-venv/bin/activate"
  info "  (venv lives in WSL2 native filesystem due to NTFS /mnt/c/ limitations)"
else
  info "  source .venv/bin/activate"
fi
echo ""
info "Next steps:"
if [[ "$OS_TYPE" == "windows" ]]; then
  info "  1. source .venv/Scripts/activate"
  info "  2. Edit .env -- add your ELECTRONHUB_API_KEY"
  info "  3. Ensure Docker Desktop is running"
  info "  4. bash scripts/start.sh"
  info "  5. python scripts/test_run.py --dry-run"
  echo ""
  warn "Windows: For GPU access and Daytona sandboxes, use WSL2."
else
  info "  1. source .venv/bin/activate"
  info "  2. Edit .env -- add your ELECTRONHUB_API_KEY"
  info "  3. bash scripts/start.sh"
  info "  4. python scripts/test_run.py --dry-run"
fi
echo ""
