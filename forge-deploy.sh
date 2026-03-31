#!/usr/bin/env bash
# forge-deploy.sh -- One-shot deploy: copies to native Linux FS, sets up, starts everything.
# Usage: bash forge-deploy.sh
# That's it. No other commands needed.
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
  log "WSL2 + NTFS detected. Copying project to native Linux filesystem..."
  log "Source: $SCRIPT_DIR"
  log "Target: $DEPLOY_DIR"

  if [ -d "$DEPLOY_DIR" ]; then
    log "Removing old $DEPLOY_DIR..."
    rm -rf "$DEPLOY_DIR"
  fi

  cp -r "$SCRIPT_DIR" "$DEPLOY_DIR"
  log "Copied to $DEPLOY_DIR"

  # Re-exec this script from the native filesystem
  cd "$DEPLOY_DIR"
  exec bash "$DEPLOY_DIR/forge-deploy.sh"
fi

# From here, we're guaranteed to be on a native filesystem
cd "$SCRIPT_DIR"
log "Working directory: $(pwd)"

# ── Step 3: Install Docker if missing ─────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  log "Docker not found. Installing Docker Engine..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  log "Docker installed. You may need to log out and back in for group changes."
  log "Trying to continue with sudo docker..."
fi

# Check docker socket permissions
if ! docker info &>/dev/null 2>&1; then
  if sudo docker info &>/dev/null 2>&1; then
    warn "Docker requires sudo. Adding $USER to docker group..."
    sudo usermod -aG docker "$USER"
    # Use sg to get the group in this session without logout
    SG_AVAILABLE=true
    sg docker -c "docker info" &>/dev/null 2>&1 || SG_AVAILABLE=false
    if [[ "$SG_AVAILABLE" == "false" ]]; then
      warn "Cannot activate docker group in current session."
      warn "Run these commands manually after this script:"
      warn "  newgrp docker"
      warn "  bash forge-deploy.sh"
      exit 1
    fi
    # Re-exec under the docker group
    exec sg docker -c "bash $(pwd)/forge-deploy.sh"
  else
    err "Docker is not running. Start Docker and re-run this script."
  fi
fi

log "Docker: $(docker --version | head -1)"

# ── Step 4: Strip CRLF from all text files ────────────────────────────────────
log "Fixing line endings..."
find . -maxdepth 1 -name "*.env*" -o -name "*.secrets*" -o -name "*.example" | while read -r f; do
  sed -i 's/\r$//' "$f" 2>/dev/null || true
done
find scripts config -name "*.sh" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sql" 2>/dev/null | while read -r f; do
  sed -i 's/\r$//' "$f" 2>/dev/null || true
done

# ── Step 5: Generate .env with real passwords ─────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
fi
sed -i 's/\r$//' .env

gen_pw() { openssl rand -base64 18 | tr -d '=/+' | head -c 24; }

CURRENT_PG_PASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
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

if [ ! -f forge.secrets ]; then
  cp forge.secrets.example forge.secrets 2>/dev/null || true
fi

# ── Step 5b: Clean stale venv state from NTFS copy ───────────────────────────
# .venv symlink from NTFS won't work here; remove it so setup.sh creates fresh
rm -f .venv 2>/dev/null || true

# ── Step 6: Run setup.sh ─────────────────────────────────────────────────────
log "Running setup..."
bash scripts/setup.sh

# ── Step 7: Tear down any old Docker state ────────────────────────────────────
log "Cleaning old Docker state..."
set -a; source .env 2>/dev/null || true; set +a
docker compose -f config/docker-compose.yml down -v 2>/dev/null || true

# ── Step 8: Start everything ─────────────────────────────────────────────────
log "Starting services..."
bash scripts/start.sh

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge is running!                          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""
info "Project location: $(pwd)"
info "Activate venv:    source .venv/bin/activate"
info ""
info "Next:"
info "  1. Edit forge.secrets -- add ELECTRONHUB_API_KEY"
info "  2. python scripts/test_run.py --dry-run"
info "  3. python agents/python/orchestrator/commander.py --listen"
echo ""
