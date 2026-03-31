#!/usr/bin/env bash
# forge.sh -- Wrapper that auto-activates .venv before running the forge CLI
# Usage: bash forge.sh scout
#        bash forge.sh run --id my-hackathon
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/Scripts/activate" ]; then
  source "$SCRIPT_DIR/.venv/Scripts/activate"
fi
exec python "$SCRIPT_DIR/forge" "$@"
