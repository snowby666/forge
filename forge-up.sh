#!/usr/bin/env bash
# forge-up.sh — Single entry point to start ALL Forge services.
#
# First run:  installs Python venv, pip deps, Node deps, Docker services, everything.
# Later runs: skips installs, just starts all services and verifies health.
#
# Usage:
#   bash forge-up.sh              # start everything
#   bash forge-up.sh --clean      # nuke Docker volumes and rebuild from scratch
#   bash forge-up.sh --rebuild    # rebuild Docker images (after code changes)
#   bash forge-up.sh scout        # start everything, then run 'forge scout'
#
set -euo pipefail

# ── Colors & logging ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
log()  { echo -e "${GREEN}[forge]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info]${NC}  $1"; }
step() { echo -e "\n${BOLD}── $1 ──${NC}"; }

# ── Parse flags ──────────────────────────────────────────────────────────────
DO_CLEAN=false; DO_REBUILD=false; FORGE_CMD=""
for arg in "$@"; do
  case "$arg" in
    --clean)   DO_CLEAN=true ;;
    --rebuild) DO_REBUILD=true ;;
    -*)        ;; # ignore unknown flags
    *)         FORGE_CMD="${FORGE_CMD:+$FORGE_CMD }$arg" ;;
  esac
done

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge — Unified Startup                            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Detect environment ───────────────────────────────────────────────────────
IS_WSL=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then
  IS_WSL=true
fi

