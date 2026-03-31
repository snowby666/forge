#!/usr/bin/env bash
# start.sh -- Start all Forge infrastructure services
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[start]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[info]${NC} $1"; }

# --- Find Python (same detection as setup.sh) --------------------------------
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
[[ -n "$PYTHON_CMD" ]] || err "Python 3.11+ not found. Run scripts/setup.sh first."

# --- Load .env ---------------------------------------------------------------
[[ -f .env ]] || err ".env not found -- run scripts/setup.sh first"
set -a; source .env; set +a

# --- Validate .env has real passwords (not placeholders) --------------------
ENV_OK=true
for var in POSTGRES_PASSWORD REDIS_PASSWORD QDRANT_API_KEY; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == "change_me" || "$val" == "change_this_strong_password" || "$val" == "change_this_strong_key" ]]; then
    warn "$var is not set or still uses the placeholder value."
    warn "  Edit .env or forge.secrets and set a real password, then re-run start.sh"
    ENV_OK=false
  fi
done
[[ "$ENV_OK" == "true" ]] || err "Fix the above .env values before starting services."

log "Starting Docker services..."
docker compose -f config/docker-compose.yml up -d

log "Waiting for services..."
MAX_WAIT=60
WAITED=0

# PostgreSQL
until docker exec forge-postgres pg_isready -U "${POSTGRES_USER:-backbone}" &>/dev/null 2>&1; do
  sleep 1; WAITED=$((WAITED+1))
  [[ $WAITED -ge $MAX_WAIT ]] && err "PostgreSQL did not start within ${MAX_WAIT}s"
done
log "PostgreSQL ready"
WAITED=0

# Redis
until docker exec forge-redis redis-cli -a "${REDIS_PASSWORD:-}" ping &>/dev/null 2>&1; do
  sleep 1; WAITED=$((WAITED+1))
  [[ $WAITED -ge $MAX_WAIT ]] && { warn "Redis health check timed out -- continuing"; break; }
done
log "Redis ready"
WAITED=0

# Qdrant
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
" || warn "Qdrant collection init failed -- may already exist"

log "Starting browser layer..."
cd agents/browser && npm start &
BROWSER_PID=$!
cd ../..
sleep 3

BROWSER_PORT="${BROWSER_SERVER_PORT:-3100}"
if curl -sf "http://localhost:${BROWSER_PORT}/health" &>/dev/null 2>&1; then
  log "Browser layer ready (port ${BROWSER_PORT})"
else
  warn "Browser layer health check failed (PID ${BROWSER_PID}) -- check agents/browser logs"
fi

echo ""
log "All services running:"
info "  Qdrant:    http://localhost:6333"
info "  Browser:   http://localhost:${BROWSER_PORT}"
if docker ps --format '{{.Names}}' | grep -q forge-n8n; then
  info "  n8n:       http://localhost:5678"
fi
if docker ps --format '{{.Names}}' | grep -q forge-temporal-ui; then
  info "  Temporal:  http://localhost:8080"
fi
echo ""
log "Test run: $PYTHON_CMD scripts/test_run.py --dry-run"
