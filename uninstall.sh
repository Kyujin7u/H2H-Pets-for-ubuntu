#!/usr/bin/env bash
set -eu

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
LAUNCHER="${HOME}/.local/bin/h2h-pets"
DESKTOP_FILE="${DATA_HOME}/applications/h2h-pets.desktop"
AUTOSTART_FILE="${CONFIG_HOME}/autostart/h2h-pets.desktop"
ICON_FILE="${DATA_HOME}/icons/h2h-pets.ico"
PURGE=false

case "${1:-}" in
  "") ;;
  --purge) PURGE=true ;;
  *) echo "Usage: ./uninstall.sh [--purge]" >&2; exit 2 ;;
esac

if [ -L "$LAUNCHER" ]; then
  rm -f "$LAUNCHER"
elif [ -e "$LAUNCHER" ]; then
  echo "Preserved unrelated non-symlink file: $LAUNCHER" >&2
fi

rm -f "$DESKTOP_FILE" "$AUTOSTART_FILE" "$ICON_FILE"

if [ "$PURGE" = true ]; then
  rm -f "${CONFIG_HOME}/h2h-pets/settings.json"
  rmdir "${CONFIG_HOME}/h2h-pets" 2>/dev/null || true
  echo "H2H Pets uninstalled and settings removed."
else
  echo "H2H Pets uninstalled. Settings were preserved."
fi
