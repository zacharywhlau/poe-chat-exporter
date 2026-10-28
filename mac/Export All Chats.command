#!/bin/bash
# Preferred full export: @export-chat layout into ./poe_exports
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== Export every chat (export-chat style → poe_exports/) ==="
echo "Thinking blocks are kept. This can take a while."
echo
poe_run export --style export-chat -o poe_exports
pause_at_end