# If running from NTFS (/mnt/c/...) on WSL, copy to native Linux FS first
if [[ "$IS_WSL" == "true" && "$SCRIPT_DIR" == /mnt/* ]]; then
  DEPLOY_DIR="$HOME/forge"
  if [[ ! -d "$DEPLOY_DIR" || "$DO_CLEAN" == "true" ]]; then
    log "WSL2 + NTFS detected — copying to native Linux filesystem..."
    rm -rf "$DEPLOY_DIR" 2>/dev/null || true
    cp -r "$SCRIPT_DIR" "$DEPLOY_DIR"
  else
    log "Syncing changes to $DEPLOY_DIR..."
    rsync -a --delete \
      --exclude='.venv/' --exclude='node_modules/' --exclude='.git/' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.egg-info/' \
      --exclude='.env' \
      "$SCRIPT_DIR/" "$DEPLOY_DIR/"
  fi
  # Re-exec from native filesystem
  exec bash "$DEPLOY_DIR/forge-up.sh" "$@"
fi

cd "$SCRIPT_DIR"
log "Working directory: $(pwd)"

# ── Ensure Docker is available ───────────────────────────────────────────────
step "Docker"
if ! command -v docker &>/dev/null; then
  log "Docker not found — installing..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

if ! docker info &>/dev/null 2>&1; then
  if sudo docker info &>/dev/null 2>&1; then
    sudo usermod -aG docker "$USER"
    warn "Docker group added. Re-running with new group..."
    exec sg docker -c "bash $(pwd)/forge-up.sh $*"
  else
    sudo service docker start 2>/dev/null || true
    sleep 3
    docker info &>/dev/null 2>&1 || err "Docker is not running. Start Docker and re-run."
  fi
fi
log "Docker OK: $(docker --version | head -1 | cut -d, -f1)"

# ── Fix line endings (CRLF → LF) ────────────────────────────────────────────
find . -maxdepth 1 \( -name "*.env*" -o -name "*.sh" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find scripts config docker -type f \( -name "*.sh" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sql" -o -name "*.env" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
sed -i 's/\r$//' docker-compose.yml docker-compose.daytona.yml 2>/dev/null || true

# ── .env setup ───────────────────────────────────────────────────────────────
step "Environment"
if [ ! -f .env ]; then
  [[ -f .env.example ]] && cp .env.example .env || err ".env.example not found"
  log "Created .env from .env.example"
fi
sed -i 's/\r$//' .env

gen_pw() { openssl rand -base64 18 | tr -d '=/+' | head -c 24; }

# Auto-generate passwords if still at defaults
for var_pair in \
  "POSTGRES_PASSWORD:change_this_strong_password" \
  "REDIS_PASSWORD:change_me" \
  "QDRANT_API_KEY:change_this_strong_key"; do
  VAR="${var_pair%%:*}"
  DEFAULT="${var_pair#*:}"
  CURRENT=$(grep "^${VAR}=" .env 2>/dev/null | cut -d= -f2- || echo "")
  if [[ -z "$CURRENT" || "$CURRENT" == "$DEFAULT" || "$CURRENT" == "change_me" ]]; then
    NEW_PW=$(gen_pw)
    if grep -q "^${VAR}=" .env; then
      sed -i "s|^${VAR}=.*|${VAR}=${NEW_PW}|" .env
    else
      echo "${VAR}=${NEW_PW}" >> .env
    fi
    log "Generated ${VAR}"
    # Update DATABASE_URL if we changed POSTGRES_PASSWORD
    if [[ "$VAR" == "POSTGRES_PASSWORD" ]]; then
      PG_USER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2- || echo "backbone")
      sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://${PG_USER}:${NEW_PW}@localhost:5432/backbone|" .env
    fi
    if [[ "$VAR" == "REDIS_PASSWORD" ]]; then
      sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:${NEW_PW}@localhost:6379|" .env
    fi
  fi
done

# FORGE_WEB_TOKEN (dashboard auth)
CURRENT_WEB_TOKEN=$(grep '^FORGE_WEB_TOKEN=' .env | cut -d= -f2- || echo "")
if [[ -z "$CURRENT_WEB_TOKEN" ]]; then
  WEB_TOKEN=$(gen_pw)
  if grep -q '^FORGE_WEB_TOKEN=' .env; then
    sed -i "s|^FORGE_WEB_TOKEN=.*|FORGE_WEB_TOKEN=${WEB_TOKEN}|" .env
  else
    echo "FORGE_WEB_TOKEN=${WEB_TOKEN}" >> .env
  fi
  log "Generated FORGE_WEB_TOKEN"
fi

set -a; source .env; set +a
export PYTHONUTF8=1
_EH_KEY="${ELECTRONHUB_API_KEY:-}"
log ".env loaded (${#_EH_KEY} char API key)"

# ── Python venv + dependencies ───────────────────────────────────────────────
step "Python environment"

NEED_INSTALL=false
if [ ! -d .venv ] && [ ! -d "$HOME/.forge-venv" ]; then
  NEED_INSTALL=true
fi

if [[ "$NEED_INSTALL" == "true" ]]; then
  log "Creating Python virtual environment..."

  # Ensure python3-venv is available
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y python3-venv python3-full -qq 2>/dev/null || true
  fi

  PYTHON_CMD=""
  for cmd in python3 python3.12 python3.11; do
    if command -v "$cmd" &>/dev/null; then
      VER=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "0.0")
      MAJOR=$(echo "$VER" | cut -d. -f1); MINOR=$(echo "$VER" | cut -d. -f2)
      if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 ]]; then
        PYTHON_CMD="$cmd"; break
      fi
    fi
  done
  [[ -n "$PYTHON_CMD" ]] || err "Python 3.11+ required. Install: sudo apt install python3.12 python3.12-venv"

  $PYTHON_CMD -m venv .venv || err "venv creation failed"
  source .venv/bin/activate
  pip install --upgrade pip --quiet

  log "Installing Python dependencies (1-3 min on first run)..."
  pip install -e ".[dev,stitch,daytona]" 2>&1 | tail -3
  pip install "crawl4ai>=0.4.0" 2>&1 | tail -3 || warn "crawl4ai install failed — HTTP fallback"
  pip install "sentence-transformers>=3.0.0" 2>&1 | tail -3 || warn "sentence-transformers failed — BM25 fallback"

  log "Installing Playwright Chromium..."
  python -m playwright install-deps chromium 2>&1 | tail -3 || true
  python -m playwright install chromium 2>&1 || sudo "$(which python)" -m playwright install chromium 2>&1 || true
else
  # Activate existing venv
  if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
  elif [ -f "$HOME/.forge-venv/bin/activate" ]; then
    source "$HOME/.forge-venv/bin/activate"
  fi
  log "Python venv OK: $(python --version 2>&1)"

  # Quick dep check — reinstall if new deps were added
  pip install -e ".[dev,stitch,daytona]" --quiet 2>&1 | tail -1
fi

PYTHON_CMD="${VIRTUAL_ENV}/bin/python"

# ── Browser layer: npm install ───────────────────────────────────────────────
step "Browser layer (Node.js)"
if [ -d agents/browser ] && [ -f agents/browser/package.json ]; then
  if [ ! -d agents/browser/node_modules ]; then
    log "Installing browser layer npm deps..."
    (cd agents/browser && npm install --silent 2>&1 | tail -3)
  else
    log "Browser layer node_modules OK"
  fi
fi

# ── Docker: infrastructure config ───────────────────────────────────────────
step "Docker infrastructure"

# Create postgres init SQL if missing
if [ ! -f config/postgres-init.sql ]; then
  mkdir -p config
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
  mkdir -p config
  cat > config/temporal-dynamicconfig.yaml << 'EOCONF'
system.forceSearchAttributesCacheRefreshOnRead:
  - value: true
    constraints: {}
EOCONF
  log "Created config/temporal-dynamicconfig.yaml"
fi

# ── Docker: start/rebuild ────────────────────────────────────────────────────
if [[ "$DO_CLEAN" == "true" ]]; then
  log "Deep clean: removing all Docker volumes..."
  docker compose down -v 2>/dev/null || true
  docker compose -f docker-compose.daytona.yml down -v 2>/dev/null || true
fi

if [[ "$DO_REBUILD" == "true" ]]; then
  log "Rebuilding Docker images..."
  docker compose up -d --build
else
  docker compose up -d
fi

# ── Daytona sandbox stack ────────────────────────────────────────────────────
if [ -f docker-compose.daytona.yml ]; then
  if [ -z "${DAYTONA_SSH_PRIVATE_KEY:-}" ]; then
    log "Generating SSH key pair for Daytona..."
    _TMP_KEY=$(mktemp)
    ssh-keygen -t ed25519 -f "$_TMP_KEY" -N "" -q
    _PRIV_B64=$(base64 -w0 "$_TMP_KEY" 2>/dev/null || base64 "$_TMP_KEY" | tr -d '\n')
    _PUB_B64=$(base64 -w0 "${_TMP_KEY}.pub" 2>/dev/null || base64 "${_TMP_KEY}.pub" | tr -d '\n')
    rm -f "$_TMP_KEY" "${_TMP_KEY}.pub"
    if grep -q '^DAYTONA_SSH_PRIVATE_KEY=' .env 2>/dev/null; then
      sed -i "s|^DAYTONA_SSH_PRIVATE_KEY=.*|DAYTONA_SSH_PRIVATE_KEY=${_PRIV_B64}|" .env
    else
      echo "DAYTONA_SSH_PRIVATE_KEY=${_PRIV_B64}" >> .env
    fi
    export DAYTONA_SSH_PRIVATE_KEY="${_PRIV_B64}"
    mkdir -p docker/daytona
    cat > docker/daytona/ssh-keys.env <<SSHEOF
SSH_PUBLIC_KEY=${_PUB_B64}
SSH_GATEWAY_PUBLIC_KEY=${_PUB_B64}
SSHEOF
    log "SSH keys generated"
  fi

  log "Starting Daytona sandbox stack..."
  docker compose -f docker-compose.daytona.yml up -d 2>&1 | tail -3 || warn "Daytona stack failed"
fi

# ── Wait for core services ───────────────────────────────────────────────────
step "Health checks"

wait_for() {
  local name="$1" cmd="$2" max="$3" interval="${4:-1}"
  local waited=0
  while ! eval "$cmd" &>/dev/null 2>&1; do
    sleep "$interval"; waited=$((waited+interval))
    [[ $waited -ge $max ]] && { warn "${name} did not start in ${max}s"; return 1; }
  done
  log "${name} ready"
  return 0
}

wait_for "PostgreSQL" "docker exec forge-postgres pg_isready -U ${POSTGRES_USER:-backbone}" 60
wait_for "Redis"      "docker exec forge-redis redis-cli -a '${REDIS_PASSWORD}' ping" 30
CURL_Q="-sf"; [[ -n "${QDRANT_API_KEY:-}" ]] && CURL_Q="$CURL_Q -H 'api-key: ${QDRANT_API_KEY}'"
wait_for "Qdrant"     "curl $CURL_Q http://localhost:6333/readyz" 60 2

# Initialize Qdrant collections
log "Initializing Qdrant collections..."
$PYTHON_CMD -c "
import asyncio, sys
sys.path.insert(0, '.')
async def main():
    from agents.python.infra.memory_keeper import ensure_collections
    await ensure_collections()
    print('Collections ready')
asyncio.run(main())
" 2>&1 || warn "Qdrant collection init failed (may already exist)"

# ── Browser layer: start ─────────────────────────────────────────────────────
BROWSER_PORT="${BROWSER_SERVER_PORT:-3100}"
if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
  log "Browser layer already running (port ${BROWSER_PORT})"
else
  if [ -d agents/browser ] && [ -f agents/browser/package.json ]; then
    log "Starting browser layer (port ${BROWSER_PORT})..."
    fuser -k "${BROWSER_PORT}/tcp" 2>/dev/null || true
    (cd agents/browser && nohup npm start > /tmp/forge-browser.log 2>&1 &)
    sleep 5
    if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
      log "Browser layer ready (port ${BROWSER_PORT})"
    else
      warn "Browser layer failed — check /tmp/forge-browser.log"
    fi
  else
    warn "agents/browser/ not found — skipping"
  fi
fi

# ── Wait for remaining services ──────────────────────────────────────────────
FORGE_WEB_PORT="${FORGE_WEB_PORT:-3000}"
wait_for "Forge Web"  "curl -sf http://localhost:${FORGE_WEB_PORT}/" 45 2 || true
wait_for "Forge API"  "curl -sf http://localhost:3001/health" 30 2 || true
wait_for "SearXNG"    "curl -sf http://localhost:8081/healthz" 30 2 || true

DAYTONA_READY=false
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
  wait_for "Daytona API" "curl -sf http://localhost:3986/health" 60 2 && DAYTONA_READY=true
fi

# ── Daytona API key auto-generation ──────────────────────────────────────────
if [[ "$DAYTONA_READY" == "true" && -z "${DAYTONA_API_KEY:-}" ]]; then
  log "No DAYTONA_API_KEY — auto-generating..."
  wait_for "Dex OIDC" "curl -sf http://localhost:5556/dex/.well-known/openid-configuration" 60 2 || true
  if [ -f scripts/daytona-keygen.sh ]; then
    if VERBOSE=1 bash scripts/daytona-keygen.sh 2>&1; then
      set -a; source .env 2>/dev/null || true; set +a
      log "Daytona API key generated and stored in .env"
    else
      warn "Auto-keygen failed. Generate at http://localhost:3986"
    fi
  fi
fi

# ── Network verification (forge-api → qdrant, daytona-api) ──────────────────
step "Network verification"
NEED_API_RESTART=false

if ! docker exec forge-api python -c "import socket; socket.getaddrinfo('qdrant', 6333)" &>/dev/null 2>&1; then
  warn "forge-api cannot resolve qdrant — fixing..."
  docker network connect forge-network forge-qdrant 2>/dev/null || true
  NEED_API_RESTART=true
else
  log "forge-api → qdrant OK"
fi

if [[ "$DAYTONA_READY" == "true" ]]; then
  if ! docker exec forge-api python -c "import socket; socket.getaddrinfo('daytona-api', 3000)" &>/dev/null 2>&1; then
    warn "forge-api cannot resolve daytona-api — fixing..."
    docker network connect forge-network daytona-api 2>/dev/null || true
    NEED_API_RESTART=true
  else
    log "forge-api → daytona-api OK"
  fi
fi

if [[ "$NEED_API_RESTART" == "true" ]]; then
  docker restart forge-api 2>/dev/null || true
  sleep 5
  log "Restarted forge-api with network fix"
fi

# ── Final health summary ─────────────────────────────────────────────────────
step "Service Status"
echo ""

check_service() {
  local name="$1" check="$2"
  if eval "$check" &>/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC}  ${name}"
  else
    echo -e "  ${RED}✗${NC}  ${name}"
  fi
}

check_service "PostgreSQL         :5432  (Docker)"   "docker exec forge-postgres pg_isready -U ${POSTGRES_USER:-backbone}"
check_service "Redis              :6379  (Docker)"   "docker exec forge-redis redis-cli -a '${REDIS_PASSWORD}' ping"
check_service "Qdrant             :6333  (Docker)"   "curl -sf ${QDRANT_API_KEY:+-H 'api-key: ${QDRANT_API_KEY}'} http://localhost:6333/readyz"
check_service "Temporal           :7233  (Docker)"   "docker exec forge-temporal tctl --address temporal:7233 cluster health 2>/dev/null || nc -z localhost 7233"
check_service "Temporal UI        :8080  (Docker)"   "curl -sf http://localhost:8080/"
check_service "N8N                :5678  (Docker)"   "curl -sf http://localhost:5678/healthz"
check_service "SearXNG            :8081  (Docker)"   "curl -sf http://localhost:8081/healthz"
check_service "Forge API          :3001  (Docker)"   "curl -sf http://localhost:3001/health"
check_service "Forge Web          :${FORGE_WEB_PORT}  (Docker)"   "curl -sf http://localhost:${FORGE_WEB_PORT}/"
check_service "Browser Layer      :${BROWSER_PORT}  (Host)"     "curl -sf http://localhost:${BROWSER_PORT}/health"
if [[ "$DAYTONA_READY" == "true" ]] || docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
  check_service "Daytona API        :3986  (Docker)"   "curl -sf http://localhost:3986/health"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge is running!                                  ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
info "Project:  $(pwd)"
info "Activate: source $(pwd)/.venv/bin/activate"
info "Dashboard: http://localhost:${FORGE_WEB_PORT}"
[[ -n "${FORGE_WEB_TOKEN:-}" ]] && info "Token:    ${FORGE_WEB_TOKEN}"
echo ""

# ── Auto-run forge command if provided ───────────────────────────────────────
if [[ -n "$FORGE_CMD" ]]; then
  log "Running: forge ${FORGE_CMD}"
  "$(pwd)/.venv/bin/forge" $FORGE_CMD
fi
