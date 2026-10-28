# Shared setup for the double-clickable Mac helpers in this folder.
# shellcheck shell=bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

_red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
_green() { printf '\033[32m%s\033[0m\n' "$*"; }

_setup_hint() {
  _red "Double-click \"Setup.command\" once (recreates .venv and installs the package), or run:"
  _red "  cd \"$REPO_ROOT\""
  _red "  rm -rf .venv"
  _red "  python3 -m venv .venv   # or: /opt/anaconda3/bin/python -m venv .venv"
  _red "  .venv/bin/python -m pip install -e ."
  _red "  .venv/bin/playwright install chromium"
}

poe_setup() {
  POE_PYTHON=""
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    POE_PYTHON="$REPO_ROOT/.venv/bin/python"
  fi

  if [[ -z "$POE_PYTHON" ]]; then
    _red "No project .venv found."
    _setup_hint
    exit 1
  fi

  # Prefer "python -m poe_bulk_export" over the console script: after moving the
  # folder, .venv/bin/poe-bulk-export can exist while the package is missing.
  if ! "$POE_PYTHON" -c "import poe_bulk_export" 2>/dev/null; then
    _red "The project package is not installed in .venv (ModuleNotFoundError)."
    _red "Using: $POE_PYTHON"
    _setup_hint
    exit 1
  fi

  if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
  fi

  if [[ -z "${POE_TOKEN:-}" ]]; then
    _red "POE_TOKEN is not set."
    _red "Copy .env.example to .env, paste your p-b cookie, then run again."
    exit 1
  fi
}

poe_run() {
  poe_setup
  _green "Using: $POE_PYTHON -m poe_bulk_export"
  "$POE_PYTHON" -m poe_bulk_export "$@"
}

pause_at_end() {
  echo
  read -r -p "Press Return to close…" _
}
