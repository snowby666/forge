#!/usr/bin/env bash
# forge.sh -- Wrapper that auto-activates .venv before running the forge CLI
# Usage: bash forge.sh scout
#        bash forge.sh run --id my-hackathon
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try .venv in project dir first (works on native Linux/macOS and via symlink)
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/Scripts/activate" ]; then
  source "$SCRIPT_DIR/.venv/Scripts/activate"
# Fallback: native WSL2 venv (created when project is on NTFS /mnt/c/)
elif [ -f "$HOME/.forge-venv/bin/activate" ]; then
  source "$HOME/.forge-venv/bin/activate"
fi

exec python "$SCRIPT_DIR/forge.py" "$@"
