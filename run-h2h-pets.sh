#!/usr/bin/env bash
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$APP_DIR" || exit 1

show_error() {
  echo "$1" >&2
  if [ -n "${DISPLAY:-}" ] && command -v zenity >/dev/null 2>&1; then
    zenity --error --title="H2H Pets" --text="$1" >/dev/null 2>&1 || true
  fi
}

if ! python3 -c "import cairo, gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; from PIL import Image" >/dev/null 2>&1; then
  show_error "H2H Pets requires Python 3, GTK3 PyGObject, Cairo, and Pillow."
  exit 1
fi

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  echo "Warning: use an Ubuntu on Xorg session for complete desktop movement support." >&2
fi

exec python3 "$APP_DIR/h2h_pets.py" "$@"
