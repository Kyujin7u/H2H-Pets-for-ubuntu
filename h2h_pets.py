#!/usr/bin/env python3
"""Native GTK3 desktop pets for Ubuntu X11."""

import argparse
import fcntl
import io
import json
import math
import os
import random
import sys
import warnings
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
from PIL import Image, ImageDraw, ImageFont

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ImportError, ValueError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except (ImportError, ValueError):
        AppIndicator = None

warnings.filterwarnings(
    "ignore", category=DeprecationWarning, message=r"Gtk\.StatusIcon\..* is deprecated"
)


APP_DIR = Path(__file__).resolve().parent
ASSET_PATH = APP_DIR / "h2h-pets-assets.pak"
LEGACY_SETTINGS_PATH = APP_DIR / "settings.json"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
CONFIG_DIR = CONFIG_HOME / "h2h-pets"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR")
LOCK_PATH = (
    Path(RUNTIME_DIR) / "h2h-pets.lock"
    if RUNTIME_DIR
    else Path("/tmp") / "h2h-pets-{}.lock".format(os.getuid())
)
ICON_PATH = APP_DIR / "icon.ico"
CELL_WIDTH = 192
CELL_HEIGHT = 208
MIN_SCALE = 0.25
DEFAULT_SCALE = 0.60
MAX_SCALE = 1.00
MAX_SCENE_CACHE = 16
PATROL_PROFILES = {
    "slow": (4500, 8500, 3, 30),
    "normal": (2800, 6500, 5, 20),
    "fast": (1800, 4000, 8, 14),
}
PATROL_DIRECTIONS = ("random", "left", "right")


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    row: int
    frames: int
    fps: int


@dataclass(frozen=True)
class Pet:
    pet_id: str
    name: str
    entry: str
    bubble_lines: tuple
    primary: str
    accent: str


@dataclass(frozen=True)
class RenderedScene:
    image: object
    pixbuf: object
    region: object


ACTIONS = (
    Action("idle", "Idle", 0, 6, 4),
    Action("running-right", "Right", 1, 8, 10),
    Action("running-left", "Left", 2, 8, 10),
    Action("waving", "Wave", 3, 4, 6),
    Action("jumping", "Jump", 4, 5, 7),
    Action("failed", "Fail", 5, 8, 8),
    Action("waiting", "Wait", 6, 6, 4),
    Action("running", "Busy", 7, 6, 8),
    Action("review", "Review", 8, 6, 5),
)
PATROL_AMBIENT_ACTIONS = (
    "idle",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review",
)

PETS = (
    Pet("carmen", "bingping", "carmen\\final\\spritesheet.png", ("bingping is running!",), "#eef8ff", "#3b91c9"),
    Pet("jiwoo", "jjoojebi", "jiwoo\\final\\spritesheet.png", ("jjoojebi is running!",), "#f7f2ff", "#7254a8"),
    Pet("yuha", "toramui", "yuha\\final\\spritesheet.png", ("toramui is running!",), "#f6f0eb", "#765334"),
    Pet("stella", "stellnyang", "stella\\final\\spritesheet.png", ("stellnyang is running!",), "#fff1f7", "#a14c77"),
    Pet("juun", "jjuuilien", "juun\\final\\spritesheet.png", ("jjuuilien is running!",), "#f4fbf7", "#3b7b57"),
    Pet("ana", "nosoongee", "ana\\final\\spritesheet.png", ("nosoongee is running!",), "#fff8e8", "#8a631e"),
    Pet("ian", "jeongddangkong", "ian\\final\\spritesheet.png", ("jeongddangkong is running!",), "#edf8f8", "#2f7472"),
    Pet("yeon", "alssonghamssong", "yeon\\final\\spritesheet.png", ("alssonghamssong is running!",), "#f3f7ff", "#3b669c"),
    Pet("fans", "falabella", "fans\\final\\spritesheet.png", ("falabella is running!",), "#f8f4ef", "#805e3c"),
)
PET_MAP = {pet.pet_id: pet for pet in PETS}


