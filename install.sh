#!/usr/bin/env bash
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
APPLICATION_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons"
AUTOSTART_DIR="${CONFIG_HOME}/autostart"
LAUNCHER="${BIN_DIR}/h2h-pets"
DESKTOP_FILE="${APPLICATION_DIR}/h2h-pets.desktop"
ICON_FILE="${ICON_DIR}/h2h-pets.ico"
ENABLE_AUTOSTART=false

case "${1:-}" in
  "") ;;
  --autostart) ENABLE_AUTOSTART=true ;;
  *) echo "Usage: ./install.sh [--autostart]" >&2; exit 2 ;;
esac

if ! env PYTHONDONTWRITEBYTECODE=1 "${APP_DIR}/run-h2h-pets.sh" --check; then
  echo "Installation stopped because the application check failed." >&2
  exit 1
fi

if [ -e "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
  echo "Refusing to replace non-symlink file: $LAUNCHER" >&2
  exit 1
fi

mkdir -p "$BIN_DIR" "$APPLICATION_DIR" "$ICON_DIR"
ln -sfn "${APP_DIR}/run-h2h-pets.sh" "$LAUNCHER"
cp "${APP_DIR}/icon.ico" "$ICON_FILE"

cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=H2H Pets
Comment=Animated desktop pets
Exec=${LAUNCHER}
Icon=${ICON_FILE}
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
chmod +x "$DESKTOP_FILE"

if [ "$ENABLE_AUTOSTART" = true ]; then
  mkdir -p "$AUTOSTART_DIR"
  cp "$DESKTOP_FILE" "${AUTOSTART_DIR}/h2h-pets.desktop"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATION_DIR" >/dev/null 2>&1 || true
fi

echo "H2H Pets installed for the current user."
if [ "$ENABLE_AUTOSTART" = true ]; then
  echo "Autostart enabled."
else
  echo "Run ./install.sh --autostart to enable autostart."
fi
