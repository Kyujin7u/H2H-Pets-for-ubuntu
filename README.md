# H2H Pets for Ubuntu

Native Ubuntu/X11 port of the H2H Pets Windows application. It uses GTK3 and
reads the original PNG sprite sheets directly from `h2h-pets-assets.pak`.

## Run

Double-click `h2h-pets.desktop`, or run:

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

## Controls

- Drag a pet to move it; horizontal dragging switches running direction.
- Click a pet to jump.
- Scroll over a pet to scale it between 25% and 60%.
- Right-click or double-click to open the control panel.
- Press `1` through `9` to select an action, or `Space` to cycle actions.
- Press `Esc` to quit.

The control panel manages visible pets, names, bubble lines, actions, bubbles,
always-on-top, patrol mode, and position reset. Settings are stored in
`settings.json` next to the application.

## Platform notes

Ubuntu 20.04 already provides the required Python 3, GTK3, Cairo, and Pillow
components on the target machine. X11 is the supported desktop session.
Wayland can restrict absolute window positioning, patrol movement, and
always-on-top behavior.

The tray uses GTK's compatibility status icon. Some GNOME configurations hide
legacy status icons; right-clicking any visible pet still opens every control.
