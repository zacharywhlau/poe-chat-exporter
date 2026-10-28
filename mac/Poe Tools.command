#!/bin/bash
# Small menu of the usual actions (same as the other .command files).
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./_lib.sh

while true; do
  clear 2>/dev/null || true
  echo "=== Poe chat exporter ==="
  echo "Project: $REPO_ROOT"
  echo
  echo "  1) List chats"
  echo "  2) Export every chat   (preferred: --style export-chat → poe_exports/)"
  echo "  3) Export changed only (incremental)"
  echo "  4) Export one chat by code/URL"
  echo "  5) Force reinstall .venv (optional; 1–4 already auto-setup)"
  echo "  q) Quit"
  echo
  read -r -p "Choose: " CHOICE
  case "$CHOICE" in
    1)
      poe_run list
      pause_at_end
      ;;
    2)
      echo "Thinking blocks are kept. This can take a while."
      poe_run export --style export-chat -o poe_exports
      pause_at_end
      ;;
    3)
      poe_run export --style export-chat -o poe_exports --incremental
      pause_at_end
      ;;
    4)
      read -r -p "Chat code or URL: " CODE
      if [[ -z "${CODE// /}" ]]; then
        _red "No chat code entered."
        pause_at_end
        continue
      fi
      poe_run export --style export-chat -o poe_exports --chat-code "$CODE"
      pause_at_end
      ;;
    5)
      rm -rf "$REPO_ROOT/.venv"
      ensure_install
      _green "Reinstall done."
      pause_at_end
      ;;
    q|Q)
      exit 0
      ;;
    *)
      _red "Unknown choice."
      pause_at_end
      ;;
  esac
done
