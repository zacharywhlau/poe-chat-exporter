#!/bin/bash
# List every conversation (bot, title, chat code).
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

echo "=== List chats ==="
poe_run list
pause_at_end
