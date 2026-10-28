#!/bin/bash
# Export a single chat by code or URL (export-chat style → poe_exports/).
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== Export one chat ==="
read -r -p "Chat code or URL: " CODE
if [[ -z "${CODE// /}" ]]; then
  _red "No chat code entered."
  pause_at_end
  exit 1
fi

poe_run export --style export-chat -o poe_exports --chat-code "$CODE"
pause_at_end
