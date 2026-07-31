# H2H Pets for Ubuntu

Native Ubuntu/X11 port of the H2H Pets Windows application. It uses GTK3 and
reads the original PNG sprite sheets directly from `h2h-pets-assets.pak`.

## Run

Run directly from the cloned directory:

```bash
./run-h2h-pets.sh
```

Show all nine pets:

```bash
./run-h2h-pets.sh --show-all
```

Validate the installation without opening a window:

```bash
./run-h2h-pets.sh --check
```

## Install

Create a portable current-user application menu entry:

```bash
./install.sh
```

Install and start H2H Pets automatically after login:

```bash
./install.sh --autostart
```

The installer generates the desktop entry from the actual clone path. It does
not contain a repository path or user name. Remove the menu entry with
`./uninstall.sh`. Use `./uninstall.sh --purge` only when settings should also be
deleted.

## Controls

- Drag a pet to move it; horizontal dragging switches running direction.
- Click a pet to jump.
- Scroll over a pet to scale it between 25% and 100%.
- Right-click or double-click to open the control panel.
- Press `1` through `9` to select an action, or `Space` to cycle actions.
- Press `Esc` to quit.

The control panel manages visible pets, names, bubble lines, per-pet size and
bubbles, actions, position, always-on-top, patrol speed and direction, and
position reset. Settings are stored in `~/.config/h2h-pets/settings.json` (or
under `$XDG_CONFIG_HOME` when set). Existing settings next to the application
are migrated automatically. The instance lock is stored in `$XDG_RUNTIME_DIR`.

## Platform notes

Ubuntu 20.04 already provides the required Python 3, GTK3, Cairo, and Pillow
components on the target machine. X11 is the supported desktop session.
Wayland can restrict absolute window positioning, patrol movement, and
always-on-top behavior.

The tray prefers Ayatana AppIndicator or AppIndicator when installed and falls
back to GTK's compatibility status icon. Some GNOME configurations hide legacy
status icons; right-clicking any visible pet still opens every control.

Rendered frames, Pixbufs, and transparent input regions use a bounded cache to
reduce animation CPU usage without allowing memory use to grow indefinitely.
Startup failures are reported in a graphical dialog when a desktop is available.
