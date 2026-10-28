# Shared setup for the double-clickable Mac helpers in this folder.
# shellcheck shell=bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

_red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
_green() { printf '\033[32m%s\033[0m\n' "$*"; }

poe_setup() {
  if [[ -x "$REPO_ROOT/.venv/bin/poe-bulk-export" ]]; then
    POE_BIN="$REPO_ROOT/.venv/bin/poe-bulk-export"
  elif command -v poe-bulk-export >/dev/null 2>&1; then
    POE_BIN="$(command -v poe-bulk-export)"
  else
    _red "poe-bulk-export is not installed."
    _red "Double-click \"Setup.command\" once, or run:"
    _red "  python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/playwright install chromium"
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
  _green "Using: $POE_BIN"
  "$POE_BIN" "$@"
}

pause_at_end() {
  echo
  read -r -p "Press Return to close…" _
}
