#!/usr/bin/env bash
# Namma Agent - uninstaller (macOS & Linux).
#
# Launched by the in-app "Uninstall" button (Settings -> About -> Danger zone).
#
#   --install-dir <path>   the app folder to remove (default: this script's ../..)
#   --scope all|keep-data  'all' wipes everything; 'keep-data' backs up chats/config first
#
# Re-execs a copy from /tmp so it can delete its own install folder while the app exits.
set -uo pipefail

INSTALL_DIR=""
SCOPE="all"
RELAUNCHED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --scope)       SCOPE="$2"; shift 2 ;;
    --relaunched)  RELAUNCHED=1; shift ;;
    *) shift ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -z "$INSTALL_DIR" ] && INSTALL_DIR="$(cd "$HERE/.." && pwd)"

# stage 1: re-exec from /tmp so we can delete INSTALL_DIR (including this script).
if [ "$RELAUNCHED" = "0" ]; then
  TMP="/tmp/namma-uninstall.sh"
  cp -f "${BASH_SOURCE[0]}" "$TMP"
  chmod +x "$TMP"
  nohup bash "$TMP" --install-dir "$INSTALL_DIR" --scope "$SCOPE" --relaunched >/dev/null 2>&1 &
  exit 0
fi

# stage 2: do the removal.
sleep 1
# Stop the running app (match `-m namma_agent` from THIS install).
pkill -f "namma_agent.*$INSTALL_DIR" 2>/dev/null || \
  ps aux | grep -F "$INSTALL_DIR" | grep namma_agent | grep -v grep | awk '{print $2}' | xargs -r kill -9
sleep 1

# keep-data: back up chats + config first.
if [ "$SCOPE" = "keep-data" ]; then
  BACKUP="$HOME/.namma_agent/backup"
  mkdir -p "$BACKUP"
  for rel in data .env namma_agent/config.local.yaml; do
    [ -e "$INSTALL_DIR/$rel" ] && { mkdir -p "$BACKUP/$(dirname "$rel")"; cp -rf "$INSTALL_DIR/$rel" "$BACKUP/$rel"; }
  done
fi

# Remove launchers (desktop entry, macOS .command, and the on-PATH `namma` command).
rm -f "$HOME/.local/share/applications/namma-agent.desktop" 2>/dev/null
rm -f "$INSTALL_DIR/Namma Agent.command" 2>/dev/null
rm -f "$HOME/.local/bin/namma" 2>/dev/null

# Remove the install folder.
rm -rf "$INSTALL_DIR"

# 'all' also wipes the per-user data dir (preserve the backup we just made for keep-data).
if [ "$SCOPE" = "all" ]; then
  rm -rf "$HOME/.namma_agent"
fi

echo "Namma Agent has been uninstalled."
