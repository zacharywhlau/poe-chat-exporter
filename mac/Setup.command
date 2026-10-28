#!/bin/bash
# Optional: force a clean reinstall of .venv (common helpers also auto-setup).
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== Poe exporter setup (forced reinstall) ==="
echo "Project: $REPO_ROOT"
echo

rm -rf .venv
ensure_install

if [[ ! -f .env ]]; then
  cp .env.example .env
  _green "Created .env — edit it and paste your p-b cookie as POE_TOKEN=..."
else
  _green ".env already exists (left unchanged)."
fi

echo
_green "Setup done. You can use List Chats / Export All Chats next."
"$POE_PYTHON" -m poe_bulk_export --version 2>/dev/null || true
pause_at_end
