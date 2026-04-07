#!/usr/bin/env bash
# forge-deploy.sh -- One-shot deploy. Zero interaction. Handles everything.
# Usage: bash forge-deploy.sh
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[forge]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info]${NC} $1"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge -- One-Shot Deploy                   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$HOME/forge"

# ── Step 1: Detect environment ────────────────────────────────────────────────
IS_WSL=false
ON_NTFS=false
if grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then
  IS_WSL=true
  if [[ "$SCRIPT_DIR" == /mnt/* ]]; then
    ON_NTFS=true
  fi
fi

# ── Step 2: Copy to native Linux filesystem if on NTFS ───────────────────────
if [[ "$ON_NTFS" == "true" ]]; then
  log "WSL2 + NTFS detected — copying to native Linux filesystem..."
  log "Source: $SCRIPT_DIR → Target: $DEPLOY_DIR"

  rm -rf "$DEPLOY_DIR" 2>/dev/null || true
  cp -r "$SCRIPT_DIR" "$DEPLOY_DIR"

  # Re-exec from native filesystem
  exec bash "$DEPLOY_DIR/forge-deploy.sh"
fi

# From here we're guaranteed to be on a native filesystem
cd "$SCRIPT_DIR"
log "Working directory: $(pwd)"

# ── Step 3: Install Docker if missing ─────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  log "Docker not found — installing..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

if ! docker info &>/dev/null 2>&1; then
  if sudo docker info &>/dev/null 2>&1; then
    sudo usermod -aG docker "$USER"
    warn "Docker group added. Re-running with new group..."
    exec sg docker -c "bash $(pwd)/forge-deploy.sh"
  else
    sudo service docker start 2>/dev/null || true
    sleep 2
    docker info &>/dev/null 2>&1 || err "Docker is not running. Start Docker and re-run."
  fi
fi

log "Docker: $(docker --version | head -1)"

# ── Step 4: Strip CRLF from all config files ─────────────────────────────────
log "Fixing line endings..."
find . -maxdepth 1 \( -name "*.env*" -o -name "*.secrets*" -o -name "*.example" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find scripts config -type f \( -name "*.sh" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sql" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true

# ── Step 5: Generate .env with real passwords ─────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
fi
sed -i 's/\r$//' .env

gen_pw() { openssl rand -base64 18 | tr -d '=/+' | head -c 24; }

CURRENT_PG_PASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2- || echo "")
if [[ "$CURRENT_PG_PASS" == "change_this_strong_password" || "$CURRENT_PG_PASS" == "change_me" || -z "$CURRENT_PG_PASS" ]]; then
  PG_PASS=$(gen_pw)
  REDIS_PASS=$(gen_pw)
  QDRANT_KEY=$(gen_pw)
  N8N_PASS=$(gen_pw)

  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" .env
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://backbone:${PG_PASS}@localhost:5432/backbone|" .env
  sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASS}|" .env
  sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:${REDIS_PASS}@localhost:6379|" .env
  sed -i "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=${QDRANT_KEY}|" .env
  sed -i "s|^N8N_PASSWORD=.*|N8N_PASSWORD=${N8N_PASS}|" .env
  log "Generated secure passwords in .env"
fi

# Generate FORGE_WEB_TOKEN if not set (requires login to access dashboard)
CURRENT_WEB_TOKEN=$(grep '^FORGE_WEB_TOKEN=' .env | cut -d= -f2- || echo "")
if [[ -z "$CURRENT_WEB_TOKEN" ]]; then
  WEB_TOKEN=$(gen_pw)
  if grep -q '^FORGE_WEB_TOKEN=' .env; then
    sed -i "s|^FORGE_WEB_TOKEN=.*|FORGE_WEB_TOKEN=${WEB_TOKEN}|" .env
  else
    echo "FORGE_WEB_TOKEN=${WEB_TOKEN}" >> .env
  fi
  log "Generated FORGE_WEB_TOKEN (required for dashboard login)"
  info "Dashboard token: ${WEB_TOKEN}"
  info "Login at: https://your-domain/?token=${WEB_TOKEN}"
fi

# ── Step 6: Ensure forge.py exists (entry point for pip install) ──────────────
if [ -f forge ] && [ ! -f forge.py ]; then
  cp forge forge.py
  log "Created forge.py from forge CLI script"
fi

# ── Step 7: Create fresh Python venv ──────────────────────────────────────────
log "Setting up Python virtual environment..."
rm -rf .venv ~/.forge-venv 2>/dev/null || true

# Ensure python3-venv is available
if command -v apt-get &>/dev/null; then
  sudo apt-get install -y python3-venv python3-full -qq 2>/dev/null || true
fi

PYTHON_CMD=""
for cmd in python3 python3.12 python3.11; do
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
[[ -n "$PYTHON_CMD" ]] || err "Python 3.11+ not found. Install: sudo apt install python3.12 python3.12-venv"

$PYTHON_CMD -m venv .venv || err "Failed to create venv. Run: sudo apt install python3-venv python3-full"
source .venv/bin/activate
pip install --upgrade pip --quiet

log "Python: $($PYTHON_CMD --version) | pip: $(pip --version | cut -d' ' -f2)"

# ── Step 8: Install ALL Python dependencies ───────────────────────────────────
log "Installing core dependencies (1-3 min)..."
pip install -e ".[dev,stitch,daytona]" 2>&1 | tail -3

log "Installing crawl4ai..."
pip install "crawl4ai>=0.4.0" 2>&1 | tail -3 || warn "crawl4ai install failed — lightweight HTTP fallback will be used"

log "Installing sentence-transformers (large download, may take a few minutes)..."
pip install "sentence-transformers>=3.0.0" 2>&1 | tail -3 || warn "sentence-transformers failed — BM25 keyword ranking will be used"

# ── Step 9: Install Playwright browsers ───────────────────────────────────────
log "Installing Playwright Chromium..."
playwright install chromium --with-deps 2>&1 | tail -5 || warn "Playwright install had issues"

# ── Step 10: Install browser layer (Node.js) ─────────────────────────────────
if [ -d agents/browser ] && [ -f agents/browser/package.json ]; then
  log "Installing browser layer..."
  cd agents/browser && npm install --silent 2>/dev/null && cd ../..
fi

# ── Step 11: Create infrastructure config files ──────────────────────────────
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

# ── Step 12: Start Docker services ────────────────────────────────────────────
log "Starting Docker services..."
set -a; source .env 2>/dev/null || true; set +a
docker compose down -v 2>/dev/null || true
docker compose up -d

# --- Daytona sandbox infrastructure -----------------------------------------
if [ -f docker-compose.daytona.yml ]; then
  log "Starting Daytona sandbox infrastructure..."
  docker compose -f docker-compose.daytona.yml up -d 2>&1 | tail -5 || warn "Daytona stack failed to start"
fi

log "Waiting for PostgreSQL..."
for i in $(seq 1 60); do
  docker exec forge-postgres pg_isready -U "${POSTGRES_USER:-backbone}" &>/dev/null && break
  sleep 1
done
log "PostgreSQL ready"

log "Waiting for Redis..."
for i in $(seq 1 30); do
  docker exec forge-redis redis-cli -a "${REDIS_PASSWORD:-changeme}" ping &>/dev/null && break
  sleep 1
done
log "Redis ready"

log "Waiting for Qdrant..."
for i in $(seq 1 30); do
  curl -sf http://localhost:6333/readyz &>/dev/null && break
  sleep 2
done
log "Qdrant ready"

# ── Step 13: Initialize Qdrant collections ────────────────────────────────────
log "Initializing Qdrant collections..."
python -c "
import asyncio, sys
sys.path.insert(0, '.')
async def main():
    from agents.python.infra.memory_keeper import ensure_collections
    await ensure_collections()
    print('Collections ready')
asyncio.run(main())
" 2>&1 || warn "Qdrant collection init failed (may already exist)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge is running!                          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""
info "Project:  $(pwd)"
info "Activate: source $(pwd)/.venv/bin/activate"
echo ""
# ── Step 14: Verify Forge web dashboard (runs inside Docker) ─────────────────
# The web dashboard runs as the forge-web Docker container (started in Step 12).
FORGE_WEB_PORT="${FORGE_WEB_PORT:-3000}"
WAITED=0
until curl -sf "http://localhost:${FORGE_WEB_PORT}/" &>/dev/null 2>&1; do
  sleep 2; WAITED=$((WAITED+2))
  [[ $WAITED -ge 30 ]] && { warn "Web dashboard health check timed out — check: docker logs forge-web"; break; }
done
[[ $WAITED -lt 30 ]] && log "Web dashboard ready (port ${FORGE_WEB_PORT})"

# --- Daytona health check ----------------------------------------------------
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
  WAITED=0
  until curl -sf http://localhost:3986/health &>/dev/null 2>&1; do
    sleep 2; WAITED=$((WAITED+2))
    [[ $WAITED -ge 60 ]] && { warn "Daytona API health check timed out"; break; }
  done
  [[ $WAITED -lt 60 ]] && log "Daytona API ready (http://localhost:3986)"
fi

info "Next:"
info "  1. Edit .env — add ELECTRONHUB_API_KEY"
info "  2. source .venv/bin/activate"
info "  3. forge scout --dry-run"
info "  4. forge test"
DAYTONA_KEY="${DAYTONA_API_KEY:-}"
if [[ -z "$DAYTONA_KEY" ]] && docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
  echo ""
  info "Daytona sandbox setup:"
  info "  Open http://localhost:3986 (login: dev@daytona.io / password)"
  info "  Generate API key → set DAYTONA_API_KEY in .env"
fi
echo ""
