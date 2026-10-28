#!/bin/bash
# Re-export only chats that changed since the last complete export-chat run.
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== Export changed chats only (incremental, export-chat → poe_exports/) ==="
poe_run export --style export-chat -o poe_exports --incremental
pause_at_end