def clamp_scale(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    if not math.isfinite(value):
        return DEFAULT_SCALE
    return max(MIN_SCALE, min(MAX_SCALE, value))


def default_settings():
    return {
        "always_on_top": True,
        "bubbles_enabled": True,
        "patrol_mode": False,
        "patrol_speed": "normal",
        "patrol_direction": "random",
        "active_pet_ids": ["carmen"],
        "pets": {},
    }


def normalize_settings(raw):
    settings = default_settings()
    if not isinstance(raw, dict):
        return settings
    for key in ("always_on_top", "bubbles_enabled", "patrol_mode"):
        if isinstance(raw.get(key), bool):
            settings[key] = raw[key]
    if raw.get("patrol_speed") in PATROL_PROFILES:
        settings["patrol_speed"] = raw["patrol_speed"]
    if raw.get("patrol_direction") in PATROL_DIRECTIONS:
        settings["patrol_direction"] = raw["patrol_direction"]
    active = raw.get("active_pet_ids")
    if isinstance(active, list):
        settings["active_pet_ids"] = []
        for pet_id in active:
            if pet_id in PET_MAP and pet_id not in settings["active_pet_ids"]:
                settings["active_pet_ids"].append(pet_id)
    pets = raw.get("pets")
    if isinstance(pets, dict):
        for pet_id, value in pets.items():
            if pet_id not in PET_MAP or not isinstance(value, dict):
                continue
            lines = value.get("bubble_lines", [])
            if not isinstance(lines, list):
                lines = []
            bubble_enabled = value.get("bubble_enabled", True)
            if not isinstance(bubble_enabled, bool):
                bubble_enabled = True
            settings["pets"][pet_id] = {
                "display_name": str(value.get("display_name", "")).strip(),
                "bubble_lines": [str(line).strip() for line in lines if str(line).strip()],
                "scale": clamp_scale(value.get("scale", DEFAULT_SCALE)),
                "bubble_enabled": bubble_enabled,
                "x": value.get("x") if isinstance(value.get("x"), int) else None,
                "y": value.get("y") if isinstance(value.get("y"), int) else None,
            }
    return settings


def load_settings(path=None, legacy_path=None):
    target = Path(path) if path is not None else SETTINGS_PATH
    legacy = Path(legacy_path) if legacy_path is not None else LEGACY_SETTINGS_PATH
    source = target if target.is_file() else legacy
    try:
        with source.open("r", encoding="utf-8") as handle:
            settings = normalize_settings(json.load(handle))
    except (OSError, ValueError):
        return default_settings()
    if source == legacy and target != legacy:
        save_settings(settings, target)
    return settings


def save_settings(settings, path=None):
    target = Path(path) if path is not None else SETTINGS_PATH
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(str(temporary), str(target))
        return True
    except OSError as error:
        print("Could not save settings: {}".format(error), file=sys.stderr)
        try:
            temporary.unlink()
        except OSError:
            pass
        return False


class SpriteStore:
    def __init__(self, path=ASSET_PATH, alpha_threshold=4, edge_padding=2):
        self.path = Path(path)
        self.alpha_threshold = max(1, min(255, int(alpha_threshold)))
        self.edge_padding = max(0, min(32, int(edge_padding)))
        self.sheets = {}

    def validate(self):
        if not self.path.is_file():
            raise FileNotFoundError("Asset pack not found: {}".format(self.path))
        with zipfile.ZipFile(str(self.path), "r") as archive:
            normalized = {name.replace("/", "\\") for name in archive.namelist()}
            missing = [pet.entry for pet in PETS if pet.entry not in normalized]
        if missing:
            raise ValueError("Asset pack is missing: {}".format(", ".join(missing)))

    def load_sheet(self, pet):
        if pet.pet_id in self.sheets:
            return self.sheets[pet.pet_id]
        with zipfile.ZipFile(str(self.path), "r") as archive:
            names = {name.replace("/", "\\"): name for name in archive.namelist()}
            actual_name = names.get(pet.entry)
            if actual_name is None:
                raise FileNotFoundError("Sprite not found in pack: {}".format(pet.entry))
            with archive.open(actual_name, "r") as source:
                sheet = Image.open(io.BytesIO(source.read())).convert("RGBA")
        if sheet.size != (CELL_WIDTH * 8, CELL_HEIGHT * 9):
            raise ValueError("Unexpected sprite size for {}: {}".format(pet.pet_id, sheet.size))
        self.sheets[pet.pet_id] = sheet
        return sheet

    def build_frame(self, pet, action, column, scale):
        sheet = self.load_sheet(pet)
        left = column * CELL_WIDTH
        top = action.row * CELL_HEIGHT
        cell = sheet.crop((left, top, left + CELL_WIDTH, top + CELL_HEIGHT))
        alpha = cell.getchannel("A")
        mask = alpha.point(lambda value: 255 if value >= self.alpha_threshold else 0)
        bounds = mask.getbbox() or (0, 0, CELL_WIDTH, CELL_HEIGHT)
        bounds = (
            max(0, bounds[0] - self.edge_padding),
            max(0, bounds[1] - self.edge_padding),
            min(CELL_WIDTH, bounds[2] + self.edge_padding),
            min(CELL_HEIGHT, bounds[3] + self.edge_padding),
        )
        frame = cell.crop(bounds)
        effective_scale = scale * 0.9 if action.name == "jumping" else scale
        width = max(1, int(math.ceil(frame.width * effective_scale)))
        height = max(1, int(math.ceil(frame.height * effective_scale)))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        return frame.resize((width, height), resampling)


def load_font(size):
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose_scene(frame, text, accent, scale, bubbles_enabled, alpha_threshold=4):
    if not bubbles_enabled:
        return crop_alpha(frame.copy(), alpha_threshold)
    font = load_font(max(9, int(round(18 * scale))))
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    text_width, text_height = probe_draw.textsize(text, font=font)
    gap = max(1, int(round(10 * scale)))
    pad_x = max(4, int(round(14 * scale)))
    pad_y = max(3, int(round(9 * scale)))
    bubble_width = max(int(round(72 * scale)), text_width + pad_x * 2)
    bubble_height = max(int(round(36 * scale)), text_height + pad_y * 2)
    tail_height = max(4, int(round(9 * scale)))
    scene_width = max(frame.width, bubble_width + max(4, int(round(18 * scale))))
    scene_height = bubble_height + tail_height + gap + frame.height
    scene = Image.new("RGBA", (scene_width, scene_height), (0, 0, 0, 0))
    pet_x = (scene_width - frame.width) // 2
    pet_y = bubble_height + tail_height + gap
    scene.alpha_composite(frame, (pet_x, pet_y))
    draw = ImageDraw.Draw(scene)
    bubble_x = max(0, pet_x + frame.width - bubble_width)
    rect = (bubble_x, 0, bubble_x + bubble_width - 1, bubble_height - 1)
    radius = max(4, int(round(12 * scale)))
    border_width = max(1, int(round(1.5 * scale)))
    draw_rounded_rectangle(draw, rect, radius, (255, 255, 255, 240), accent, border_width)
    tail_target = pet_x + frame.width // 2
    tail_x = max(bubble_x + 8, min(bubble_x + bubble_width - 8, tail_target))
    tail = ((tail_x - 4, bubble_height - 1), (tail_x + 4, bubble_height - 1), (tail_x, bubble_height + tail_height - 1))
    draw.polygon(tail, fill=(255, 255, 255, 240), outline=accent)
    text_x = bubble_x + (bubble_width - text_width) // 2
    text_y = (bubble_height - text_height) // 2
    draw.text((text_x, text_y), text, font=font, fill=(31, 35, 42, 245))
    return crop_alpha(scene, alpha_threshold)


def draw_rounded_rectangle(draw, rect, radius, fill, outline, width):
    left, top, right, bottom = rect
    radius = min(radius, (right - left + 1) // 2, (bottom - top + 1) // 2)
    for inset in range(max(1, width)):
        current = (left + inset, top + inset, right - inset, bottom - inset)
        current_radius = max(1, radius - inset)
        color = outline if inset < width else fill
        draw.pieslice(
            (current[0], current[1], current[0] + current_radius * 2, current[1] + current_radius * 2),
            180,
            270,
            fill=color,
        )
        draw.pieslice(
            (current[2] - current_radius * 2, current[1], current[2], current[1] + current_radius * 2),
            270,
            360,
            fill=color,
        )
        draw.pieslice(
            (current[2] - current_radius * 2, current[3] - current_radius * 2, current[2], current[3]),
            0,
            90,
            fill=color,
        )
        draw.pieslice(
            (current[0], current[3] - current_radius * 2, current[0] + current_radius * 2, current[3]),
            90,
            180,
            fill=color,
        )
        draw.rectangle((current[0] + current_radius, current[1], current[2] - current_radius, current[3]), fill=color)
        draw.rectangle((current[0], current[1] + current_radius, current[2], current[3] - current_radius), fill=color)
    inner = (left + width, top + width, right - width, bottom - width)
    if inner[2] > inner[0] and inner[3] > inner[1]:
        inner_radius = max(1, radius - width)
        draw_rounded_rectangle(draw, inner, inner_radius, fill, fill, 1) if outline != fill else None


def crop_alpha(image, threshold):
    mask = image.getchannel("A").point(lambda value: 255 if value >= threshold else 0)
    bounds = mask.getbbox()
    return image.crop(bounds) if bounds else image


def image_to_pixbuf(image):
    rgba = image.convert("RGBA")
    data = GLib.Bytes.new(rgba.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(
        data, GdkPixbuf.Colorspace.RGB, True, 8, rgba.width, rgba.height, rgba.width * 4
    )


def alpha_region(image, threshold=12):
    alpha = image.getchannel("A")
    pixels = alpha.load()
    region = cairo.Region()
    for y in range(image.height):
        x = 0
        while x < image.width:
            while x < image.width and pixels[x, y] < threshold:
                x += 1
            if x >= image.width:
                break
            start = x
            while x < image.width and pixels[x, y] >= threshold:
                x += 1
            region.union(cairo.RectangleInt(start, y, x - start, 1))
    if region.is_empty():
        region.union(cairo.RectangleInt(0, 0, image.width, image.height))
    return region


class PetWindow(Gtk.Window):
    def __init__(self, manager, pet, index):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.manager = manager
        self.pet = pet
        self.pet_settings = manager.pet_settings(pet.pet_id)
        self.index = index
        self.action_index = 0
        self.frame_index = 0
        self.bubble_index = 0
        self.frame_cache = {}
        self.scene_cache = OrderedDict()
        self.current_frame = None
        self.current_scene = None
        self.current_pixbuf = None
        self.current_region = None
        self.dragging = False
        self.drag_moved = False
        self.drag_start_pointer = (0, 0)
        self.drag_start_center = (0, 0)
        self.frame_source = None
        self.bubble_source = None
        self.reset_source = None
        self.patrol_source = None
        self.patrol_move_source = None
        self.patrol_steps = 0
        self.patrol_step_x = 0.0
        self.patrol_step_y = 0.0
        self.patrol_position_x = 0.0
        self.patrol_position_y = 0.0

        saved_x = self.pet_settings.get("x")
        saved_y = self.pet_settings.get("y")
        self.bottom_center = (
            (saved_x, saved_y)
            if isinstance(saved_x, int) and isinstance(saved_y, int)
            else manager.default_bottom_center(index)
        )

        self.set_title("H2H Pets - {}".format(pet.name))
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(manager.settings["always_on_top"])
        self.set_app_paintable(True)
        self.set_accept_focus(True)
        self.set_resizable(False)
        self.set_default_size(1, 1)
        self.connect("screen-changed", self._configure_visual)
        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", self._on_delete)
        self._configure_visual(self, None)

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_can_focus(True)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
        )
        self.canvas.connect("draw", self._on_draw)
        self.canvas.connect("button-press-event", self._on_button_press)
        self.canvas.connect("button-release-event", self._on_button_release)
        self.canvas.connect("motion-notify-event", self._on_motion)
        self.canvas.connect("scroll-event", self._on_scroll)
        self.add(self.canvas)

    @property
    def action(self):
        return ACTIONS[self.action_index]

    def _configure_visual(self, widget, old_screen):
        del widget, old_screen
        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        if visual is not None:
            self.set_visual(visual)

    def start(self):
        self.show_all()
        self.canvas.grab_focus()
        self._apply_current_frame()
        self._start_frame_timer()
        self.bubble_source = GLib.timeout_add(7000, self._cycle_bubble)
        self.apply_patrol_mode()

    def stop(self):
        for name in ("frame_source", "bubble_source", "reset_source", "patrol_source", "patrol_move_source"):
            source = getattr(self, name)
            if source is not None:
                GLib.source_remove(source)
                setattr(self, name, None)
        self._store_position()
        self.destroy()

    def _on_delete(self, *unused):
        self.manager.hide_pet(self.pet.pet_id)
        return True

    def _on_draw(self, widget, context):
        del widget
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        if self.current_pixbuf is not None:
            Gdk.cairo_set_source_pixbuf(context, self.current_pixbuf, 0, 0)
            context.paint()
        return False

    def _on_button_press(self, widget, event):
        del widget
        self.canvas.grab_focus()
        if event.button == 3 or event.type == Gdk.EventType._2BUTTON_PRESS:
            self.manager.open_control_panel(self.pet.pet_id)
            return True
        if event.button != 1:
            return False
        self.dragging = True
        self.drag_moved = False
        self._cancel_source("reset_source")
        self._cancel_source("patrol_source")
        self._cancel_source("patrol_move_source")
        self.patrol_steps = 0
        self.drag_start_pointer = (int(event.x_root), int(event.y_root))
        self.drag_start_center = self.bottom_center
        return True

    def _on_motion(self, widget, event):
        del widget
        if not self.dragging:
            return False
        dx = int(event.x_root) - self.drag_start_pointer[0]
        dy = int(event.y_root) - self.drag_start_pointer[1]
        self.bottom_center = (self.drag_start_center[0] + dx, self.drag_start_center[1] + dy)
        self.drag_moved = abs(dx) > 3 or abs(dy) > 3
        self._store_position()
        if dx > 3:
            self.set_action("running-right")
        elif dx < -3:
            self.set_action("running-left")
        else:
            self._place_window()
        return True

    def _on_button_release(self, widget, event):
        del widget
        if event.button != 1 or not self.dragging:
            return False
        self.dragging = False
        self.manager.save()
        if self.drag_moved:
            if self.manager.settings["patrol_mode"]:
                self._enter_patrol_rest()
            else:
                self.set_action("idle")
        else:
            self.activate_action("jumping")
        return True

    def _on_scroll(self, widget, event):
        del widget
        increase = event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.RIGHT)
        delta = 0.05 if increase else -0.05
        self.set_scale(self.pet_settings["scale"] + delta)
        return True

    def _on_key_press(self, widget, event):
        del widget
        if event.keyval == Gdk.KEY_Escape:
            self.manager.quit()
            return True
        if event.keyval == Gdk.KEY_space:
            self._set_action_index((self.action_index + 1) % len(ACTIONS))
            return True
        if Gdk.KEY_1 <= event.keyval <= Gdk.KEY_9:
            self._set_action_index(event.keyval - Gdk.KEY_1)
            return True
        return False

    def _start_frame_timer(self):
        self._cancel_source("frame_source")
        interval = max(16, 1000 // self.action.fps)
        self.frame_source = GLib.timeout_add(interval, self._advance_frame)

    def _advance_frame(self):
        self.frame_index = (self.frame_index + 1) % self.action.frames
        self._apply_current_frame()
        return True

    def _cycle_bubble(self):
        lines = self.manager.bubble_lines(self.pet)
        if lines:
            self.bubble_index = (self.bubble_index + 1) % len(lines)
            self.refresh_scene()
        return True

    def activate_action(self, action_name):
        self.set_action(action_name)
        self._cycle_bubble()
        if action_name == "jumping":
            self._cancel_source("reset_source")
            self.reset_source = GLib.timeout_add(950, self._reset_to_idle)

    def set_action(self, action_name):
        for index, action in enumerate(ACTIONS):
            if action.name == action_name:
                self._set_action_index(index)
                return

    def _set_action_index(self, index):
        if not 0 <= index < len(ACTIONS):
            return
        self._cancel_source("reset_source")
        if self.action_index != index:
            self.action_index = index
            self.frame_index = 0
            self._start_frame_timer()
        self._apply_current_frame()
        self.manager.update_panel_status(self.pet.pet_id)

    def _reset_to_idle(self):
        self.reset_source = None
        if not self.dragging and self.patrol_steps <= 0:
            if self.manager.settings["patrol_mode"]:
                self._enter_patrol_rest()
            else:
                self.set_action("idle")
        return False

    def _frames(self):
        key = self.action.name
        if key not in self.frame_cache:
            scale = self.pet_settings["scale"]
            self.frame_cache[key] = [
                self.manager.store.build_frame(self.pet, self.action, index, scale)
                for index in range(self.action.frames)
            ]
        return self.frame_cache[key]

    def _apply_current_frame(self):
        frames = self._frames()
        self.current_frame = frames[self.frame_index % len(frames)]
        self.refresh_scene()

    def refresh_scene(self):
        if self.current_frame is None:
            return
        lines = self.manager.bubble_lines(self.pet)
        text = lines[self.bubble_index % len(lines)] if lines else self.manager.display_name(self.pet)
        bubbles_enabled = (
            self.manager.settings["bubbles_enabled"]
            and self.pet_settings.get("bubble_enabled", True)
        )
        cache_key = (
            self.action.name,
            self.frame_index % self.action.frames,
            text,
            round(self.pet_settings["scale"], 2),
            bubbles_enabled,
        )
        rendered = self.scene_cache.pop(cache_key, None)
        if rendered is None:
            scene = compose_scene(
                self.current_frame,
                text,
                self.pet.accent,
                self.pet_settings["scale"],
                bubbles_enabled,
            )
            rendered = RenderedScene(scene, image_to_pixbuf(scene), alpha_region(scene))
            if len(self.scene_cache) >= MAX_SCENE_CACHE:
                self.scene_cache.popitem(last=False)
        self.scene_cache[cache_key] = rendered
        self.current_scene = rendered.image
        self.current_pixbuf = rendered.pixbuf
        self.current_region = rendered.region
        self.canvas.set_size_request(self.current_scene.width, self.current_scene.height)
        self.resize(self.current_scene.width, self.current_scene.height)
        self._place_window()
        self.queue_draw()
        gdk_window = self.get_window()
        if gdk_window is not None:
            gdk_window.shape_combine_region(self.current_region, 0, 0)
            gdk_window.input_shape_combine_region(self.current_region, 0, 0)

    def invalidate_scene_cache(self):
        self.scene_cache.clear()

    def set_scale(self, value):
        next_scale = clamp_scale(value)
        if math.isclose(next_scale, self.pet_settings["scale"], abs_tol=0.001):
            return
        self.pet_settings["scale"] = next_scale
        self.frame_cache.clear()
        self.invalidate_scene_cache()
        self._apply_current_frame()
        self.manager.save()
        self.manager.update_panel_status(self.pet.pet_id)

    def _place_window(self):
        if self.current_scene is None:
            return
        jump = 0
        if self.action.name == "jumping":
            denominator = max(1, self.action.frames - 1)
            progress = max(0.0, min(1.0, self.frame_index / denominator))
            jump = int(round(math.sin(progress * math.pi) * max(1, round(32 * self.pet_settings["scale"]))))
        x = self.bottom_center[0] - self.current_scene.width // 2
        y = self.bottom_center[1] - self.current_scene.height - jump
        self.move(x, y)

    def apply_patrol_mode(self):
        self._cancel_source("patrol_source")
        self._cancel_source("patrol_move_source")
        self.patrol_steps = 0
        if self.manager.settings["patrol_mode"]:
            self._enter_patrol_rest()
        elif not self.dragging:
            self.set_action("idle")

    def _enter_patrol_rest(self):
        if not self.manager.settings["patrol_mode"] or self.dragging:
            return
        choices = [name for name in PATROL_AMBIENT_ACTIONS if name != self.action.name]
        self.set_action(random.choice(choices or PATROL_AMBIENT_ACTIONS))
        work = self.manager.work_area_at(self.bottom_center)
        left, right, top, bottom = self._patrol_bounds(work)
        self.bottom_center = (
            int(round(max(left, min(right, self.bottom_center[0])))),
            int(round(max(top, min(bottom, self.bottom_center[1])))),
        )
        self._store_position()
        self._place_window()
        self._schedule_patrol()

    def _patrol_bounds(self, work):
        width = self.current_scene.width if self.current_scene is not None else 1
        height = self.current_scene.height if self.current_scene is not None else 1
        padding = 8
        left = work.x + width // 2 + padding
        right = work.x + work.width - (width - width // 2) - padding
        jump_height = (
            max(1, round(32 * self.pet_settings["scale"]))
            if self.action.name == "jumping"
            else 0
        )
        top = work.y + height + jump_height + padding
        bottom = work.y + work.height - padding
        if left > right:
            left = right = work.x + work.width / 2
        if top > bottom:
            top = bottom = work.y + work.height - padding
        return float(left), float(right), float(top), float(bottom)

    def _schedule_patrol(self):
        self._cancel_source("patrol_source")
        if not self.manager.settings["patrol_mode"]:
            return
        minimum, maximum, unused_step, unused_interval = PATROL_PROFILES[
            self.manager.settings["patrol_speed"]
        ]
        self.patrol_source = GLib.timeout_add(random.randint(minimum, maximum), self._begin_patrol)

    def _begin_patrol(self):
        self.patrol_source = None
        if not self.manager.settings["patrol_mode"] or self.dragging:
            self._schedule_patrol()
            return False
        work = self.manager.work_area_at(self.bottom_center)
        configured_direction = self.manager.settings["patrol_direction"]
        if configured_direction == "left":
            direction = -1
        elif configured_direction == "right":
            direction = 1
        else:
            direction = random.choice((-1, 1))
        if self.bottom_center[0] < work.x + 120:
            direction = 1
        elif self.bottom_center[0] > work.x + work.width - 120:
            direction = -1
        vertical_direction = random.choice((-1, 1))
        if self.bottom_center[1] < work.y + 160:
            vertical_direction = 1
        elif self.bottom_center[1] > work.y + work.height - 120:
            vertical_direction = -1
        unused_minimum, unused_maximum, step, interval = PATROL_PROFILES[
            self.manager.settings["patrol_speed"]
        ]
        distance = max(1.0, step * self.pet_settings["scale"])
        vertical_ratio = vertical_direction * random.uniform(0.35, 1.0)
        magnitude = math.hypot(1.0, vertical_ratio)
        self.patrol_step_x = direction * distance / magnitude
        self.patrol_step_y = vertical_ratio * distance / magnitude
        self.patrol_position_x = float(self.bottom_center[0])
        self.patrol_position_y = float(self.bottom_center[1])
        self.patrol_steps = random.randint(20, 37)
        self.set_action("running-left" if direction < 0 else "running-right")
        self.patrol_move_source = GLib.timeout_add(interval, self._continue_patrol)
        return False

    def _continue_patrol(self):
        if self.dragging or self.patrol_steps <= 0:
            self.patrol_move_source = None
            self.patrol_steps = 0
            if not self.dragging:
                self._enter_patrol_rest()
            return False
        work = self.manager.work_area_at(self.bottom_center)
        left, right, top, bottom = self._patrol_bounds(work)
        next_x = self.patrol_position_x + self.patrol_step_x
        next_y = self.patrol_position_y + self.patrol_step_y
        if next_x < left or next_x > right:
            self.patrol_step_x = -self.patrol_step_x
            next_x = self.patrol_position_x + self.patrol_step_x
            self.set_action("running-left" if self.patrol_step_x < 0 else "running-right")
        if next_y < top or next_y > bottom:
            self.patrol_step_y = -self.patrol_step_y
            next_y = self.patrol_position_y + self.patrol_step_y
        self.patrol_position_x = max(left, min(right, next_x))
        self.patrol_position_y = max(top, min(bottom, next_y))
        self.bottom_center = (
            int(round(self.patrol_position_x)),
            int(round(self.patrol_position_y)),
        )
        self.patrol_steps -= 1
        self._store_position()
        self._place_window()
        return True

    def _store_position(self):
        self.pet_settings["x"], self.pet_settings["y"] = self.bottom_center

    def _cancel_source(self, name):
        source = getattr(self, name)
        if source is not None:
            GLib.source_remove(source)
            setattr(self, name, None)


class ControlPanel(Gtk.Window):
    def __init__(self, manager):
        super().__init__(title="H2H Pets Controls")
        self.manager = manager
        self.rendering = False
        self.set_default_size(560, 700)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self._hide_panel)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        active_label = Gtk.Label(label="Active Pets", xalign=0)
        active_label.get_style_context().add_class("heading")
        root.pack_start(active_label, False, False, 0)
        active_scroll = Gtk.ScrolledWindow()
        active_scroll.set_min_content_height(115)
        self.active_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        active_scroll.add(self.active_box)
        root.pack_start(active_scroll, False, True, 0)

        edit_label = Gtk.Label(label="Edit Pet", xalign=0)
        root.pack_start(edit_label, False, False, 0)
        self.pet_combo = Gtk.ComboBoxText()
        self.pet_combo.connect("changed", self._render_editor)
        root.pack_start(self.pet_combo, False, False, 0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.action_status = Gtk.Label(label="Action: Hidden", xalign=0)
        self.position_status = Gtk.Label(label="Position: Not set", xalign=0)
        status_box.pack_start(self.action_status, True, True, 0)
        status_box.pack_start(self.position_status, True, True, 0)
        root.pack_start(status_box, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("Display name")
        root.pack_start(self.name_entry, False, False, 0)
        bubble_scroll = Gtk.ScrolledWindow()
        bubble_scroll.set_min_content_height(90)
        self.bubble_view = Gtk.TextView()
        self.bubble_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        bubble_scroll.add(self.bubble_view)
        root.pack_start(bubble_scroll, True, True, 0)

        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        size_box.pack_start(Gtk.Label(label="Size", xalign=0), False, False, 0)
        self.size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, MIN_SCALE * 100, MAX_SCALE * 100, 5
        )
        self.size_scale.set_digits(0)
        self.size_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.size_scale.set_hexpand(True)
        self.size_scale.connect("value-changed", self._change_size)
        size_box.pack_start(self.size_scale, True, True, 0)
        reset_size = Gtk.Button(label="Default Size")
        reset_size.connect("clicked", self._reset_size)
        size_box.pack_start(reset_size, False, False, 0)
        root.pack_start(size_box, False, False, 0)

        self.pet_bubble_toggle = Gtk.CheckButton(label="Bubble for this pet")
        self.pet_bubble_toggle.connect("toggled", self._toggle_pet_bubble)
        root.pack_start(self.pet_bubble_toggle, False, False, 0)

        self.action_box = Gtk.FlowBox()
        self.action_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.action_box.set_max_children_per_line(5)
        for action in ACTIONS:
            button = Gtk.Button(label=action.label)
            button.connect("clicked", self._activate_action, action.name)
            self.action_box.add(button)
        root.pack_start(self.action_box, False, False, 0)

        toggles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.bubbles_toggle = Gtk.CheckButton(label="Show Bubbles")
        self.top_toggle = Gtk.CheckButton(label="Always On Top")
        self.patrol_toggle = Gtk.CheckButton(label="Patrol Mode")
        self.bubbles_toggle.connect("toggled", self._toggle_bubbles)
        self.top_toggle.connect("toggled", self._toggle_top)
        self.patrol_toggle.connect("toggled", self._toggle_patrol)
        for toggle in (self.bubbles_toggle, self.top_toggle, self.patrol_toggle):
            toggles.pack_start(toggle, False, False, 0)
        root.pack_start(toggles, False, False, 0)

        patrol_options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        patrol_options.pack_start(Gtk.Label(label="Patrol Speed", xalign=0), False, False, 0)
        self.patrol_speed = Gtk.ComboBoxText()
        self.patrol_speed.append("slow", "Slow")
        self.patrol_speed.append("normal", "Normal")
        self.patrol_speed.append("fast", "Fast")
        self.patrol_speed.connect("changed", self._change_patrol_speed)
        patrol_options.pack_start(self.patrol_speed, False, False, 0)
        patrol_options.pack_start(Gtk.Label(label="Direction", xalign=0), False, False, 0)
        self.patrol_direction = Gtk.ComboBoxText()
        self.patrol_direction.append("random", "Random")
        self.patrol_direction.append("left", "Left")
        self.patrol_direction.append("right", "Right")
        self.patrol_direction.connect("changed", self._change_patrol_direction)
        patrol_options.pack_start(self.patrol_direction, False, False, 0)
        root.pack_start(patrol_options, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_button = Gtk.Button(label="Save Pet Text")
        reset_button = Gtk.Button(label="Reset Positions")
        close_button = Gtk.Button(label="Close Panel")
        quit_button = Gtk.Button(label="Quit")
        save_button.connect("clicked", self._save_pet_text)
        reset_button.connect("clicked", lambda unused: self.manager.reset_positions())
        close_button.connect("clicked", lambda unused: self.hide())
        quit_button.connect("clicked", lambda unused: self.manager.quit())
        for button in (save_button, reset_button, close_button, quit_button):
            buttons.pack_start(button, False, False, 0)
        root.pack_start(buttons, False, False, 0)

    def _hide_panel(self, *unused):
        self.hide()
        return True

    def refresh(self, selected_pet_id=None):
        current = selected_pet_id or self.pet_combo.get_active_id() or "carmen"
        self.rendering = True
        for child in self.active_box.get_children():
            self.active_box.remove(child)
        self.pet_combo.remove_all()
        for pet in PETS:
            toggle = Gtk.CheckButton(label=self.manager.display_name(pet))
            toggle.set_active(pet.pet_id in self.manager.settings["active_pet_ids"])
            toggle.connect("toggled", self._toggle_pet, pet.pet_id)
            self.active_box.pack_start(toggle, False, False, 0)
            self.pet_combo.append(pet.pet_id, self.manager.display_name(pet))
        self.pet_combo.set_active_id(current if current in PET_MAP else "carmen")
        self.bubbles_toggle.set_active(self.manager.settings["bubbles_enabled"])
        self.top_toggle.set_active(self.manager.settings["always_on_top"])
        self.patrol_toggle.set_active(self.manager.settings["patrol_mode"])
        self.patrol_speed.set_active_id(self.manager.settings["patrol_speed"])
        self.patrol_direction.set_active_id(self.manager.settings["patrol_direction"])
        self.rendering = False
        self._render_editor()
        self.show_all()

    def _selected_pet(self):
        return PET_MAP.get(self.pet_combo.get_active_id())

    def _render_editor(self, *unused):
        if self.rendering:
            return
        pet = self._selected_pet()
        if pet is None:
            return
        self.rendering = True
        self.name_entry.set_text(self.manager.display_name(pet))
        buffer_ = self.bubble_view.get_buffer()
        buffer_.set_text("\n".join(self.manager.bubble_lines(pet)))
        settings = self.manager.pet_settings(pet.pet_id)
        self.size_scale.set_value(settings["scale"] * 100)
        self.pet_bubble_toggle.set_active(settings.get("bubble_enabled", True))
        self.rendering = False
        self.update_status(pet.pet_id)

    def update_status(self, pet_id):
        pet = self._selected_pet()
        if pet is None or pet.pet_id != pet_id:
            return
        action, position = self.manager.pet_status(pet_id)
        self.action_status.set_text("Action: {}".format(action))
        self.position_status.set_text("Position: {}".format(position))

    def _toggle_pet(self, toggle, pet_id):
        if self.rendering:
            return
        if toggle.get_active():
            self.manager.show_pet(pet_id)
        else:
            self.manager.hide_pet(pet_id)
        self.refresh(pet_id)

    def _activate_action(self, button, action_name):
        del button
        pet = self._selected_pet()
        if pet is not None:
            self.manager.set_pet_action(pet.pet_id, action_name)
            self.update_status(pet.pet_id)

    def _change_size(self, scale):
        if self.rendering:
            return
        pet = self._selected_pet()
        if pet is not None:
            self.manager.set_pet_scale(pet.pet_id, scale.get_value() / 100.0)

    def _reset_size(self, button):
        del button
        pet = self._selected_pet()
        if pet is None:
            return
        self.manager.set_pet_scale(pet.pet_id, DEFAULT_SCALE)
        self.rendering = True
        self.size_scale.set_value(DEFAULT_SCALE * 100)
        self.rendering = False

    def _toggle_pet_bubble(self, toggle):
        if self.rendering:
            return
        pet = self._selected_pet()
        if pet is not None:
            self.manager.set_pet_bubble_enabled(pet.pet_id, toggle.get_active())

    def _toggle_bubbles(self, toggle):
        if not self.rendering:
            self.manager.set_bubbles_enabled(toggle.get_active())

    def _toggle_top(self, toggle):
        if not self.rendering:
            self.manager.set_always_on_top(toggle.get_active())

    def _toggle_patrol(self, toggle):
        if not self.rendering:
            self.manager.set_patrol_mode(toggle.get_active())

    def _change_patrol_speed(self, combo):
        if not self.rendering and combo.get_active_id():
            self.manager.set_patrol_speed(combo.get_active_id())

    def _change_patrol_direction(self, combo):
        if not self.rendering and combo.get_active_id():
            self.manager.set_patrol_direction(combo.get_active_id())

    def _save_pet_text(self, button):
        del button
        pet = self._selected_pet()
        if pet is None:
            return
        buffer_ = self.bubble_view.get_buffer()
        text = buffer_.get_text(buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        self.manager.save_pet_text(pet.pet_id, self.name_entry.get_text(), text.splitlines())
        self.refresh(pet.pet_id)


class PetManager:
    def __init__(self, show_all=False, duration=0):
        self.settings = load_settings()
        if show_all:
            self.settings["active_pet_ids"] = [pet.pet_id for pet in PETS]
        if not self.settings["active_pet_ids"]:
            self.settings["active_pet_ids"] = ["carmen"]
        self.store = SpriteStore()
        self.store.validate()
        self.windows = {}
        self.panel = None
        self.status_icon = None
        self.indicator = None
        self.duration = max(0, int(duration))
        self.lock_handle = None

    def acquire_lock(self):
        self.lock_handle = LOCK_PATH.open("w")
        try:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_handle.close()
            self.lock_handle = None
            return False
        return True

    def start(self):
        for pet_id in list(self.settings["active_pet_ids"]):
            self.show_pet(pet_id)
        self._create_status_icon()
        self.save()
        if self.duration:
            GLib.timeout_add_seconds(self.duration, self._duration_quit)

    def _duration_quit(self):
        self.quit()
        return False

    def pet_settings(self, pet_id):
        pets = self.settings["pets"]
        if pet_id not in pets:
            pets[pet_id] = {
                "display_name": "",
                "bubble_lines": [],
                "scale": DEFAULT_SCALE,
                "bubble_enabled": True,
                "x": None,
                "y": None,
            }
        pets[pet_id]["scale"] = clamp_scale(pets[pet_id].get("scale", DEFAULT_SCALE))
        pets[pet_id]["bubble_enabled"] = pets[pet_id].get("bubble_enabled", True) is not False
        return pets[pet_id]

    def display_name(self, pet):
        custom = self.pet_settings(pet.pet_id).get("display_name", "").strip()
        return custom or pet.name

    def bubble_lines(self, pet):
        custom = self.pet_settings(pet.pet_id).get("bubble_lines", [])
        return custom or list(pet.bubble_lines)

    def show_pet(self, pet_id):
        if pet_id not in PET_MAP:
            return
        if pet_id not in self.settings["active_pet_ids"]:
            self.settings["active_pet_ids"].append(pet_id)
        existing = self.windows.get(pet_id)
        if existing is not None:
            existing.present()
            return
        index = self.settings["active_pet_ids"].index(pet_id)
        window = PetWindow(self, PET_MAP[pet_id], index)
        self.windows[pet_id] = window
        window.start()
        self.save()
        self._refresh_indicator_menu()

    def hide_pet(self, pet_id):
        if pet_id in self.settings["active_pet_ids"]:
            self.settings["active_pet_ids"].remove(pet_id)
        window = self.windows.pop(pet_id, None)
        if window is not None:
            window.stop()
        self.save()
        self._refresh_indicator_menu()

    def show_all(self):
        for pet in PETS:
            self.show_pet(pet.pet_id)

    def hide_all(self):
        for pet_id in list(self.windows):
            self.hide_pet(pet_id)

    def set_pet_action(self, pet_id, action_name):
        window = self.windows.get(pet_id)
        if window is not None:
            window.activate_action(action_name)

    def set_bubbles_enabled(self, enabled):
        self.settings["bubbles_enabled"] = bool(enabled)
        for window in self.windows.values():
            window.invalidate_scene_cache()
            window.refresh_scene()
        self.save()
        self._refresh_indicator_menu()

    def set_always_on_top(self, enabled):
        self.settings["always_on_top"] = bool(enabled)
        for window in self.windows.values():
            window.set_keep_above(bool(enabled))
        self.save()
        self._refresh_indicator_menu()

    def set_patrol_mode(self, enabled):
        self.settings["patrol_mode"] = bool(enabled)
        for window in self.windows.values():
            window.apply_patrol_mode()
        self.save()
        self._refresh_indicator_menu()

    def set_patrol_speed(self, speed):
        if speed not in PATROL_PROFILES:
            return
        self.settings["patrol_speed"] = speed
        for window in self.windows.values():
            window.apply_patrol_mode()
        self.save()

    def set_patrol_direction(self, direction):
        if direction not in PATROL_DIRECTIONS:
            return
        self.settings["patrol_direction"] = direction
        for window in self.windows.values():
            window.apply_patrol_mode()
        self.save()

    def set_pet_scale(self, pet_id, scale):
        settings = self.pet_settings(pet_id)
        value = clamp_scale(scale)
        window = self.windows.get(pet_id)
        if window is not None:
            window.set_scale(value)
        else:
            settings["scale"] = value
            self.save()
        self.update_panel_status(pet_id)

    def set_pet_bubble_enabled(self, pet_id, enabled):
        settings = self.pet_settings(pet_id)
        settings["bubble_enabled"] = bool(enabled)
        window = self.windows.get(pet_id)
        if window is not None:
            window.invalidate_scene_cache()
            window.refresh_scene()
        self.save()

    def save_pet_text(self, pet_id, display_name, lines):
        settings = self.pet_settings(pet_id)
        settings["display_name"] = display_name.strip()
        settings["bubble_lines"] = [line.strip() for line in lines if line.strip()]
        window = self.windows.get(pet_id)
        if window is not None:
            window.bubble_index = 0
            window.invalidate_scene_cache()
            window.refresh_scene()
        self.save()

    def pet_status(self, pet_id):
        window = self.windows.get(pet_id)
        settings = self.pet_settings(pet_id)
        if window is None:
            action = "Hidden"
            x, y = settings.get("x"), settings.get("y")
        else:
            action = window.action.label
            x, y = window.bottom_center
        position = "Not set" if x is None or y is None else "{}, {}".format(x, y)
        return action, position

    def update_panel_status(self, pet_id):
        if self.panel is not None and self.panel.get_visible():
            self.panel.update_status(pet_id)

    def default_bottom_center(self, index):
        work = self.primary_work_area()
        column = max(0, index) % 4
        row = max(0, index) // 4
        return (work.x + work.width - 80 - column * 96, work.y + work.height - 52 - row * 84)

    def primary_work_area(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()

    def work_area_at(self, point):
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(point[0], point[1])
        if monitor is None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()

    def reset_positions(self):
        for index, pet in enumerate(PETS):
            position = self.default_bottom_center(index)
            settings = self.pet_settings(pet.pet_id)
            settings["x"], settings["y"] = position
            window = self.windows.get(pet.pet_id)
            if window is not None:
                window.bottom_center = position
                window._place_window()
            self.update_panel_status(pet.pet_id)
        self.save()

    def open_control_panel(self, selected_pet_id=None):
        if self.panel is None:
            self.panel = ControlPanel(self)
        self.panel.refresh(selected_pet_id)
        self.panel.present()

    def save(self):
        save_settings(self.settings)

    def _create_status_icon(self):
        if AppIndicator is not None:
            try:
                self.indicator = AppIndicator.Indicator.new(
                    "h2h-pets",
                    str(ICON_PATH) if ICON_PATH.is_file() else "applications-games",
                    AppIndicator.IndicatorCategory.APPLICATION_STATUS,
                )
                self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
                self._refresh_indicator_menu()
                return
            except Exception as error:
                self.indicator = None
                print("AppIndicator unavailable, using GTK tray: {}".format(error), file=sys.stderr)
        if not hasattr(Gtk, "StatusIcon"):
            return
        if ICON_PATH.is_file():
            self.status_icon = Gtk.StatusIcon.new_from_file(str(ICON_PATH))
        else:
            self.status_icon = Gtk.StatusIcon.new_from_icon_name("applications-games")
        self.status_icon.set_tooltip_text("H2H Pets")
        self.status_icon.set_visible(True)
        self.status_icon.connect("activate", lambda unused: self.open_control_panel())
        self.status_icon.connect("popup-menu", self._popup_status_menu)

    def _popup_status_menu(self, status_icon, button, activate_time):
        menu = self._build_tray_menu()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, status_icon, button, activate_time)

    def _build_tray_menu(self):
        menu = Gtk.Menu()
        self._menu_item(menu, "Control Panel", lambda unused: self.open_control_panel())
        self._menu_item(menu, "Show All Pets", lambda unused: self.show_all())
        self._menu_item(menu, "Hide All Pets", lambda unused: self.hide_all())
        menu.append(Gtk.SeparatorMenuItem())
        for pet in PETS:
            item = Gtk.CheckMenuItem(label=self.display_name(pet))
            item.set_active(pet.pet_id in self.settings["active_pet_ids"])
            item.connect("toggled", self._tray_toggle_pet, pet.pet_id)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        self._check_menu_item(menu, "Show Bubbles", self.settings["bubbles_enabled"], self.set_bubbles_enabled)
        self._check_menu_item(menu, "Always On Top", self.settings["always_on_top"], self.set_always_on_top)
        self._check_menu_item(menu, "Patrol Mode", self.settings["patrol_mode"], self.set_patrol_mode)
        self._menu_item(menu, "Reset Positions", lambda unused: self.reset_positions())
        menu.append(Gtk.SeparatorMenuItem())
        self._menu_item(menu, "Quit", lambda unused: self.quit())
        menu.show_all()
        return menu

    def _refresh_indicator_menu(self):
        if self.indicator is not None:
            self.indicator.set_menu(self._build_tray_menu())

    def _menu_item(self, menu, label, callback):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        menu.append(item)

    def _check_menu_item(self, menu, label, active, setter):
        item = Gtk.CheckMenuItem(label=label)
        item.set_active(active)
        item.connect("toggled", lambda toggle: setter(toggle.get_active()))
        menu.append(item)

    def _tray_toggle_pet(self, item, pet_id):
        if item.get_active():
            self.show_pet(pet_id)
        else:
            self.hide_pet(pet_id)

    def quit(self):
        self.save()
        for window in list(self.windows.values()):
            window.stop()
        self.windows.clear()
        if self.panel is not None:
            self.panel.destroy()
            self.panel = None
        if self.status_icon is not None:
            self.status_icon.set_visible(False)
        if self.indicator is not None:
            self.indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        Gtk.main_quit()


def check_installation():
    store = SpriteStore()
    store.validate()
    for pet in PETS:
        sheet = store.load_sheet(pet)
        if sheet.size != (1536, 1872):
            raise ValueError("Invalid sheet for {}".format(pet.pet_id))
    tray = "AppIndicator" if AppIndicator is not None else "GTK StatusIcon fallback"
    print("H2H Pets check passed: 9 pets, 9 actions, GTK3 available, {}".format(tray))


def show_error(message, title="H2H Pets"):
    print("{}: {}".format(title, message), file=sys.stderr)
    try:
        initialized, unused_argv = Gtk.init_check([])
        if not initialized:
            return
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()
    except Exception:
        pass


def parse_args(argv):
    parser = argparse.ArgumentParser(description="H2H Pets for Ubuntu X11")
    parser.add_argument("--show-all", action="store_true", help="show all nine pets")
    parser.add_argument("--duration", type=int, default=0, help="quit after N seconds")
    parser.add_argument("--check", action="store_true", help="validate dependencies and assets")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.check:
        check_installation()
        return 0
    initialized, unused_argv = Gtk.init_check([])
    if not initialized:
        raise RuntimeError("Cannot connect to the graphical desktop. Check DISPLAY and XAUTHORITY.")
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        print("Warning: Wayland may restrict pet movement and always-on-top behavior.", file=sys.stderr)
    manager = PetManager(show_all=args.show_all, duration=args.duration)
    if not manager.acquire_lock():
        show_error("H2H Pets is already running.")
        return 1
    manager.start()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        manager.quit()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        show_error(str(error), "H2H Pets failed to start")
        sys.exit(1)
