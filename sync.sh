#!/usr/bin/env bash
# sync.sh — Hot-reload code changes to ~/forge without rebuilding anything.
# Usage: bash sync.sh
#
# What it does:
#   1. Copies only source files (Python, config, scripts) to ~/forge
#   2. Skips venv, node_modules, Docker volumes, .git
#   3. Takes ~1 second
#
# What it does NOT do:
#   - Reinstall pip packages (run: cd ~/forge && pip install -e ".[dev]")
#   - Restart Docker (run: cd ~/forge && bash scripts/start.sh)

set -euo pipefail

GREEN='\033[0;32m'; DIM='\033[2m'; NC='\033[0m'
log() { echo -e "${GREEN}[sync]${NC} $1"; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$HOME/forge"

if [[ ! -d "$DST/.venv" ]]; then
  echo "Error: $DST/.venv not found. Run forge-deploy.sh first."
  exit 1
fi

log "Syncing $SRC → $DST"

rsync -a --delete \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='*.egg-info/' \
  --exclude='.env' \
  --exclude='forge.secrets' \
  "$SRC/" "$DST/"

# Fix line endings on anything that might have CRLF
find "$DST" -maxdepth 1 -name "*.py" -exec sed -i 's/\r$//' {} + 2>/dev/null || true
find "$DST/agents" "$DST/config" "$DST/scripts" -type f \( -name "*.py" -o -name "*.sh" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true

# Re-install in editable mode (picks up new deps in pyproject.toml, ~2s if nothing changed)
cd "$DST"
source .venv/bin/activate
pip install -e ".[dev]" --quiet 2>&1 | tail -1

log "Done. $(date +%H:%M:%S)"
log "${DIM}Run: cd ~/forge && source .venv/bin/activate && forge scout${NC}"
