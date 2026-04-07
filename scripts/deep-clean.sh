#!/usr/bin/env bash
# deep-clean.sh -- Nuclear cleanup of ALL Docker artifacts, caches, and temp files.
# Run before redeploy to reclaim disk space.
#
# Usage:  bash scripts/deep-clean.sh [--keep-images]
#   --keep-images   Skip removing pulled base images (saves re-download time)
#
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[clean]${NC} $1"; }
warn() { echo -e "${YELLOW}[clean]${NC} $1"; }
info() { echo -e "${CYAN}[clean]${NC} $1"; }

KEEP_IMAGES=false
for arg in "$@"; do
  [[ "$arg" == "--keep-images" ]] && KEEP_IMAGES=true
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Forge -- Deep Clean                        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Show current disk usage
info "Disk usage before cleanup:"
df -h / 2>/dev/null | tail -1 || true
echo ""

FREED_HINT=0

# ── 1. Stop ALL Forge & Daytona containers ────────────────────────────────────
log "Stopping all Forge containers..."
docker compose down -v --remove-orphans 2>/dev/null || true

if [ -f docker-compose.daytona.yml ]; then
  log "Stopping all Daytona containers..."
  docker compose -f docker-compose.daytona.yml down -v --remove-orphans 2>/dev/null || true
fi

# Kill any leftover forge-related containers that might not be in compose
STALE=$(docker ps -aq --filter "name=forge-" --filter "name=daytona-" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  log "Removing leftover containers..."
  docker rm -f $STALE 2>/dev/null || true
fi

# ── 2. Remove ALL Docker volumes (forge + daytona) ───────────────────────────
log "Removing Docker volumes..."
FORGE_VOLS=$(docker volume ls -q --filter "name=forge-" 2>/dev/null || true)
DAYTONA_VOLS=$(docker volume ls -q --filter "name=daytona-" 2>/dev/null || true)
ALL_VOLS="$FORGE_VOLS $DAYTONA_VOLS"
if [ -n "$(echo "$ALL_VOLS" | tr -d ' ')" ]; then
  for vol in $ALL_VOLS; do
    docker volume rm -f "$vol" 2>/dev/null && info "  Removed volume: $vol" || true
  done
fi

# Also remove anonymous/dangling volumes
DANGLING_VOLS=$(docker volume ls -qf dangling=true 2>/dev/null || true)
if [ -n "$DANGLING_VOLS" ]; then
  log "Removing dangling volumes..."
  docker volume rm $DANGLING_VOLS 2>/dev/null || true
fi

# ── 3. Remove Docker images ──────────────────────────────────────────────────
if [[ "$KEEP_IMAGES" == "false" ]]; then
  log "Removing Forge/Daytona Docker images..."
  FORGE_IMGS=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' 2>/dev/null | grep -E 'forge-|daytonaio/' | awk '{print $2}' || true)
  if [ -n "$FORGE_IMGS" ]; then
    docker rmi -f $FORGE_IMGS 2>/dev/null || true
  fi

  log "Removing ALL dangling images..."
  docker image prune -f 2>/dev/null || true
else
  warn "Keeping base images (--keep-images). Only removing dangling..."
  docker image prune -f 2>/dev/null || true
fi

# ── 4. Docker builder cache ─────────────────────────────────────────────────
log "Clearing Docker build cache..."
CACHE_BEFORE=$(docker system df 2>/dev/null | grep "Build Cache" | awk '{print $4}' || echo "?")
docker builder prune -af 2>/dev/null || true
info "  Build cache was: ${CACHE_BEFORE}"

# ── 5. Docker system prune (catch-all) ───────────────────────────────────────
log "Running Docker system prune..."
if [[ "$KEEP_IMAGES" == "false" ]]; then
  docker system prune -af --volumes 2>/dev/null || true
else
  docker system prune -f --volumes 2>/dev/null || true
fi

# ── 6. Application caches and temp files ─────────────────────────────────────
log "Cleaning application caches..."

# Python caches
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
rm -rf .mypy_cache .pytest_cache .ruff_cache 2>/dev/null || true
info "  Cleared Python caches"

# Next.js build cache
if [ -d web/.next ]; then
  rm -rf web/.next
  info "  Cleared web/.next"
fi

# Node modules (will be reinstalled by deploy)
if [ -d web/node_modules ]; then
  NODE_SIZE=$(du -sh web/node_modules 2>/dev/null | awk '{print $1}' || echo "?")
  rm -rf web/node_modules
  info "  Cleared web/node_modules (${NODE_SIZE})"
fi

# NPM/Yarn/PNPM caches
rm -rf web/.turbo 2>/dev/null || true
rm -rf web/.eslintcache 2>/dev/null || true

# Forge run logs
if [ -d logs ]; then
  LOG_COUNT=$(find logs -type f | wc -l)
  LOG_SIZE=$(du -sh logs 2>/dev/null | awk '{print $1}' || echo "?")
  rm -rf logs/*
  info "  Cleared ${LOG_COUNT} log files (${LOG_SIZE})"
fi

# Forge web logs (inside container, already removed with volumes)
rm -rf forge_web/logs 2>/dev/null || true

# Python virtual env (optional — deploy recreates it)
if [ -d .venv ]; then
  VENV_SIZE=$(du -sh .venv 2>/dev/null | awk '{print $1}' || echo "?")
  rm -rf .venv
  info "  Cleared .venv (${VENV_SIZE})"
fi

# Pip cache
pip cache purge 2>/dev/null || true
rm -rf ~/.cache/pip 2>/dev/null || true
info "  Cleared pip cache"

# ── 7. System-level temp files ───────────────────────────────────────────────
log "Cleaning system temp files..."
rm -rf /tmp/forge-* /tmp/daytona-* /tmp/_dkgen_* 2>/dev/null || true

# APT cache (Ubuntu/Debian)
if command -v apt-get &>/dev/null; then
  sudo apt-get clean 2>/dev/null || true
  sudo apt-get autoremove -y 2>/dev/null || true
  info "  Cleared apt cache"
fi

# Journal logs (can grow huge)
if command -v journalctl &>/dev/null; then
  JOURNAL_SIZE=$(journalctl --disk-usage 2>/dev/null | grep -oP '[\d.]+[KMGT]' || echo "?")
  sudo journalctl --vacuum-time=1d 2>/dev/null || true
  info "  Trimmed journal logs (was: ${JOURNAL_SIZE})"
fi

# ── 8. Docker overlay2 leftover cleanup ──────────────────────────────────────
# Sometimes Docker doesn't clean up overlay layers properly
log "Checking Docker disk usage..."
docker system df 2>/dev/null || true

echo ""
info "Disk usage after cleanup:"
df -h / 2>/dev/null | tail -1 || true

echo ""
echo -e "${GREEN}${BOLD}Deep clean complete!${NC}"
echo -e "${CYAN}Run ${BOLD}bash forge-deploy.sh${NC}${CYAN} to redeploy.${NC}"
echo ""
