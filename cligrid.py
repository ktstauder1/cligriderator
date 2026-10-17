#!/usr/bin/env python3
"""Cli Griderator - a grid of terminals in its own dark palette, backed by tmux.

Copyright (c) 2026 Kutty Stauder / Konatus Research Group. All rights reserved.
Use is free. Redistribution and derivative works are not. See LICENSE.

One window holds up to twenty panes (six by default). Each pane is a tmux
client, so work survives hide, restart, and quit. Rows beyond the first two
sit below the visible grid; scroll to reach them. A pane whose program exits
starts again in the same cell. Wayland-native: no wmctrl.

Commands (sent to a running instance over a unix socket):
    cligrid                 start, or raise if already running
    cligrid toggle          minimize / restore the grid
    cligrid show|hide
    cligrid zoom [N|off]    one pane fills the window; N focuses pane N
    cligrid focus N         focus pane N
    cligrid swap A B        swap the panes in positions A and B
    cligrid restart [N]     reconnect pane N (or the focused pane)
    cligrid reset [N]       kill pane N's session, or every session, and start empty
    cligrid panes N         pane count, 1-20 (default 6)
    cligrid all <command>   run one command in every pane (replaces their sessions)
    cligrid remove [N]      remove pane N, or the focused pane
    cligrid fit             re-apply the configured fit (config key "fit")
    cligrid status          JSON: window size, per-pane cols x rows
    cligrid quit            quit the grid (tmux sessions keep running)
"""

import datetime
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Vte", "2.91")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo, Vte  # noqa: E402

import cligrid_art as art  # noqa: E402
import cligrid_control as control  # noqa: E402
import cligrid_doctor as doctor  # noqa: E402
import cligrid_keymap as keymap  # noqa: E402
import cligrid_layout as layout  # noqa: E402
import cligrid_palette as palette  # noqa: E402
import cligrid_state as state  # noqa: E402
import cligrid_workspace as workspace  # noqa: E402

APP = "cligrid"
APP_TITLE = "Cli Griderator"
VERSION = "4.3.0"  # keep equal to pyproject.toml; test_cligrid_release.py checks
AUTHOR = "Kutty Stauder"
ORG = "Konatus Research Group"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), APP)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
# CLIGRID_SOCKET points at a full path, which is how a second grid (or a test
# instance) runs beside the first without stealing its commands.
SOCKET_PATH = os.environ.get("CLIGRID_SOCKET") or os.path.join(
    RUNTIME, "%s-%s.sock" % (APP, os.getuid()))
ICON_PATH = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/cligrid.svg")
HEADER_H = 44  # px fallback for a pane title strip until one is measured
TOOLBAR_H = 60  # px fallback for the header bar until it is measured
MIN_PANES = 1
MAX_PANES = 20
DEFAULT_PANE_COUNT = 6
KITTY_CONF_PATH = os.path.expanduser("~/.config/kitty/kitty.conf")
URL_PATTERN = r"(https?://|www\.)[^\s<>\"']+"
WORD_CHARS = ":@-./_~?&=%+#"
ART_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cligrid_art.py")
LOG_PATH = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cligrid.log")
LOG_KEEP_BYTES = 256 * 1024  # the log is trimmed to this tail at every launch
PANE_COLOR_SLOTS = (4, 5, 6, 2, 3, 1)  # kitty palette: blue, purple, cyan, green, yellow, red
NOTIFY_INTERVAL_SECONDS = 30  # at most one desktop notification per pane in this window
POLL_MS = 1000  # one timer for cwd, git branch and pane state
MAX_DUMP_LINES = 20000  # `dump --lines` ceiling; the scrollback default is 10000
WAIT_ROWS = 40  # rows of a pane a `wait` pattern is matched against
WAIT_TEXT_CHARS = 32 * 1024  # and never more text than this, per poll
PULSE_MS = 650  # alert blink half-period; a timer, not a CSS animation repainting every frame
QUIET_SECONDS = 2.5  # text reflow after a layout or font change is not new output

# Motion: one easing and three durations for every transition in the stylesheet,
# so hover, focus, overlays and toasts share a rhythm instead of drifting apart.
EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)"
MOTION_FAST = 110  # ms: hover, press, chip colour
MOTION_BASE = 170  # ms: focus ring, pane elevation, list rows
MOTION_SLOW = 260  # ms: overlays opening and closing
TOAST_MS = 3200  # ms a toast stays on screen before it starts to leave
TOAST_MAX = 3  # toasts on screen at once

GRID_COLS = 3  # most panes in one row
GRID_VISIBLE_ROWS = 2  # rows on screen; further rows scroll
GRID_SUBCOLS = 6  # grid columns, so a short last row can stretch to fill
GRID_GAP = 14  # px between panes
GRID_BORDER = 18  # px around the grid
PANE_INSET = 3  # px between a pane's rounded border and its terminal
QUICK_EXIT_SECONDS = 2.0  # a pane that dies this soon after starting failed to start
MAX_QUICK_EXITS = 3  # failed starts in a row before a pane stops respawning
UI_FONT = '"Inter", "Noto Sans", "Ubuntu", "Cantarell", sans-serif'
MONO_FONT = '"JetBrainsMono Nerd Font", "JetBrains Mono", "Ubuntu Sans Mono", monospace'
PREFERRED_FONTS = (
    "JetBrainsMono Nerd Font",
    "JetBrainsMono Nerd Font Mono",
    "Ubuntu Sans Mono",
    "Ubuntu Mono",
    "Fira Mono",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Noto Sans Mono",
    "Noto Mono",
)

DEFAULT_CONFIG = {
    "fit": "maximized",  # maximized (compositor respects panel+dock) | workarea | WxH
    "font": "JetBrainsMono Nerd Font",
    "font_size": 11,
    "min_font_size": 7,
    "auto_font": True,  # shrink font so every pane fits min_cols/min_rows
    "min_cols": 60,
    "min_rows": 15,
    "scrollback": 10000,
    "cursor_blink": False,
    "banner": True,  # ASCII welcome when a pane starts a new tmux session
    "bell_alerts": True,  # pulse a background pane that rings its bell
    "activity_marks": True,  # mark background panes that print new output
    "notify_desktop": True,  # desktop notification for a bell while the grid is not in front
    "notify_rules": [],  # extra pane patterns live in panes[n].notify_on
    "quiet_hours": "",  # "22:00-07:00" suppresses desktop notifications
    "theme": "griderator",  # the grid's own palette; "kitty" follows kitty.conf
    "prefix": "space",  # two-stroke prefix key; "none" turns the mode off
    "guard": "panes",  # refuse reset/all/remove/quit from inside a pane unless --force; "off"
    "keymap": {},  # key name -> action id overrides
    "restore_on_start": True,  # bring back the last arrangement on launch
    "layout": "auto",  # grid shape: auto, 2x2, 3x2, master, 1x6, ...
    "stack": [],  # pane positions that share one cell as tabs
    "cwd": os.path.expanduser("~"),
    "pane_count": DEFAULT_PANE_COUNT,
    "panes": [
        {"name": name, "cmd": "tmux new-session -A -s %s" % name}
        for name in ("g1", "g2", "g3", "g4", "g5", "g6")
    ],
}

# Default keys, pressed with Ctrl+Shift so they never reach the terminal.
# Copy and paste also accept Ctrl+C (when text is selected) and Ctrl+V.
# The value is an action id from CliGrid.action_table(); a keymap in config.json
# overrides any entry, and "prefix" arms a two-stroke mode where one key runs an
# action without Ctrl+Shift.
DEFAULT_KEYMAP = {
    "1": "focus.1", "2": "focus.2", "3": "focus.3", "4": "focus.4", "5": "focus.5",
    "6": "focus.6", "7": "focus.7", "8": "focus.8", "9": "focus.9",
    "0": "focus.10", "parenright": "focus.10",
    "Page_Up": "scroll.up", "KP_Page_Up": "scroll.up",
    "Page_Down": "scroll.down", "KP_Page_Down": "scroll.down",
    "Left": "focus.left", "H": "focus.left",
    "Right": "focus.right", "L": "focus.right",
    "Up": "focus.up", "K": "focus.up",
    "Down": "focus.down", "J": "focus.down",
    "Z": "zoom",
    "A": "attention",
    "P": "palette",
    "S": "search.all",
    "G": "search.pane",
    "N": "reset.all",
    "E": "fill.all",
    "R": "reset.pane",
    "B": "paste.all",
    "minus": "remove", "underscore": "remove", "KP_Subtract": "remove",
    "C": "copy",
    "V": "paste",
    "F": "fit",
    "comma": "settings", "less": "settings",
    "slash": "shortcuts", "question": "shortcuts", "questiondown": "shortcuts",
    "W": "hide",
    "Q": "quit",
}
PREFIX_KEY_NAMES = {
    "space": ("space",), "grave": ("grave", "asciitilde"),
    "semicolon": ("semicolon", "colon"), "backslash": ("backslash", "bar"),
    "tab": ("Tab", "ISO_Left_Tab"), "none": (),
}
PREFIX_CHOICES = (
    ("space", "Space"),
    ("grave", "` Grave"),
    ("semicolon", "; Semicolon"),
    ("backslash", "\\ Backslash"),
    ("tab", "Tab"),
    ("none", "Off"),
)


def as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def used_session_names(panes):
    """Names and tmux session targets already taken by the given pane configs."""
    names = set()
    for pane in panes:
        names.add(str(pane.get("name", "")))
        target = tmux_target(pane.get("cmd", ""))
        if target:
            names.add(target)
    return names


def default_pane(index, taken=()):
    """gN for position N, or the lowest free gN when another pane already uses
    that name, so a new pane never attaches to a neighbour's session."""
    taken = set(taken)
    name = "g%d" % (index + 1)
    n = 1
    while name in taken:
        name = "g%d" % n
        n += 1
    return {"name": name, "cmd": "tmux new-session -A -s %s" % name}


def clamp_pane_count(value):
    return max(MIN_PANES, min(MAX_PANES, as_int(value, DEFAULT_PANE_COUNT)))


def normalize_panes(raw, count):
    count = clamp_pane_count(count)
    source = raw if isinstance(raw, list) else []
    panes = []
    for i in range(count):
        later = [p for p in source[i + 1:count] if isinstance(p, dict)]
        fallback = default_pane(i, used_session_names(panes + later))
        if i < len(source) and isinstance(source[i], dict):
            panes.append({
                "name": str(source[i].get("name", fallback["name"])),
                "cmd": str(source[i].get("cmd", fallback["cmd"])),
            })
        else:
            panes.append(fallback)
    return panes


def grid_rows(cols, count):
    cols = max(1, as_int(cols, 1))
    count = max(0, as_int(count, 0))
    if count == 0:
        return 1
    return (count + cols - 1) // cols


def needs_window_scroll(cols, vis_rows, count):
    return grid_rows(cols, count) > max(1, as_int(vis_rows, 1))


def drop_pane_config(panes, index):
    if not isinstance(panes, list) or len(panes) <= MIN_PANES:
        return None
    if not (0 <= index < len(panes)):
        return None
    return [dict(pane) for i, pane in enumerate(panes) if i != index]


TOKYO_NIGHT = {
    "foreground": "#c0caf5",
    "background": "#1a1b26",
    "cursor": "#c0caf5",
    "cursor_text": "#1a1b26",
    "selection_bg": "#33467c",
    "selection_fg": "#c0caf5",
    "palette": [
        "#15161e", "#f7768e", "#9ece6a", "#e0af68",
        "#7aa2f7", "#bb9af7", "#7dcfff", "#a9b1d6",
        "#414868", "#f7768e", "#9ece6a", "#e0af68",
        "#7aa2f7", "#bb9af7", "#7dcfff", "#c0caf5",
    ],
    "font_family": "JetBrainsMono Nerd Font",
    "font_size": 11,
    "scrollback": 10000,
    "copy_on_select": True,
    "padding": 10,
    "accent": "#7aa2f7",
    "url": "#7dcfff",
    "border": "#292e42",
}


def decide_child_exit_action(quitting, pending_fresh, spawned=True, quick_exits=0):
    """When a pane process dies, respawn in that cell unless we are leaving,
    or it keeps dying right after starting; then stop and show why."""
    if quitting or pending_fresh or not spawned:
        return "ignore"
    if quick_exits >= MAX_QUICK_EXITS:
        return "halt"
    return "respawn"


def _rgb(value):
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def mix(a, b, amount):
    """Blend hex color a toward b: 0 keeps a, 1 gives b."""
    return "#%02x%02x%02x" % tuple(
        round(x + (y - x) * amount) for x, y in zip(_rgb(a), _rgb(b))
    )


def luminance(value):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_on(background, *candidates):
    """The candidate text color with the most contrast on background."""
    return max(candidates, key=lambda color: contrast_ratio(background, color))


def _kitty_key_value(line):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None, None
    parts = stripped.split(None, 1)
    if len(parts) < 2:
        return None, None
    key, value = parts[0], parts[1]
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    return key, value


KITTY_KEYS = {
    "foreground": "foreground",
    "background": "background",
    "cursor": "cursor",
    "cursor_text_color": "cursor_text",
    "selection_background": "selection_bg",
    "selection_foreground": "selection_fg",
    "active_border_color": "accent",
    "inactive_border_color": "border",
    "url_color": "url",
    "font_family": "font_family",
}


def parse_kitty_conf(path=None):
    """Read colors and terminal prefs from kitty.conf. Tokyo Night if missing.

    Accent, link and border colors that kitty.conf leaves out are derived from
    the colors it does set, so another theme does not inherit Tokyo Night's."""
    theme = json.loads(json.dumps(TOKYO_NIGHT))
    path = path or KITTY_CONF_PATH
    if not os.path.isfile(path):
        return theme
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return theme
    palette = list(theme["palette"])
    seen = set()
    for line in lines:
        key, value = _kitty_key_value(line)
        if not key:
            continue
        seen.add(key)
        if key in KITTY_KEYS:
            theme[KITTY_KEYS[key]] = value
        elif key == "font_size":
            numeric = float(value) if value.replace(".", "", 1).isdigit() else value
            theme["font_size"] = as_int(numeric, theme["font_size"])
        elif key == "scrollback_lines":
            theme["scrollback"] = as_int(value, theme["scrollback"])
        elif key == "window_padding_width":
            theme["padding"] = as_int(value.split()[0], theme["padding"])
        elif key == "copy_on_select":
            theme["copy_on_select"] = value.lower() not in ("no", "false", "0", "never")
        elif key.startswith("color") and key[5:].isdigit():
            idx = int(key[5:])
            if 0 <= idx < 16:
                palette[idx] = value
    theme["palette"] = palette
    recolored = bool(seen & {"foreground", "background"}) or any(
        k.startswith("color") and k[5:].isdigit() for k in seen)
    if recolored:
        if "active_border_color" not in seen:
            theme["accent"] = palette[4]
        if "url_color" not in seen:
            theme["url"] = palette[6]
        if "inactive_border_color" not in seen:
            theme["border"] = mix(theme["background"], theme["foreground"], 0.14)
    return theme


THEME = parse_kitty_conf()


def short_path(path):
    if not path:
        return ""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def uri_to_path(uri):
    if not uri:
        return ""
    try:
        parsed = urlparse(uri)
        return unquote(parsed.path or "")
    except Exception:
        return ""


def hex_rgba(value):
    color = Gdk.RGBA()
    color.parse(value)
    return color


def text_on(background, preferred):
    """First preferred text color that reads at 4.5:1 on background, else black or white."""
    for color in preferred:
        if contrast_ratio(background, color) >= 4.5:
            return color
    return readable_on(background, "#000000", "#ffffff")


def chrome_palette(theme):
    """Window chrome colors derived from the terminal theme, so the header bar,
    pane cards and dialogs follow whichever kitty theme is active."""
    bg, fg = theme["background"], theme["foreground"]
    palette = theme["palette"]
    accent = theme.get("accent") or palette[4]
    red = palette[1]
    ok, warn, purple, info = palette[2], palette[3], palette[5], palette[6]
    return {
        "bg": bg,
        "fg": fg,
        "accent": accent,
        "on_accent": text_on(accent, (bg, fg)),
        "accent_hover": mix(accent, fg, 0.18),
        "accent_soft": mix(bg, accent, 0.24),
        "border": theme.get("border") or mix(bg, fg, 0.14),
        "surface": theme.get("surface") or mix(bg, "#000000", 0.18),
        "bg_deep": theme.get("bg_deep") or mix(bg, "#000000", 0.45),
        "sheen": mix(bg, fg, 0.035),
        "raised": mix(bg, fg, 0.06),
        "hover": mix(bg, fg, 0.11),
        "muted": theme.get("muted") or mix(bg, fg, 0.545),
        "subtle": mix(bg, fg, 0.72),
        "red": red,
        "on_red": text_on(red, (bg, fg)),
        "red_hover": mix(red, fg, 0.15),
        "red_soft": mix(bg, red, 0.16),
        "red_line": mix(bg, red, 0.55),
        "ok_soft": mix(bg, ok, 0.20),
        "ok_line": mix(bg, ok, 0.55),
        "warn_soft": mix(bg, warn, 0.20),
        "warn_line": mix(bg, warn, 0.55),
        "ok": ok,
        "on_ok": text_on(ok, (bg, fg)),
        "warn": warn,
        "on_warn": text_on(warn, (bg, fg)),
        "purple": purple,
        "info": info,
        "selection_bg": theme.get("selection_bg") or mix(bg, accent, 0.35),
        "selection_fg": theme.get("selection_fg") or fg,
        "pad": max(2, min(6, as_int(theme.get("padding"), 6))),
    }


def pane_color(theme, position):
    """Color for a grid position: blue, purple, cyan, green, yellow, red, repeating."""
    return theme["palette"][PANE_COLOR_SLOTS[position % len(PANE_COLOR_SLOTS)]]


def tint_css(theme):
    """Per-position rules: pane number, title strip, focus border, switcher button."""
    c = chrome_palette(theme)
    rules = []
    for i in range(len(PANE_COLOR_SLOTS)):
        color = pane_color(theme, i)
        rules.append(TINT_CSS.format(
            i=i, color=color, ink=text_on(mix(c["bg"], color, 0.22), (color, c["fg"])),
            on_color=text_on(color, (c["bg"], c["fg"])),
            wash=mix(c["bg"], color, 0.12),
            base=c["surface"], glint=mix(color, c["fg"], 0.28),
            soft=mix(c["bg"], color, 0.22), faint=mix(c["bg"], color, 0.55), border=c["border"]))
        # The alert pulse is the tint plus a glow; .pane transitions box-shadow,
        # so the blink breathes instead of snapping.
        rules.append(
            ".window-cligrid .pane.tint-%d.alert.alert-on {"
            " box-shadow: 0 0 0 1px %s, 0 4px 20px %s; }"
            % (i, color, mix(c["bg"], color, 0.45)))
    return "".join(rules)


def compact_path(path, keep=2):
    """~/Desktop/Folders/VibeCode/cligrid -> …/VibeCode/cligrid; short paths stay whole."""
    short = short_path(path)
    parts = short.split("/")
    if len(parts) <= keep + 1:
        return short
    return "…/" + "/".join(parts[-keep:])


def reveal(widget):
    """show_all() skips widgets marked set_no_show_all(), and their children, so
    lift the flag for the call. Plain hide() still works to take them away."""
    widget.set_no_show_all(False)
    widget.show_all()
    widget.set_no_show_all(True)


def grid_shape(count):
    """(columns, rows) for count panes: rows of up to three, 2x2 for four."""
    count = max(1, as_int(count, 1))
    cols = 2 if count == 4 else min(GRID_COLS, count)
    return cols, (count + cols - 1) // cols


def grid_cells(count):
    """(column, row, span) per position on a GRID_SUBCOLS-wide grid. A shorter
    last row stretches its panes, so the grid never shows an empty cell."""
    count = max(1, as_int(count, 1))
    cols, rows = grid_shape(count)
    last_row = count - cols * (rows - 1)
    cells = []
    for pos in range(count):
        row = pos // cols
        span = GRID_SUBCOLS // (cols if row < rows - 1 else last_row)
        cells.append(((pos % cols) * span, row, span))
    return cells


def neighbor_position(count, pos, direction):
    """Position reached by moving focus from pos; stays put at an edge."""
    cells = grid_cells(count)
    col, row, span = cells[pos]
    if direction in ("left", "right"):
        target = pos + (-1 if direction == "left" else 1)
        if 0 <= target < len(cells) and cells[target][1] == row:
            return target
        return pos
    target_row = row + (-1 if direction == "up" else 1)
    center = col + span / 2.0
    for i, (c, r, s) in enumerate(cells):
        if r == target_row and c <= center < c + s:
            return i
    return pos


def tmux_target(cmd, fallback=None):
    """Session name for a pane command, or None if it is not a tmux client."""
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        parts = (cmd or "").split()
    if not parts or os.path.basename(parts[0]) != "tmux":
        return None
    for flag in ("-s", "-t"):
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return fallback


def kill_tmux_session(target):
    if not target:
        return False
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", target],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return True
    except Exception:
        return False


def detach_tmux_client(target):
    """Detach the clients of a session without ending the session itself, which
    is how a workspace switch lets go of a pane without losing its work."""
    if not target:
        return False
    try:
        subprocess.run(
            ["tmux", "detach-client", "-s", target],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return True
    except Exception:
        return False


KEY_LABELS = {"minus": "-", "comma": ",", "slash": "/", "space": "Space",
              "parenright": ")", "period": ".", "KP_Subtract": "-"}


def key_hint(key):
    """A readable Ctrl+Shift+<key> label for a keymap key name."""
    name = KEY_LABELS.get(key, key)
    if len(name) == 1 and name.isalpha():
        name = name.upper()
    return "Ctrl+Shift+%s" % name


def terminal_selection(term):
    """Plain text of the current VTE selection, or empty."""
    if term is None:
        return ""
    try:
        if hasattr(term, "get_has_selection") and not term.get_has_selection():
            return ""
    except Exception:
        pass
    readers = []
    if hasattr(term, "get_text_selected"):
        readers.append(lambda: term.get_text_selected(Vte.Format.TEXT))
        readers.append(term.get_text_selected)
    if hasattr(term, "get_text_selected_full"):
        readers.append(lambda: term.get_text_selected_full(Vte.Format.TEXT))
    for reader in readers:
        try:
            text = reader()
        except Exception:
            continue
        if isinstance(text, tuple):
            text = text[0] if text else ""
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        if text:
            return text
    return ""


def _run_clipboard(argv, runner=None, payload=None):
    """Run wl-copy/wl-paste. runner is injected by tests."""
    run = runner or subprocess.run
    try:
        return run(
            argv, input=payload, capture_output=True, timeout=1, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def write_clipboard(text, clipboard=None, primary=None, runner=None):
    """Put text on CLIPBOARD, and on PRIMARY only when the caller asks.

    Do not pass VTE's PRIMARY: claiming it steals the highlight from the
    terminal and drops the cursor back on the prompt.
    """
    if not text:
        return False
    ok = False
    for clip in (clipboard, primary):
        if clip is None:
            continue
        try:
            clip.set_text(text, -1)
            ok = True
        except Exception:
            pass
    result = _run_clipboard(["wl-copy"], runner=runner, payload=text.encode("utf-8"))
    if result is not None and getattr(result, "returncode", 1) == 0:
        ok = True
    return ok


def clipboard_text(clipboard=None, runner=None):
    """Best-effort clipboard read: GTK first, then wl-paste on Wayland."""
    if clipboard is not None:
        try:
            text = clipboard.wait_for_text()
            if text:
                return text
        except Exception:
            pass
    result = _run_clipboard(["wl-paste", "-n"], runner=runner)
    if result is not None and getattr(result, "returncode", 1) == 0:
        out = getattr(result, "stdout", b"") or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if out:
            return out
    return ""


def paste_into_terminal(term, text):
    """Paste text into a VTE widget, keeping bracketed-paste when the API exists."""
    if term is None or not text:
        return False
    try:
        term.paste_text(text)
        return True
    except Exception:
        pass
    try:
        term.paste_text(text.encode("utf-8"))
        return True
    except Exception:
        pass
    try:
        term.feed_child(text)
        return True
    except Exception:
        pass
    try:
        term.feed_child(text.encode("utf-8"))
        return True
    except Exception:
        return False


def gtk_clipboards():
    """(CLIPBOARD, PRIMARY) or (None, None) when GTK has no display."""
    try:
        return (
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD),
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY),
        )
    except Exception:
        return (None, None)


def wipe_configured_sessions(cfg=None, positions=None):
    """Kill the tmux sessions named in config so the next spawn is empty."""
    cfg = cfg if cfg is not None else load_config()
    panes = cfg.get("panes", [])
    selected = panes if positions is None else [panes[n - 1] for n in positions]
    for pane in selected:
        kill_tmux_session(tmux_target(pane.get("cmd", ""), pane.get("name")))


def as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return default


DROP_ENV = (
    "TMUX", "TMUX_PANE", "STY", "WINDOW",
    "KITTY_WINDOW_ID", "KITTY_PID", "KITTY_LISTEN_ON",
    "KITTY_PUBLIC_KEY", "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
)


def env_list(slot):
    """Environment for a pane. Strip multiplexer vars so tmux is not nested."""
    env = dict(os.environ)
    for key in DROP_ENV:
        env.pop(key, None)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["CLIGRID"] = "1"
    env["CLIGRID_SLOT"] = str(slot)
    out = []
    for key, value in env.items():
        text = "" if value is None else str(value)
        if not key or "\n" in key or "\n" in text:
            continue
        out.append("%s=%s" % (key, text))
    return out


# A command a shell has to read: operators, and quoting tmux would otherwise
# pass along as a literal. Everything else reaches tmux as plain argv.
SHELL_COMMAND_CHARS = ("&&", "||", "|", ";", "'", '"', "\\")


def pane_cmd_for_cli(name, cli):
    """One tmux session per window, running the same CLI inside it.

    The session name is quoted, so a pane called `Build logs` keeps that
    name instead of becoming a session `Build` that runs a command `logs`."""
    name = shlex.quote(str(name or "g1").strip() or "g1")
    cli = (cli or "").strip()
    if not cli:
        return "tmux new-session -A -s %s" % name
    if any(token in cli for token in SHELL_COMMAND_CHARS):
        return "tmux new-session -A -s %s bash -lc %s" % (name, shlex.quote(cli))
    return "tmux new-session -A -s %s %s" % (name, cli)


def pane_argv(cmd):
    """Run a simple tmux/shell command directly; wrap compound commands."""
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        parts = []
    raw = cmd or ""
    if parts and os.path.basename(parts[0]) == "tmux":
        return parts
    if parts and not any(token in raw for token in ("&&", "||", "|", ";")):
        return parts
    return ["/bin/bash", "-lc", raw]


def in_quiet_hours(spec, when=None):
    """True when the clock is inside a "22:00-07:00" window from the config.
    An empty or malformed spec means notifications are never suppressed."""
    text = str(spec or "").strip()
    if "-" not in text:
        return False
    start_text, _, end_text = text.partition("-")

    def minutes(value):
        parts = value.strip().split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return None
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        return hour * 60 + minute

    start, end = minutes(start_text), minutes(end_text)
    if start is None or end is None:
        return False
    now = when or datetime.datetime.now()
    current = now.hour * 60 + now.minute
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end  # a window that crosses midnight


def notification_patterns(pane_entry):
    """Compiled regexes from a pane's notify_on list: a match earns a desktop
    notification even when the pane is not ringing its bell."""
    raw = (pane_entry or {}).get("notify_on")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    patterns = []
    for item in raw:
        try:
            patterns.append(re.compile(str(item), re.IGNORECASE))
        except re.error:
            continue
    return patterns


def decide_bell(pane_focused, window_watched, alerts_on=True, notify_on=True):
    """(pulse the pane, send a desktop notification) for a bell: pulse any pane
    that is not focused; notify only while the grid window is not in front."""
    return alerts_on and not pane_focused, notify_on and not window_watched


def notification_text(position, name, cmd, cwd):
    summary = "Pane %d · %s" % (position, name)
    body = "%s rang its bell" % art.command_summary(cmd)
    if cwd:
        body += " in %s" % compact_path(cwd)
    return summary, body


