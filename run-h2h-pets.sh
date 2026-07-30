#!/usr/bin/env bash
set -u

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$APP_DIR" || exit 1

if ! python3 -c "import cairo, gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; from PIL import Image" >/dev/null 2>&1; then
  echo "H2H Pets requires Python 3, GTK3 PyGObject, Cairo, and Pillow." >&2
  exit 1
fi

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  echo "Warning: use an Ubuntu on Xorg session for complete desktop movement support." >&2
fi

exec python3 "$APP_DIR/h2h_pets.py" "$@"
