#!/usr/bin/env bash
# forge-up.sh — Single entry point to start ALL Forge services.
#
# Handles: WSL2/NTFS detection, .env generation, Docker builds, health checks,
# network verification, Daytona sandbox stack, Qdrant collection init.
#
# Usage:
#   bash forge-up.sh                 # start everything (auto-rebuilds stale images)
#   bash forge-up.sh --rebuild       # force rebuild all Docker images
#   bash forge-up.sh --clean         # nuke Docker volumes and rebuild from scratch
#   bash forge-up.sh --status        # check running services without starting anything
#   bash forge-up.sh --stop          # stop all services
#   bash forge-up.sh --logs browser  # tail logs for a specific container
#   bash forge-up.sh scout           # start everything, then run 'forge scout'
#
set -euo pipefail

FORGE_VERSION="2.0.0"

# ── Colors & logging ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

_ts() { date +%H:%M:%S; }
log()  { echo -e "${GREEN}[forge $(_ts)]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn  $(_ts)]${NC} $1"; }
err()  { echo -e "${RED}[error $(_ts)]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info  $(_ts)]${NC} $1"; }
step() { echo -e "\n${BOLD}── $1 ──${NC}"; }

# ── Parse flags ──────────────────────────────────────────────────────────────
DO_CLEAN=false; DO_REBUILD=false; DO_STATUS=false; DO_STOP=false
SHOW_LOGS=""; FORGE_CMD=""
for arg in "$@"; do
  case "$arg" in
    --clean)   DO_CLEAN=true; DO_REBUILD=true ;;
    --rebuild) DO_REBUILD=true ;;
    --status)  DO_STATUS=true ;;
    --stop)    DO_STOP=true ;;
    --logs)    SHOW_LOGS="__next__" ;;
    --help|-h)
      echo "forge-up.sh v${FORGE_VERSION} — Start all Forge services"
      echo ""
      echo "Usage: bash forge-up.sh [flags] [command]"
      echo ""
      echo "Flags:"
      echo "  --rebuild       Force rebuild Docker images"
      echo "  --clean         Nuke volumes + rebuild from scratch"
      echo "  --status        Show service status (no start)"
      echo "  --stop          Stop all services"
      echo "  --logs <svc>    Tail logs (postgres|redis|qdrant|api|web|browser|temporal|n8n|searxng)"
      echo "  --help          Show this help"
      echo ""
      echo "Commands:"
      echo "  scout           Start services, then run 'forge scout'"
      echo "  <any>           Start services, then run 'forge <command>'"
      exit 0
      ;;
    -*)
      if [[ "$SHOW_LOGS" == "__next__" ]]; then SHOW_LOGS="$arg"; else warn "Unknown flag: $arg"; fi
      ;;
    *)
      if [[ "$SHOW_LOGS" == "__next__" ]]; then
        SHOW_LOGS="$arg"
      else
        FORGE_CMD="${FORGE_CMD:+$FORGE_CMD }$arg"
      fi
      ;;
  esac
done
[[ "$SHOW_LOGS" == "__next__" ]] && SHOW_LOGS=""

# ── Service name → container name map ────────────────────────────────────────
declare -A CONTAINER_MAP=(
  [postgres]=forge-postgres [redis]=forge-redis [qdrant]=forge-qdrant
  [temporal]=forge-temporal [temporal-ui]=forge-temporal-ui [n8n]=forge-n8n
  [searxng]=forge-searxng [api]=forge-api [web]=forge-web [browser]=forge-browser
  [daytona]=daytona-api [daytona-api]=daytona-api
)

# ── Handle --logs ────────────────────────────────────────────────────────────
if [[ -n "$SHOW_LOGS" ]]; then
  cname="${CONTAINER_MAP[$SHOW_LOGS]:-forge-$SHOW_LOGS}"
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
    exec docker logs -f --tail 100 "$cname"
  else
    err "Container '$cname' not found. Running containers:"
    docker ps --format '  {{.Names}}\t{{.Status}}' 2>/dev/null
    exit 1
  fi
fi

# ── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Forge — Unified Startup v${FORGE_VERSION}                            ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_START=$(date +%s)

# ── Detect environment ───────────────────────────────────────────────────────
IS_WSL=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then
  IS_WSL=true