def applescript_string(text):
    """AppleScript string literal for arbitrary text, newlines flattened."""
    flattened = " ".join(str(text).split())
    return '"%s"' % flattened.replace("\\", "\\\\").replace('"', '\\"')


def osascript_notify(summary, body):
    """Desktop notification on macOS, which has no session D-Bus.

    Returns True only when osascript was handed the notification. On any other
    platform, and when the grid is not on macOS, it returns False so the caller
    keeps its D-Bus-only behaviour.
    """
    if sys.platform != "darwin":
        return False
    script = "display notification %s with title %s" % (
        applescript_string(body), applescript_string(summary))
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def without_status_line(text):
    """Screen text minus its last row, where tmux's status bar keeps a clock."""
    lines = (text or "").rstrip("\n").split("\n")
    return "\n".join(lines[:-1])


def tmux_has_session(name):
    try:
        return subprocess.run(["tmux", "has-session", "-t", "=" + name],
                              capture_output=True, timeout=2, check=False).returncode == 0
    except Exception:
        return True  # unknown: treat as existing, so no banner is added


def peer_pid(connection):
    """The process id behind a control connection, from SO_PEERCRED, or None."""
    try:
        return connection.get_socket().get_credentials().get_unix_pid()
    except Exception:
        return None


def process_environ(pid):
    """A process's environment from /proc, or {} when it cannot be read."""
    if not pid:
        return {}
    try:
        with open("/proc/%d/environ" % int(pid), "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError):
        return {}
    env = {}
    for item in raw.split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep:
            env[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return env


def request_from_pane(connection):
    """True when the client process runs inside one of the grid's panes, which
    every pane marks with CLIGRID=1 in its environment. Unknown means False:
    a shell outside the grid must keep working when /proc is not readable."""
    return process_environ(peer_pid(connection)).get("CLIGRID") == "1"


def tmux_capture_argv(target, lines):
    """tmux argv for the last `lines` rows of a session, scrollback included.
    `-S -N` starts N rows back in history; `-J` rejoins wrapped lines so a long
    log line comes back whole."""
    return ["tmux", "capture-pane", "-p", "-J", "-t", "=" + str(target),
            "-S", "-%d" % max(1, int(lines))]


def tmux_capture(target, lines, timeout=2):
    """The last `lines` rows of a tmux session as text, or None when the
    session does not exist or tmux cannot be reached."""
    if not target:
        return None
    try:
        result = subprocess.run(tmux_capture_argv(target, lines),
                                capture_output=True, text=True, timeout=timeout, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def with_banner(head, tail, show):
    """tmux new-session argv that prints the banner, then runs the original
    command, or a login shell, in its place."""
    script = " ".join(shlex.quote(part) for part in show)
    if tail:
        return head + ["sh", "-c", script + '; exec "$@"', "sh"] + tail
    return head + ["sh", "-c", script + '; exec "${SHELL:-/bin/sh}" -l']


def tmux_chrome_options(theme):
    """Session-local tmux chrome using literal hex from the grid theme.

    ~/.tmux.conf styles the status bar and messages with #{@blue} user options.
    Style strings expand those; colour-only options such as display-panes-colour
    do not, so tmux prints `bad colour: #{@blue}` into every pane. The grid
    already has a title strip, so the status bar is turned off (a 1-row chrome
    the user never sees). Messages keep the theme so a leftover notice matches
    the pane instead of flashing the default yellow bar.
    """
    chrome = chrome_palette(theme)
    accent = chrome["accent"]
    border = chrome["border"]
    fg = chrome["fg"]
    surface = chrome["selection_bg"]
    return (
        ("status", "off"),
        ("display-panes-colour", border),
        ("display-panes-active-colour", accent),
        ("clock-mode-colour", accent),
        ("message-style", "bg=%s,fg=%s" % (surface, fg)),
        ("message-command-style", "bg=%s,fg=%s" % (surface, fg)),
    )


def tmux_attach_verb(argv):
    """The tmux subcommand that attaches a client, or None."""
    if not argv or os.path.basename(argv[0]) != "tmux":
        return None
    for part in argv[1:]:
        if part.startswith("-"):
            continue
        if part in ("new-session", "new", "attach-session", "attach", "a"):
            return part
        return None
    return None


def with_tmux_chrome(argv, theme=None):
    """After attach, set session chrome so 'bad colour' never paints the pane."""
    if tmux_attach_verb(argv) is None:
        return list(argv) if argv else argv
    extras = []
    for key, value in tmux_chrome_options(theme if theme is not None else THEME):
        extras.extend([";", "set-option", key, str(value)])
    return list(argv) + extras


def tmux_chrome_apply_argv(target, theme=None):
    """tmux argv that restyles an already-running session."""
    args = ["tmux"]
    first = True
    for key, value in tmux_chrome_options(theme if theme is not None else THEME):
        if not first:
            args.append(";")
        first = False
        args.extend(["set-option", "-t", str(target), key, str(value)])
    return args


def apply_tmux_chrome(target, theme=None):
    """Restyle a live session. Session-local, so other tmux sessions stay put."""
    if not target:
        return False
    try:
        subprocess.run(
            tmux_chrome_apply_argv(target, theme),
            capture_output=True, timeout=2, check=False,
        )
        return True
    except Exception:
        return False


def exit_text(status):
    """'with code 1' or 'on signal 9' from a child wait status."""
    try:
        code = os.waitstatus_to_exitcode(status)
    except (TypeError, ValueError):
        return "with status %s" % status
    return "on signal %d" % -code if code < 0 else "with code %d" % code


def theme_has_icon(name):
    theme = Gtk.IconTheme.get_default()
    return bool(theme and theme.has_icon(name))


def styled(widget, *classes):
    ctx = widget.get_style_context()
    for name in classes:
        ctx.add_class(name)
    return widget


def set_accessible(widget, name):
    """Give a widget a screen reader name. GTK3 exposes this through the
    widget's accessible object; set_accessible_name() is GTK4 only."""
    try:
        accessible = widget.get_accessible()
        if accessible is not None and name:
            accessible.set_name(name)
    except Exception:
        pass


def icon_button(icon_name, fallback, tooltip, callback, extra_class="icon-btn"):
    button = Gtk.Button()
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_focus_on_click(False)
    button.set_tooltip_text(tooltip)
    button.get_style_context().add_class(extra_class)
    if theme_has_icon(icon_name):
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        button.set_image(image)
        button.set_always_show_image(True)
    else:
        button.set_label(fallback)
    button.connect("clicked", lambda *_: callback())
    # Icon-only buttons are invisible to a screen reader without a name.
    set_accessible(button, tooltip or fallback)
    return button


def keycaps(keys):
    """A row of key caps, one per space-separated key."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    for key in keys.split():
        box.pack_start(styled(Gtk.Label(label=key), "kbd"), False, False, 0)
    return box


def menu_item(label, callback, accel=None, sensitive=True):
    """Menu item with an optional accelerator hint, e.g. "<Ctrl><Shift>z"."""
    item = Gtk.MenuItem(label=label)
    item.set_sensitive(sensitive)
    if accel:
        key, mods = Gtk.accelerator_parse(accel)
        child = item.get_child()
        if key and isinstance(child, Gtk.AccelLabel):
            child.set_accel(key, mods)
    item.connect("activate", lambda _i: callback())
    return item


def build_css(theme):
    """Application stylesheet from the active kitty theme.

    Installed just above user priority: COSMIC's generated gtk.css would
    otherwise tint switches, focus rings and title bars with its own accent,
    and VTE's built-in 1px padding rule would beat ours at equal priority."""
    c = chrome_palette(theme)
    c.update(
        ui_font=UI_FONT, mono_font=MONO_FONT, inset=PANE_INSET,
        ease=EASE,
        t_fast="%dms" % MOTION_FAST,
        t_base="%dms" % MOTION_BASE,
        t_slow="%dms" % MOTION_SLOW,
    )
    parts = (NAMED_COLORS_CSS, WINDOW_CSS, PANE_CSS, STATE_CSS, PALETTE_CSS,
             CHROME_CSS, TOAST_CSS, DIALOG_CSS)
    css = "".join(part.format_map(c) for part in parts)
    return (css + tint_css(theme) + EXITED_CSS.format_map(c)).encode()


NAMED_COLORS_CSS = """
@define-color accent_color {accent};
@define-color accent_bg_color {accent};
@define-color accent_fg_color {on_accent};
@define-color destructive_color {red};
@define-color destructive_bg_color {red};
@define-color destructive_fg_color {on_red};
@define-color error_color {red};
@define-color window_bg_color {bg};
@define-color window_fg_color {fg};
@define-color view_bg_color {bg};
@define-color view_fg_color {fg};
@define-color headerbar_bg_color {surface};
@define-color headerbar_fg_color {fg};
@define-color headerbar_border_color {border};
@define-color headerbar_backdrop_color {surface};
@define-color dialog_bg_color {surface};
@define-color dialog_fg_color {fg};
@define-color popover_bg_color {surface};
@define-color popover_fg_color {fg};
@define-color card_bg_color {raised};
@define-color card_fg_color {fg};
@define-color theme_selected_bg_color {accent};
@define-color theme_selected_fg_color {on_accent};
"""

WINDOW_CSS = """
.window-cligrid, .cligrid-dialog, menu, tooltip {{
  font-family: {ui_font};
}}
.window-cligrid {{
  background-image: none;
  background-color: {bg};
  color: {fg};
}}
.window-cligrid headerbar {{
  background-image: none;
  background-color: {surface};
  color: {fg};
  border: none;
  border-bottom: 1px solid {border};
  box-shadow: inset 0 1px 0 alpha({fg}, 0.06), 0 4px 18px alpha(black, 0.28);
  min-height: 60px;
  padding: 0 12px;
}}
.window-cligrid headerbar:backdrop {{
  background-color: {surface};
}}
.window-cligrid headerbar button {{
  background-image: none;
  background-color: transparent;
  color: {subtle};
  border: 1px solid transparent;
  border-radius: 7px;
  box-shadow: none;
  text-shadow: none;
  min-height: 38px;
  min-width: 38px;
  padding: 0 8px;
  font-size: 13px;
  transition: background-color {t_fast} {ease}, color {t_fast} {ease},
              box-shadow {t_fast} {ease};
}}
.window-cligrid headerbar button:hover {{
  background-color: {hover};
  color: {fg};
}}
.window-cligrid headerbar button:checked,
.window-cligrid headerbar button:active {{
  background-color: {accent_soft};
  color: {fg};
  box-shadow: none;
}}
.window-cligrid headerbar button:focus {{
  box-shadow: 0 0 0 2px alpha({accent}, 0.55);
}}
.window-cligrid headerbar button.command-trigger {{
  color: {subtle};
  background-image: none;
  border: 1px solid {border};
  box-shadow: none;
}}
.window-cligrid headerbar button.command-trigger:hover {{
  color: {fg};
  background-color: {hover};
  border-color: {muted};
  box-shadow: none;
}}
.window-cligrid headerbar button.image-button {{
  padding: 0 6px;
}}
.window-cligrid headerbar button.titlebutton {{
  min-height: 24px;
  min-width: 24px;
  padding: 0;
  margin: 0 2px;
  border-radius: 999px;
}}
.window-cligrid headerbar button.titlebutton.close:hover {{
  background-color: {red};
  color: {on_red};
}}
.window-cligrid .brand {{
  color: {fg};
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.3px;
  margin: 0 16px 0 2px;
}}
.window-cligrid .brand-mark {{
  color: {accent};
  background-image: none;
  border: 1px solid alpha({accent}, 0.30);
  border-radius: 9px;
  padding: 8px;
  box-shadow: none;
  margin-left: 4px;
}}
.window-cligrid .switcher {{
  background-image: linear-gradient(to bottom, {surface}, {bg});
  background-color: {bg};
  border: 1px solid {border};
  border-radius: 12px;
  padding: 4px;
  box-shadow: inset 0 1px 2px alpha(black, 0.30), 0 1px 0 alpha({fg}, 0.06);
}}
.window-cligrid headerbar .switcher button {{
  min-width: 28px;
  min-height: 34px;
  padding: 0 4px;
  border-radius: 6px;
  font-size: 12px;
  font-feature-settings: "tnum";
  transition: background-color {t_fast} {ease}, color {t_fast} {ease},
              box-shadow {t_fast} {ease};
}}
.window-cligrid headerbar .switcher button.active {{
  background-color: {accent};
  color: {on_accent};
  font-weight: 700;
}}
.window-cligrid headerbar .switcher button.exited {{
  color: {red};
}}
.window-cligrid headerbar .switcher button.active.exited {{
  background-image: none;
  background-color: {red};
  color: {on_red};
}}
.window-cligrid headerbar .switcher button.add {{
  color: {muted};
}}
.window-cligrid headerbar .switcher button.add:hover {{
  color: {fg};
}}
.window-cligrid .status {{
  color: {muted};
  font-family: {mono_font};
  font-size: 11px;
  font-feature-settings: "tnum";
  margin: 0 8px;
}}
tooltip {{
  background-color: {raised};
  border: 1px solid {border};
  border-radius: 6px;
}}
tooltip * {{
  color: {fg};
}}
menu, .menu, .context-menu {{
  background-color: {surface};
  color: {fg};
  border: 1px solid {border};
  padding: 4px 0;
}}
menu menuitem {{
  color: {fg};
  padding: 6px 14px;
  min-height: 18px;
}}
menu menuitem:hover {{
  background-color: {accent_soft};
  color: {fg};
}}
menu menuitem:disabled,
menu menuitem:disabled label {{
  color: {muted};
}}
menu menuitem accelerator {{
  color: {muted};
  margin-left: 24px;
}}
menu separator {{
  background-color: {border};
  margin: 4px 0;
  min-height: 1px;
}}
"""

PANE_CSS = """
.window-cligrid .grid-scroll,
.window-cligrid .grid-scroll viewport {{
  background-image: none;
  background-color: {bg_deep};
  border: none;
}}
.window-cligrid scrollbar {{
  background-color: transparent;
  border: none;
}}
.window-cligrid scrollbar slider {{
  background-color: {muted};
  border: 2px solid transparent;
  border-radius: 8px;
  min-width: 6px;
  min-height: 40px;
  transition: background-color {t_fast} {ease};
}}
.window-cligrid scrollbar slider:hover {{
  background-color: {subtle};
}}
.window-cligrid .pane {{
  background-color: {bg};
  border: 1px solid {border};
  border-radius: 12px;
  box-shadow: 0 4px 10px alpha(black, 0.25);
  transition: border-color {t_base} {ease}, box-shadow {t_base} {ease},
              background-color {t_base} {ease};
}}
.window-cligrid .pane.hover {{
  border-color: {subtle};
}}
.window-cligrid .pane.focused {{
  border-color: {accent};
  box-shadow: 0 0 0 1px alpha({accent}, 0.20);
}}
.window-cligrid .pane.exited {{
  border-color: {red_line};
}}
.window-cligrid .pane:drop(active) {{
  border-color: {accent};
  box-shadow: inset 0 0 0 1px {accent};
}}
.window-cligrid .pane-header {{
  background-image: none;
  background-color: {surface};
  border-bottom: 1px solid {border};
  border-radius: 11px 11px 0 0;
  padding: 0 4px 0 8px;
  min-height: 44px;
  transition: background-color {t_base} {ease}, box-shadow {t_base} {ease};
}}
.window-cligrid .pane.focused .pane-header {{
  background-image: none;
  background-color: {raised};
}}
.window-cligrid .pane-index {{
  min-width: 24px;
  min-height: 24px;
  border-radius: 5px;
  margin: 10px 0;
  background-color: {raised};
  color: {muted};
  font-size: 12px;
  font-weight: 700;
  font-feature-settings: "tnum";
}}
.window-cligrid .pane.focused .pane-index {{
  color: {accent};
}}
.window-cligrid .pane-name {{
  color: {subtle};
  font-size: 12px;
  font-weight: 600;
}}
.window-cligrid .pane.focused .pane-name {{
  color: {fg};
}}
.window-cligrid .pane.exited .pane-name {{
  color: {red};
}}
.window-cligrid .pane-cwd {{
  color: {muted};
  font-family: {mono_font};
  font-size: 11px;
}}
.window-cligrid .pane.focused .pane-cwd {{
  color: {subtle};
}}
.window-cligrid .pane-actions {{
  opacity: 0.65;
  transition: opacity {t_fast} {ease};
}}
.window-cligrid .pane.focused .pane-actions,
.window-cligrid .pane.hover .pane-actions {{
  opacity: 1;
}}
.window-cligrid .pane button.icon-btn {{
  background-image: none;
  background-color: transparent;
  color: {muted};
  border: none;
  box-shadow: none;
  border-radius: 6px;
  min-height: 40px;
  min-width: 32px;
  padding: 0 4px;
  transition: background-color {t_fast} {ease}, color {t_fast} {ease};
}}
.window-cligrid .pane button.icon-btn:focus,
.window-cligrid .pane button.icon-btn:hover {{
  background-color: {hover};
  color: {fg};
}}
.window-cligrid vte-terminal {{
  padding: {pad}px;
}}
.window-cligrid .pane-body {{
  margin: 0 {inset}px {inset}px {inset}px;
}}
.window-cligrid .find-bar {{
  background-color: {surface};
  border: 1px solid {border};
  border-radius: 9px;
  padding: 4px;
  margin: 8px 10px;
  box-shadow: 0 4px 12px alpha(black, 0.35);
}}
.window-cligrid .find-bar entry {{
  background-color: {bg};
  color: {fg};
  border: 1px solid {border};
  border-radius: 6px;
  box-shadow: none;
  padding: 0 8px;
  min-height: 26px;
  caret-color: {accent};
}}
.window-cligrid .find-bar entry:focus {{
  border-color: {accent};
}}
.window-cligrid .find-bar button {{
  background-image: none;
  background-color: transparent;
  color: {subtle};
  border: none;
  box-shadow: none;
  border-radius: 6px;
  min-height: 26px;
  min-width: 26px;
  padding: 0 4px;
}}
.window-cligrid .find-bar button:hover {{
  background-color: {hover};
  color: {fg};
}}
.window-cligrid .exited-banner {{
  background-color: {surface};
  border: 1px solid {red_line};
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 6px 18px alpha(black, 0.4);
}}
.window-cligrid .banner-title {{
  color: {fg};
  font-size: 13px;
  font-weight: 700;
}}
.window-cligrid .banner-detail {{
  color: {subtle};
  font-size: 12px;
}}
.window-cligrid .exited-banner button {{
  background-image: none;
  background-color: {raised};
  color: {fg};
  border: 1px solid {border};
  border-radius: 7px;
  box-shadow: none;
  padding: 0 12px;
  min-height: 28px;
  font-weight: 600;
}}
.window-cligrid .exited-banner button:hover {{
  background-color: {hover};
}}
.window-cligrid .exited-banner button.suggested-action {{
  background-color: {accent};
  color: {on_accent};
  border-color: {accent};
}}
.window-cligrid .exited-banner button.suggested-action:hover {{
  background-color: {accent_hover};
}}
"""

DIALOG_CSS = """
.cligrid-dialog {{
  background-color: {surface};
  color: {fg};
}}
.cligrid-dialog .titlebar,
.cligrid-dialog .titlebar:backdrop {{
  min-height: 0;
  margin: 0;
  padding: 0;
  border: none;
  box-shadow: none;
  background: none;
}}
.cligrid-dialog .dialog-body {{
  padding: 20px 22px 4px 22px;
}}
.cligrid-dialog .dialog-title {{
  color: {fg};
  font-size: 17px;
  font-weight: 700;
}}
.cligrid-dialog .dialog-copy {{
  color: {subtle};
  font-size: 13px;
}}
.cligrid-dialog .section-title {{
  color: {accent};
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
}}
.cligrid-dialog .field-label {{
  color: {fg};
  font-size: 13px;
}}
.cligrid-dialog .field-hint {{
  color: {muted};
  font-size: 12px;
}}
.cligrid-dialog .dialog-action-box {{
  padding: 16px 22px 20px 22px;
}}
.cligrid-dialog button {{
  background-image: none;
  background-color: {raised};
  color: {fg};
  border: 1px solid {border};
  border-radius: 8px;
  box-shadow: none;
  text-shadow: none;
  padding: 0 16px;
  min-height: 32px;
  font-weight: 600;
}}
.cligrid-dialog button:hover {{
  background-color: {hover};
}}
.cligrid-dialog button.suggested-action {{
  background-color: {accent};
  color: {on_accent};
  border-color: {accent};
}}
.cligrid-dialog button.suggested-action:hover {{
  background-color: {accent_hover};
  border-color: {accent_hover};
}}
.cligrid-dialog button.destructive-action {{
  background-color: {red};
  color: {on_red};
  border-color: {red};
}}
.cligrid-dialog button.destructive-action:hover {{
  background-color: {red_hover};
  border-color: {red_hover};
}}
.cligrid-dialog entry,
.cligrid-dialog spinbutton {{
  background-color: {bg};
  color: {fg};
  border: 1px solid {border};
  border-radius: 8px;
  box-shadow: none;
  min-height: 32px;
}}
.cligrid-dialog entry {{
  padding: 0 10px;
  caret-color: {accent};
}}
.cligrid-dialog spinbutton entry {{
  background-color: transparent;
  border: none;
  min-height: 30px;
  padding: 0 8px;
}}
.cligrid-dialog spinbutton button {{
  background-color: transparent;
  color: {subtle};
  border: none;
  border-left: 1px solid {border};
  border-radius: 0;
  min-height: 30px;
  min-width: 30px;
  padding: 0;
}}
.cligrid-dialog spinbutton button:last-child {{
  border-radius: 0 7px 7px 0;
}}
.cligrid-dialog spinbutton button:hover {{
  background-color: {hover};
  color: {fg};
}}
.cligrid-dialog entry:focus,
.cligrid-dialog spinbutton:focus {{
  border-color: {accent};
}}
.cligrid-dialog selection {{
  background-color: {selection_bg};
  color: {selection_fg};
}}
.cligrid-dialog combobox button {{
  padding: 0 10px;
  font-weight: normal;
}}
.cligrid-dialog switch {{
  background-color: {hover};
  border: 1px solid {border};
  border-radius: 999px;
}}
.cligrid-dialog switch:checked {{
  background-color: {accent};
  border-color: {accent};
}}
.cligrid-dialog switch slider {{
  background-color: {fg};
  border: none;
  border-radius: 999px;
  box-shadow: none;
  min-width: 20px;
  min-height: 20px;
}}
.cligrid-dialog switch:checked slider {{
  background-color: {on_accent};
}}
.cligrid-dialog .kbd {{
  background-color: {bg};
  color: {fg};
  border: 1px solid {border};
  border-bottom-width: 2px;
  border-radius: 5px;
  padding: 0 7px;
  font-family: {mono_font};
  font-size: 11px;
}}
.cligrid-dialog .about-name {{
  color: {fg};
  font-size: 20px;
  font-weight: 700;
}}
.cligrid-dialog .about-version {{
  color: {muted};
  font-family: {mono_font};
  font-size: 12px;
}}
.cligrid-dialog .about-author {{
  color: {muted};
  font-size: 12px;
}}
"""

TINT_CSS = """
.window-cligrid .pane.tint-{i} {{
  border-color: {border};
}}
.window-cligrid .pane.tint-{i}.focused {{
  border-color: {color};
}}
.window-cligrid .pane.tint-{i} .pane-header {{
  background-image: linear-gradient(110deg, alpha({color}, 0.04), transparent 75%);
  background-color: {base};
  box-shadow: none;
}}
.window-cligrid .pane.tint-{i}.focused .pane-header {{
  background-color: {wash};
  box-shadow: inset 0 1px 0 {glint}, inset 0 -1px 0 alpha({color}, 0.20);
}}
.window-cligrid .pane.tint-{i}.hover {{
  border-color: {color};
  box-shadow: none;
}}
.window-cligrid .pane.tint-{i}.focused {{
  box-shadow: 0 0 0 1px alpha({color}, 0.32),
              0 0 18px alpha({color}, 0.26), 0 6px 16px alpha(black, 0.35);
}}
.window-cligrid .pane.tint-{i} .pane-index {{
  color: {on_color};
  background-image: none;
  background-color: {color};
  box-shadow: none;
}}
.window-cligrid headerbar .switcher button.tint-{i} {{
  color: {ink};
}}
.window-cligrid headerbar .switcher button.tint-{i}:hover {{
  background-color: {soft};
}}
.window-cligrid headerbar .switcher button.tint-{i}.active {{
  background-color: {color};
  color: {on_color};
  background-image: none;
  box-shadow: none;
}}
.window-cligrid .pane.tint-{i}.alert {{
  border-color: {faint};
}}
.window-cligrid .pane.tint-{i}.alert.alert-on {{
  border-color: {color};
}}
.window-cligrid .pane.tint-{i}.alert.alert-on .pane-header {{
  background-color: {soft};
  box-shadow: inset 0 3px 0 0 {color};
}}
.window-cligrid .pane.tint-{i} .alert-dot {{
  color: {ink};
}}
.window-cligrid headerbar .switcher button.tint-{i}.activity {{
  box-shadow: inset 0 -2px 0 0 {faint};
}}
.window-cligrid headerbar .switcher button.tint-{i}.alert {{
  box-shadow: inset 0 -2px 0 0 {color};
}}
.window-cligrid headerbar .switcher button.tint-{i}.alert.alert-on {{
  background-color: {soft};
  color: {ink};
}}
"""

# After the tints, so an exited pane reads red whatever its position color.
EXITED_CSS = """
.window-cligrid .alert-dot {{
  font-size: 10px;
}}
.window-cligrid .pane.alert:not(.alert-on) .alert-dot {{
  opacity: 0.45;
}}
.window-cligrid .pane.exited,
.window-cligrid .pane.exited.focused {{
  border-color: {red_line};
}}
.window-cligrid .pane.exited .pane-header {{
  box-shadow: inset 0 2px 0 0 {red};
}}
.window-cligrid .pane.exited .pane-index {{
  color: {red};
}}
.window-cligrid headerbar .switcher button.exited {{
  color: {red};
}}
.window-cligrid headerbar .switcher button.active.exited {{
  background-image: none;
  background-color: {red};
  color: {on_red};
}}
"""

# Pane state badges: what each pane is doing, on the title strip.
STATE_CSS = """
.window-cligrid .pane-state {{
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background-color: {hover};
  color: {muted};
}}
.window-cligrid .pane-state.state-running {{
  background-color: {accent_soft};
  color: {accent};
}}
.window-cligrid .pane-state.state-waiting {{
  background-color: {warn};
  color: {on_warn};
}}
.window-cligrid .pane-state.state-failed {{
  background-color: {red};
  color: {on_red};
}}
.window-cligrid .pane-state.state-exited {{
  background-color: {red_soft};
  color: {red};
}}
.window-cligrid .pane-branch {{
  color: {purple};
  font-family: {mono_font};
  font-size: 10px;
  padding: 0 4px;
}}
.window-cligrid .pane-elapsed {{
  color: {muted};
  font-family: {mono_font};
  font-size: 10px;
  font-feature-settings: "tnum";
}}
.window-cligrid .pane.chip-selected .pane-header {{
  background-color: {accent_soft};
}}
.window-cligrid headerbar .switcher button.waiting {{
  box-shadow: inset 0 -3px 0 0 {warn};
  color: {warn};
}}
.window-cligrid headerbar button.attention-chip {{
  color: {warn};
  font-weight: 700;
}}
.window-cligrid headerbar button.ws-chip {{
  font-weight: 600;
  color: {subtle};
}}
.window-cligrid headerbar .prefix-chip {{
  background-color: {accent};
  color: {on_accent};
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.6px;
}}
"""

# The command palette and the grid-wide search results list.
PALETTE_CSS = """
.window-cligrid .palette-scrim {{
  background-color: alpha(black, 0.45);
}}
.window-cligrid .palette-card {{
  background-image: none;
  background-color: {surface};
  border: 1px solid {border};
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 20px 48px alpha(black, 0.60);
}}
.window-cligrid .palette-title {{
  color: {fg};
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 0 0 8px 0;
}}
.window-cligrid .palette-card entry {{
  background-color: {bg};
  color: {fg};
  border: 1px solid {accent};
  border-radius: 8px;
  min-height: 44px;
  font-size: 15px;
  padding: 0 12px;
  caret-color: {accent};
}}
.window-cligrid .palette-list {{
  background-color: transparent;
}}
.window-cligrid .palette-list row {{
  min-height: 36px;
  padding: 6px 8px;
  border-radius: 7px;
}}
.window-cligrid .palette-list row:selected {{
  background-image: linear-gradient(to right, alpha({accent}, 0.12), transparent);
  background-color: {accent_soft};
  box-shadow: inset 3px 0 0 {accent}, inset 0 1px 0 alpha({accent}, 0.16);
}}
.window-cligrid .palette-label {{
  color: {fg};
  font-size: 13px;
}}
.window-cligrid .palette-label.match {{
  color: {accent};
  font-weight: 700;
}}
.window-cligrid .palette-hint {{
  color: {muted};
  font-family: {mono_font};
  font-size: 11px;
}}
.window-cligrid .palette-empty {{
  color: {muted};
  padding: 10px;
}}
.window-cligrid .result-row {{
  padding: 6px 8px;
  border-radius: 7px;
}}
.window-cligrid .result-pane {{
  color: {accent};
  font-weight: 700;
  font-size: 12px;
}}
.window-cligrid .result-line {{
  color: {fg};
  font-family: {mono_font};
  font-size: 11px;
}}
.window-cligrid .result-hit {{
  color: {warn};
  font-weight: 700;
}}
.window-cligrid .palette-section {{
  color: {muted};
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
  padding: 16px 8px 6px 8px;
}}
.window-cligrid .palette-footer {{
  border-top: 1px solid {border};
  padding: 8px 4px 0 4px;
}}
"""

# Surfaces, elevation and focus, kept beside the palette rather than scattered
# through the rules above.
CHROME_CSS = """
.window-cligrid .grid-scroll viewport {{
  box-shadow: none;
}}
.cligrid-dialog entry,
.window-cligrid entry {{
  transition: border-color {t_fast} {ease}, box-shadow {t_fast} {ease};
}}
.cligrid-dialog entry:focus,
.window-cligrid entry:focus {{
  border-color: {accent};
  box-shadow: 0 0 0 2px alpha({accent}, 0.28);
}}
.cligrid-dialog button:focus,
.window-cligrid .exited-banner button:focus {{
  box-shadow: 0 0 0 2px alpha({accent}, 0.45);
}}
.window-cligrid .menu menuitem,
.window-cligrid menu menuitem {{
  transition: background-color {t_fast} {ease}, color {t_fast} {ease};
}}
"""

# Action feedback: the app says what it just did, in place, without a dialog.
TOAST_CSS = """
.window-cligrid .toast-layer {{
  margin-bottom: 16px;
  background-color: transparent;
}}
.window-cligrid .toast-card {{
  background-color: {raised};
  border: 1px solid {border};
  border-left: 3px solid {accent};
  border-radius: 10px;
  padding: 9px 14px;
  box-shadow: 0 10px 26px alpha(black, 0.45);
  min-width: 200px;
}}
.window-cligrid .toast-card.toast-success {{ border-left-color: {ok}; }}
.window-cligrid .toast-card.toast-warn {{ border-left-color: {warn}; }}
.window-cligrid .toast-card.toast-error {{ border-left-color: {red}; }}
.window-cligrid .toast-text {{
  color: {fg};
  font-size: 13px;
  font-weight: 600;
}}
.window-cligrid .toast-detail {{
  color: {muted};
  font-family: {mono_font};
  font-size: 11px;
}}
"""

CSS = build_css(THEME)


_STORE = {"cfg": None}  # schema 2 configuration, read once per process


def read_store():
    """Schema 2 configuration from disk, migrated on read and cached here, so a
    workspace switch does not need to re-read a file the grid is also writing."""
    if _STORE["cfg"] is None:
        raw = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as fh:
                    raw = json.load(fh)
            except Exception as exc:  # never let a bad config stop the grid
                sys.stderr.write("cligrid: config unreadable (%s), using defaults\n" % exc)
                raw = {}
        _STORE["cfg"] = workspace.migrate(raw)
    return _STORE["cfg"]


def set_store(store):
    """Replace the cached schema 2 configuration."""
    _STORE["cfg"] = workspace.validate(store)
    return _STORE["cfg"]


def write_json_atomic(path, data):
    """Write JSON through a sibling temp file and rename it into place, so a
    crash mid-write leaves the previous file rather than a truncated one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def write_store(store):
    write_json_atomic(CONFIG_PATH, store)


def flatten_config(store):
    """The runtime config the window works with: the global preferences plus the
    active workspace, in the flat shape the rest of this file already uses."""
    store = workspace.validate(store)
    active = workspace.active_workspace(store)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy of the defaults
    for key in workspace.GLOBAL_KEYS:
        if key in store:
            cfg[key] = store[key]
    for key in ("pane_count", "panes", "layout", "cwd", "stack"):
        if key in active:
            cfg[key] = active[key]
    cfg["font_size"] = as_int(cfg.get("font_size"), DEFAULT_CONFIG["font_size"])
    cfg["min_font_size"] = as_int(cfg.get("min_font_size"), DEFAULT_CONFIG["min_font_size"])
    cfg["min_cols"] = as_int(cfg.get("min_cols"), DEFAULT_CONFIG["min_cols"])
    cfg["min_rows"] = as_int(cfg.get("min_rows"), DEFAULT_CONFIG["min_rows"])
    cfg["scrollback"] = as_int(cfg.get("scrollback"), DEFAULT_CONFIG["scrollback"])
    cfg["auto_font"] = as_bool(cfg.get("auto_font"), True)
    cfg["cursor_blink"] = as_bool(cfg.get("cursor_blink"), False)
    cfg["banner"] = as_bool(cfg.get("banner"), True)
    for key in ("bell_alerts", "activity_marks", "notify_desktop"):
        cfg[key] = as_bool(cfg.get(key), True)
    cfg["restore_on_start"] = as_bool(cfg.get("restore_on_start"), True)
    cfg["font"] = str(cfg.get("font") or DEFAULT_CONFIG["font"])
    cfg["fit"] = str(cfg.get("fit") or DEFAULT_CONFIG["fit"])
    cfg["cwd"] = str(cfg.get("cwd") or DEFAULT_CONFIG["cwd"])
    cfg["layout"] = layout.normalize_shape(cfg.get("layout"))
    cfg["prefix"] = str(cfg.get("prefix") or "space")
    guard = str(cfg.get("guard") or "panes").strip().lower()
    cfg["guard"] = guard if guard in control.GUARD_MODES else "panes"
    cfg["quiet_hours"] = str(cfg.get("quiet_hours") or "")
    if not isinstance(cfg.get("keymap"), dict):
        cfg["keymap"] = {}
    if not isinstance(cfg.get("notify_rules"), list):
        cfg["notify_rules"] = []
    if not isinstance(cfg.get("stack"), list):
        cfg["stack"] = []
    cfg["stack"] = [group for group in cfg["stack"]
                    if isinstance(group, list) and len(group) > 1]
    cfg["workspace"] = active["name"]
    raw_panes = cfg.get("panes")
    counted = isinstance(raw_panes, list) and "pane_count" not in cfg
    inferred = len(raw_panes) if counted else cfg.get("pane_count")
    cfg["pane_count"] = clamp_pane_count(inferred if inferred else DEFAULT_PANE_COUNT)
    cfg["panes"] = normalize_panes(raw_panes, cfg["pane_count"])
    heal_panes_flag(cfg)
    cfg.pop("version", None)
    cfg.pop("workspaces", None)
    cfg.pop("active", None)
    return cfg


def load_config():
    """Runtime configuration for the active workspace (schema 2 on disk)."""
    return flatten_config(read_store())


def save_config(cfg):
    """Fold the runtime config back into the store and write it out."""
    store = read_store()
    for key in workspace.GLOBAL_KEYS:
        if key in cfg:
            store[key] = cfg[key]
    store = workspace.update_workspace(
        store, panes=cfg.get("panes"), pane_count=cfg.get("pane_count"),
        layout=cfg.get("layout"), cwd=cfg.get("cwd"), stack=cfg.get("stack"))
    set_store(store)
    write_store(_STORE["cfg"])
    return _STORE["cfg"]


STATE_TEXT = {
    state.STATE_IDLE: "At a prompt; nothing running",
    state.STATE_RUNNING: "Working: a program is running",
    state.STATE_WAITING: "Waiting for you: it needs an answer",
    state.STATE_EXITED: "The program ended",
    state.STATE_FAILED: "The program ended with an error",
}


def state_text(name):
    """Human sentence for a pane state, for tooltips and notifications."""
    return STATE_TEXT.get(name, "")


def resident_mb():
    """Resident set size of this process, in MB, or None when unavailable.

    Linux reads /proc. macOS has no /proc, so it reports the peak resident size
    from resource, the closest figure available without a native call.
    """
    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    if sys.platform == "darwin":
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if peak:
                return round(peak / (1024.0 * 1024.0), 1)  # ru_maxrss is bytes on macOS
        except (ImportError, OSError, ValueError):
            return None
    return None


def theme_for(name, base):
    """Theme dict for the theme setting. "kitty" keeps what kitty.conf says; a
    preset overrides the colours and keeps the terminal preferences."""
    preset = art.theme_preset(name)
    if preset is None:
        return base
    theme = dict(base)
    theme.update(preset)
    for key in ("font_family", "font_size", "scrollback", "padding", "copy_on_select"):
        if base.get(key) is not None:
            theme[key] = base[key]
    return theme


ACTIVE_THEME = {"name": "griderator"}


def active_theme_name():
    """The theme setting currently in force: "kitty" or a preset name."""
    return ACTIVE_THEME["name"]


def set_active_theme(name):
    """Record the theme setting. An unknown name changes nothing, so a typo can
    never quietly replace the chosen theme with the fallback."""
    preset = art.theme_preset(name)
    if preset is not None:
        ACTIVE_THEME["name"] = str(name).strip().lower()
    return ACTIVE_THEME["name"]


class ControlLink:
    """One control-socket client: bounded, asynchronous output.

    Every write goes through a queue drained with write_bytes_async, so a
    client that stops reading `cligrid events` can never stall the GTK main
    loop. When the unread backlog passes MAX_PENDING_BYTES the client is
    dropped and `on_gone` runs, which is how the window forgets a subscriber
    or a waiter. `finish()` closes the connection once the queue drains, which
    is the shape every one-reply verb uses.
    """

    CHUNK = 64 * 1024

    def __init__(self, connection, on_gone=None):
        self.connection = connection
        self.stream = connection.get_output_stream()
        self.pending = bytearray()
        self.writing = False
        self.closing = False
        self.gone = False
        self.on_gone = on_gone
        self.reason = ""

    def send(self, data):
        """Queue bytes for the client. False when the client is gone or too slow."""
        if self.gone:
            return False
        if isinstance(data, str):
            data = data.encode()
        if len(self.pending) + len(data) > control.MAX_PENDING_BYTES:
            self.fail("slow reader: %d bytes unread" % len(self.pending))
            return False
        self.pending += data
        self._pump()
        return True

    def finish(self):
        """Close once everything queued has been written."""
        self.closing = True
        self._pump()

    def _pump(self):
        if self.gone or self.writing:
            return
        if not self.pending:
            if self.closing:
                self.close()
            return
        self.writing = True
        chunk = bytes(self.pending[:self.CHUNK])
        try:
            self.stream.write_bytes_async(
                GLib.Bytes.new(chunk), GLib.PRIORITY_DEFAULT, None, self._written)
        except Exception as exc:  # a stream already torn down by the peer
            self.writing = False
            self.fail(str(exc))

    def _written(self, stream, result):
        self.writing = False
        try:
            count = stream.write_bytes_finish(result)
        except GLib.Error as exc:
            self.fail(exc.message)
            return
        if count <= 0:
            self.fail("client closed")
            return
        del self.pending[:count]
        self._pump()

    def fail(self, reason=""):
        """The client is unusable: drop the backlog, close, tell the owner."""
        if self.gone:
            return
        self.reason = reason
        self.close()
        if self.on_gone:
            callback, self.on_gone = self.on_gone, None
            callback(self)

    def close(self):
        self.gone = True
        self.pending = bytearray()
        try:
            self.connection.close(None)
        except Exception:
            pass


class Pane:
    """One grid cell: a title strip plus an embedded terminal."""

    def __init__(self, app, slot):
        self.app = app
        self.slot = slot
        self.name = app.config["panes"][slot]["name"]
        self.cmd = app.config["panes"][slot]["cmd"]
        self.exited = False
        self.last_status = None
        self.font_size = app.font_size
        self.pending_fresh = False
        self.spawned = False
        self.cwd = app.config.get("cwd") or ""
        self.started_at = 0
        self.quick_exits = 0
        self.dead = False  # set once the pane leaves the grid
        self.mark = None  # "alert" after a bell, "activity" after new output
        self.seen_text = None  # screen text when the pane was last looked at
        self.state = state.STATE_IDLE  # idle, running, waiting, exited, failed
        self.state_since = 0
        self.output_at = 0  # when the screen last changed, for the state poll
        self.poll_text = None  # last text the state poll saw (separate from seen_text)
        self.dirty = True  # set by contents-changed, cleared by the state poll
        self.branch = ""  # git branch of the pane's directory, when there is one
        self.pid = 0
        self.last_notified = 0
        self.notification_id = 0
        self._activity_check = 0
        self._selection = ""  # last selected text; right-click can clear VTE's selection

        self.box = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "pane")
        self.box.set_hexpand(True)
        self.box.set_vexpand(True)
        self.box.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.DROP | Gtk.DestDefaults.HIGHLIGHT,
            [Gtk.TargetEntry.new("text/plain", 0, 0)],
            Gdk.DragAction.MOVE,
        )
        self.box.connect("drag-data-received", self.on_drop)

        # The whole title strip is the drag handle: drag onto another pane to swap.
        self.header = Gtk.EventBox()
        self.header.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.header.connect("button-press-event", self.on_header_click)
        self.header.connect("enter-notify-event", self.on_hover, True)
        self.header.connect("leave-notify-event", self.on_hover, False)
        self.header.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            [Gtk.TargetEntry.new("text/plain", 0, 0)],
            Gdk.DragAction.MOVE,
        )
        self.header.drag_source_set_icon_name("utilities-terminal-symbolic")
        self.header.connect("drag-data-get", self.on_drag_get)

        row = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8), "pane-header")
        self.index = styled(Gtk.Label(label=str(slot + 1), xalign=0.5), "pane-index")
        self.label = styled(Gtk.Label(label=self.name, xalign=0.0), "pane-name")
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_tooltip_text("Drag to swap with another pane · double-click to zoom")
        self.cwd_label = styled(Gtk.Label(label="", xalign=0.0), "pane-cwd")
        self.cwd_label.set_ellipsize(Pango.EllipsizeMode.START)
        self.alert_dot = styled(Gtk.Label(label="●"), "alert-dot")
        self.alert_dot.set_tooltip_text("Rang its bell")
        self.alert_dot.set_no_show_all(True)
        # What the pane is doing, plus its git branch, right of the directory.
        self.state_label = styled(Gtk.Label(label=""), "pane-state")
        self.state_label.set_no_show_all(True)
        self.state_label.set_tooltip_text("Pane state")
        self.branch_label = styled(Gtk.Label(label=""), "pane-branch")
        self.branch_label.set_no_show_all(True)

        # Actions stay discoverable; focus and hover increase their contrast
        # without changing the strip height or terminal rows.
        actions = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2), "pane-actions")
        self.zoom_btn = icon_button(
            "view-fullscreen-symbolic", "⛶",
            "Zoom this pane  (Ctrl+Shift+Z)",
            lambda: self.app.zoom_pane(self),
        )
        find_btn = icon_button(
            "edit-find-symbolic", "/",
            "Find in this pane  (Ctrl+Shift+G)",
            self.show_find,
        )
        self.more_btn = icon_button(
            "view-more-symbolic", "⋮",
            "Pane actions",
            lambda: self.app.popup_menu(self, None, self.more_btn),
        )
        for button in (self.zoom_btn, find_btn, self.more_btn):
            actions.pack_start(button, False, False, 0)

        row.pack_start(self.index, False, False, 0)
        row.pack_start(self.label, False, False, 0)
        row.pack_start(self.alert_dot, False, False, 0)
        row.pack_start(self.cwd_label, True, True, 0)
        row.pack_end(actions, False, False, 0)
        row.pack_end(self.state_label, False, False, 0)
        row.pack_end(self.branch_label, False, False, 0)
        self.header.add(row)

        self.term = Vte.Terminal()
        self.term.set_vexpand(True)
        self.term.set_hexpand(True)
        self.term.set_scrollback_lines(app.config["scrollback"])
        self.term.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if app.config["cursor_blink"] else Vte.CursorBlinkMode.OFF
        )
        self.term.set_scroll_on_output(False)
        self.term.set_mouse_autohide(True)
        self.term.set_audible_bell(False)
        self.term.set_allow_hyperlink(True)
        self.term.set_cursor_shape(Vte.CursorShape.BLOCK)
        try:
            self.term.set_word_char_exceptions(WORD_CHARS)
        except Exception:
            pass
        self.term.connect("child-exited", self.on_child_exited)
        self.term.connect("focus-in-event", self.on_focus)
        self.term.connect("button-press-event", self.on_term_click)
        self.term.connect("selection-changed", self.on_selection)
        self.term.connect("scroll-event", self.on_term_scroll)
        self.term.connect("bell", lambda _term: self.app.pane_bell(self))
        self.term.connect("contents-changed", self.on_contents_changed)
        self.apply_colors()
        self.apply_font(app.font_size)
        self.install_url_match()

        self.banner = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "exited-banner")
        self.banner.set_halign(Gtk.Align.CENTER)
        self.banner.set_valign(Gtk.Align.CENTER)
        self.banner.set_no_show_all(True)
        self.banner_title = styled(Gtk.Label(label="Session ended", xalign=0.0), "banner-title")
        self.banner_detail = styled(Gtk.Label(label="", xalign=0.0), "banner-detail")
        self.banner_detail.set_line_wrap(True)
        self.banner_detail.set_max_width_chars(44)
        banner_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        banner_buttons.set_margin_top(6)
        edit = Gtk.Button(label="Edit command…")
        edit.connect("clicked", lambda *_: self.app.edit_command(self))
        set_accessible(edit, "Edit command")
        restart = styled(Gtk.Button(label="Restart"), "suggested-action")
        restart.connect("clicked", lambda *_: self.restart())
        set_accessible(restart, "Restart pane")
        banner_buttons.pack_end(restart, False, False, 0)
        banner_buttons.pack_end(edit, False, False, 0)
        self.banner.pack_start(self.banner_title, False, False, 0)
        self.banner.pack_start(self.banner_detail, False, False, 0)
        self.banner.pack_start(banner_buttons, False, False, 0)

        self.find_bar = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2), "find-bar")
        self.find_bar.set_halign(Gtk.Align.END)
        self.find_bar.set_valign(Gtk.Align.START)
        self.find_bar.set_no_show_all(True)
        self.find_entry = Gtk.Entry()
        self.find_entry.set_placeholder_text("Find in pane")
        self.find_entry.set_width_chars(22)
        set_accessible(self.find_entry, "Find in pane")
        self.find_entry.connect("changed", lambda *_: self.find_next())
        self.find_entry.connect("key-press-event", self.on_find_key)
        self.find_bar.pack_start(self.find_entry, False, False, 0)
        for icon, fallback, tip, action in (
            ("go-up-symbolic", "↑", "Previous match  (Shift+Enter)", self.find_prev),
            ("go-down-symbolic", "↓", "Next match  (Enter)", self.find_next),
            ("window-close-symbolic", "×", "Close  (Esc)", self.hide_find),
        ):
            self.find_bar.pack_start(icon_button(icon, fallback, tip, action, "find-btn"), False, False, 0)

        overlay = styled(Gtk.Overlay(), "pane-body")
        overlay.add(self.term)
        overlay.add_overlay(self.banner)
        overlay.add_overlay(self.find_bar)
        self.box.pack_start(self.header, False, False, 0)
        self.box.pack_start(overlay, True, True, 0)
        self.box.show_all()
        GLib.idle_add(self.spawn)

    def update_title(self):
        self.index.set_text(str(self.app.position_of(self) + 1))
        self.label.set_text(self.name + ("  ·  exited" if self.exited else ""))
        self.cwd_label.set_text(compact_path(self.cwd))
        self.cwd_label.set_tooltip_text(short_path(self.cwd) or None)
        zoomed = self.app.zoom and self.app.active is self
        icon = "view-restore-symbolic" if zoomed else "view-fullscreen-symbolic"
        if theme_has_icon(icon):
            self.zoom_btn.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        self.zoom_btn.set_tooltip_text(
            "Back to the grid  (Ctrl+Shift+Z)" if zoomed else "Zoom this pane  (Ctrl+Shift+Z)")

    def refresh_cwd(self):
        path = uri_to_path(self.term.get_current_directory_uri())
        if path and path != self.cwd:
            self.cwd = path
            self.cwd_label.set_text(compact_path(path))
            self.cwd_label.set_tooltip_text(short_path(path))
            self.app.add_event("cwd", pane=self.name, cwd=short_path(path))
            if self.app.active is self:
                self.app.update_status()

    def on_hover(self, widget, event, inside):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False  # moving onto a button inside the strip
        ctx = self.box.get_style_context()
        if inside:
            ctx.add_class("hover")
        else:
            ctx.remove_class("hover")
        return False

    def apply_colors(self):
        try:
            self.term.set_colors(
                hex_rgba(THEME["foreground"]), hex_rgba(THEME["background"]),
                [hex_rgba(h) for h in THEME["palette"]],
            )
            self.term.set_color_cursor(hex_rgba(THEME["cursor"]))
            self.term.set_color_cursor_foreground(hex_rgba(THEME["cursor_text"]))
            self.term.set_color_highlight(hex_rgba(THEME["selection_bg"]))
            self.term.set_color_highlight_foreground(hex_rgba(THEME["selection_fg"]))
        except Exception:
            pass

    def install_url_match(self):
        try:
            regex = Vte.Regex.new_for_match(URL_PATTERN, -1, 0x400)
            self.term.match_add_regex(regex, 0)
        except Exception:
            pass

    def apply_font(self, size):
        self.font_size = size
        self.term.set_font(Pango.FontDescription("%s %d" % (self.app.config["font"], size)))

    def apply_terminal_prefs(self):
        self.term.set_scrollback_lines(int(self.app.config["scrollback"]))
        self.term.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if self.app.config["cursor_blink"] else Vte.CursorBlinkMode.OFF
        )
        self.apply_font(self.app.font_size)

    def set_focused(self, focused):
        ctx = self.box.get_style_context()
        if focused:
            ctx.add_class("focused")
        else:
            ctx.remove_class("focused")

    def visible_text(self):
        try:
            return without_status_line(self.term.get_text_format(Vte.Format.TEXT))
        except Exception:
            return None

    def on_contents_changed(self, term):
        self.dirty = True
        if (self.mark or self._activity_check or self.app.active is self
                or not self.app.config.get("activity_marks", True)):
            return
        self._activity_check = GLib.timeout_add(400, self.check_activity)

    def check_activity(self):
        """Mark new output in a background pane; reflow after a layout or font
        change only moves the baseline."""
        self._activity_check = 0
        if self.dead or self.mark or self.app.active is self:
            return False
        text = self.visible_text()
        if self.seen_text is None or GLib.get_monotonic_time() < self.app.quiet_until:
            self.seen_text = text
        elif text != self.seen_text:
            self.set_mark("activity")
        return False

    def screen_text(self, rows=12):
        """The tail of this pane's text, for classification. VTE's range API
        returns nothing usable through GI in this version, so this formats the
        buffer the way the activity check already does and keeps the last rows."""
        text = self.visible_text()
        if not text:
            return ""
        return "\n".join(text.splitlines()[-max(1, rows):])

    def refresh_state(self):
        """Classify what this pane is doing; the badge, the header count and the
        waiting notification all read the result. The screen is only re-read when
        the pane printed something, so an idle grid costs almost nothing."""
        if self.dirty or self.poll_text is None:
            fresh_text = self.screen_text()
            if fresh_text != self.poll_text:
                self.output_at = GLib.get_monotonic_time()
            self.poll_text = fresh_text
            self.dirty = False
        now = GLib.get_monotonic_time()
        command = state.foreground_command(self.pid) if self.pid else None
        age = (now - self.output_at) / 1e6 if self.output_at else None
        self.set_state(state.classify_state(
            self.poll_text, foreground_cmd=command, exited=self.exited,
            exit_status=self.last_status, output_age=age))
        if not self.exited:
            self.refresh_branch()

    def refresh_branch(self):
        branch = state.git_branch(self.cwd) if self.cwd else None
        branch = branch or ""
        if branch == self.branch:
            return
        self.branch = branch
        if branch:
            self.branch_label.set_text(" " + branch)
            self.branch_label.set_tooltip_text("git branch %s" % branch)
            reveal(self.branch_label)
        else:
            self.branch_label.set_tooltip_text(None)
            self.branch_label.hide()

    def set_state(self, fresh):
        if fresh == self.state:
            return
        self.state = fresh
        self.state_since = GLib.get_monotonic_time()
        ctx = self.state_label.get_style_context()
        for name in ("state-idle", "state-running", "state-waiting",
                     "state-exited", "state-failed"):
            ctx.remove_class(name)
        ctx.add_class("state-%s" % fresh)
        badge = state.state_badge(fresh)
        if badge:
            self.state_label.set_text(badge)
            self.state_label.set_tooltip_text(state_text(fresh))
            reveal(self.state_label)
        else:
            self.state_label.set_tooltip_text(None)
            self.state_label.hide()
        self.app.on_pane_state(self, fresh)
        self.app.add_event("state", pane=self.name, state=fresh)

    def set_mark(self, kind):
        """Set the pane's mark: "alert" (rang its bell), "activity" (new output) or None."""
        if kind == self.mark or (kind == "activity" and self.mark == "alert"):
            return
        self.mark = kind
        ctx = self.box.get_style_context()
        for name in ("alert", "activity", "alert-on"):
            ctx.remove_class(name)
        if kind:
            ctx.add_class(kind)
        if kind == "alert":
            reveal(self.alert_dot)
        else:
            self.alert_dot.hide()
        self.app.refresh_pills()
        self.app.update_pulse()

    def set_tint(self, position):
        ctx = self.box.get_style_context()
        tint = "tint-%d" % (position % len(PANE_COLOR_SLOTS))
        if not ctx.has_class(tint):
            for i in range(len(PANE_COLOR_SLOTS)):
                ctx.remove_class("tint-%d" % i)
            ctx.add_class(tint)

    def set_exited(self, exited, title=None, detail=None):
        self.exited = exited
        ctx = self.box.get_style_context()
        if exited:
            ctx.add_class("exited")
            self.banner_title.set_text(title or "Session ended")
            self.banner_detail.set_text(detail or "")
            reveal(self.banner)
            if not detail:
                self.banner_detail.hide()
        else:
            ctx.remove_class("exited")
            self.banner.hide()
        self.update_title()
        self.app.refresh_pills()

    def set_name(self, name):
        name = (name or "").strip()
        if not name:
            return
        self.name = name
        self.app.config["panes"][self.slot]["name"] = name
        save_config(self.app.config)
        self.update_title()
        self.app.update_status()

    def send_text(self, text, enter=True):
        """Type text into the pane's terminal, as if it came from the keyboard.
        This is what `cligrid send` and `cligrid run` use. The introspected VTE
        call takes the text alone; the length argument is handled by GI."""
        payload = "%s%s" % (text, "\n" if enter else "")
        try:
            self.term.feed_child(payload)
            return True
        except Exception as exc:
            first = "%s: %s" % (type(exc).__name__, exc)
        try:
            self.term.feed_child(payload.encode())
            return True
        except Exception as exc:
            second = "%s: %s" % (type(exc).__name__, exc)
        sys.stderr.write("cligrid: feed_child failed (%s / %s)\n" % (first, second))
        return False

    def dump_text(self, lines=40):
        """The last lines of this pane, scrollback included, as plain text.

        VTE's text API only reaches the visible screen, so a tmux pane asks
        tmux for its history instead; a pane running something else, or one
        whose session is gone, falls back to what is on screen."""
        lines = max(1, min(int(lines), MAX_DUMP_LINES))
        captured = tmux_capture(tmux_target(self.cmd, self.name), lines)
        if captured is not None:
            rows = captured.rstrip("\n").splitlines()
            while rows and not rows[-1].strip():  # tmux pads the tail with blank rows
                rows.pop()
            return "\n".join(rows[-lines:])
        text = self.visible_text()
        if text is None:
            text = self.screen_text(rows=lines)
        rows = (text or "").splitlines()
        return "\n".join(rows[-lines:])

    def search_for(self, needle):
        """Open the find bar on a term and jump to its first match."""
        if not needle:
            return False
        self.show_find()
        self.find_entry.set_text(needle)
        if not self._search_regex():
            return False
        self.term.search_find_next()
        return True

    def spawn(self):
        if self.dead:
            return False
        had_child = self.spawned
        self.spawned = False
        self.set_exited(False)
        if had_child:
            self.term.reset(True, True)
        argv = self.spawn_argv()
        try:
            self.term.spawn_async(
                Vte.PtyFlags.DEFAULT,
                self.app.config["cwd"],
                argv,
                env_list(self.slot),
                GLib.SpawnFlags.SEARCH_PATH_FROM_ENVP,
                None, None, -1, None,
                self.on_spawn_finished,
            )
        except Exception as exc:
            self.term.feed(("cligrid: cannot start pane: %s\r\n" % exc).encode())
            self.set_exited(True, "Could not start this pane", str(exc))
        return False

    def spawn_argv(self):
        """The pane command; a brand-new tmux session opens with the welcome banner.
        tmux chrome is restyled with literal theme colours so #{@name} in the
        user's tmux.conf cannot print `bad colour` into the pane."""
        argv = pane_argv(self.cmd)
        split = art.split_tmux_new_session(argv) if self.app.config.get("banner", True) else None
        name = tmux_target(self.cmd, self.name) if split else None
        if name and not tmux_has_session(name):
            position = self.app.position_of(self)
            show = [
                sys.executable, ART_PATH, "banner",
                "--pane", str(position + 1), "--name", name,
                "--color", pane_color(THEME, position),
                "--gradient", ",".join(THEME["palette"][i] for i in (4, 5, 6)),
                "--dim", chrome_palette(THEME)["subtle"],
            ]
            argv = with_banner(split[0], split[1], show)
        return with_tmux_chrome(argv)

    def on_spawn_finished(self, terminal, pid, error):
        if error is not None:
            message = getattr(error, "message", None) or str(error)
            sys.stderr.write("cligrid: cannot start pane %s: %s\n" % (self.name, message))
            self.spawned = False
            self.term.feed(("cligrid: %s\r\n" % message).encode())
            self.set_exited(True, "Could not start this pane", message)
            return
        self.spawned = True
        self.pid = pid or 0
        self.started_at = GLib.get_monotonic_time()
        self.app.add_event("spawn", pane=self.name)
        self.set_exited(False)
        apply_tmux_chrome(tmux_target(self.cmd, self.name))

    def restart(self, cmd=None):
        """Run the pane command again; a tmux pane reattaches to its session."""
        if cmd:
            self.cmd = cmd
            self.app.config["panes"][self.slot]["cmd"] = cmd
            save_config(self.app.config)
        self.quick_exits = 0
        self.spawn()

    def kill_session(self):
        kill_tmux_session(tmux_target(self.cmd, self.name))

    def close_and_respawn(self, confirm=True):
        """Kill this pane's session and open an empty terminal in the same cell."""
        if confirm and not self.app.confirm_reset([self]):
            return
        self.pending_fresh = True
        self.quick_exits = 0
        self.kill_session()
        GLib.timeout_add(80, self._finish_respawn)

    def _finish_respawn(self):
        self.pending_fresh = False
        self.spawn()
        self.app.set_active(self)
        self.app.update_status()
        return False

    def _respawn_in_place(self):
        self.spawn()
        return False

    def copy_text(self):
        text = terminal_selection(self.term) or getattr(self, "_selection", "")
        if not text:
            try:
                if self.term.get_has_selection():
                    self.term.copy_clipboard_format(Vte.Format.TEXT)
                    return True
            except Exception:
                pass
            return False
        try:
            self.term.copy_clipboard_format(Vte.Format.TEXT)
        except Exception:
            pass
        clip, _primary = gtk_clipboards()
        return write_clipboard(text, clipboard=clip)

    def paste_text(self):
        clip, _primary = gtk_clipboards()
        text = clipboard_text(clipboard=clip)
        if text:
            return paste_into_terminal(self.term, text)
        try:
            self.term.paste_clipboard()
            return True
        except Exception:
            return False

    def on_selection(self, term):
        text = terminal_selection(term)
        if text:
            self._selection = text
            if THEME.get("copy_on_select"):
                clip, _primary = gtk_clipboards()
                write_clipboard(text, clipboard=clip)

    def show_find(self):
        reveal(self.find_bar)
        self.find_entry.grab_focus()
        self.find_entry.select_region(0, -1)

    def hide_find(self):
        try:
            self.term.search_set_regex(None, 0)
        except Exception:
            pass
        self.find_bar.hide()
        self.term.grab_focus()

    def on_find_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval) or ""
        backwards = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if key == "Escape":
            self.hide_find()
            return True
        if key in ("Return", "KP_Enter", "ISO_Enter") or (
                key in ("g", "G") and event.state & Gdk.ModifierType.CONTROL_MASK):
            if backwards:
                self.find_prev()
            else:
                self.find_next()
            return True
        return False

    def _search_regex(self):
        text = self.find_entry.get_text()
        if not text:
            self.term.search_set_regex(None, 0)
            return False
        try:
            regex = Vte.Regex.new_for_search(text, -1, 0x400)
            self.term.search_set_regex(regex, 0)
            self.term.search_set_wrap_around(True)
            return True
        except Exception:
            return False

    def find_next(self):
        if self._search_regex():
            self.term.search_find_next()

    def find_prev(self):
        if self._search_regex():
            self.term.search_find_previous()

    def open_url(self, url):
        if not url:
            return
        if url.startswith("www."):
            url = "https://" + url
        try:
            Gtk.show_uri_on_window(self.app.win, url, Gdk.CURRENT_TIME)
        except Exception:
            subprocess.Popen(["xdg-open", url], start_new_session=True)

    def on_child_exited(self, term, status):
        if self.dead:
            return  # a removed pane's client exits after its widgets are gone
        self.last_status = status
        self.app.add_event("exit", pane=self.name, status=status)
        if status:
            self.set_state(state.STATE_FAILED)
        if self.spawned and not self.pending_fresh:
            lived = (GLib.get_monotonic_time() - self.started_at) / 1e6
            self.quick_exits = self.quick_exits + 1 if lived < QUICK_EXIT_SECONDS else 0
        action = decide_child_exit_action(
            self.app.quitting, self.pending_fresh, self.spawned, self.quick_exits)
        self.spawned = False
        if action == "ignore":
            return
        if action == "halt":
            self.set_exited(
                True,
                "This pane keeps exiting",
                "%s\nExited %s right after starting, %d times in a row."
                % (self.cmd, exit_text(status), self.quick_exits),
            )
            return
        GLib.timeout_add(50, self._respawn_in_place)

    def on_focus(self, widget, event):
        self.app.set_active(self)
        return False

    def on_header_click(self, widget, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.app.zoom_pane(self)
            return True
        if event.button == 3:
            self.app.set_active(self)
            self.app.popup_menu(self, event)
            return True
        if event.button == 1:
            self.app.set_active(self)
        return False

    def on_term_click(self, widget, event):
        self.app.set_active(self)
        if event.button == 3:
            text = terminal_selection(self.term)
            if text:
                self._selection = text
            self.app.popup_menu(self, event)
            return True
        if event.button == 1 and (event.state & Gdk.ModifierType.CONTROL_MASK):
            url = None
            try:
                url = self.term.hyperlink_check_event(event)
            except Exception:
                url = None
            if not url:
                try:
                    match = self.term.match_check_event(event)
                    if match:
                        url = match[0]
                except Exception:
                    url = None
            if url:
                self.open_url(url)
                return True
        return False

    def on_term_scroll(self, widget, event):
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            return self.app.scroll_from_event(event)
        return False

    def on_drag_get(self, widget, ctx, selection, info, time):
        selection.set_text(str(self.slot), -1)

    def on_drop(self, widget, ctx, x, y, selection, info, time):
        try:
            src = int(selection.get_text() or -1)
        except (TypeError, ValueError):
            return
        self.app.swap_slots(src, self.slot)


class CliGrid:
    def __init__(self, self_test=False):
        global THEME, CSS
        self.self_test = self_test
        self.config = load_config()
        self.quitting = False
        self.hidden = False
        self.zoom = False
        self.font_size = int(self.config["font_size"])
        self._font_caps = {}
        self.quiet_until = GLib.get_monotonic_time() + 5 * 1e6  # panes redraw as they attach
        self.panes = []
        self.order = []
        self.active = None
        self.keymap = self.build_keymap()
        self.prefix_armed = False
        self._prefix_source = 0
        # Grid shape and stacked cells come from the active workspace.
        self.layout_shape = self.config.get("layout") or "auto"
        self.search_dialog = None
        self.palette_entries = []
        self.palette_recents = []
        self.palette_seq = 0
        self.waiting_count = 0
        self.event_log = control.EventLog(500)
        self.subscribers = []  # connections holding an `events` stream
        self.waiters = []  # connections holding a `wait`

        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property(
                "gtk-application-prefer-dark-theme", luminance(THEME["background"]) < 0.4)

        GLib.set_prgname(APP)
        GLib.set_application_name(APP_TITLE)
        self.win = Gtk.Window(title=APP_TITLE)
        self.win.get_style_context().add_class("window-cligrid")
        self.win.set_role(APP)
        self.win.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        if os.path.exists(ICON_PATH):
            try:
                self.win.set_default_icon_from_file(ICON_PATH)
                self.win.set_icon_from_file(ICON_PATH)
            except GLib.Error:
                pass
        self.win.connect("destroy", self.on_destroy)
        self.win.connect("key-press-event", self.on_key)
        self.win.connect("window-state-event", self.on_state)
        self.win.connect("delete-event", lambda *a: self.quit())

        # The theme setting decides the colours of the whole window, so resolve
        # it before the stylesheet is built.
        THEME = theme_for(self.config.get("theme", DEFAULT_CONFIG["theme"]), parse_kitty_conf())
        CSS = build_css(THEME)
        set_active_theme(self.config.get("theme", DEFAULT_CONFIG["theme"]))

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
        )
        self.theme_provider = provider

        # One bar: the header bar is the title bar, so there is no second strip.
        self.toolbar = self.build_headerbar()
        self.win.set_titlebar(self.toolbar)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.overlay = Gtk.Overlay()
        self.overlay.add(root)
        self.win.add(self.overlay)

        self.grid = Gtk.Grid()
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_spacing(GRID_GAP)
        self.grid.set_column_spacing(GRID_GAP)
        self.grid.set_border_width(GRID_BORDER)
        self.grid.connect("size-allocate", self.on_grid_allocate)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.get_style_context().add_class("grid-scroll")
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        try:
            self.scroller.set_overlay_scrolling(False)
        except AttributeError:
            pass
        self.scroller.set_kinetic_scrolling(True)
        self.scroller.add(self.grid)
        self.scroller.connect("size-allocate", self.on_scroller_allocate)
        self.win.connect("scroll-event", self.on_window_scroll)
        root.pack_start(self.scroller, True, True, 0)

        count = clamp_pane_count(self.config.get("pane_count"))
        self.panes = [Pane(self, i) for i in range(count)]
        self.order = list(self.panes)
        self.active = self.panes[0]
        self.rebuild_pills()
        self.restore_state()
        self.palette = self.build_palette()
        self.overlay.add_overlay(self.palette)
        self.toasts = []
        self.toast_layer = self.build_toast_layer()
        self.overlay.add_overlay(self.toast_layer)
        try:
            # Toasts are read, not clicked: leave the grid usable underneath.
            self.overlay.set_overlay_pass_through(self.toast_layer, True)
        except AttributeError:
            pass
        self.render()
        self.prepare_size()

        self.socket_service = self.start_socket()
        self.win.connect("map-event", self.on_map)
        self.win.show_all()
        self.win.present()
        display = Gdk.Display.get_default()
        if display is not None:
            try:
                display.connect("monitor-added", lambda *a: GLib.timeout_add(400, self.post_show))
            except (TypeError, AttributeError):
                pass
        GLib.timeout_add(300, self.post_show)
        GLib.idle_add(self.focus_active)
        GLib.timeout_add(POLL_MS, self.poll_panes)
        if self.self_test:
            GLib.timeout_add(3200, self.run_self_test)

    def prepare_size(self):
        """COSMIC/Wayland ignores gtk_window_resize() entirely, and lets the
        children's natural size win after the first map. Two things do work:
        a grid size request fixed at map time, and compositor maximize (which
        already subtracts the panel and dock bands). Prefer maximize when
        configured, since Gdk reports the full screen as the workarea and
        cannot see COSMIC's exclusive zones."""
        wa, _scale = self.monitor_workarea()
        self.win.set_default_size(wa.width, max(200, wa.height - 8))
        if str(self.config.get("fit", "maximized")) == "maximized":
            self.win.maximize()
            return
        self.grid.set_size_request(*self.target_grid_px(wa))

    def toolbar_height(self):
        alloc = self.toolbar.get_allocation()
        return alloc.height if alloc.height > 1 else TOOLBAR_H

    def target_grid_px(self, wa=None):
        """Grid size that makes the whole window (toolbar + decorations) fill
        the workarea without overflowing it. Undershoot rather than overshoot:
        Wayland will not let us correct it afterwards."""
        if wa is None:
            wa, _s = self.monitor_workarea()
        fit = str(self.config.get("fit", "workarea"))
        if fit != "workarea" and "x" in fit:
            try:
                w, h = (int(v) for v in fit.lower().split("x", 1))
                return max(120, w - 12), max(80, h - self.toolbar_height() - 14)
            except ValueError:
                pass
        return max(400, wa.width - 8), max(240, wa.height - self.toolbar_height() - 14)

    def on_map(self, widget, event):
        GLib.timeout_add(150, self.post_show)
        return False

    def post_show(self):
        self.fit_window()
        self.schedule_settle(10)
        self.autosize_font()
        self.update_status()
        return False

    def toggle_maximized(self):
        if self.win.get_window() and self.win.get_window().get_state() & Gdk.WindowState.MAXIMIZED:
            self.win.unmaximize()
        else:
            self.win.maximize()

    def build_headerbar(self):
        bar = Gtk.HeaderBar()
        bar.set_show_close_button(True)
        bar.set_has_subtitle(False)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if theme_has_icon("view-grid-symbolic"):
            mark = Gtk.Image.new_from_icon_name("view-grid-symbolic", Gtk.IconSize.MENU)
        else:
            mark = Gtk.Label(label="▦")
        mark.set_valign(Gtk.Align.CENTER)
        brand.pack_start(styled(mark, "brand-mark"), False, False, 0)
        title = styled(Gtk.Label(label=APP_TITLE), "brand")
        title.set_ellipsize(Pango.EllipsizeMode.END)  # lets a narrow window shrink the bar
        brand.pack_start(title, True, True, 0)
        bar.pack_start(brand)

        self.zoom_btn = Gtk.ToggleButton()
        self.zoom_btn.set_focus_on_click(False)
        zoom_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if theme_has_icon("view-fullscreen-symbolic"):
            zoom_content.pack_start(Gtk.Image.new_from_icon_name(
                "view-fullscreen-symbolic", Gtk.IconSize.MENU), False, False, 0)
        zoom_content.pack_start(Gtk.Label(label="Zoom"), False, False, 0)
        self.zoom_btn.add(zoom_content)
        self.zoom_btn.set_tooltip_text("Fill the window with the focused pane  (Ctrl+Shift+Z)")
        self._zoom_handler = self.zoom_btn.connect(
            "toggled", lambda button: self.toggle_zoom(button.get_active()))
        bar.pack_start(self.zoom_btn)

        # Where you are, and one click to be somewhere else.
        self.ws_btn = styled(Gtk.Button(label="Workspace: %s ▾" % self.workspace_name()), "ws-chip")
        self.ws_btn.set_focus_on_click(False)
        set_accessible(self.ws_btn, "Workspace: switch")
        self.ws_btn.connect("clicked", lambda _button: self.show_workspace_menu())
        bar.pack_start(self.ws_btn)

        # Pane switcher: one number per pane, plus a button to add one.
        self.pill_box = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2), "switcher")
        self.pane_pills = []
        self.pill_scroll = Gtk.ScrolledWindow()
        self.pill_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.pill_scroll.set_min_content_width(80)
        self.pill_scroll.set_max_content_width(320)
        self.pill_scroll.set_propagate_natural_width(True)
        self.pill_scroll.add(self.pill_box)
        self.pill_scroll.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.pill_scroll.connect("scroll-event", self.on_selector_scroll)
        selector = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        selector.pack_start(icon_button("go-previous-symbolic", "‹", "Scroll panes left",
                                       lambda: self.scroll_selector(-120)), False, False, 0)
        selector.pack_start(self.pill_scroll, True, True, 0)
        selector.pack_start(icon_button("go-next-symbolic", "›", "Scroll panes right",
                                       lambda: self.scroll_selector(120)), False, False, 0)
        bar.set_custom_title(selector)

        self.menu_btn = icon_button(
            "open-menu-symbolic", "☰", "Menu", self.show_app_menu, extra_class="image-button")
        bar.pack_end(self.menu_btn)
        self.command_btn = icon_button(
            "system-search-symbolic", "⌕",
            "Search commands  (Ctrl+Shift+P)", self.show_palette,
            extra_class="command-trigger")
        bar.pack_end(self.command_btn)
        self.status = styled(Gtk.Label(label=""), "status")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_end(self.status)
        self.font_btn = Gtk.Button()
        self.font_btn.set_focus_on_click(False)
        self.font_btn.set_tooltip_text("Change font family · size adapts automatically")
        set_accessible(self.font_btn, "Change font family · size adapts automatically")
        self.font_btn.connect("clicked", lambda _button: self.show_font_dialog())
        bar.pack_end(self.font_btn)

        # A pane that blocks on a question shows up here, and one click goes to it.
        self.attention_btn = Gtk.Button(label="")
        self.attention_btn.set_focus_on_click(False)
        self.attention_btn.get_style_context().add_class("attention-chip")
        set_accessible(self.attention_btn, "Panes waiting for you")
        self.attention_btn.connect("clicked", lambda _button: self.jump_to_blocked())
        self.attention_btn.set_no_show_all(True)
        self.attention_btn.hide()
        bar.pack_end(self.attention_btn)

        # Shown while the two-stroke prefix waits for its second key.
        self.prefix_chip = styled(Gtk.Label(label="PREFIX"), "prefix-chip")
        self.prefix_chip.set_no_show_all(True)
        self.prefix_chip.hide()
        bar.pack_end(self.prefix_chip)

        self.scroll_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.scroll_btns.pack_start(icon_button(
            "go-up-symbolic", "▲",
            "Scroll to panes above  (Ctrl+Shift+Page Up)",
            lambda: self.scroll_windows(-1), extra_class="image-button",
        ), False, False, 0)
        self.scroll_btns.pack_start(icon_button(
            "go-down-symbolic", "▼",
            "Scroll to panes below  (Ctrl+Shift+Page Down)",
            lambda: self.scroll_windows(1), extra_class="image-button",
        ), False, False, 0)
        self.scroll_btns.set_no_show_all(True)
        bar.pack_end(self.scroll_btns)
        return bar

    def layout_groups(self):
        """Cells for layout.cells: stacked positions together, every other pane
        alone. The module wants every position covered exactly once, and a pane
        count change can leave a stale position behind, so rebuild it here."""
        count = len(self.order)
        seen = set()
        groups = []
        for group in self.config.get("stack") or []:
            members = []
            for item in group or []:
                try:
                    pos = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= pos < count and pos not in seen:
                    seen.add(pos)
                    members.append(pos)
            if members:
                groups.append(members)
        for pos in range(count):
            if pos not in seen:
                groups.append([pos])
        return groups or None

    def cell_pane(self, cell):
        """Which pane a cell shows: the focused one when it belongs in that cell,
        otherwise the cell's first pane. Stacked panes switch by focusing them."""
        members = [self.order[index] for index in cell["panes"] if index < len(self.order)]
        if not members:
            return None
        return self.active if self.active in members else members[0]

    def render(self):
        """Attach the panes to the grid in the configured shape."""
        for child in list(self.grid.get_children()):
            self.grid.remove(child)
        if self.zoom:
            self.grid.attach(self.active.box, 0, 0, layout.SUBCOLS, 1)
        else:
            cells = layout.cells(len(self.order), self.layout_shape, self.layout_groups())
            for cell in cells:
                pane = self.cell_pane(cell)
                if pane is not None:
                    self.grid.attach(pane.box, cell["col"], cell["row"],
                                     cell["span"], cell.get("rowspan", 1))
        self.grid.show_all()
        for pane in self.panes:
            pane.set_focused(pane is self.active)
            pane.set_tint(self.position_of(pane))
            pane.update_title()
        with self.zoom_btn.handler_block(self._zoom_handler):
            self.zoom_btn.set_active(self.zoom)
        self.hush_activity()
        GLib.idle_add(self.after_render)

    def after_render(self):
        self.apply_pane_geometry()
        self.focus_active()
        self.scroll_pane_into_view(self.active)
        self.autosize_font()
        self.update_status()
        return False

    def focus_active(self):
        if self.active.box.get_parent() is not None:
            self.active.term.grab_focus()
        return False

    def position_of(self, pane):
        return self.order.index(pane) if pane in self.order else pane.slot

    def sync_window_title(self):
        self.win.set_title(APP_TITLE)

    def poll_panes(self):
        """One timer for everything that changes on its own: working directory,
        git branch, and what each pane is doing. A second is fast enough for a
        badge and slow enough that twenty panes stay cheap."""
        if self.quitting:
            return False
        for pane in self.panes:
            pane.refresh_cwd()
            if not pane.dead:
                pane.refresh_state()
                self.check_notify_rules(pane)
        self.poll_waiters()
        self.refresh_pills()
        self.refresh_attention()
        return True

    def refresh_attention(self):
        """Header chip for the panes that are blocked waiting for an answer."""
        waiting = [p for p in self.order if state.needs_input(p.state)]
        self.waiting_count = len(waiting)
        if waiting:
            names = ", ".join(
                "%d %s" % (self.position_of(p) + 1, p.name) for p in waiting[:6])
            self.attention_btn.set_label("⏳ %d" % len(waiting))
            self.attention_btn.set_tooltip_text(
                "Waiting for you: %s\nClick to go there (Ctrl+Shift+A)" % names)
            reveal(self.attention_btn)
        else:
            self.attention_btn.hide()

    def on_pane_state(self, pane, fresh):
        """A pane changed what it is doing: the header and the pills follow, and a
        pane that starts waiting for an answer tells the desktop."""
        self.refresh_attention()
        self.refresh_pills()
        if state.needs_input(fresh) and pane is not self.active:
            self.notify_waiting(pane)

    def notifications_allowed(self, pane):
        """Desktop notifications respect the setting, quiet hours, and a pane's
        own mute flag."""
        if not self.config.get("notify_desktop", True):
            return False
        entry = self.config.get("panes", [{}])[pane.slot] if pane.slot < len(
            self.config.get("panes", [])) else {}
        if entry.get("notify") is False:
            return False
        if self.config.get("quiet_hours") and in_quiet_hours(self.config["quiet_hours"]):
            return False
        return True

    def notify_waiting(self, pane):
        """A pane is blocked on an answer: say so on the desktop."""
        if not self.notifications_allowed(pane):
            return
        summary = "Pane %d (%s) waits for you" % (self.position_of(pane) + 1, pane.name)
        line = state.last_prompt_line(pane.poll_text or "")
        self.notify_desktop(pane, summary, line or state_text(pane.state))

    def check_notify_rules(self, pane):
        """A pane's own notify_on patterns: a match earns one notification, at
        most once per interval."""
        entry = self.config.get("panes", [{}])[pane.slot] if pane.slot < len(
            self.config.get("panes", [])) else {}
        patterns = notification_patterns(entry)
        if not patterns or not self.notifications_allowed(pane):
            return
        text = pane.poll_text or ""
        if not text or text == getattr(pane, "_rule_text", None):
            return
        for pattern in patterns:
            if pattern.search(text):
                pane._rule_text = text
                summary = "Pane %d (%s) matched %s" % (
                    self.position_of(pane) + 1, pane.name, pattern.pattern)
                self.notify_desktop(pane, summary, (state.last_prompt_line(text)
                                                    or text.strip().splitlines()[-1] if text.strip() else ""))
                return

    def notify_desktop(self, pane, summary, body):
        """One desktop notification for a pane, rate limited per pane."""
        now = GLib.get_monotonic_time()
        if pane.last_notified and now - pane.last_notified < NOTIFY_INTERVAL_SECONDS * 1e6:
            return
        bus = self.session_bus()
        if bus is None:
            return
        pane.last_notified = now
        params = GLib.Variant("(susssasa{sv}i)", (
            APP_TITLE, pane.notification_id, APP, summary, body or "",
            ["default", "Show pane"], {"desktop-entry": GLib.Variant("s", APP)}, -1))
        bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                 "org.freedesktop.Notifications", "Notify", params, GLib.VariantType("(u)"),
                 Gio.DBusCallFlags.NONE, -1, None, self.on_notified, pane)

    def scroll_selector(self, distance):
        adjustment = self.pill_scroll.get_hadjustment()
        maximum = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(adjustment.get_lower(),
                                 min(maximum, adjustment.get_value() + distance)))

    def on_selector_scroll(self, _widget, event):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, dx, dy = event.get_scroll_deltas()
            if not valid:
                return False
            distance = (dx if abs(dx) > abs(dy) else dy) * 40
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            distance = 40
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            distance = -40
        else:
            return False
        self.scroll_selector(distance)
        return True

    def rebuild_pills(self):
        for child in list(self.pill_box.get_children()):
            self.pill_box.remove(child)
            child.destroy()
        self.pane_pills = []
        for i in range(len(self.order)):
            btn = Gtk.Button(label=str(i + 1))
            btn.set_focus_on_click(False)
            btn.connect("clicked", lambda _b, n=i + 1: self.focus_slot(n))
            btn.connect("button-press-event", self.on_pill_press, i + 1)
            set_accessible(btn, "Pane %d" % (i + 1))
            self.pill_box.pack_start(btn, False, False, 0)
            self.pane_pills.append(btn)
        add = icon_button("list-add-symbolic", "+", "Add a pane", self.add_pane, extra_class="add")
        add.set_sensitive(len(self.order) < MAX_PANES)
        self.pill_box.pack_start(add, False, False, 0)
        self.pill_box.show_all()
        self.refresh_pills()

    def add_pane(self):
        if len(self.panes) >= MAX_PANES:
            return
        self.set_pane_count(len(self.panes) + 1)
        self.focus_slot(len(self.order))

    def on_pill_press(self, btn, event, n):
        if event.button != 3 or n > len(self.order):
            return False
        menu = Gtk.Menu()
        menu.append(menu_item(
            "Remove pane %d" % n,
            lambda: self.remove_window(self.order[n - 1]),
            sensitive=len(self.panes) > MIN_PANES,
        ))
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def refresh_pills(self):
        pills = getattr(self, "pane_pills", None)
        if not pills:
            return
        for i, btn in enumerate(pills[:len(self.order)]):
            pane = self.order[i]
            ctx = btn.get_style_context()
            tint = "tint-%d" % (i % len(PANE_COLOR_SLOTS))
            if not ctx.has_class(tint):
                for n in range(len(PANE_COLOR_SLOTS)):
                    ctx.remove_class("tint-%d" % n)
                ctx.add_class(tint)
            for name, on in (("active", pane is self.active), ("exited", pane.exited),
                             ("alert", pane.mark == "alert"), ("activity", pane.mark == "activity"),
                             ("alert-on", pane.mark == "alert" and getattr(self, "_pulse_on", False))):
                if on:
                    ctx.add_class(name)
                else:
                    ctx.remove_class(name)
            tip = "%s · %s" % (pane.name, short_path(pane.cwd) or "pane %d" % (i + 1))
            if pane.mark:
                tip += " · " + ("rang its bell" if pane.mark == "alert" else "new output")
            if i < 9:
                tip += "  (Ctrl+Shift+%d)" % (i + 1)
            elif i == 9:
                tip += "  (Ctrl+Shift+0)"
            if btn.get_tooltip_text() != tip:
                btn.set_tooltip_text(tip)

    def set_active(self, pane):
        if pane not in self.panes:
            return  # a removed pane can still emit focus events while it is torn down
        pane.set_mark(None)
        if pane is self.active:
            self.sync_window_title()
            return
        if self.active is not None and not self.active.dead:
            self.active.seen_text = self.active.visible_text()
        self.active = pane
        for item in self.panes:
            item.set_focused(item is pane)
        self.sync_window_title()
        self.add_event("focus", pane=pane.name)
        self.mark_state_dirty()
        if self.zoom:
            self.render()
        else:
            self.focus_active()
            self.scroll_pane_into_view(pane)
            self.update_status()

    def hush_activity(self):
        self.quiet_until = max(self.quiet_until, GLib.get_monotonic_time() + QUIET_SECONDS * 1e6)

    def pane_bell(self, pane):
        if pane.dead:
            return
        self.add_event("bell", pane=pane.name)
        window_watched = self.win.is_active() and not self.hidden
        mark, notify = decide_bell(pane is self.active, window_watched,
                                   self.config.get("bell_alerts", True),
                                   self.config.get("notify_desktop", True))
        if mark:
            pane.set_mark("alert")
        if notify:
            self.notify_bell(pane)

    def session_bus(self):
        if getattr(self, "_bus", None) is None:
            try:
                self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self._bus.signal_subscribe(
                    "org.freedesktop.Notifications", "org.freedesktop.Notifications",
                    "ActionInvoked", "/org/freedesktop/Notifications", None,
                    Gio.DBusSignalFlags.NONE, self.on_notification_action)
            except GLib.Error:
                self._bus = False
        return self._bus or None

    def notify_bell(self, pane):
        now = GLib.get_monotonic_time()
        if pane.last_notified and now - pane.last_notified < NOTIFY_INTERVAL_SECONDS * 1e6:
            return
        summary, body = notification_text(self.position_of(pane) + 1, pane.name,
                                          pane.cmd, pane.cwd)
        bus = self.session_bus()
        if bus is None:
            # macOS has no session D-Bus; there the notification goes out
            # through osascript instead. Everywhere else this is unchanged.
            if osascript_notify(summary, body):
                pane.last_notified = now
            return
        pane.last_notified = now
        params = GLib.Variant("(susssasa{sv}i)", (
            APP_TITLE, pane.notification_id, APP, summary, body,
            ["default", "Show pane"], {"desktop-entry": GLib.Variant("s", APP)}, -1))
        bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                 "org.freedesktop.Notifications", "Notify", params, GLib.VariantType("(u)"),
                 Gio.DBusCallFlags.NONE, -1, None, self.on_notified, pane)

    def on_notified(self, bus, result, pane):
        try:
            pane.notification_id = bus.call_finish(result).unpack()[0]
        except GLib.Error:
            pass

    def on_notification_action(self, bus, sender, path, interface, signal, params, *user_data):
        notification_id = params.unpack()[0]
        for pane in self.panes:
            if pane.notification_id and pane.notification_id == notification_id:
                self.show_window()
                self.set_active(pane)
                break

    def update_pulse(self):
        alerted = any(p.mark == "alert" for p in self.panes)
        if alerted and not getattr(self, "_pulse_source", 0):
            self._pulse_on = False
            self._pulse_source = GLib.timeout_add(PULSE_MS, self.pulse_alerts)

    def pulse_alerts(self):
        """Blink alerted panes and their switcher buttons."""
        alerted = any(p.mark == "alert" for p in self.panes)
        self._pulse_on = alerted and not getattr(self, "_pulse_on", False)
        for i, pane in enumerate(self.order):
            widgets = [pane.box] + self.pane_pills[i:i + 1]
            for widget in widgets:
                ctx = widget.get_style_context()
                if pane.mark == "alert" and self._pulse_on:
                    ctx.add_class("alert-on")
                else:
                    ctx.remove_class("alert-on")
        if not alerted:
            self._pulse_source = 0
        return alerted

    def jump_to_attention(self):
        """Focus the next pane that rang its bell, else the next with new output."""
        start = self.order.index(self.active) if self.active in self.order else -1
        ring = self.order[start + 1:] + self.order[:start + 1]
        for kind in ("alert", "activity"):
            for pane in ring:
                if pane.mark == kind:
                    self.set_active(pane)
                    return True
        return False

    def zoom_pane(self, pane):
        self.set_active(pane)
        if self.zoom and pane is self.active:
            self.toggle_zoom(False)
        else:
            self.toggle_zoom(True)

    def swap_slots(self, src_slot, dst_slot):
        count = len(self.panes)
        if src_slot == dst_slot or not (0 <= src_slot < count and 0 <= dst_slot < count):
            return
        src, dst = self.panes[src_slot], self.panes[dst_slot]
        i, j = self.order.index(src), self.order.index(dst)
        self.order[i], self.order[j] = dst, src
        self.render()

    def move_focus(self, direction):
        count = len(self.order)
        idx = self.order.index(self.active)
        if self.zoom:
            step = 1 if direction in ("right", "down") else -1
            self.set_active(self.order[(idx + step) % count])
            return
        target = layout.neighbor(count, idx, direction, self.layout_shape,
                                 self.layout_groups())
        if target != idx:
            self.set_active(self.order[target])

    def focus_slot(self, n):
        if 1 <= n <= len(self.order):
            self.set_active(self.order[n - 1])

    def pane_range_text(self):
        return "1-%d" % len(self.order)

    def apply_pane_geometry(self):
        if not getattr(self, "scroller", None):
            return
        self.grid.set_size_request(-1, -1)
        if self.zoom:
            self._cell_req = None
            self._cell_h = None
            for pane in self.panes:
                pane.box.set_size_request(-1, -1)
            self.update_scroll_chrome(False)
            return
        width = self.scroller.get_allocated_width()
        height = self.scroller.get_allocated_height()
        if width < 80 or height < 80:
            return
        _cols, rows = layout.shape_for(len(self.order), self.layout_shape)
        visible_rows = layout.short_rows(len(self.order), self.layout_shape)
        overflow = rows > visible_rows
        self.update_scroll_chrome(overflow)
        if not overflow:
            if getattr(self, "_cell_req", None) is not None:
                self._cell_req = None
                self._cell_h = None
                for pane in self.panes:
                    pane.box.set_size_request(-1, -1)
            return
        vis_rows = visible_rows
        cell_h = max(90, (height - GRID_BORDER * 2 - GRID_GAP * (vis_rows - 1)) // vis_rows)
        request = (cell_h, height)
        if getattr(self, "_cell_req", None) == request:
            return
        self._cell_req = request
        self._cell_h = cell_h
        for pane in self.panes:
            pane.box.set_size_request(-1, cell_h)

    def update_scroll_chrome(self, overflow):
        if getattr(self, "scroll_btns", None) is not None:
            if not overflow:
                self.scroll_btns.hide()
            elif not self.scroll_btns.get_visible():
                reveal(self.scroll_btns)
        if overflow:
            self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            try:
                self.scroller.set_overlay_scrolling(True)
            except AttributeError:
                pass
        else:
            self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)

    def on_scroller_allocate(self, widget, allocation):
        size = (allocation.width, allocation.height)
        if size != getattr(self, "_scroller_size", None):
            self._scroller_size = size
            self.hush_activity()
        self.apply_pane_geometry()
        self.schedule_settle(4)

    def scroll_windows(self, direction):
        if self.zoom or not getattr(self, "scroller", None):
            return
        adj = self.scroller.get_vadjustment()
        step = adj.get_page_increment() or adj.get_page_size() or 120
        if getattr(self, "_cell_h", None):
            step = self._cell_h + GRID_GAP
        value = adj.get_value() + direction * step
        upper = max(adj.get_lower(), adj.get_upper() - adj.get_page_size())
        adj.set_value(max(adj.get_lower(), min(upper, value)))

    def scroll_from_event(self, event):
        delta = 0
        if getattr(event, "direction", None) == Gdk.ScrollDirection.SMOOTH:
            delta = event.delta_y
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = 1
        elif event.direction == Gdk.ScrollDirection.UP:
            delta = -1
        if not delta:
            return False
        self.scroll_windows(1 if delta > 0 else -1)
        return True

    def on_window_scroll(self, widget, event):
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            return self.scroll_from_event(event)
        return False

    def scroll_pane_into_view(self, pane):
        if self.zoom or pane is None or getattr(self, "scroller", None) is None:
            return
        if pane.box.get_parent() is None:
            return
        alloc = pane.box.get_allocation()
        adj = self.scroller.get_vadjustment()
        top = alloc.y
        bottom = alloc.y + alloc.height
        view_top = adj.get_value()
        view_bottom = view_top + adj.get_page_size()
        if top < view_top:
            adj.set_value(top)
        elif bottom > view_bottom:
            adj.set_value(max(adj.get_lower(), bottom - adj.get_page_size()))

    def toggle_zoom(self, on=None):
        new = (not self.zoom) if on is None else bool(on)
        if new == self.zoom:
            return
        self.zoom = new
        self.mark_state_dirty()
        self.add_event("zoom", on=bool(new))
        self.render()

    def monitor_workarea(self):
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() if hasattr(display, "get_primary_monitor") else None
        if mon is None:
            mon = display.get_monitor(0)
        return mon.get_workarea(), mon.get_scale_factor()

    def fit_window(self):
        wa, _scale = self.monitor_workarea()
        fit = str(self.config.get("fit", "maximized"))
        if fit == "maximized":
            if not (self.win.get_window() and
                    self.win.get_window().get_state() & Gdk.WindowState.MAXIMIZED):
                self.win.maximize()
        else:
            # Effective on X11 and at map time on Wayland; a no-op on COSMIC
            # after map, where the size fixed at launch stands.
            self.win.resize(wa.width, max(200, wa.height - 8))
        self.update_status()

    def on_grid_allocate(self, grid, allocation):
        self.schedule_settle(6)

    def schedule_settle(self, passes=8):
        """COSMIC animates maximize/unmaximize, so the allocation keeps moving
        for a few hundred ms. Re-evaluate the font and status on a short timer
        until the allocation stops changing, otherwise a mid-animation size
        freezes the font."""
        self._passes = max(getattr(self, "_passes", 0) or 0, passes)
        if not getattr(self, "_settling", False):
            self._settling = True
            self._prev_alloc = None
            GLib.timeout_add(250, self._settle_tick)

    def _settle_tick(self):
        alloc = self.grid.get_allocation()
        current = (alloc.width, alloc.height)
        self.autosize_font()
        settled = current == self._prev_alloc
        corrected = False
        # The Pango prediction can miss VTE's real cell size by a pixel. Once the
        # allocation stops moving, step down if the smallest pane is short, and
        # cap that size for this allocation so autosize does not climb back.
        if (settled and not self.zoom and self.font_size > 7):
            cols = min(p.term.get_column_count() for p in self.order)
            visible_rows = layout.short_rows(len(self.order), self.layout_shape)
            shape_cols = layout.shape_for(len(self.order), self.layout_shape)[0]
            rows = min(p.term.get_row_count()
                       for p in self.order[:max(1, shape_cols * visible_rows)])
            if cols < int(self.config["min_cols"]) or rows < int(self.config["min_rows"]):
                self._font_caps[self.font_key()] = self.font_size - 1
                self.apply_font_all(self.font_size - 1)
                corrected = True
        self.update_status()
        self._passes -= 1
        if (settled and not corrected) or self._passes <= 0:
            self._settling = False
            self._prev_alloc = None
            return False
        self._prev_alloc = current
        return True

    def font_key(self):
        alloc = self.scroller.get_allocation()
        return (alloc.width, alloc.height, len(self.order), self.layout_shape, self.zoom)

    def autosize_font(self):
        size = self.best_font_size()
        if size and size != self.font_size:
            self.apply_font_all(size)

    def best_font_size(self):
        """Largest font step that still gives the narrowest pane min_cols and
        each visible row min_rows, for the layout actually on screen. Character
        cells are measured per size with Pango rather than scaled."""
        alloc = self.scroller.get_allocation()
        if alloc.width < 80 or alloc.height < 80:
            return None
        cols, rows = (1, 1) if self.zoom else layout.shape_for(len(self.order), self.layout_shape)
        rows = min(rows, GRID_VISIBLE_ROWS)
        pad = chrome_palette(THEME)["pad"]
        header_h = max(p.header.get_allocated_height() for p in self.order)
        if header_h <= 1:
            header_h = HEADER_H
        cell_w = (alloc.width - 2 * GRID_BORDER - (cols - 1) * GRID_GAP) / float(cols)
        cell_h = (alloc.height - 2 * GRID_BORDER - (rows - 1) * GRID_GAP) / float(rows)
        # Pane border (1px each side), the inset around the terminal, VTE padding.
        text_w = cell_w - 2 * (1 + PANE_INSET + pad)
        text_h = cell_h - 2 - header_h - PANE_INSET - 2 * pad
        if text_w < 40 or text_h < 40:
            return None
        base_size, min_size = 22, 7  # Automatic readability bounds, independent of legacy preferences.
        cap = self._font_caps.get(self.font_key())
        top = min(base_size, cap) if cap else base_size
        if not hasattr(self, "_trace"):
            self._trace = []
        for size in range(top, min_size - 1, -1):
            cw, ch = self.char_metrics_for(size)
            if cw <= 0 or ch <= 0:
                continue
            got_cols = int(text_w / cw)
            got_rows = int(text_h / ch)
            if (got_cols >= int(self.config["min_cols"]) and
                    got_rows >= int(self.config["min_rows"])):
                self.predicted = (got_cols, got_rows, size)
                self._trace.append((alloc.width, alloc.height, size,
                                    round(cw, 2), round(ch, 2),
                                    "%dx%d" % (got_cols, got_rows)))
                del self._trace[:-14]
                return size
        self.predicted = (0, 0, min_size)
        self._trace.append((alloc.width, alloc.height, min_size,
                            None, None, "no-fit"))
        del self._trace[:-14]
        return min_size

    def apply_font_all(self, size):
        self.font_size = size
        self.hush_activity()
        for pane in self.panes:
            pane.apply_font(size)

    def char_metrics_for(self, size):
        """Pixel size of one character cell at a given font size.

        Measured per size, not scaled: VTE/Pango cell metrics are not linear in
        point size (hinting and rounding), so scaling from the current size
        predicts the wrong grid and walks the font down to the floor."""
        cache = getattr(self, "_metrics_cache", None)
        if cache is None:
            cache = self._metrics_cache = {}
        if size in cache:
            return cache[size]
        result = None
        try:
            ctx = PangoCairo.font_map_get_default().create_context()
            layout = Pango.Layout(ctx)
            layout.set_font_description(
                Pango.FontDescription("%s %d" % (self.config["font"], int(size))))
            layout.set_text("M" * 16)
            width, height = layout.get_pixel_size()
            _wa, scale = self.monitor_workarea()
            if width > 0 and height > 0:
                result = (width / 16.0 * scale, float(height) * scale)
        except Exception:
            result = None
        if result is None:
            term = self.active.term
            cw, ch = term.get_char_width(), term.get_char_height()
            result = (float(cw or 0), float(ch or 0))
        cache[size] = result
        return result

    def base_char_metrics(self):
        return self.char_metrics_for(self.font_size)

    def update_status(self):
        if self.active is None:
            return
        term = self.active.term
        cols, rows = term.get_column_count(), term.get_row_count()
        facts = ["%d×%d" % (cols, rows)]
        self.font_btn.set_label("%s · Auto %dpt ▾" % (self.config["font"], self.font_size))
        if self.waiting_count:
            facts.append("%d waiting" % self.waiting_count)
        if self.prefix_armed:
            facts.append("prefix")
        if active_theme_name() != "kitty":
            facts.append(active_theme_name())
        if self.layout_shape != "auto":
            facts.append(self.layout_shape)
        self.status.set_text(" · ".join(facts))
        self.status.set_tooltip_text(
            "Focused pane %s: %d columns × %d rows at %dpt%s"
            % (self.active.name, cols, rows, self.font_size,
               " · workspace %s" % self.workspace_name()))
        self.sync_window_title()
        self.refresh_pills()
        self.refresh_workspace_chip()

    def toggle_visibility(self):
        state = self.win.get_window().get_state() if self.win.get_window() else 0
        if self.hidden or (state & Gdk.WindowState.ICONIFIED):
            self.show_window()
        else:
            self.hide_window()

    def hide_window(self):
        self.hidden = True
        self.win.iconify()

    def show_window(self):
        self.hidden = False
        self.win.deiconify()
        self.win.present()
        GLib.idle_add(self.focus_active)

    def on_state(self, widget, event):
        if event.changed_mask & Gdk.WindowState.ICONIFIED:
            self.hidden = bool(event.new_window_state & Gdk.WindowState.ICONIFIED)
        return False

    def on_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if self.prefix_armed:
            return self.handle_prefixed_key(key)
        if ctrl and shift and key in self.prefix_keys():
            self.arm_prefix()
            return True
        has_sel = bool(self.active and getattr(self.active, "_selection", ""))
        if not has_sel and self.active is not None and self.active.term is not None:
            try:
                has_sel = bool(self.active.term.get_has_selection())
            except Exception:
                has_sel = False
        action = keymap.resolve_shortcut(self.keymap, key, ctrl, shift, has_sel)
        if not action:
            return False
        if action == "copy":
            if self.active and self.active.copy_text():
                return True
            return False
        return self.run_action(action)

    def build_keymap(self):
        """key name -> action id: the defaults with the user's keymap applied.
        An override with an empty value removes the binding."""
        return keymap.merge(DEFAULT_KEYMAP, self.config.get("keymap"))

    def prefix_keys(self):
        """Key names that arm the two-stroke prefix, from the prefix setting."""
        name = str(self.config.get("prefix") or "space").strip().lower()
        return PREFIX_KEY_NAMES.get(name, PREFIX_KEY_NAMES["space"])

    def arm_prefix(self):
        """Two-stroke mode: one key runs an action without Ctrl+Shift."""
        self.prefix_armed = True
        reveal(self.prefix_chip)
        self.update_status()
        if getattr(self, "_prefix_source", 0):
            GLib.source_remove(self._prefix_source)
        self._prefix_source = GLib.timeout_add(2500, self.disarm_prefix)

    def disarm_prefix(self):
        self._prefix_source = 0
        if self.prefix_armed:
            self.prefix_armed = False
            self.prefix_chip.hide()
            self.update_status()
        return False

    def handle_prefixed_key(self, key):
        """A key pressed after the prefix: Escape cancels, anything else is looked up."""
        self.disarm_prefix()
        if key == "Escape":
            return True
        action = keymap.lookup(self.keymap, key)
        if action:
            return self.run_action(action)
        return True

    def action_table(self):
        """Every command the window can run, with the key that runs it. One table
        feeds the keymap, the command palette, and the shortcuts dialog, so they
        cannot drift apart."""
        return [
            ("palette", "Command palette", "Ctrl+Shift+P", self.show_palette),
            ("zoom", "Zoom the focused pane", "Ctrl+Shift+Z", lambda: self.toggle_zoom()),
            ("attention", "Jump to the pane that needs you", "Ctrl+Shift+A", self.jump_to_attention),
            ("search.pane", "Find in the focused pane", "Ctrl+Shift+G", self.find_in_pane),
            ("search.all", "Search every pane", "Ctrl+Shift+S", self.show_search_all),
            ("focus.left", "Focus the pane to the left", "Ctrl+Shift+H", lambda: self.move_focus("left")),
            ("focus.right", "Focus the pane to the right", "Ctrl+Shift+L", lambda: self.move_focus("right")),
            ("focus.up", "Focus the pane above", "Ctrl+Shift+K", lambda: self.move_focus("up")),
            ("focus.down", "Focus the pane below", "Ctrl+Shift+J", lambda: self.move_focus("down")),
            ("focus.next", "Next pane", "", self.focus_next),
            ("focus.prev", "Previous pane", "", self.focus_prev),
            ("focus.blocked", "Jump to the next pane that waits for you", "", self.jump_to_blocked),
            ("scroll.up", "Scroll to the panes above", "Ctrl+Shift+Page Up", lambda: self.scroll_windows(-1)),
            ("scroll.down", "Scroll to the panes below", "Ctrl+Shift+Page Down",
             lambda: self.scroll_windows(1)),
            ("add", "Add a pane", "", self.add_pane),
            ("remove", "Remove the focused pane", "Ctrl+Shift+-", lambda: self.remove_window(self.active)),
            ("rename", "Rename the focused pane", "", lambda: self.rename_pane(self.active)),
            ("restart", "Restart the focused pane", "", lambda: self.restart_pane(self.active)),
            ("reset.pane", "Reset the focused pane", "Ctrl+Shift+R", lambda: self.reset_pane(self.active)),
            ("reset.all", "Reset every pane", "Ctrl+Shift+N", lambda: self.fresh_sessions(confirm=True)),
            ("fill.all", "Run one command in every pane", "Ctrl+Shift+E", self.show_fill_dialog),
            ("copy", "Copy the selection", "Ctrl+Shift+C or Ctrl+C",
             lambda: self.active and self.active.copy_text()),
            ("paste", "Paste into the focused pane", "Ctrl+Shift+V or Ctrl+V",
             lambda: self.active and self.active.paste_text()),
            ("paste.all", "Paste into every pane", "Ctrl+Shift+B", self.paste_to_all),
            ("layout.next", "Next grid layout", "", self.cycle_layout),
            ("stack", "Stack the focused pane with the next one", "", self.stack_with_next),
            ("theme.next", "Next theme", "", self.cycle_theme),
            ("ws.next", "Next workspace", "", lambda: self.switch_workspace_step(1)),
            ("ws.prev", "Previous workspace", "", lambda: self.switch_workspace_step(-1)),
            ("fit", "Fit the window", "Ctrl+Shift+F", self.fit_window),
            ("hide", "Hide the grid", "Ctrl+Shift+W", self.hide_window),
            ("settings", "Settings", "Ctrl+Shift+,", self.show_settings),
            ("shortcuts", "Keyboard shortcuts", "Ctrl+Shift+/", self.show_shortcuts),
            ("doctor", "Check the environment", "", self.show_doctor),
            ("about", "About %s" % APP_TITLE, "", self.show_about),
            ("quit", "Quit; sessions keep running", "Ctrl+Shift+Q", self.quit),
        ]

    def run_action(self, action_id):
        """Run an action by id; True when the key event is consumed."""
        for name, _label, _hint, callback in self.action_table():
            if name == action_id:
                callback()
                return True
        if action_id.startswith("focus.") and action_id[6:].isdigit():
            self.focus_slot(int(action_id[6:]))
            return True
        return False

    def action_titles(self):
        """action id -> (label, hint), for the palette and the shortcuts dialog."""
        return {name: (label, hint) for name, label, hint, _cb in self.action_table()}

    def find_in_pane(self):
        if self.active is not None:
            self.active.show_find()

    def restart_pane(self, pane):
        if pane is not None:
            pane.restart()

    def reset_pane(self, pane):
        if pane is not None:
            pane.close_and_respawn()

    def focus_next(self):
        if self.order:
            self.focus_slot(self.order.index(self.active) % len(self.order) + 1)

    def focus_prev(self):
        if self.order:
            self.focus_slot((self.order.index(self.active) - 1) % len(self.order) + 1)

    def paste_to_all(self):
        clip, _primary = gtk_clipboards()
        text = clipboard_text(clipboard=clip)
        sent = 0
        for pane in self.panes:
            if text:
                if paste_into_terminal(pane.term, text):
                    sent += 1
                continue
            try:
                pane.term.paste_clipboard()
                sent += 1
            except Exception:
                pass
        self.toast("Pasted into %d%s" % (sent, " panes" if sent != 1 else " pane"))

    def jump_to_blocked(self):
        """Focus the next pane waiting for an answer, else the next with a bell,
        else the next with new output."""
        start = self.order.index(self.active) if self.active in self.order else -1
        ring = self.order[start + 1:] + self.order[:start + 1]
        for _kind, match in (("blocked", lambda p: state.needs_input(p.state)),
                            ("bell", lambda p: p.mark == "alert"),
                            ("output", lambda p: p.mark == "activity")):
            for pane in ring:
                if match(pane):
                    self.set_active(pane)
                    return True
        return False

    def apply_theme(self, name, save=True, restyle=True):
        """Switch themes at runtime: the terminal palette, the window stylesheet
        and the saved setting all follow."""
        global THEME, CSS
        THEME = theme_for(name, parse_kitty_conf())
        CSS = build_css(THEME)
        chosen = set_active_theme(name)
        try:
            self.theme_provider.load_from_data(CSS)
        except Exception:
            pass
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property(
                "gtk-application-prefer-dark-theme", luminance(THEME["background"]) < 0.4)
        if restyle:
            for pane in self.panes:
                pane.apply_colors()
                pane.apply_terminal_prefs()
                pane.set_tint(self.position_of(pane))
                apply_tmux_chrome(tmux_target(pane.cmd, pane.name))
        self.config["theme"] = chosen
        if save:
            save_config(self.config)
        self.add_event("theme", name=chosen)
        self.update_status()
        if restyle:
            self.toast("Theme: %s" % chosen, kind="success", detail="cligrid theme list")
        return chosen

    def cycle_theme(self):
        """Step through kitty plus every built in theme."""
        names = art.theme_names()
        current = active_theme_name()
        index = names.index(current) if current in names else 0
        self.apply_theme(names[(index + 1) % len(names)])

    def set_layout(self, name):
        """Set the grid shape and remember it in the workspace."""
        chosen = layout.normalize_shape(name)
        self.layout_shape = chosen
        self.config["layout"] = chosen
        save_config(self.config)
        self.add_event("layout", name=chosen)
        self._cell_req = None
        self.after_count_change()
        self.update_status()
        self.toast("Layout: %s" % chosen, detail="%d panes" % len(self.order))
        return chosen

    def cycle_layout(self):
        """Step through every grid shape."""
        names = layout.shape_names()
        current = self.layout_shape if self.layout_shape in names else "auto"
        self.set_layout(names[(names.index(current) + 1) % len(names)])

    def stack_with_next(self):
        """Put the focused pane and the next one in one cell, as tabs. Focusing
        either one brings it to the front of that cell."""
        if len(self.order) < 2:
            return False
        pos = self.order.index(self.active)
        other = self.order[(pos + 1) % len(self.order)]
        wanted = sorted([self.position_of(self.active), self.position_of(other)])
        groups = []
        for group in self.config.get("stack") or []:
            kept = [item for item in group if item not in wanted]
            if len(kept) > 1:
                groups.append(kept)
        groups.append(wanted)
        self.config["stack"] = groups
        save_config(self.config)
        self._cell_req = None
        self.after_count_change()
        return True

    def unstack_all(self):
        """Every pane gets its own cell again."""
        self.config["stack"] = []
        save_config(self.config)
        self._cell_req = None
        self.after_count_change()

    def workspace_name(self):
        """The active workspace's display name."""
        try:
            return workspace.active_workspace(read_store())["name"]
        except Exception:
            return str(self.config.get("workspace") or "default")

    def switch_workspace(self, name, save=True):
        """Switch workspaces. The live pane list is stored first, then the window
        rebuilds its panes on the new list. tmux sessions in both workspaces keep
        running: only the clients are detached."""
        if save:
            save_config(self.config)
        target = workspace.set_active(read_store(), name)
        active = workspace.active_workspace(target)
        if workspace.slug(active["name"]) != workspace.slug(name):
            return None  # unknown workspace, nothing changed
        set_store(target)
        write_store(_STORE["cfg"])
        self.config = flatten_config(target)
        self.layout_shape = self.config.get("layout") or "auto"
        self.set_pane_count(self.config["pane_count"], save=False)
        for pane in self.panes:
            old = tmux_target(pane.cmd, pane.name)
            if old:
                detach_tmux_client(old)
            pane.pending_fresh = True  # the detach makes the child exit; ignore it
            pane.quick_exits = 0
        for index, pane in enumerate(self.panes):
            entry = self.config["panes"][index]
            pane.slot = index
            pane.name = entry["name"]
            pane.cmd = entry["cmd"]
            pane.branch = ""
            pane.poll_text = None
            pane.update_title()
        self.order = list(self.panes)
        self.active = self.panes[0]
        self.zoom = False
        self.keymap = self.build_keymap()
        self.rebuild_pills()
        self.add_event("workspace", name=active["name"])
        self.toast("Workspace: %s" % active["name"], kind="success",
                   detail="%d panes" % len(self.panes))
        GLib.timeout_add(150, self._finish_workspace_switch)
        return active["name"]

    def _finish_workspace_switch(self):
        for pane in self.panes:
            pane.pending_fresh = False
            pane.spawn()
        self.set_active(self.order[0])
        self.focus_active()
        self.mark_state_dirty()
        self.update_status()
        return False

    def switch_workspace_step(self, step):
        """Next or previous workspace, in stored order."""
        names = workspace.workspace_names(read_store())
        if not names:
            return
        current = self.workspace_name()
        index = names.index(current) if current in names else 0
        self.switch_workspace(names[(index + step) % len(names)])

    def mark_state_dirty(self):
        """Save the arrangement soon, without writing a file on every keystroke."""
        self._state_dirty = True
        if not getattr(self, "_state_source", 0):
            self._state_source = GLib.timeout_add(2000, self._save_state_soon)

    def _save_state_soon(self):
        self._state_source = 0
        if self._state_dirty:
            self._state_dirty = False
            self.save_state()
        return False

    def save_state(self):
        """Remember the arrangement (pane order, active pane, zoom, stacks) so the
        next launch can bring it back."""
        data = {
            "version": VERSION,
            "workspace": self.workspace_name(),
            "order": [pane.slot for pane in self.order],
            "active": self.active.slot if self.active else 0,
            "zoom": bool(self.zoom),
            "layout": self.layout_shape,
            "stack": self.config.get("stack") or [],
            "recents": self.palette_recents,
        }
        try:
            write_json_atomic(os.path.join(CONFIG_DIR, "state.json"), data)
        except OSError:
            pass
        self._state_dirty = False
        return data

    def restore_state(self):
        """Bring back the saved arrangement when it belongs to this workspace."""
        path = os.path.join(CONFIG_DIR, "state.json")
        if not self.config.get("restore_on_start", True) or not os.path.exists(path):
            return False
        try:
            with open(path) as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return False
        if str(data.get("workspace")) != self.workspace_name():
            return False
        try:
            order = [self.panes[int(slot)] for slot in data.get("order", [])]
        except (TypeError, ValueError, IndexError):
            return False
        if len(order) != len(self.panes):
            return False
        self.order = order
        active = as_int(data.get("active"), 0)
        if 0 <= active < len(self.panes):
            self.active = self.panes[active]
        self.zoom = bool(data.get("zoom"))
        if isinstance(data.get("stack"), list):
            self.config["stack"] = data["stack"]
        if isinstance(data.get("layout"), str):
            self.layout_shape = layout.normalize_shape(data["layout"])
        if isinstance(data.get("recents"), list):
            self.palette_recents = [str(item) for item in data["recents"]][:8]
        self.after_count_change()
        return True

    def show_doctor(self):
        """Check the environment and show what to fix."""
        rows = doctor.checks(CONFIG_PATH)
        counts = doctor.summary(rows)
        copy = "%d ok, %d to fix." % (counts["ok"], counts["failed"])
        if counts["failed"] == 0:
            copy = "%d checks passed." % counts["ok"]
        dialog, body = self.new_dialog("Environment check", copy, width=640)
        text = doctor.report_text(rows)
        fixes = [row for row in rows if not row["ok"] and row.get("fix")]
        if fixes:
            text += "\n\nTo fix:\n" + "\n".join(
                "  %s: %s" % (row["name"], row["fix"]) for row in fixes)
        view = styled(Gtk.Label(label=text, xalign=0.0), "result-line")
        view.set_selectable(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(300)
        scroller.add(view)
        body.pack_start(scroller, True, True, 0)
        self.add_actions(dialog, "Close", cancel=None)
        self.run_dialog(dialog)

    def build_toast_layer(self):
        """Floating cards over the grid: the app's own channel for saying what it
        just did, so an action never ends in silence."""
        box = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8),
                     "toast-layer")
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.END)
        box.set_no_show_all(True)
        box.hide()
        return box

    def toast(self, text, kind="info", detail=None, timeout=TOAST_MS):
        """Show a toast and return its widget. kind is info, success, warn or
        error. The newest sits lowest; only TOAST_MAX stay on screen."""
        layer = getattr(self, "toast_layer", None)
        if layer is None or not text:
            return None
        if kind not in ("info", "success", "warn", "error"):
            kind = "info"
        card = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2),
                      "toast-card", "toast-%s" % kind)
        label = styled(Gtk.Label(label=text, xalign=0.0), "toast-text")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(64)
        card.pack_start(label, False, False, 0)
        if detail:
            note = styled(Gtk.Label(label=detail, xalign=0.0), "toast-detail")
            note.set_ellipsize(Pango.EllipsizeMode.END)
            note.set_max_width_chars(72)
            card.pack_start(note, False, False, 0)
        set_accessible(card, "%s. %s" % (text, detail) if detail else text)
        holder = Gtk.Revealer()
        holder.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        holder.set_transition_duration(MOTION_BASE)
        holder.add(card)
        layer.pack_end(holder, False, False, 0)
        layer.set_no_show_all(False)
        layer.show_all()
        layer.set_no_show_all(True)
        holder.set_reveal_child(True)
        self.toasts.append(holder)
        while len(self.toasts) > TOAST_MAX:
            self.dismiss_toast(self.toasts[0], animate=False)
        holder._dismiss_source = GLib.timeout_add(
            max(700, int(timeout)), self.dismiss_toast, holder)
        self.add_event("toast", level=kind, text=text)
        return holder

    def dismiss_toast(self, holder, animate=True):
        """Take one toast away; the card is destroyed once its slide finishes."""
        source = getattr(holder, "_dismiss_source", 0)
        if source:
            holder._dismiss_source = 0
            GLib.source_remove(source)
        if holder in self.toasts:
            self.toasts.remove(holder)
        if animate:
            holder.set_reveal_child(False)
            GLib.timeout_add(MOTION_BASE + 60, self._drop_toast, holder)
        else:
            holder.destroy()
        if not self.toasts:
            self.toast_layer.hide()
        return False

    def _drop_toast(self, holder):
        if holder.get_parent() is not None:
            holder.destroy()
        return False

    def toast_reply(self, reply):
        """A verb the window refused is exactly what a background caller cannot
        show the user, so put it on screen as well as on the socket."""
        text = (reply or "").strip()
        if not text or "\n" in text or text.startswith("{"):
            return False
        lowered = text.lower()
        for marker in ("expects", "unknown command", "cannot ", "no such", "not a valid"):
            if marker in lowered:
                self.toast(text, kind="error", detail="control socket")
                return True
        return False

    def build_palette(self):
        """The command palette: one card over the grid with a filter entry and a
        list of every action, pane, workspace, theme and layout."""
        scrim = Gtk.EventBox()
        scrim.get_style_context().add_class("palette-scrim")
        scrim.connect("button-press-event", self.on_palette_scrim)
        card = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "palette-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.START)
        card.set_margin_top(48)
        card.set_size_request(560, -1)
        heading = styled(Gtk.Label(label="Command center", xalign=0.0), "palette-title")
        card.pack_start(heading, False, False, 0)
        self.palette_entry = Gtk.Entry()
        self.palette_entry.set_placeholder_text("Command, pane, workspace, theme or layout")
        set_accessible(self.palette_entry, "Command palette filter")
        self.palette_entry.connect("changed", lambda *_a: self.refresh_palette())
        self.palette_entry.connect("key-press-event", self.on_palette_key)
        card.pack_start(self.palette_entry, False, False, 0)
        self.palette_list = Gtk.ListBox()
        self.palette_list.get_style_context().add_class("palette-list")
        self.palette_list.set_activate_on_single_click(True)
        self.palette_list.connect("row-activated", self.on_palette_row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(180)
        scroller.add(self.palette_list)
        card.pack_start(scroller, True, True, 0)
        footer = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8),
                        "palette-footer")
        for keys, what in (("\u2191 \u2193", "move"), ("\u23ce", "run"), ("esc", "close")):
            footer.pack_start(keycaps(keys), False, False, 0)
            footer.pack_start(styled(Gtk.Label(label=what, xalign=0.0), "palette-hint"),
                              False, False, 0)
        self.palette_hint = styled(Gtk.Label(label="", xalign=1.0), "palette-hint")
        footer.pack_end(self.palette_hint, False, False, 0)
        card.pack_start(footer, False, False, 0)
        # A fade inside a slide: GTK3 revealers animate one transition each, so
        # nesting them is how the card gets both.
        fade = Gtk.Revealer()
        fade.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        fade.set_transition_duration(MOTION_BASE)
        fade.add(card)
        slide = Gtk.Revealer()
        slide.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        slide.set_transition_duration(MOTION_BASE)
        slide.add(fade)
        self.palette_fade = fade
        self.palette_revealer = slide
        def fit_palette(_widget, allocation):
            # Leave the search field and keyboard hints visible in short windows.
            top = min(48, max(12, allocation.height // 12))
            card.set_margin_top(top)
            scroller.set_min_content_height(max(80, min(320, allocation.height - top - 220)))

        scrim.connect("size-allocate", fit_palette)
        scrim.add(slide)
        scrim.set_no_show_all(True)
        scrim.hide()
        return scrim

    def palette_rows(self):
        """Every palette row as a dict: the actions, then the panes, workspaces,
        themes and layouts, each tagged with the section it belongs to."""
        reverse = {}
        for key, action in self.keymap.items():
            reverse.setdefault(action, key_hint(key))
        rows = []
        for name, label, hint, callback in self.action_table():
            rows.append({
                "label": label, "hint": reverse.get(name) or hint or "action",
                "section": "Actions", "callback": callback})
        for pane in self.order:
            position = self.position_of(pane) + 1
            rows.append({
                "label": "Pane %d: %s" % (position, pane.name),
                "hint": "go to pane %d" % position, "section": "Panes",
                "callback": (lambda target=pane: self.set_active(target))})
        for name in workspace.workspace_names(read_store()):
            rows.append({
                "label": "Workspace: %s" % name, "hint": "switch workspace",
                "section": "Workspaces",
                "callback": (lambda target=name: self.switch_workspace(target))})
        for name in art.theme_names():
            rows.append({
                "label": "Theme: %s" % name, "hint": "switch theme",
                "section": "Themes",
                "callback": (lambda target=name: self.apply_theme(target))})
        for shape in layout.shape_names():
            rows.append({
                "label": "Layout: %s" % shape, "hint": "grid shape",
                "section": "Layouts",
                "callback": (lambda target=shape: self.set_layout(target))})
        return rows

    def palette_markup(self, label, spans, color):
        """The row label with the matched letters picked out, escaped for Pango."""
        if not spans:
            return GLib.markup_escape_text(label)
        parts, cursor = [], 0
        for start, end in spans:
            parts.append(GLib.markup_escape_text(label[cursor:start]))
            parts.append('<span foreground="%s" weight="bold">%s</span>'
                         % (color, GLib.markup_escape_text(label[start:end])))
            cursor = end
        parts.append(GLib.markup_escape_text(label[cursor:]))
        return "".join(parts)

    def palette_section_row(self, title):
        """A group heading. Not selectable, so Enter can never land on one."""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.add(styled(Gtk.Label(label=title.upper(), xalign=0.0), "palette-section"))
        return row

    def refresh_palette(self):
        """Rank every row against the filter, group it by section, and pick the
        matched letters out of each label."""
        for child in list(self.palette_list.get_children()):
            self.palette_list.remove(child)
        query = self.palette_entry.get_text().strip()
        rows = palette.rank(query, self.palette_rows(), limit=200,
                            recents=self.palette_recents)
        color = chrome_palette(THEME)["accent"]
        shown = 0
        first = None
        for title, group in palette.sections(rows):
            self.palette_list.add(self.palette_section_row(title))
            for item in group:
                row = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                label = Gtk.Label(xalign=0.0)
                label.set_markup(self.palette_markup(item["label"], item["match"], color))
                label.set_ellipsize(Pango.EllipsizeMode.END)
                box.pack_start(styled(label, "palette-label"), True, True, 0)
                box.pack_end(styled(Gtk.Label(label=item["hint"], xalign=1.0),
                                    "palette-hint"), False, False, 0)
                row.add(box)
                row.callback = item["callback"]
                row.palette_label = item["label"]
                set_accessible(row, item["label"])
                self.palette_list.add(row)
                shown += 1
                if first is None:
                    first = row
        if not shown:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            empty.set_activatable(False)
            copy = styled(Gtk.Label(xalign=0.0), "palette-empty")
            copy.set_line_wrap(True)
            copy.set_text("Nothing matches %s. Try a pane number, a workspace, "
                          "a theme, or a word from a command." % query)
            empty.add(copy)
            self.palette_list.add(empty)
        self.palette_list.show_all()
        self.palette_hint.set_text(
            "%d of %d" % (shown, len(self.palette_rows())) if query else "%d rows" % shown)
        if first is not None:
            self.palette_list.select_row(first)


    def on_palette_scrim(self, widget, event):
        """A click on the dimmed area closes the palette."""
        self.hide_palette()
        return True

    def on_palette_key(self, widget, event):
        key = Gdk.keyval_name(event.keyval) or ""
        if key == "Escape":
            self.hide_palette()
            return True
        if key in ("Down", "Up", "Page_Down", "Page_Up"):
            return False  # let the list move its selection
        return False

    def on_palette_row(self, _listbox, row):
        callback = getattr(row, "callback", None)
        label = getattr(row, "palette_label", None)
        if label:
            self.remember_palette_choice(label)
        self.hide_palette()
        if callback is not None:
            GLib.idle_add(callback)
        return True

    def remember_palette_choice(self, label):
        """Recently run rows float to the top of an empty palette."""
        rest = [item for item in self.palette_recents if item != label]
        self.palette_recents = ([label] + rest)[:8]

    def show_palette(self):
        self.palette_seq += 1
        self.palette_entry.set_text("")
        self.refresh_palette()
        reveal(self.palette)
        GLib.idle_add(self.reveal_palette_card, True)
        self.palette_entry.grab_focus()
        self.palette_entry.select_region(0, -1)

    def reveal_palette_card(self, open_card):
        """Open or close the card. GTK3 does one transition type per revealer, so
        the card sits in a fade inside a slide and the two compose."""
        revealer = getattr(self, "palette_revealer", None)
        fade = getattr(self, "palette_fade", None)
        if revealer is not None:
            revealer.set_reveal_child(open_card)
        if fade is not None:
            fade.set_reveal_child(open_card)
        if not open_card and (revealer is None or not revealer.get_reveal_child()):
            self.palette.hide()
        return False

    def hide_palette(self):
        revealer = getattr(self, "palette_revealer", None)
        if revealer is None:
            self.palette.hide()
        else:
            revealer.set_reveal_child(False)
            fade = getattr(self, "palette_fade", None)
            if fade is not None:
                fade.set_reveal_child(False)
            GLib.timeout_add(MOTION_BASE + 60, self.palette_settle, self.palette_seq)
        self.focus_active()

    def palette_settle(self, seq):
        """Close the card once its slide finishes, unless it was reopened since."""
        revealer = getattr(self, "palette_revealer", None)
        if (seq == self.palette_seq and revealer is not None
                and not revealer.get_reveal_child()):
            self.palette.hide()
        return False

    def show_search_all(self):
        """Search every pane's screen and jump to a match."""
        dialog, body = self.new_dialog(
            "Search every pane", "Case insensitive, over each pane's scrollback.", width=640)
        entry = Gtk.Entry()
        entry.set_placeholder_text("text to find")
        set_accessible(entry, "Search every pane")
        body.pack_start(entry, False, False, 0)
        summary = styled(Gtk.Label(label="", xalign=0.0), "field-hint")
        body.pack_start(summary, False, False, 0)
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(260)
        scroller.add(results)
        body.pack_start(scroller, True, True, 0)

        def run(_widget=None):
            for child in list(results.get_children()):
                results.remove(child)
            needle = entry.get_text().strip()
            if not needle:
                summary.set_text("Type something to search for.")
                results.show_all()
                return
            lowered = needle.lower()
            panes_hit = 0
            lines_hit = 0
            for pane in self.order:
                text = pane.visible_text() or ""
                matches = [line for line in text.splitlines() if lowered in line.lower()]
                if not matches:
                    continue
                panes_hit += 1
                lines_hit += len(matches)
                for line in matches[:4]:
                    row = styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8),
                                 "result-row")
                    row.pack_start(styled(Gtk.Label(
                        label="%d %s" % (self.position_of(pane) + 1, pane.name),
                        xalign=0.0), "result-pane"), False, False, 0)
                    label = styled(Gtk.Label(label=line.strip()[:110] or "(blank)", xalign=0.0),
                                   "result-line")
                    label.set_ellipsize(Pango.EllipsizeMode.END)
                    row.pack_start(label, True, True, 0)
                    go = Gtk.Button(label="Go")
                    go.connect("clicked", lambda _b, target=pane, term=needle: self.focus_find(target, term))
                    set_accessible(go, "Go to pane %s" % pane.name)
                    row.pack_end(go, False, False, 0)
                    results.pack_start(row, False, False, 0)
            summary.set_text(
                "No match in %d panes." % len(self.order) if not panes_hit
                else "%d line%s in %d pane%s." % (lines_hit, "" if lines_hit == 1 else "s",
                                                  panes_hit, "" if panes_hit == 1 else "s"))
            results.show_all()

        entry.connect("activate", run)
        self.add_actions(dialog, "Close", cancel=None)
        dialog.show_all()
        entry.grab_focus()
        dialog.run()
        dialog.destroy()

    def focus_find(self, pane, needle):
        """Focus a pane and search for a term inside it."""
        self.set_active(pane)
        pane.search_for(needle)

    def popup_menu(self, pane, event, widget=None):
        """Pane menu, from a right-click (event) or the pane's ⋮ button (widget)."""
        self.set_active(pane)
        zoomed = self.zoom and pane is self.active
        menu = Gtk.Menu()
        entries = (
            ("Back to the grid" if zoomed else "Zoom pane", lambda: self.zoom_pane(pane), "<Ctrl><Shift>z"),
            ("Find…", pane.show_find, "<Ctrl><Shift>g"),
            None,
            ("Copy", pane.copy_text, "<Ctrl><Shift>c"),
            ("Paste", pane.paste_text, "<Ctrl><Shift>v"),
            ("Select all", pane.term.select_all, None),
            None,
            ("Rename pane…", lambda: self.rename_pane(pane), None),
            ("Edit command…", lambda: self.edit_command(pane), None),
        )
        for entry in entries:
            menu.append(Gtk.SeparatorMenuItem() if entry is None else menu_item(*entry))
        sessions = self.tmux_sessions()
        if sessions:
            sub = Gtk.Menu()
            for name in sessions:
                sub.append(menu_item(name, lambda n=name: pane.restart(
                    "tmux new-session -A -s %s" % shlex.quote(n))))
            item = Gtk.MenuItem(label="Attach tmux session")
            item.set_submenu(sub)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item("Restart pane", pane.restart))
        menu.append(menu_item("Reset pane…", pane.close_and_respawn, "<Ctrl><Shift>r"))
        menu.append(menu_item("Remove pane", lambda: self.remove_window(pane),
                              "<Ctrl><Shift>minus", len(self.panes) > MIN_PANES))
        menu.show_all()
        if widget is not None:
            menu.popup_at_widget(widget, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, event)
        else:
            menu.popup_at_pointer(event)

    def show_app_menu(self):
        menu = Gtk.Menu()
        entries = (
            ("Run in all panes…", self.show_fill_dialog, "<Ctrl><Shift>e"),
            ("Add pane", self.add_pane, None, len(self.panes) < MAX_PANES),
            ("Remove focused pane", lambda: self.remove_window(self.active),
             "<Ctrl><Shift>minus", len(self.panes) > MIN_PANES),
            None,
            ("Fit to screen", self.fit_window, "<Ctrl><Shift>f"),
            ("Hide", self.hide_window, "<Ctrl><Shift>w"),
            None,
            ("Reset all panes…", lambda: self.fresh_sessions(confirm=True), "<Ctrl><Shift>n"),
            None,
            ("Settings…", self.show_settings, "<Ctrl><Shift>comma"),
            ("Keyboard shortcuts", self.show_shortcuts, "<Ctrl><Shift>slash"),
            ("About %s" % APP_TITLE, self.show_about, None),
            None,
            ("Quit", self.quit, "<Ctrl><Shift>q"),
        )
        for entry in entries:
            menu.append(Gtk.SeparatorMenuItem() if entry is None else menu_item(*entry))
        menu.show_all()
        menu.popup_at_widget(self.menu_btn, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, None)

    def save_workspace(self, name=None, rename=False):
        """Persist the current setup, optionally under a new workspace name."""
        current = self.workspace_name()
        if name is not None:
            name = name.strip()
            if not name:
                self.toast("Enter a workspace name", kind="warn")
                return False
            occupied = {workspace.slug(item) for item in workspace.workspace_names(read_store())}
            if name != current and workspace.slug(name) in occupied:
                self.toast("That workspace name already exists", kind="warn")
                return False
        try:
            save_config(self.config)
            if name and name != current:
                store = read_store()
                updated = (workspace.rename_workspace(store, current, name) if rename
                           else workspace.add_workspace(store, name, copy_from=current))
                updated = workspace.set_active(updated, name)
                write_store(updated)
                set_store(updated)
                self.config["workspace"] = name
            self.save_state()
        except OSError as exc:
            self.toast("Could not save workspace", detail=str(exc), kind="error")
            return False
        self.refresh_workspace_chip()
        self.toast("Workspace renamed" if rename else "Workspace saved",
                   detail=self.workspace_name(), kind="success")
        return True

    def prompt_workspace_name(self, rename=False):
        self.prompt(
            "Rename workspace" if rename else "Save workspace as",
            "Choose a name to find this pane setup in the workspace menu later.",
            self.workspace_name() if rename else "",
            lambda name: self.save_workspace(name, rename=rename),
            ok_label="Rename" if rename else "Save",
            placeholder="For example: Website project")

    def show_workspace_menu(self):
        """The header chip: every workspace, the active one ticked and inert."""
        menu = Gtk.Menu()
        names = workspace.workspace_names(read_store())
        current = workspace.slug(self.workspace_name())
        for name in names:
            menu.append(menu_item(
                name, (lambda target=name: self.switch_workspace(target)),
                sensitive=workspace.slug(name) != current))
        if not names:
            menu.append(menu_item("No workspaces", lambda: None, sensitive=False))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item("Save workspace", self.save_workspace))
        menu.append(menu_item("Save workspace as…", self.prompt_workspace_name))
        menu.append(menu_item("Rename workspace…", lambda: self.prompt_workspace_name(rename=True)))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item("Next workspace", lambda: self.switch_workspace_step(1)))
        menu.append(menu_item("Previous workspace", lambda: self.switch_workspace_step(-1)))
        menu.show_all()
        menu.popup_at_widget(self.ws_btn, Gdk.Gravity.SOUTH_WEST,
                             Gdk.Gravity.NORTH_WEST, None)

    def refresh_workspace_chip(self):
        """Keep the header chip naming the workspace the window is showing."""
        button = getattr(self, "ws_btn", None)
        if button is None:
            return False
        name = self.workspace_name()
        button.set_label("Workspace: %s ▾" % name)
        set_accessible(button, "Workspace: %s. Switch workspace" % name)
        button.set_tooltip_text(
            "Switch saved pane arrangements. Current workspace: %s. "
            "Terminal sessions keep running.  (Ctrl+Shift+P, type workspace)" % name)
        return False

    def tmux_sessions(self):
        try:
            out = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"],
                                 capture_output=True, text=True, timeout=3, check=False)
            return [s for s in out.stdout.split() if s]
        except Exception:
            return []

    def new_dialog(self, title, copy=None, width=440):
        """Dialog whose heading sits in the body, with no separate title strip."""
        dialog = Gtk.Dialog(transient_for=self.win, modal=True, use_header_bar=0)
        dialog.set_title(title)
        dialog.set_titlebar(Gtk.Box())  # hidden title bar, as GtkMessageDialog does
        dialog.set_default_size(width, -1)
        dialog.set_resizable(False)
        dialog.get_style_context().add_class("cligrid-dialog")
        area = dialog.get_content_area()
        area.set_spacing(0)
        body = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "dialog-body")
        body.pack_start(styled(Gtk.Label(label=title, xalign=0.0), "dialog-title"), False, False, 0)
        if copy:
            label = styled(Gtk.Label(label=copy, xalign=0.0), "dialog-copy")
            label.set_line_wrap(True)
            label.set_max_width_chars(54)
            body.pack_start(label, False, False, 0)
        area.pack_start(body, True, True, 0)
        return dialog, body

    def add_actions(self, dialog, ok, cancel="Cancel", style="suggested-action", default_ok=True):
        if cancel:
            dialog.add_button(cancel, Gtk.ResponseType.CANCEL)
        button = dialog.add_button(ok, Gtk.ResponseType.OK)
        if style:
            button.get_style_context().add_class(style)
        response = Gtk.ResponseType.OK if default_ok or not cancel else Gtk.ResponseType.CANCEL
        dialog.set_default_response(response)
        return dialog.get_widget_for_response(response)

    def run_dialog(self, dialog, focus=None):
        dialog.show_all()
        if focus is not None:
            focus.grab_focus()
        ok = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return ok

    def confirm_reset(self, panes):
        """Ask before ending sessions. Enter cancels; the red button confirms."""
        if len(panes) == 1:
            name = panes[0].name
            title = "Reset %s?" % name
            copy = ("This ends the session in %s and starts an empty terminal in its "
                    "place. Anything running there is lost." % name)
            action = "Reset pane"
        else:
            title = "Reset all %d panes?" % len(panes)
            copy = ("This ends every pane's session and starts empty terminals. "
                    "Anything running in them is lost.")
            action = "Reset all"
        dialog, _body = self.new_dialog(title, copy, width=420)
        cancel = self.add_actions(dialog, action, style="destructive-action", default_ok=False)
        return self.run_dialog(dialog, focus=cancel)

    def fresh_pane(self, pane):
        pane.close_and_respawn(confirm=True)

    def _finish_fresh_pane(self, pane):
        pane.pending_fresh = False
        pane.spawn()
        self.set_active(pane)
        self.update_status()
        return False

    def populate_all(self, cli):
        cli = (cli or "").strip()
        if not cli:
            return False
        if cli.startswith("-"):
            # An option is not a command. Written here it kills every pane and
            # the value persists, so refuse it instead of saving it.
            return False
        self.config["fill_cmd"] = cli
        if self.zoom:
            self.toggle_zoom(False)
        for pane in self.panes:
            pane.cmd = pane_cmd_for_cli(pane.name, cli)
            if 0 <= pane.slot < len(self.config["panes"]):
                self.config["panes"][pane.slot]["cmd"] = pane.cmd
            pane.pending_fresh = True
            pane.quick_exits = 0
            pane.kill_session()
        save_config(self.config)
        self.toast("Running %s in %d panes" % (cli, len(self.panes)), kind="warn",
                   detail="their previous sessions ended")
        GLib.timeout_add(80, self._finish_fresh_all)
        return True

    def show_fill_dialog(self):
        self.prompt(
            "Run in all panes",
            "Each pane's current session ends and this command starts in its "
            "place, in a tmux session of its own.",
            str(self.config.get("fill_cmd") or ""),
            self.populate_all,
            ok_label="Run in all panes",
            placeholder="e.g. claude",
            destructive=True,
        )

    def fresh_sessions(self, confirm=True):
        if confirm and not self.confirm_reset(list(self.panes)):
            return
        if self.zoom:
            self.toggle_zoom(False)
        for pane in self.panes:
            pane.pending_fresh = True
            pane.quick_exits = 0
            pane.kill_session()
        GLib.timeout_add(80, self._finish_fresh_all)

    def _finish_fresh_all(self):
        for pane in self.panes:
            pane.pending_fresh = False
            pane.spawn()
        self.set_active(self.order[0])
        self.focus_active()
        self.update_status()
        return False

    def rename_pane(self, pane):
        self.prompt("Rename pane", "Shown in the pane title and the pane switcher.",
                    pane.name, pane.set_name, ok_label="Rename")

    def edit_command(self, pane):
        self.prompt(
            "Pane command",
            "Runs when %s starts. A tmux session such as tmux new-session -A -s %s "
            "keeps its work across restarts." % (pane.name, pane.name),
            pane.cmd, pane.restart, ok_label="Save and restart",
        )

    def prompt(self, title, hint, initial, callback, ok_label="Save",
               placeholder=None, destructive=False):
        dialog, body = self.new_dialog(title, hint, width=460)
        entry = Gtk.Entry()
        entry.set_text(initial)
        entry.set_activates_default(True)
        entry.set_margin_top(6)
        if placeholder:
            entry.set_placeholder_text(placeholder)
        body.pack_start(entry, False, False, 0)
        self.add_actions(dialog, ok_label,
                         style="destructive-action" if destructive else "suggested-action")
        dialog.show_all()
        entry.grab_focus()
        accepted = dialog.run() == Gtk.ResponseType.OK
        value = entry.get_text().strip()
        dialog.destroy()
        if accepted and value:
            callback(value)

    def set_terminal_font(self, family):
        """Apply and persist font preferences without restarting terminal sessions."""
        self.config["font"] = family or self.config["font"]
        save_config(self.config)
        self._metrics_cache = {}
        self._font_caps = {}
        self.apply_font_all(self.font_size)
        self.autosize_font()
        self.update_status()

    def show_font_dialog(self):
        dialog, body = self.new_dialog(
            "Terminal font", "Font size automatically fits the window and pane layout.", width=460)
        fonts = Gtk.ComboBoxText()
        names = self.list_mono_fonts()
        for name in names:
            fonts.append_text(name)
        fonts.set_active(names.index(self.config["font"]))
        set_accessible(fonts, "Font family")
        body.pack_start(Gtk.Label(label="Font family", xalign=0), False, False, 0)
        body.pack_start(fonts, False, False, 0)
        self.add_actions(dialog, "Apply")
        dialog.show_all()
        accepted = dialog.run() == Gtk.ResponseType.OK
        family = fonts.get_active_text()
        dialog.destroy()
        if accepted:
            self.set_terminal_font(family)

    def list_mono_fonts(self):
        try:
            families = self.win.get_pango_context().list_families()
        except Exception:
            families = []
        installed = {f.get_name() for f in families}
        names = sorted({f.get_name() for f in families if f.is_monospace()})
        for preferred in reversed(PREFERRED_FONTS):
            if preferred in installed and preferred not in names:
                names.insert(0, preferred)
        current = self.config["font"]
        if current not in names:
            names.insert(0, current)
        return names or list(PREFERRED_FONTS)

    def set_pane_count(self, count, save=True):
        count = clamp_pane_count(count)
        self.config["pane_count"] = count
        self.config["panes"] = normalize_panes(self.config.get("panes"), count)
        if save:
            save_config(self.config)
        while len(self.panes) < count:
            pane = Pane(self, len(self.panes))
            self.panes.append(pane)
            self.order.append(pane)
        while len(self.panes) > count:
            pane = self.panes.pop()
            if pane in self.order:
                self.order.remove(pane)
            self.detach_pane(pane)
        self.after_count_change()
        return True

    def detach_pane(self, pane):
        pane.dead = True
        if self.active is pane or self.active not in self.order:
            self.active = self.order[0]
        parent = pane.box.get_parent()
        if parent is not None:
            parent.remove(pane.box)
        pane.box.destroy()

    def after_count_change(self):
        if self.active not in self.order:
            self.active = self.order[0]
        self._cell_req = None
        self._cell_h = None
        self.rebuild_pills()
        self.render()

    def remove_window(self, pane):
        if pane is None or pane not in self.panes:
            return False
        leftover = drop_pane_config(
            [{"name": item.name, "cmd": item.cmd} for item in self.panes],
            self.panes.index(pane),
        )
        if leftover is None:
            return False
        self.zoom = False
        self.panes.remove(pane)
        if pane in self.order:
            self.order.remove(pane)
        self.detach_pane(pane)
        for i, item in enumerate(self.panes):
            item.slot = i
        self.config["pane_count"] = len(self.panes)
        self.config["panes"] = leftover
        save_config(self.config)
        self.after_count_change()
        self.poll_waiters()  # a wait on this pane must answer now, not on the next timer
        return True

    def dialog_columns(self, body):
        """Two side-by-side grids; sections in one column share its label width."""
        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=36)
        columns.set_margin_top(10)
        grids = []
        for _ in range(2):
            grid = Gtk.Grid(column_spacing=16, row_spacing=8)
            grid.set_valign(Gtk.Align.START)
            columns.pack_start(grid, True, True, 0)
            grids.append(grid)
        body.pack_start(columns, False, False, 0)
        return grids

    @staticmethod
    def grid_rows(grid):
        rows = 0
        for child in grid.get_children():
            top = grid.child_get_property(child, "top-attach")
            rows = max(rows, top + grid.child_get_property(child, "height"))
        return rows

    def dialog_section(self, grid, title):
        top = self.grid_rows(grid)
        label = styled(Gtk.Label(label=title.upper(), xalign=0.0), "section-title")
        if top:
            label.set_margin_top(14)
        grid.attach(label, 0, top, 2, 1)

    def dialog_row(self, grid, first, second):
        top = self.grid_rows(grid)
        grid.attach(first, 0, top, 1, 1)
        grid.attach(second, 1, top, 1, 1)

    def show_settings(self):
        dialog, body = self.new_dialog(
            "Settings", "Applies to every pane. Sessions keep running in tmux.", width=640)
        left, right = self.dialog_columns(body)

        def row(grid, text, widget):
            widget.set_hexpand(True)
            set_accessible(widget, text)
            self.dialog_row(grid, styled(Gtk.Label(label=text, xalign=0.0), "field-label"), widget)

        def spin(low, high, step, value):
            button = Gtk.SpinButton.new_with_range(low, high, step)
            button.set_value(value)
            button.set_width_chars(6)
            return button

        def switch(value):
            toggle = Gtk.Switch()
            toggle.set_active(bool(value))
            toggle.set_halign(Gtk.Align.START)
            toggle.set_valign(Gtk.Align.CENTER)
            return toggle

        def combo(options, current):
            box = Gtk.ComboBoxText()
            for key, label in options:
                box.append(key, label)
            box.set_active_id(str(current))
            return box

        fonts = Gtk.ComboBoxText()
        font_names = self.list_mono_fonts()
        for name in font_names:
            fonts.append_text(name)
        try:
            fonts.set_active(font_names.index(self.config["font"]))
        except ValueError:
            fonts.set_active(0)
        for cell in fonts.get_cells():
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
            cell.set_property("width-chars", 16)
        blink = switch(self.config.get("cursor_blink", False))
        self.dialog_section(left, "Font")
        row(left, "Family", fonts)
        row(left, "Blinking cursor", blink)
        bell = switch(self.config.get("bell_alerts", True))
        activity = switch(self.config.get("activity_marks", True))
        notify = switch(self.config.get("notify_desktop", True))
        self.dialog_section(left, "Alerts")
        row(left, "Bell alerts", bell)
        row(left, "Activity marks", activity)
        row(left, "Desktop notifications", notify)

        windows = spin(MIN_PANES, MAX_PANES, 1, len(self.panes))
        fit = Gtk.ComboBoxText()
        fit_options = [("maximized", "Fill the screen"), ("workarea", "Use the work area")]
        current_fit = str(self.config.get("fit", "maximized"))
        if current_fit not in ("maximized", "workarea"):
            fit_options.append((current_fit, "Custom (%s)" % current_fit))
        for key, label in fit_options:
            fit.append(key, label)
        fit.set_active_id(current_fit)
        cols = spin(20, 140, 1, int(self.config["min_cols"]))
        rows = spin(8, 50, 1, int(self.config["min_rows"]))
        scroll = spin(500, 50000, 500, int(self.config["scrollback"]))
        self.dialog_section(right, "Layout")
        row(right, "Panes", windows)
        row(right, "Window size", fit)
        self.dialog_section(right, "Terminal")
        row(right, "Minimum columns", cols)
        row(right, "Minimum rows", rows)
        row(right, "Scrollback lines", scroll)
        banner = switch(self.config.get("banner", True))
        row(right, "Welcome banner", banner)

        prefix = combo(PREFIX_CHOICES, self.config.get("prefix") or "space")
        guard = combo(
            (("panes", "Refuse destructive verbs from panes"),
             ("off", "Allow everything")),
            self.config.get("guard") or "panes",
        )
        self.dialog_section(right, "Keyboard")
        row(right, "Prefix key", prefix)
        row(right, "Control guard", guard)

        self.add_actions(dialog, "Save")
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self.config["font"] = fonts.get_active_text() or self.config["font"]
            self.config["min_cols"] = int(cols.get_value())
            self.config["min_rows"] = int(rows.get_value())
            self.config["scrollback"] = int(scroll.get_value())
            self.config["cursor_blink"] = bool(blink.get_active())
            self.config["banner"] = bool(banner.get_active())
            self.config["bell_alerts"] = bool(bell.get_active())
            self.config["activity_marks"] = bool(activity.get_active())
            self.config["notify_desktop"] = bool(notify.get_active())
            for pane in self.panes:
                if ((pane.mark == "alert" and not self.config["bell_alerts"]) or
                        (pane.mark == "activity" and not self.config["activity_marks"])):
                    pane.set_mark(None)
            self.config["fit"] = fit.get_active_id() or self.config["fit"]
            self.config["prefix"] = prefix.get_active_id() or self.config["prefix"]
            chosen_guard = guard.get_active_id() or self.config["guard"]
            self.config["guard"] = chosen_guard if chosen_guard in control.GUARD_MODES else "panes"
            if self.config["min_font_size"] > self.config["font_size"]:
                self.config["min_font_size"] = self.config["font_size"]
            self.set_pane_count(int(windows.get_value()), save=False)
            save_config(self.config)
            self._metrics_cache = {}
            self._font_caps = {}
            self.apply_font_all(self.font_size)
            for pane in self.panes:
                pane.apply_terminal_prefs()
            self.fit_window()
            self.autosize_font()
            self.keymap = self.build_keymap()
            self.update_status()
        dialog.destroy()

    def show_shortcuts(self):
        dialog, body = self.new_dialog(
            "Keyboard shortcuts",
            "Ctrl+Shift plus the key, unless the prefix is armed. Empty unbinds. "
            "A key that collides with the prefix, or is used twice, is refused.",
            width=720,
        )
        prefix = Gtk.ComboBoxText()
        for key, label in PREFIX_CHOICES:
            prefix.append(key, label)
        current_prefix = str(self.config.get("prefix") or "space")
        prefix.set_active_id(current_prefix if current_prefix in PREFIX_KEY_NAMES else "space")
        set_accessible(prefix, "Prefix key")
        prefix_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        prefix_row.pack_start(styled(Gtk.Label(label="Prefix key", xalign=0.0), "field-label"),
                              False, False, 0)
        prefix_row.pack_start(prefix, True, True, 0)
        body.pack_start(prefix_row, False, False, 0)

        grouped = keymap.invert(self.keymap)
        entries = {}
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(4)
        rows = [(name, label) for name, label, _hint, _cb in self.action_table()]
        for n in range(1, 11):
            rows.append(("focus.%d" % n, "Focus pane %d" % n))
        for index, (name, label) in enumerate(rows):
            caption = styled(Gtk.Label(label=label, xalign=0.0), "field-label")
            field = Gtk.Entry()
            field.set_text(" ".join(grouped.get(name, [])))
            field.set_placeholder_text("unbound")
            set_accessible(field, "Keys for %s" % label)
            grid.attach(caption, 0, index, 1, 1)
            grid.attach(field, 1, index, 1, 1)
            entries[name] = field
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(320)
        scroller.add(grid)
        body.pack_start(scroller, True, True, 0)

        mouse = styled(Gtk.Label(
            label="Mouse: drag a title to swap, double-click to zoom, "
                  "right-click for the pane menu, Ctrl+click a link to open it.",
            xalign=0.0), "dialog-copy")
        mouse.set_line_wrap(True)
        body.pack_start(mouse, False, False, 0)
        error = styled(Gtk.Label(label="", xalign=0.0), "field-hint")
        error.set_line_wrap(True)
        body.pack_start(error, False, False, 0)

        self.add_actions(dialog, "Save")
        dialog.show_all()
        while True:
            if dialog.run() != Gtk.ResponseType.OK:
                break
            message = self._save_edited_keymap(entries, prefix.get_active_id())
            if not message:
                break
            error.set_text(message)
        dialog.destroy()

    def _save_edited_keymap(self, entries, prefix_id):
        """Write a shortcuts-editor map. Return an error string, or empty on success."""
        built, dupes = keymap.parse_fields(
            (name, field.get_text()) for name, field in entries.items())
        known = keymap.known_ids(entries)
        chosen = prefix_id if prefix_id in PREFIX_KEY_NAMES else "space"
        rows = list(dupes) + keymap.conflicts(built, known, PREFIX_KEY_NAMES[chosen])
        if rows:
            return "; ".join("%s: %s" % (key, reason) for key, _action, reason in rows[:6])
        self.config["prefix"] = chosen
        self.config["keymap"] = keymap.diff(DEFAULT_KEYMAP, built)
        save_config(self.config)
        self.keymap = self.build_keymap()
        return ""

    def show_about(self):
        dialog, body = self.new_dialog(APP_TITLE, width=400)
        if theme_has_icon(APP):
            icon = Gtk.Image.new_from_icon_name(APP, Gtk.IconSize.DIALOG)
            icon.set_pixel_size(64)
            icon.set_halign(Gtk.Align.START)
            body.pack_start(icon, False, False, 0)
            body.reorder_child(icon, 0)
        body.pack_start(styled(Gtk.Label(label="Version %s" % VERSION, xalign=0.0), "about-version"),
                        False, False, 0)
        body.pack_start(styled(Gtk.Label(
            label="Developed by %s, %s" % (AUTHOR, ORG), xalign=0.0), "about-author"),
                        False, False, 0)
        copy = styled(Gtk.Label(
            label="Up to twenty terminals in one window, in the grid's own dark "
                  "palette. Every pane is a tmux session, so work survives hiding, "
                  "restarting and quitting the grid.",
            xalign=0.0,
        ), "dialog-copy")
        copy.set_line_wrap(True)
        copy.set_max_width_chars(46)
        copy.set_width_chars(40)  # without a floor, wrapping inflates the dialog height
        copy.set_margin_top(4)
        body.pack_start(copy, False, False, 0)
        self.add_actions(dialog, "Close", cancel=None, style=None)
        self.run_dialog(dialog)

    def start_socket(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        service = Gio.SocketService.new()
        try:
            # A /tmp fallback must be private even with a permissive user umask.
            mask = os.umask(0o177)
            try:
                service.add_address(
                    Gio.UnixSocketAddress.new(SOCKET_PATH),
                    Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None,
                )
            finally:
                os.umask(mask)
            service.connect("incoming", self.on_incoming)
            service.start()
        except GLib.Error as exc:
            sys.stderr.write("cligrid: control socket unavailable: %s\n" % exc.message)
            return None
        return service

    def on_incoming(self, service, connection, _source):
        """Read one request line in bounded chunks. A client that sends more
        than MAX_REQUEST_BYTES without a newline is answered with an error and
        dropped, so no local process can grow the window's memory at will."""
        self.read_request(connection, connection.get_input_stream(), bytearray())
        return True

    def read_request(self, connection, stream, buffer):
        stream.read_bytes_async(
            4096, GLib.PRIORITY_DEFAULT, None, self.on_request_bytes, (connection, buffer))

    def on_request_bytes(self, stream, result, holder):
        connection, buffer = holder
        try:
            data = stream.read_bytes_finish(result).get_data() or b""
        except GLib.Error:
            connection.close(None)
            return
        buffer += data
        newline = buffer.find(b"\n")
        if newline < 0:
            if not data:  # the client closed without a newline: take what it sent
                self.on_request(connection, bytes(buffer))
                return
            if len(buffer) > control.MAX_REQUEST_BYTES:
                self.reply(connection, "request is longer than %d bytes\n"
                           % control.MAX_REQUEST_BYTES)
                return
            self.read_request(connection, stream, buffer)
            return
        self.on_request(connection, bytes(buffer[:newline]))

    def on_request(self, connection, line):
        request = line.decode("utf-8", "replace").strip()
        tokens, forced = control.split_force(request.split())
        if forced:
            request = " ".join(tokens)
        parsed = control.parse(request)
        verb = parsed["verb"] if not parsed["error"] else ""
        refusal = control.guard_refusal(
            verb, forced, verb in control.GUARDED_VERBS and request_from_pane(connection),
            self.config.get("guard", "panes"))
        if refusal:
            self.add_event("error", text=refusal)
            self.toast(refusal, kind="warn", detail="control socket")
            self.reply(connection, refusal + "\n")
            return
        if verb in ("events", "watch"):
            self.subscribe_events(parsed, connection)
            return
        if verb == "wait":
            self.start_wait(parsed, connection)
            return
        reply = self.dispatch(request)
        if verb and not self.quitting:
            try:
                self.toast_reply(reply)
            except Exception as exc:  # feedback must never break a reply
                sys.stderr.write("cligrid: toast failed: %s\n" % exc)
        self.reply(connection, reply)

    def reply(self, connection, text):
        """Queue one reply and close once it is written, the shape every plain
        verb uses. Nothing here blocks on the client."""
        link = ControlLink(connection)
        link.send(text or "ok\n")
        link.finish()
        return link

    def hold(self, connection, group, **fields):
        """A connection the window keeps: a subscriber or a waiter. The link
        drops it from `group` when the client hangs up or stops reading."""
        holder = dict(fields)
        holder["link"] = ControlLink(connection, on_gone=lambda _link: self.drop_holder(holder))
        holder["watch"] = self.watch_connection(connection, holder)
        group.append(holder)
        return holder

    def subscribe_events(self, parsed, connection):
        """`events` holds the connection open and writes one JSON line per event
        until the client goes away or stops reading."""
        options = control.parse_events(parsed["args"])
        kinds = set(options.get("kinds") or [])
        subscriber = self.hold(connection, self.subscribers, kinds=kinds,
                               seq=options.get("since", 0))
        backfill = [event for event in self.event_log.since(subscriber["seq"])
                    if not kinds or event.get("kind") in kinds]
        if backfill:
            subscriber["seq"] = max(event.get("seq", 0) for event in backfill)
            if not self.write_events(subscriber, backfill):
                return
        self.add_event("subscribe", kinds=sorted(kinds))

    def watch_connection(self, connection, holder):
        """Drop a held connection when its client goes away."""
        try:
            fd = connection.get_socket().get_fd()
        except Exception:
            return 0
        return GLib.io_add_watch(
            fd, GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.HUP | GLib.IOCondition.ERR | GLib.IOCondition.NVAL,
            self.on_held_io, holder)

    def on_held_io(self, _fd, _condition, holder):
        """The client hung up: stop sending to it."""
        self.drop_holder(holder)
        return False

    def drop_holder(self, holder):
        for group in (self.subscribers, self.waiters):
            if holder in group:
                group.remove(holder)
        watch = holder.get("watch") or 0
        if watch:
            try:
                GLib.source_remove(watch)
            except Exception:
                pass
            holder["watch"] = 0
        link = holder.get("link")
        if link is not None:
            reason = link.reason
            link.on_gone = None
            link.finish()  # closes now, or once a queued final reply is written
            if reason and "pane" not in holder:
                self.add_event("error", text="events subscriber dropped: %s" % reason)

    def write_events(self, subscriber, events):
        """Queue events for one subscriber; False means the client is gone."""
        payload = "".join(control.format_event(event) for event in events)
        return subscriber["link"].send(payload)

    def add_event(self, kind, **fields):
        """Record an event and push it to every subscriber that wants that kind."""
        event = self.event_log.add(kind, **fields)
        for subscriber in list(self.subscribers):
            kinds = subscriber["kinds"]
            if kinds and kind not in kinds:
                continue
            self.write_events(subscriber, [event])  # a failed send drops the holder itself
        return event

    def start_wait(self, parsed, connection):
        """`wait` holds the connection until a pane matches a pattern or the
        timeout runs out, then answers with the matching line."""
        try:
            options = control.parse_wait(parsed["args"])
        except ValueError as exc:
            self.reply(connection, "%s\n" % exc)
            return
        pane = self.pane_arg(str(options["pane"]), "wait")
        if pane is None:
            self.reply(connection, "wait expects a pane number %s\n" % self.pane_range_text())
            return
        try:
            regex = re.compile(options["pattern"], re.IGNORECASE)
        except re.error as exc:
            self.reply(connection, "wait: bad pattern (%s)\n" % exc)
            return
        waiter = self.hold(connection, self.waiters, pane=pane, pattern=options["pattern"],
                           regex=regex, deadline=time.monotonic() + options["timeout"])
        self.check_waiter(waiter)

    def check_waiter(self, waiter):
        """Answer a waiter when its pane matches, when it runs out of time, or
        when its pane has been removed. The text the pattern sees is bounded to
        the pane's last WAIT_ROWS rows and WAIT_TEXT_CHARS characters."""
        pane = waiter["pane"]
        if pane.dead or pane not in self.panes:
            self.finish_waiter(waiter, matched=False, line="pane removed")
            return True
        text = pane.poll_text
        if text is None:
            text = pane.screen_text(rows=WAIT_ROWS)
        text = (text or "")[-WAIT_TEXT_CHARS:]
        match = waiter["regex"].search(text) if text else None
        if match:
            line = ""
            for row in text.splitlines():
                if waiter["regex"].search(row):
                    line = row.strip()
            self.finish_waiter(waiter, matched=True, line=line)
            return True
        if time.monotonic() >= waiter["deadline"]:
            self.finish_waiter(waiter, matched=False)
            return True
        return False

    def finish_waiter(self, waiter, matched, line=""):
        """Reply to a waiter and let its connection go."""
        payload = json.dumps({
            "matched": bool(matched),
            "pane": self.position_of(waiter["pane"]) + 1,
            "name": waiter["pane"].name,
            "line": line,
            "state": waiter["pane"].state,
        }) + "\n"
        link = waiter["link"]
        link.on_gone = None
        link.send(payload)
        link.finish()
        self.add_event("wait", pane=waiter["pane"].name, matched=bool(matched))
        self.drop_holder(waiter)

    def poll_waiters(self):
        for waiter in list(self.waiters):
            self.check_waiter(waiter)

    def dispatch(self, request):
        """One request line, one reply. control.parse validates the verb; a
        table of handlers owns what each verb does, so adding a verb cannot
        grow this method back into a 48-branch chain."""
        parsed = control.parse(request)
        if parsed["error"]:
            return parsed["error"] + "\n"
        handler = _VERB_HANDLERS.get(parsed["verb"])
        if handler is None:
            return "unknown command: %s\n" % parsed["verb"]
        reply = handler(self, parsed["args"])
        return "ok\n" if reply is None else reply

    def _verb_show(self, _args):
        self.show_window()

    def _verb_hide(self, _args):
        self.hide_window()

    def _verb_toggle(self, _args):
        self.toggle_visibility()

    def _verb_zoom(self, args):
        arg = args[0] if args else None
        if arg in (None, "toggle"):
            self.toggle_zoom()
        elif arg == "off":
            self.toggle_zoom(False)
        else:
            position = self.position_arg(arg, "zoom")
            if position is None:
                return "zoom expects a pane number %s or off\n" % self.pane_range_text()
            self.focus_slot(position)
            self.toggle_zoom(True)
        return None

    def _verb_panes(self, args):
        arg = args[0] if args else None
        if not arg:
            return "%d\n" % len(self.panes)
        try:
            self.set_pane_count(int(arg))
        except ValueError:
            return "panes expects a count from %d to %d\n" % (MIN_PANES, MAX_PANES)
        return None

    def _verb_remove(self, args):
        arg = args[0] if args else None
        pane = self.pane_arg(arg, "remove")
        if arg and pane is None:
            return "remove expects a window number %s\n" % self.pane_range_text()
        if not self.remove_window(pane or self.active):
            return "cannot remove the last window\n"
        return None

    def _verb_restart(self, args):
        arg = args[0] if args else None
        pane = self.pane_arg(arg, "restart")
        if arg and pane is None:
            return "restart expects a pane number %s\n" % self.pane_range_text()
        (pane or self.active).restart()

    def _verb_reset(self, args):
        arg = args[0] if args else None
        if arg:
            pane = self.pane_arg(arg, "reset")
            if pane is None:
                return ("reset expects a pane number %s, or no argument for every pane\n"
                        % self.pane_range_text())
            pane.pending_fresh = True
            pane.kill_session()
            GLib.timeout_add(80, self._finish_fresh_pane, pane)
        else:
            self.fresh_sessions(confirm=False)
        return None

    def _verb_all(self, args):
        try:
            command, positions = self.split_fill(args)
        except ValueError as exc:
            return "all expects valid pane positions: %s\n" % exc
        if not command.strip():
            return "all expects a command, e.g. all htop\n"
        if command.startswith("-"):
            return "all expects a command, not an option: %s\n" % command
        if positions:
            panes = [self.pane_arg(str(position), "all") for position in positions]
            panes = [pane for pane in panes if pane is not None]
            if not panes:
                return "all expects positions in %s\n" % self.pane_range_text()
            for pane in panes:
                pane.restart(pane_cmd_for_cli(pane.name, command))
            self.update_status()
        else:
            self.populate_all(command)
        return None

    def _verb_fit(self, _args):
        self.fit_window()

    def _verb_focus(self, args):
        position = self.position_arg(args[0] if args else None, "focus")
        if position is None:
            return "focus expects a pane number %s\n" % self.pane_range_text()
        self.focus_slot(position)
        return None

    def _verb_swap(self, args):
        return self.dispatch_swap(args, move=False)

    def _verb_move(self, args):
        return self.dispatch_swap(args, move=True)

    def _verb_send(self, args):
        return self.dispatch_send("send", args)

    def _verb_run(self, args):
        return self.dispatch_send("run", args)

    def _verb_notify(self, args):
        text = " ".join(args).strip() or "Notifications work"
        self.toast(text, kind="info", detail="control socket")
        self.notify_desktop(self.active, "Cli Griderator", text)

    def _verb_keymap(self, _args):
        return json.dumps({"keymap": self.keymap,
                           "actions": {name: {"label": label, "key": hint}
                                       for name, label, hint in
                                       [(n, lb, h) for n, lb, h, _c in self.action_table()]}},
                          indent=2) + "\n"

    def _verb_palette(self, _args):
        self.show_palette()

    def _verb_doctor(self, _args):
        rows = doctor.checks(CONFIG_PATH)
        return json.dumps({"checks": rows, "summary": doctor.summary(rows)}) + "\n"

    def _verb_quit(self, _args):
        GLib.idle_add(self.quit)

    def _verb_state(self, _args):
        return self.dispatch_state()

    def _verb_status(self, _args):
        return self.status_json()

    def position_arg(self, arg, verb):
        """1-based position from a command argument, or None when it is not one."""
        try:
            position = int(arg)
        except (TypeError, ValueError):
            return None
        return position if 1 <= position <= len(self.order) else None

    def pane_arg(self, arg, verb):
        """Pane for a command argument, or the focused pane when there is none."""
        if arg is None:
            return self.active
        position = self.position_arg(arg, verb)
        return self.order[position - 1] if position else None

    def split_fill(self, args):
        """(command, positions) for `all`, accepting --panes 1,3 first."""
        command, spec = split_fill_args(args)
        if not spec:
            return command, []
        positions = control.pane_positions(spec, len(self.order))
        return command, positions or [self.position_of(self.active) + 1]

    def dispatch_swap(self, args, move=False):
        if len(args) < 2:
            return "%s expects two positions, e.g. %s 1 6\n" % (
                "move" if move else "swap", "move" if move else "swap")
        try:
            a, b = int(args[0]), int(args[1])
        except ValueError:
            return "%s expects two positions, e.g. 1 6\n" % ("move" if move else "swap")
        if not (1 <= a <= len(self.order) and 1 <= b <= len(self.order)):
            return "positions are %s\n" % self.pane_range_text()
        if move:
            pane = self.order.pop(a - 1)
            self.order.insert(b - 1, pane)
            self.after_count_change()
        else:
            self.swap_slots(self.order[a - 1].slot, self.order[b - 1].slot)
        self.mark_state_dirty()
        return "ok\n"

    def dispatch_rename(self, args):
        if len(args) < 2:
            return "rename expects a pane number and a name\n"
        pane = self.pane_arg(args[0], "rename")
        if pane is None:
            return "rename expects a pane number %s\n" % self.pane_range_text()
        pane.set_name(" ".join(args[1:]))
        return "ok\n"

    def dispatch_send(self, verb, args):
        """send types text into a pane; run adds Enter. Writing to the pty is the
        same call either way."""
        if len(args) < 2:
            return "%s expects a pane number and text\n" % verb
        pane = self.pane_arg(args[0], verb)
        if pane is None:
            return "%s expects a pane number %s\n" % (verb, self.pane_range_text())
        rest = args[1:]
        enter = verb == "run" or "--enter" in rest
        text = " ".join(item for item in rest if item != "--enter")
        if not pane.send_text(text, enter=enter):
            return "cannot write to pane %d\n" % (self.position_of(pane) + 1)
        if str(pane.state) != state.STATE_RUNNING:
            pane.set_state(state.STATE_RUNNING)
        self.add_event("send", pane=pane.name, text=text[:200], enter=enter)
        return "ok\n"

    def dispatch_dump(self, args):
        if not args:
            return "dump expects a pane number\n"
        pane = self.pane_arg(args[0], "dump")
        if pane is None:
            return "dump expects a pane number %s\n" % self.pane_range_text()
        lines = 40
        if "--lines" in args:
            index = args.index("--lines")
            if index + 1 < len(args):
                lines = max(1, as_int(args[index + 1], 40))
        text = pane.dump_text(lines)
        return text if text.endswith("\n") or not text else text + "\n"

    def dispatch_workspace(self, args):
        """ws, ws list, ws <name>, ws new NAME, ws save, ws rm NAME, ws rename A B."""
        action = args[0] if args else "list"
        store = read_store()
        if action in ("list", ""):
            names = workspace.workspace_names(store)
            return json.dumps({"active": self.workspace_name(), "workspaces": names}) + "\n"
        if action in ("new", "add", "duplicate", "dup"):
            if len(args) < 2:
                return "ws %s expects a name\n" % action
            source = args[2] if len(args) > 2 else None
            copy_from = source or (None if action == "new" else self.workspace_name())
            updated = workspace.add_workspace(store, args[1], copy_from=copy_from)
            if len(workspace.workspace_names(updated)) == len(workspace.workspace_names(store)):
                return "a workspace named %s already exists\n" % args[1]
            set_store(updated)
            self.save_workspaces()
            return "ok\n"
        if action in ("rm", "remove", "delete"):
            if len(args) < 2:
                return "ws rm expects a name\n"
            updated = workspace.remove_workspace(store, args[1])
            if len(workspace.workspace_names(updated)) == len(workspace.workspace_names(store)):
                return "cannot remove %s: unknown workspace, or the last one\n" % args[1]
            set_store(updated)
            if workspace.active_workspace(updated)["name"] != self.workspace_name():
                return self.dispatch_workspace([workspace.active_workspace(updated)["name"]])
            return "ok\n"
        if action == "rename":
            if len(args) < 3:
                return "ws rename expects the old name and the new name\n"
            updated = workspace.rename_workspace(store, args[1], args[2])
            if workspace.workspace_names(updated) == workspace.workspace_names(store):
                return "cannot rename %s\n" % args[1]
            set_store(updated)
            self.save_workspaces()
            self.update_status()
            return "ok\n"
        if action == "save":
            save_config(self.config)
            return "ok\n"
        if action in ("next", "prev"):
            self.switch_workspace_step(1 if action == "next" else -1)
            return "%s\n" % self.workspace_name()
        chosen = self.switch_workspace(action)
        if chosen is None:
            return "unknown workspace: %s\n" % action
        return "%s\n" % chosen

    def save_workspaces(self):
        """Write the cached store back to disk after a workspace edit."""
        write_store(read_store())

    def dispatch_layout(self, args):
        if args and args[0] in ("--list", "list"):
            return "\n".join(layout.shape_names()) + "\n"
        if not args:
            return "%s\n" % self.layout_shape
        chosen = self.set_layout(args[0])
        return "%s\n" % chosen

    def dispatch_stack(self, args):
        if args and args[0] in ("--clear", "clear", "none"):
            self.unstack_all()
            return "ok\n"
        if len(args) < 2:
            return "stack expects two pane numbers, e.g. stack 1 2\n"
        positions = []
        for item in args:
            position = self.position_arg(item, "stack")
            if position is None:
                return "stack expects pane numbers in %s\n" % self.pane_range_text()
            positions.append(position)
        self.config["stack"] = [positions]
        save_config(self.config)
        self.after_count_change()
        return "ok\n"

    def dispatch_theme(self, args):
        if not args or args[0] in ("list", "--list"):
            return "\n".join("%s%s" % (name, " (active)" if name == active_theme_name() else "")
                             for name in art.theme_names()) + "\n"
        wanted = str(args[0]).strip().lower()
        if wanted not in art.theme_names():
            return "unknown theme %s; choose one of: %s\n" % (args[0], ", ".join(art.theme_names()))
        chosen = self.apply_theme(wanted)
        return "%s\n" % chosen

    def dispatch_state(self):
        rows = {self.position_of(pane) + 1: {
            "name": pane.name,
            "state": pane.state,
            "badge": state.state_badge(pane.state),
            "cwd": short_path(pane.cwd),
            "branch": pane.branch or None,
            "waiting": state.needs_input(pane.state),
        } for pane in self.order}
        return json.dumps({"waiting": self.waiting_count, "panes": rows}) + "\n"

    def dispatch_find(self, args):
        """Find text in every pane, without opening a dialog."""
        needle = " ".join(args).strip()
        if not needle:
            return "find expects text\n"
        lowered = needle.lower()
        hits = []
        for pane in self.order:
            text = pane.visible_text() or ""
            for line in text.splitlines():
                if lowered in line.lower():
                    hits.append({"pane": self.position_of(pane) + 1,
                                 "name": pane.name, "line": line.strip()[:200]})
                    break
        return json.dumps({"pattern": needle, "panes": hits}) + "\n"

    def dispatch_log(self, args):
        """The tail of the window's log, for bug reports."""
        count = max(1, as_int(args[0], 40) if args else 40)
        try:
            with open(LOG_PATH) as handle:
                lines = handle.readlines()
        except OSError:
            return "(no log yet)\n"
        return "".join(lines[-count:])

    def is_maximized(self):
        gdk_window = self.win.get_window()
        return bool(gdk_window and gdk_window.get_state() & Gdk.WindowState.MAXIMIZED)

    def surface_size(self):
        gdk_window = self.win.get_window()
        return [gdk_window.get_width(), gdk_window.get_height()] if gdk_window else None

    def status_json(self):
        wa, scale = self.monitor_workarea()
        alloc = self.grid.get_allocation()
        panes = []
        for pane in (self.order if not self.zoom else [self.active]):
            panes.append({
                "position": self.position_of(pane) + 1,
                "slot": pane.slot,
                "color": pane_color(THEME, self.position_of(pane)),
                "name": pane.name,
                "cmd": pane.cmd,
                "cwd": short_path(pane.cwd),
                "branch": pane.branch or None,
                "cols": pane.term.get_column_count(),
                "rows": pane.term.get_row_count(),
                "state": pane.state,
                "mark": pane.mark,
                "elapsed": state.elapsed_text(
                    (GLib.get_monotonic_time() - pane.started_at) / 1e6
                    if pane.started_at else None),
                "session": tmux_target(pane.cmd, pane.name),
                "exited": pane.exited,
                "focused": pane is self.active,
            })
        return json.dumps({
            "layout": self.layout_shape,
            "grid": "%dx%d" % layout.shape_for(len(self.order), self.layout_shape),
            "stacks": self.config.get("stack") or [],
            "version": VERSION,
            "theme": active_theme_name(),
            "workspace": self.workspace_name(),
            "pane_count": len(self.panes),
            "waiting": self.waiting_count,
            "zoom": self.zoom,
            "visible": not self.hidden,
            "screen": [wa.width, wa.height],
            "grid_px": [alloc.width, alloc.height],
            "window_px": list(self.win.get_size()),
            "toolbar_px": self.toolbar.get_allocated_height(),
            "maximized": self.is_maximized(),
            "surface_px": self.surface_size(),
            "headerbar_px": [self.toolbar.get_allocated_width(), self.toolbar.get_allocated_height()],
            "scroller_px": [self.scroller.get_allocated_width(), self.scroller.get_allocated_height()],
            "font_size": self.font_size,
            "rss_mb": resident_mb(),
            "char_px": [self.active.term.get_char_width(), self.active.term.get_char_height()],
            "predicted": getattr(self, "predicted", None),
            "trace": getattr(self, "_trace", []),
            "scale_factor": scale,
            "panes": panes,
        }) + "\n"

    def run_self_test(self):
        print(self.status_json().strip())
        self.quit()
        return False

    def quit(self, *args):
        self.quitting = True
        try:
            self.save_state()
        except Exception:
            pass
        for holder in list(self.subscribers) + list(self.waiters):
            self.drop_holder(holder)
        if self.socket_service:
            self.socket_service.close()
        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
        except OSError:
            pass
        Gtk.main_quit()
        return False

    def on_destroy(self, *args):
        self.quit()


# Verb → handler. Aliases share a method. Help/events/wait never reach dispatch:
# on_request intercepts them. Returning None from a handler becomes "ok\n".
_VERB_HANDLERS = {
    "show": CliGrid._verb_show, "raise": CliGrid._verb_show,
    "hide": CliGrid._verb_hide, "toggle": CliGrid._verb_toggle,
    "zoom": CliGrid._verb_zoom,
    "panes": CliGrid._verb_panes, "windows": CliGrid._verb_panes,
    "remove": CliGrid._verb_remove, "close-window": CliGrid._verb_remove,
    "restart": CliGrid._verb_restart,
    "reset": CliGrid._verb_reset, "fresh": CliGrid._verb_reset, "new": CliGrid._verb_reset,
    "all": CliGrid._verb_all, "fill": CliGrid._verb_all, "run-all": CliGrid._verb_all,
    "fit": CliGrid._verb_fit, "focus": CliGrid._verb_focus,
    "swap": CliGrid._verb_swap, "move": CliGrid._verb_move,
    "rename": CliGrid.dispatch_rename,
    "send": CliGrid._verb_send, "run": CliGrid._verb_run,
    "dump": CliGrid.dispatch_dump,
    "ws": CliGrid.dispatch_workspace, "workspace": CliGrid.dispatch_workspace,
    "layout": CliGrid.dispatch_layout, "stack": CliGrid.dispatch_stack,
    "theme": CliGrid.dispatch_theme,
    "state": CliGrid._verb_state,
    "find": CliGrid.dispatch_find, "notify": CliGrid._verb_notify,
    "keymap": CliGrid._verb_keymap, "palette": CliGrid._verb_palette,
    "doctor": CliGrid._verb_doctor, "log": CliGrid.dispatch_log,
    "status": CliGrid._verb_status,
    "quit": CliGrid._verb_quit,
}


GLOBAL_FLAGS = ("--json", "--self-test", "--version", "--help", "-h")
NON_STARTING_VERBS = ("help", "version", "events", "watch", "status", "state", "log",
                      "doctor", "dump", "send", "run", "find", "keymap")


def request_timeout(request):
    """A wait holds the connection as long as its own timeout needs."""
    parsed = control.parse(request)
    if parsed["verb"] != "wait" or parsed["error"]:
        return 5
    seconds = control.parse_wait(parsed["args"])["timeout"]
    return max(5.0, seconds + 6.0)


def send_command(request, quiet=False, timeout=None):
    """Return (running, reply); raise on uncertain delivery, never retry it."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout or request_timeout(request))
    try:
        try:
            client.connect(SOCKET_PATH)
        except (FileNotFoundError, ConnectionRefusedError):
            return False, ""
        client.sendall((request + "\n").encode())
        chunks = []
        while True:
            data = client.recv(65536)
            if not data:
                break
            chunks.append(data)
        return True, b"".join(chunks).decode("utf-8", "replace")
    except OSError as exc:
        if not quiet:
            sys.stderr.write("cligrid: %s\n" % exc)
        raise
    finally:
        client.close()


def format_event_line(line, out_color=True):
    """One line of the events stream, as a time, a kind, a pane and the details."""
    try:
        event = json.loads(line)
    except ValueError:
        return line
    if not isinstance(event, dict):
        return line
    when = time.strftime("%H:%M:%S", time.localtime(float(event.get("time") or 0)))
    kind = str(event.get("kind") or "?")
    kinds = {"bell": art.COLORS["warn"], "exit": art.COLORS["error"],
             "state": art.COLORS["accent"], "wait": art.COLORS["ok"]}
    color = kinds.get(kind, art.COLORS["dim"])
    details = " ".join("%s=%s" % (key, event[key]) for key in sorted(event)
                       if key not in ("kind", "seq", "time"))
    return "%s %s  %s" % (
        art.paint(when, art.COLORS["dim"], out_color),
        art.paint(kind.ljust(9), color, out_color, bold=True),
        details,
    )


def stream_events(request):
    """Print the events stream until interrupted. Used by `cligrid events`."""
    out_color = art.color_enabled(sys.stdout)
    err_color = art.color_enabled(sys.stderr)
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(SOCKET_PATH)
    except OSError:
        sys.stderr.write(art.error("not running; start the grid with cligrid", err_color))
        return 1
    client.sendall((request + "\n").encode())
    buffer = b""
    try:
        while True:
            data = client.recv(65536)
            if not data:
                break
            buffer += data
            while b"\n" in buffer:
                line, _sep, buffer = buffer.partition(b"\n")
                text = line.decode("utf-8", "replace").strip()
                if text:
                    sys.stdout.write(format_event_line(text, out_color) + "\n")
                    sys.stdout.flush()
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        client.close()
    return 0


def verb_help(verb, out_color):
    """The usage lines for one verb, from the help table. An alias such as
    `fresh` or `watch` shows the rows of the verb it stands for."""
    verb = art.canonical_verb(verb)
    rows = [(spec, desc) for _title, items in art.HELP_SECTIONS for spec, desc in items
            if verb in [part.strip().split()[0] for part in spec.split("|")
                        if part.strip()]]
    if not rows:
        return art.error("no such command: %s; try cligrid --help" % verb, out_color), 1
    width = max(len(spec) for spec, _desc in rows)
    lines = ["", "  %s" % art.paint(verb, art.COLORS["accent"], out_color, bold=True)]
    for spec, desc in rows:
        lines.append("    %s%s%s" % (spec, " " * (width - len(spec) + 3),
                                     art.paint(desc, art.COLORS["dim"], out_color)))
    return "\n".join(lines) + "\n\n", 0


def drop_panes_flag(parts):
    """(parts without any --panes SPEC, that SPEC). Accepts --panes SPEC and
    --panes=SPEC, so a stray flag can never survive into a pane command."""
    kept = []
    spec = ""
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--panes":
            if index + 1 < len(parts):
                spec = spec or parts[index + 1]
            index += 2
            continue
        if part.startswith("--panes="):
            spec = spec or part.split("=", 1)[1]
            index += 1
            continue
        kept.append(part)
        index += 1
    return kept, spec


def strip_panes_flag(text):
    """A stored command line with a leaked `--panes SPEC` taken back out.

    `--panes` belongs to `cligrid all`, not to a pane: tmux refuses the flag,
    the pane exits at once, and because the command is saved the grid stays
    broken across restarts. Configs written by an older version are healed
    through this on load.
    """
    raw = str(text or "").strip()
    if "--panes" not in raw:
        return raw
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    kept, _spec = drop_panes_flag(parts)
    return " ".join(kept)


def heal_panes_flag(cfg):
    """Take a leaked `--panes` back out of a stored fill command and its panes.

    A grid that once ran `cligrid all --panes 1,3 <command>` saved the flag into
    fill_cmd and into every pane command, so it came up with every pane dead.
    Load-time healing means such a config repairs itself instead of staying
    broken. True when anything changed.
    """
    changed = False
    fill = str(cfg.get("fill_cmd") or "")
    clean = strip_panes_flag(fill)
    if clean != fill:
        cfg["fill_cmd"] = clean
        changed = True
    for pane in cfg.get("panes") or []:
        if not isinstance(pane, dict):
            continue
        cmd = str(pane.get("cmd") or "")
        cleaned = strip_panes_flag(cmd)
        if cleaned != cmd:
            pane["cmd"] = cleaned
            changed = True
    return changed


def split_fill_args(args):
    """(command, position spec) from `all --panes 1,3 htop` style arguments.

    The CLI hands over argv tokens; the control layer hands `all` its whole
    payload as one still-quoted token. Both shapes lose --panes and are joined
    the same way, so `all --panes 1 'bash -l'` saves the same bare command the
    plain `all bash -l` would.
    """
    rest = list(args)
    if len(rest) == 1:
        try:
            rest = shlex.split(rest[0])
        except ValueError:
            rest = rest[0].split()
    has_selection = any(token == "--panes" or token.startswith("--panes=") for token in rest)
    rest, spec = drop_panes_flag(rest)
    if has_selection and not spec.strip():
        raise ValueError("--panes requires a non-empty selection")
    return " ".join(rest), spec


def event_kinds():
    """The event kinds the window can emit, re-exported for the CLI help."""
    return control.event_kinds()


def quiet_vte_warnings():
    """VTE warns on every text read about an attributes array that GI allocates
    for us. The text still comes back, so keep the log clean."""
    try:
        GLib.log_set_handler(
            "Vte",
            GLib.LogLevelFlags.LEVEL_WARNING | GLib.LogLevelFlags.FLAG_RECURSION,
            lambda _domain, _level, _message, _data: None,
        )
    except Exception:
        pass


def trim_log(path, keep=LOG_KEEP_BYTES):
    """Keep only the tail of an append-only log, cut at a line boundary. Runs
    once per launch so the file cannot grow without bound. True when trimmed."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= keep:
        return False
    try:
        with open(path, "rb") as handle:
            handle.seek(size - keep)
            tail = handle.read()
        cut = tail.find(b"\n")
        tail = tail[cut + 1:] if cut >= 0 else tail
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(b"[cligrid: earlier log trimmed]\n" + tail)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def log_to_file():
    """The window process sends GTK noise to the log, not to the launching terminal."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        trim_log(LOG_PATH)
        fd = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(fd, 2)
        os.close(fd)
    except OSError:
        pass


def install_signal_handlers(app):
    """Quit cleanly on SIGINT and SIGTERM. GLib's unix signal sources run on
    the main loop, unlike signal.signal handlers, which only run once Python
    bytecode executes again and so would wait for the next timer tick."""
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, _on_signal, app)
        except (AttributeError, TypeError, ValueError):
            signal.signal(signum, lambda *_args: app.quit())


def _on_signal(app):
    app.quit()
    return False


def _print_status(data, out_color):
    sys.stdout.write(art.format_status(data, out_color))
    return 0


def _print_wait(data, out_color):
    if data.get("matched"):
        print("%s pane %s matched: %s" % (
            art.paint("✓", art.COLORS["ok"], out_color),
            data.get("name"), (data.get("line") or "").strip()))
        return 0
    print("%s no match in pane %s before the timeout" % (
        art.paint("✗", art.COLORS["warn"], out_color), data.get("name")))
    return 1


def _print_state(data, _out_color):
    waiting = data.get("waiting", 0)
    print("%d pane%s waiting" % (waiting, "" if waiting == 1 else "s"))
    for position, row in sorted(data.get("panes", {}).items(),
                                key=lambda item: int(item[0])):
        print("  %2s %-14s %-8s %-10s %s" % (
            position, row.get("name", ""), row.get("state", ""),
            row.get("branch") or "", row.get("cwd") or ""))
    return 0


def _print_find(data, _out_color):
    hits = data.get("panes", [])
    if not hits:
        print("no pane matches %s" % data.get("pattern"))
        return 1
    for hit in hits:
        print("  %2s %-12s %s" % (hit.get("pane"), hit.get("name"), hit.get("line")))
    return 0


def _print_workspaces(data, _out_color):
    for name in data.get("workspaces", []):
        marker = "*" if name == data.get("active") else " "
        print("%s %s" % (marker, name))
    return 0


def _print_doctor(data, _out_color):
    summary = data.get("summary", {})
    print("%d ok, %d to fix" % (summary.get("ok", 0), summary.get("failed", 0)))
    for row in data.get("checks", []):
        print("  %s %-22s %s" % ("✓" if row.get("ok") else "✗",
                                 row.get("name"), row.get("detail") or ""))
        if not row.get("ok") and row.get("fix"):
            print("      fix: %s" % row["fix"])
    return 0


def _print_keymap(data, _out_color):
    for key, action in sorted(data.get("keymap", {}).items()):
        print("  %-12s %s" % (key, action))
    return 0


_STRUCTURED_REPLIES = {
    "status": _print_status, "wait": _print_wait, "state": _print_state,
    "find": _print_find, "ws": _print_workspaces, "workspace": _print_workspaces,
    "doctor": _print_doctor, "keymap": _print_keymap,
}


def print_reply(args, flags, reply, out_color, err_color):
    """Show a running instance's reply: status as a summary, ok as a check,
    usage messages as errors. Plain text when output is not a terminal."""
    text = (reply or "ok\n").strip()
    verb = args[0] if args else ""
    printer = _STRUCTURED_REPLIES.get(verb) if "--json" not in flags else None
    if printer is not None:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            return printer(data, out_color)
    if text == "ok":
        print(art.paint("✓ ok", art.COLORS["ok"], out_color) if out_color else "ok")
        return 0
    if text.startswith(("unknown command", "cannot", "positions are", "no such", "refused")) \
            or " expects " in text:
        sys.stderr.write(art.error(text, err_color))
        return 1
    print(text)
    return 0


def _offline_reset(args, err_color):
    """Wipe selected sessions when the grid is not running. None = start the
    window afterwards; an int is the process exit status."""
    cfg = load_config()
    positions = None
    if len(args) > 1:
        try:
            number = int(args[1])
            if not 1 <= number <= len(cfg["panes"]):
                raise ValueError
            positions = [number]
        except ValueError:
            sys.stderr.write(art.error("reset expects a pane number 1-%d" % len(cfg["panes"]),
                                       err_color))
            return 1
    wipe_configured_sessions(cfg, positions)
    return None


def _offline_fill(args, err_color):
    """Apply `all` to the config when the grid is not running."""
    try:
        command, spec = split_fill_args(args[1:])
    except ValueError as exc:
        sys.stderr.write(art.error("all expects valid pane positions: %s" % exc, err_color))
        return 1
    if not command.strip():
        sys.stderr.write(art.error("all expects a command, e.g. cligrid all htop", err_color))
        return 1
    if command.startswith("-"):
        sys.stderr.write(art.error(
            "all expects a command, not an option: %s" % command, err_color))
        return 1
    cfg = load_config()
    try:
        positions = control.pane_positions(spec or "all", len(cfg["panes"]))
        if not positions:
            raise ValueError("focused requires a running grid")
    except ValueError as exc:
        sys.stderr.write(art.error("all expects valid pane positions: %s" % exc, err_color))
        return 1
    if not spec or spec == "all":
        cfg["fill_cmd"] = command
    original = {"panes": [dict(pane) for pane in cfg["panes"]]}
    for position in positions:
        i = position - 1
        pane = cfg["panes"][i]
        name = pane.get("name") or default_pane(i)["name"]
        pane["name"] = name
        pane["cmd"] = pane_cmd_for_cli(name, command)
    save_config(cfg)
    wipe_configured_sessions(original, positions)
    return None


def offline_action(args, err_color):
    """What to do when no grid is listening. None means start one; 1 is an error."""
    if not args or args[0] in ("show", "raise"):
        return None
    if args[0] in ("reset", "fresh", "new"):
        return _offline_reset(args, err_color)
    if args[0] in ("all", "fill", "run-all"):
        return _offline_fill(args, err_color)
    sys.stderr.write(art.error("not running; start the grid with cligrid", err_color))
    return 1


def main(argv):
    tokens = list(argv[1:])
    flags = [token for token in tokens if token in GLOBAL_FLAGS]
    args = [token for token in tokens if token not in GLOBAL_FLAGS]
    out_color = art.color_enabled(sys.stdout)
    err_color = art.color_enabled(sys.stderr)

    if "--version" in flags or args[:1] == ["version"]:
        print("%s %s" % (APP, VERSION))
        return 0
    if "--help" in flags or "-h" in flags or args[:1] == ["help"] and len(args) < 2:
        sys.stdout.write(art.help_text(VERSION, out_color))
        return 0
    if args[:1] == ["help"]:
        text, code = verb_help(args[1], out_color)
        (sys.stdout if code == 0 else sys.stderr).write(text)
        return code
    if args and args[0] not in control.VERBS:
        sys.stderr.write(art.error(
            "unknown command: %s; try cligrid --help" % args[0], err_color))
        return 1
    if args[:1] in (["events"], ["watch"]):
        return stream_events(" ".join(args))
    if args[:1] == ["doctor"]:
        rows = doctor.checks(CONFIG_PATH)
        counts = doctor.summary(rows)
        print(doctor.report_text(rows))
        print("%d ok, %d to fix" % (counts["ok"], counts["failed"]))
        return 0 if counts["failed"] == 0 else 1

    # `cligrid reset --force 2`: the flag rides after the verb so the running
    # grid's guard sees it, and it never reaches a pane command offline.
    args, forced = control.split_force(args)
    request_tokens = [shlex.quote(token) for token in args] or ["show"]
    if forced:
        request_tokens.insert(1, "--force")
    request = " ".join(request_tokens)
    try:
        running, reply = send_command(request, quiet=True)
    except OSError as exc:
        sys.stderr.write(art.error("control connection failed: %s; command was not retried" % exc, err_color))
        return 1
    if running:
        return print_reply(args, flags, reply, out_color, err_color)
    code = offline_action(args, err_color)
    if code is not None:
        return code

    self_test = "--self-test" in flags
    if not self_test:
        log_to_file()
        quiet_vte_warnings()
    app = CliGrid(self_test=self_test)
    install_signal_handlers(app)
    Gtk.main()
    return 0


def main_entry():
    """Console script entry point, for `pipx install .` or the installed script."""
    return main(sys.argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
