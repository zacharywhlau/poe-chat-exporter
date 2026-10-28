# Shared setup for the double-clickable Mac helpers in this folder.
# Ensures .venv + package install before every common action.
# shellcheck shell=bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

_red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_dim() { printf '\033[2m%s\033[0m\n' "$*"; }

_builder_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif [[ -x /opt/anaconda3/bin/python ]]; then
    echo /opt/anaconda3/bin/python
  elif [[ -x /usr/local/bin/python3 ]]; then
    echo /usr/local/bin/python3
  else
    return 1
  fi
}

_venv_ok() {
  [[ -x "$REPO_ROOT/.venv/bin/python" ]] \
    && "$REPO_ROOT/.venv/bin/python" -c "import poe_bulk_export" 2>/dev/null
}

ensure_install() {
  if _venv_ok; then
    POE_PYTHON="$REPO_ROOT/.venv/bin/python"
    return 0
  fi

  local py
  if ! py="$(_builder_python)"; then
    _red "No python3 found. Install Python 3.10+ (or Anaconda) and try again."
    exit 1
  fi

  _dim "Project environment missing or broken — setting up .venv automatically…"
  _dim "Builder: $py ($("$py" --version 2>&1))"
  rm -rf .venv
  "$py" -m venv .venv
  .venv/bin/python -m pip install -U pip
  .venv/bin/python -m pip install -e .
  .venv/bin/playwright install chromium

  if ! _venv_ok; then
    _red "Automatic setup failed: still cannot import poe_bulk_export."
    exit 1
  fi

  POE_PYTHON="$REPO_ROOT/.venv/bin/python"
  _green "Setup complete."
}

ensure_env_file() {
  if [[ ! -f "$REPO_ROOT/.env" ]]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    _red "Created .env from .env.example."
    _red "Edit .env, paste your p-b cookie as POE_TOKEN=..., save, then run this again."
    exit 1
  fi

  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a

  if [[ -z "${POE_TOKEN:-}" || "$POE_TOKEN" == "your_p-b_cookie_value_here" ]]; then
    _red "POE_TOKEN is not set in .env."
    _red "Edit .env and paste your p-b cookie, then run again."
    exit 1
  fi
}

poe_setup() {
  ensure_install
  ensure_env_file
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