fi

# ── WSL: copy to native filesystem ──────────────────────────────────────────
if [[ "$IS_WSL" == "true" && "$SCRIPT_DIR" == /mnt/* ]]; then
  DEPLOY_DIR="$HOME/forge"

  if [[ ! -d "$DEPLOY_DIR" || "$DO_CLEAN" == "true" ]]; then
    log "WSL2 + NTFS detected — copying to native Linux filesystem..."
    rm -rf "$DEPLOY_DIR" 2>/dev/null || true
    rsync -a \
      --exclude='.venv/' --exclude='node_modules/' --exclude='.git/' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.egg-info/' \
      "$SCRIPT_DIR/" "$DEPLOY_DIR/"
  else
    log "Syncing changes to $DEPLOY_DIR..."
    rsync -a --delete \
      --exclude='.venv/' --exclude='node_modules/' --exclude='.git/' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.egg-info/' \
      --exclude='.env' \
      "$SCRIPT_DIR/" "$DEPLOY_DIR/"

    # Merge env vars from source .env into deploy .env
    # Keeps auto-generated passwords intact while syncing user additions (API keys, tokens)
    _merge_env() {
      local src="$1" dst="$2"
      [[ -f "$src" && -f "$dst" ]] || return 0
      local merged=0
      while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* || "$line" == " "* ]] && continue
        local key="${line%%=*}" val="${line#*=}"
        # Skip auto-managed fields
        case "$key" in
          POSTGRES_PASSWORD|REDIS_PASSWORD|QDRANT_API_KEY|DATABASE_URL|REDIS_URL|FORGE_WEB_TOKEN|DAYTONA_SSH_PRIVATE_KEY) continue ;;
        esac
        local dst_val
        dst_val=$(grep "^${key}=" "$dst" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
        if [[ -z "$dst_val" ]]; then
          echo "$line" >> "$dst"
          merged=$((merged+1))
        elif [[ "$val" != "$dst_val" && "$val" != "your_"* && "$val" != "change_"* && -n "$val" ]]; then
          sed -i "s|^${key}=.*|${key}=${val}|" "$dst"
          merged=$((merged+1))
        fi
      done < "$src"
      [[ $merged -gt 0 ]] && log "Merged $merged env var(s) from source .env"
    }
    _merge_env "$SCRIPT_DIR/.env" "$DEPLOY_DIR/.env"
  fi

  exec bash "$DEPLOY_DIR/forge-up.sh" "$@"
fi

cd "$SCRIPT_DIR"
log "Working directory: $(pwd)"

# ── Ensure Docker is available ───────────────────────────────────────────────
ensure_docker() {
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
}

# ── Service status display ───────────────────────────────────────────────────
# Runs health checks in parallel, shows container logs on failure
_FAIL_COUNT=0

check_service() {
  local name="$1" check="$2" container="${3:-}"
  if eval "$check" &>/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC}  ${name}"
  else
    echo -e "  ${RED}✗${NC}  ${name}"
    _FAIL_COUNT=$((_FAIL_COUNT+1))
    # Show last few log lines for failed services
    if [[ -n "$container" ]] && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
      local logs
      logs=$(docker logs --tail 5 "$container" 2>&1 || true)
      if [[ -n "$logs" ]]; then
        echo -e "        ${DIM}$(echo "$logs" | head -5 | sed 's/^/        /')${NC}"
      fi
    fi
  fi
}

show_status() {
  local pg_user="${POSTGRES_USER:-backbone}"
  local redis_pw="${REDIS_PASSWORD:-}"
  local qdrant_key="${QDRANT_API_KEY:-}"
  local web_port="${FORGE_WEB_PORT:-3000}"
  local browser_port="${BROWSER_SERVER_PORT:-3100}"

  step "Service Status"
  echo ""
  _FAIL_COUNT=0

  check_service "PostgreSQL         :5432  (Docker)" \
    "docker exec forge-postgres pg_isready -U $pg_user" "forge-postgres"

  check_service "Redis              :6379  (Docker)" \
    "docker exec forge-redis redis-cli -a '$redis_pw' ping" "forge-redis"

  check_service "Qdrant             :6333  (Docker)" \
    "curl -sf ${qdrant_key:+-H 'api-key: $qdrant_key'} http://localhost:6333/readyz" "forge-qdrant"

  check_service "Temporal           :7233  (Docker)" \
    "nc -z localhost 7233" "forge-temporal"

  check_service "Temporal UI        :8080  (Docker)" \
    "curl -sf http://localhost:8080/" "forge-temporal-ui"

  check_service "N8N                :5678  (Docker)" \
    "curl -sf http://localhost:5678/healthz" "forge-n8n"

  check_service "SearXNG            :8081  (Docker)" \
    "curl -sf http://localhost:8081/healthz" "forge-searxng"

  check_service "Forge API          :3001  (Docker)" \
    "curl -sf http://localhost:3001/health" "forge-api"

  check_service "Forge Web          :${web_port}  (Docker)" \
    "curl -sf http://localhost:${web_port}/api/health" "forge-web"

  check_service "Browser Layer      :${browser_port}  (Docker)" \
    "curl -sf http://localhost:${browser_port}/health" "forge-browser"

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
    check_service "Daytona API        :3986  (Docker)" \
      "curl -sf http://localhost:3986/health" "daytona-api"
  fi
  echo ""
}

# ── Handle --status ──────────────────────────────────────────────────────────
if [[ "$DO_STATUS" == "true" ]]; then
  ensure_docker
  [[ -f .env ]] && { set -a; source .env; set +a; }
  show_status
  echo -e "  ${DIM}Containers:${NC}"
  docker ps --format '  {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | sort
  echo ""
  exit 0
fi

# ── Handle --stop ────────────────────────────────────────────────────────────
if [[ "$DO_STOP" == "true" ]]; then
  ensure_docker
  log "Stopping all services..."
  docker compose down 2>/dev/null || true
  docker compose -f docker-compose.daytona.yml down 2>/dev/null || true
  log "All services stopped."
  exit 0
fi

# ── Main startup ─────────────────────────────────────────────────────────────
step "Docker"
ensure_docker

# Disk space check
AVAIL_GB=$(df -BG . 2>/dev/null | awk 'NR==2{gsub("G","");print $4}' || echo "999")
if [[ "$AVAIL_GB" -lt 5 ]]; then
  warn "Low disk space: ${AVAIL_GB}GB available. Docker builds may fail."
fi

# Fix line endings (CRLF → LF) — critical on WSL with NTFS source
find . -maxdepth 1 \( -name "*.env*" -o -name "*.sh" -o -name "Dockerfile*" -o -name "*.yml" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find scripts config docker -type f \( -name "*.sh" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sql" -o -name "*.env" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true

# ── .env setup ───────────────────────────────────────────────────────────────
step "Environment"
if [ ! -f .env ]; then
  [[ -f .env.example ]] && cp .env.example .env || err ".env.example not found"
  log "Created .env from .env.example"
fi
sed -i 's/\r$//' .env

gen_pw() { openssl rand -base64 18 | tr -d '=/+' | head -c 24; }

# Set or update an env var in .env
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

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
    set_env "$VAR" "$NEW_PW"
    log "Generated ${VAR}"
    if [[ "$VAR" == "POSTGRES_PASSWORD" ]]; then
      PG_USER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2- || echo "backbone")
      set_env "DATABASE_URL" "postgresql+asyncpg://${PG_USER}:${NEW_PW}@localhost:5432/backbone"
    fi
    if [[ "$VAR" == "REDIS_PASSWORD" ]]; then
      set_env "REDIS_URL" "redis://:${NEW_PW}@localhost:6379"
    fi
  fi
done

# FORGE_WEB_TOKEN (dashboard auth)
CURRENT_WEB_TOKEN=$(grep '^FORGE_WEB_TOKEN=' .env | cut -d= -f2- || echo "")
if [[ -z "$CURRENT_WEB_TOKEN" ]]; then
  set_env "FORGE_WEB_TOKEN" "$(gen_pw)"
  log "Generated FORGE_WEB_TOKEN"
fi

set -a; source .env; set +a
export PYTHONUTF8=1
_EH_KEY="${ELECTRONHUB_API_KEY:-}"
log ".env loaded (${#_EH_KEY} char API key)"

# ── Python venv + dependencies ───────────────────────────────────────────────
step "Python environment"

if [ ! -d .venv ] && [ ! -d "$HOME/.forge-venv" ]; then
  log "Creating Python virtual environment..."

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
  if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
  elif [ -f "$HOME/.forge-venv/bin/activate" ]; then
    source "$HOME/.forge-venv/bin/activate"
  fi
  log "Python venv OK: $(python --version 2>&1)"
  pip install -e ".[dev,stitch,daytona]" --quiet 2>&1 | tail -1
fi

PYTHON_CMD="${VIRTUAL_ENV}/bin/python"

# ── Docker: generate config files if missing ─────────────────────────────────
step "Docker infrastructure"

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

# ── Smart rebuild detection ──────────────────────────────────────────────────
# Auto-rebuild when Dockerfiles or build context changed since last build
CHECKSUM_FILE=".forge-build-checksums"

compute_build_checksum() {
  # Hash the Dockerfiles + key config that affects the image
  cat Dockerfile.api Dockerfile.browser Dockerfile.web \
    agents/browser/package.json agents/browser/server.ts \
    web/package.json \
    pyproject.toml 2>/dev/null | md5sum | cut -d' ' -f1
}

CURRENT_CHECKSUM=$(compute_build_checksum)
PREVIOUS_CHECKSUM=""
[[ -f "$CHECKSUM_FILE" ]] && PREVIOUS_CHECKSUM=$(cat "$CHECKSUM_FILE" 2>/dev/null || echo "")

if [[ "$DO_REBUILD" == "false" && "$CURRENT_CHECKSUM" != "$PREVIOUS_CHECKSUM" && -n "$PREVIOUS_CHECKSUM" ]]; then
  log "Build context changed since last run — auto-rebuilding images..."
  DO_REBUILD=true
fi

# ── Docker: start/rebuild ────────────────────────────────────────────────────
if [[ "$DO_CLEAN" == "true" ]]; then
  log "Deep clean: removing all Docker volumes..."
  docker compose down -v 2>/dev/null || true
  docker compose -f docker-compose.daytona.yml down -v 2>/dev/null || true
fi

if [[ "$DO_REBUILD" == "true" ]]; then
  log "Rebuilding Docker images (this may take a few minutes)..."
  docker compose build --parallel 2>&1 | tail -20
  docker compose up -d --force-recreate
else
  docker compose up -d
fi

# Save build checksum
echo "$CURRENT_CHECKSUM" > "$CHECKSUM_FILE"

# ── Daytona sandbox stack ────────────────────────────────────────────────────
if [ -f docker-compose.daytona.yml ]; then
  if [ -z "${DAYTONA_SSH_PRIVATE_KEY:-}" ]; then
    log "Generating SSH key pair for Daytona..."
    _TMP_KEY=$(mktemp)
    ssh-keygen -t ed25519 -f "$_TMP_KEY" -N "" -q
    _PRIV_B64=$(base64 -w0 "$_TMP_KEY" 2>/dev/null || base64 "$_TMP_KEY" | tr -d '\n')
    _PUB_B64=$(base64 -w0 "${_TMP_KEY}.pub" 2>/dev/null || base64 "${_TMP_KEY}.pub" | tr -d '\n')
    rm -f "$_TMP_KEY" "${_TMP_KEY}.pub"
    set_env "DAYTONA_SSH_PRIVATE_KEY" "$_PRIV_B64"
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

# ── Health checks (parallel) ─────────────────────────────────────────────────
step "Health checks"

wait_for() {
  local name="$1" cmd="$2" max="$3" interval="${4:-2}"
  local waited=0
  while ! eval "$cmd" &>/dev/null 2>&1; do
    sleep "$interval"; waited=$((waited+interval))
    if [[ $waited -ge $max ]]; then
      warn "${name} did not start in ${max}s"
      return 1
    fi
  done
  log "${name} ready (${waited}s)"
  return 0
}

# Core infra first (other services depend on these)
log "Waiting for core infrastructure..."
wait_for "PostgreSQL" "docker exec forge-postgres pg_isready -U ${POSTGRES_USER:-backbone}" 60
wait_for "Redis"      "docker exec forge-redis redis-cli -a '${REDIS_PASSWORD}' ping" 30

CURL_Q="-sf"
[[ -n "${QDRANT_API_KEY:-}" ]] && CURL_Q="$CURL_Q -H 'api-key: ${QDRANT_API_KEY}'"
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

# App services (wait in parallel using background jobs)
BROWSER_PORT="${BROWSER_SERVER_PORT:-3100}"
FORGE_WEB_PORT="${FORGE_WEB_PORT:-3000}"

log "Waiting for application services..."
_pids=()
wait_for "Browser"   "curl -sf http://localhost:${BROWSER_PORT}/health"  90 3 &
_pids+=($!)
wait_for "Forge API" "curl -sf http://localhost:3001/health"             90 3 &
_pids+=($!)
wait_for "SearXNG"   "curl -sf http://localhost:8081/healthz"            60 3 &
_pids+=($!)

# Wait for parallel checks
for pid in "${_pids[@]}"; do
  wait "$pid" 2>/dev/null || true
done

# Web depends on API, so wait for it after API is up
wait_for "Forge Web" "curl -sf http://localhost:${FORGE_WEB_PORT}/api/health" 120 3 || true

# Daytona
DAYTONA_READY=false
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'daytona-api'; then
  wait_for "Daytona API" "curl -sf http://localhost:3986/health" 60 3 && DAYTONA_READY=true
fi

# ── Daytona API key auto-generation ──────────────────────────────────────────
if [[ "$DAYTONA_READY" == "true" && -z "${DAYTONA_API_KEY:-}" ]]; then
  log "No DAYTONA_API_KEY — auto-generating..."
  wait_for "Dex OIDC" "curl -sf http://localhost:5556/dex/.well-known/openid-configuration" 60 3 || true
  if [ -f scripts/daytona-keygen.sh ]; then
    if VERBOSE=1 bash scripts/daytona-keygen.sh 2>&1; then
      set -a; source .env 2>/dev/null || true; set +a
      log "Daytona API key generated and stored in .env"
    else
      warn "Auto-keygen failed. Generate at http://localhost:3986"
    fi
  fi
fi

# ── Network verification ────────────────────────────────────────────────────
step "Network verification"
NEED_API_RESTART=false

_check_dns() {
  local src="$1" target="$2" port="$3"
  if ! docker exec "$src" python -c "import socket; socket.getaddrinfo('$target', $port)" &>/dev/null 2>&1; then
    warn "$src cannot resolve $target — fixing..."
    docker network connect forge-network "$(docker ps -a --filter name="$target" --format '{{.Names}}' | head -1)" 2>/dev/null || true
    NEED_API_RESTART=true
  else
    log "$src → $target OK"
  fi
}

_check_dns forge-api qdrant 6333
_check_dns forge-api browser 3100

if [[ "$DAYTONA_READY" == "true" ]]; then
  _check_dns forge-api daytona-api 3000
fi

if [[ "$NEED_API_RESTART" == "true" ]]; then
  docker restart forge-api 2>/dev/null || true
  sleep 5
  log "Restarted forge-api with network fix"
fi

# ── Final status ─────────────────────────────────────────────────────────────
show_status

ELAPSED=$(($(date +%s) - SCRIPT_START))
MINS=$((ELAPSED / 60)); SECS=$((ELAPSED % 60))

if [[ $_FAIL_COUNT -eq 0 ]]; then
  echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║  ${GREEN}Forge is running!${NC}${BOLD}  (${MINS}m ${SECS}s)                               ║${NC}"
  echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
else
  echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║  ${YELLOW}Forge started with ${_FAIL_COUNT} warning(s)${NC}${BOLD}  (${MINS}m ${SECS}s)                  ║${NC}"
  echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  info "Debug failing services: bash forge-up.sh --logs <service>"
fi
echo ""
info "Project:   $(pwd)"
info "Activate:  source $(pwd)/.venv/bin/activate"
info "Dashboard: http://localhost:${FORGE_WEB_PORT}"
[[ -n "${FORGE_WEB_TOKEN:-}" ]] && info "Token:     ${FORGE_WEB_TOKEN}"
info "Status:    bash forge-up.sh --status"
echo ""

# ── Auto-run forge command if provided ───────────────────────────────────────
if [[ -n "$FORGE_CMD" ]]; then
  log "Running: forge ${FORGE_CMD}"
  "$(pwd)/.venv/bin/forge" $FORGE_CMD
fi
