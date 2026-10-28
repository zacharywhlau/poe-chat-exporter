#!/bin/bash
# One-time (or after moving the folder): recreate .venv and install the CLI.
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== Poe exporter setup ==="
echo "Project: $REPO_ROOT"
echo

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif [[ -x /opt/anaconda3/bin/python ]]; then
  PY=/opt/anaconda3/bin/python
else
  _red "No python3 found. Install Python 3.10+ (or Anaconda) and try again."
  pause_at_end
  exit 1
fi

echo "Using builder: $PY ($("$PY" --version 2>&1))"
echo "Removing old .venv (if any)…"
rm -rf .venv

"$PY" -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
.venv/bin/playwright install chromium

if ! .venv/bin/python -c "import poe_bulk_export"; then
  _red "Install finished but import still fails."
  pause_at_end
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  _green "Created .env — edit it and paste your p-b cookie as POE_TOKEN=..."
else
  _green ".env already exists (left unchanged)."
fi

echo
_green "Setup done. Next: use List Chats or Export All Chats."
.venv/bin/python -m poe_bulk_export --version 2>/dev/null || true
pause_at_end
