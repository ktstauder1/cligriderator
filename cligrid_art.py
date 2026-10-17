#!/usr/bin/env python3
"""ASCII logo, colors and terminal output for Cli Griderator.

No GTK here: the welcome banner runs at the start of every new pane session,
so it has to start instantly. Script use:
    cligrid_art.py banner --pane N --name NAME [--color HEX] [--gradient HEX,HEX,HEX] [--dim HEX]
"""

import argparse
import json
import os
import shlex
import shutil
import sys

LOGO = (
    "╔═╗╦  ╦  ╔═╗╦═╗╦╔╦╗╔═╗╦═╗╔═╗╔╦╗╔═╗╦═╗",
    "║  ║  ║  ║ ╦╠╦╝║ ║║║╣ ╠╦╝╠═╣ ║ ║ ║╠╦╝",
    "╚═╝╩═╝╩  ╚═╝╩╚═╩═╩╝╚═╝╩╚═╩ ╩ ╩ ╚═╝╩╚═",
)
LOGO_WIDTH = max(len(row) for row in LOGO)
WORDMARK = "▦ CLI GRIDERATOR"

# The Griderator palette fallbacks, used when the app passes no theme colors.
GRADIENT = ("#d8be86", "#ffad70", "#43e0df")
COLORS = {
    "accent": "#d8be86",
    "fg": "#e6e8eb",
    "dim": "#9ca3ae",
    "ok": "#a0f5bd",
    "warn": "#ffad70",
    "error": "#ff718b",
}
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
TMUX_VALUE_FLAGS = {"-s", "-t", "-n", "-c", "-x", "-y", "-e", "-F", "-f"}

# Built-in themes for `cligrid theme set`. The palette is the sixteen-colour
# terminal palette; the rest is chrome. Font, padding and scrollback stay with
# whatever kitty.conf says, so a theme swap never touches the terminal prefs.
#
# "griderator" is the application's own scheme and the default: near-black charcoal with
# luminous spectrum colors and a golden accent, rather than any published terminal
# theme. Later entries are stock palettes kept for people who prefer them.
THEME_PRESETS = {
    "griderator": {
        "foreground": "#e6e8eb", "background": "#15171b", "cursor": "#d8be86",
        "cursor_text": "#15171b", "selection_bg": "#353b45", "selection_fg": "#ffffff",
        "accent": "#d8be86", "border": "#30353d", "url": "#43e0df",
        "surface": "#1d2025", "bg_deep": "#0d0f12", "muted": "#9ca3ae",
        "palette": [
            "#1d2025", "#ff718b", "#6ee7a0", "#d8be86",
            "#66b7ff", "#d69aff", "#43e0df", "#d0d4da",
            "#9ca3ae", "#ff9aac", "#a0f5bd", "#ffe49a",
            "#9ed5ff", "#edbcff", "#98f6ee", "#ffffff",
        ],
    },
    "tokyo-night": {
        "foreground": "#c0caf5", "background": "#1a1b26", "cursor": "#c0caf5",
        "cursor_text": "#1a1b26", "selection_bg": "#33467c", "selection_fg": "#c0caf5",
        "accent": "#7aa2f7", "border": "#292e42", "url": "#7dcfff",
        "palette": [
            "#15161e", "#f7768e", "#9ece6a", "#e0af68",
            "#7aa2f7", "#bb9af7", "#7dcfff", "#a9b1d6",
            "#414868", "#f7768e", "#9ece6a", "#e0af68",
            "#7aa2f7", "#bb9af7", "#7dcfff", "#c0caf5",
        ],
    },
    "gruvbox-dark": {
        "foreground": "#ebdbb2", "background": "#282828", "cursor": "#ebdbb2",
        "cursor_text": "#282828", "selection_bg": "#504945", "selection_fg": "#ebdbb2",
        "accent": "#458588",
        "palette": [
            "#282828", "#cc241d", "#98971a", "#d79921",
            "#458588", "#b16286", "#689d6a", "#a89984",
            "#928374", "#fb4934", "#b8bb26", "#fabd2f",
            "#83a598", "#d3869b", "#8ec07c", "#ebdbb2",
        ],
    },
    "gruvbox-light": {
        "foreground": "#3c3836", "background": "#fbf1c7", "cursor": "#3c3836",
        "cursor_text": "#fbf1c7", "selection_bg": "#ebdbb2", "selection_fg": "#3c3836",
        "accent": "#076678",
        "palette": [
            "#fbf1c7", "#cc241d", "#98971a", "#d79921",
            "#458588", "#b16286", "#689d6a", "#7c6f64",
            "#928374", "#9d0006", "#79740e", "#b57614",
            "#076678", "#8f3f71", "#427b58", "#3c3836",
        ],
    },
    "nord": {
        "foreground": "#d8dee9", "background": "#2e3440", "cursor": "#d8dee9",
        "cursor_text": "#2e3440", "selection_bg": "#434c5e", "selection_fg": "#d8dee9",
        "accent": "#88c0d0",
        "palette": [
            "#3b4252", "#bf616a", "#a3be8c", "#ebcb8b",
            "#81a1c1", "#b48ead", "#88c0d0", "#e5e9f0",
            "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b",
            "#81a1c1", "#b48ead", "#8fbcbb", "#eceff4",
        ],
    },
    "dracula": {
        "foreground": "#f8f8f2", "background": "#282a36", "cursor": "#f8f8f2",
        "cursor_text": "#282a36", "selection_bg": "#44475a", "selection_fg": "#f8f8f2",
        "accent": "#bd93f9",
        "palette": [
            "#21222c", "#ff5555", "#50fa7b", "#f1fa8c",
            "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",
            "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5",
            "#d6acff", "#ff92df", "#a4ffff", "#ffffff",
        ],
    },
    "catppuccin-mocha": {
        "foreground": "#cdd6f4", "background": "#1e1e2e", "cursor": "#f5e0dc",
        "cursor_text": "#1e1e2e", "selection_bg": "#585b70", "selection_fg": "#cdd6f4",
        "accent": "#89b4fa",
        "palette": [
            "#45475a", "#f38ba8", "#a6e3a1", "#f9e2af",
            "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
            "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af",
            "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8",
        ],
    },
    "solarized-dark": {
        "foreground": "#839496", "background": "#002b36", "cursor": "#93a1a1",
        "cursor_text": "#002b36", "selection_bg": "#073642", "selection_fg": "#93a1a1",
        "accent": "#268bd2",
        "palette": [
            "#073642", "#dc322f", "#859900", "#b58900",
            "#268bd2", "#d33682", "#2aa198", "#eee8d5",
            "#002b36", "#cb4b16", "#586e75", "#657b83",
            "#839496", "#6c71c4", "#93a1a1", "#fdf6e3",
        ],
    },
    "solarized-light": {
        "foreground": "#657b83", "background": "#fdf6e3", "cursor": "#586e75",
        "cursor_text": "#fdf6e3", "selection_bg": "#eee8d5", "selection_fg": "#586e75",
        "accent": "#268bd2",
        "palette": [
            "#eee8d5", "#dc322f", "#859900", "#b58900",
            "#268bd2", "#d33682", "#2aa198", "#073642",
            "#fdf6e3", "#cb4b16", "#93a1a1", "#839496",
            "#657b83", "#6c71c4", "#586e75", "#002b36",
        ],
    },
    # Black/white/yellow, for a screen reader or a bright room. Chrome and
    # terminal colours both sit well above 7:1 against the background.
    "high-contrast": {
        "foreground": "#ffffff", "background": "#000000", "cursor": "#ffff00",
        "cursor_text": "#000000", "selection_bg": "#ffffff", "selection_fg": "#000000",
        "accent": "#ffff00", "border": "#ffffff", "url": "#00ffff",
        "surface": "#000000", "bg_deep": "#000000", "muted": "#c0c0c0",
        "palette": [
            "#000000", "#ff6b6b", "#5cff8d", "#ffff00",
            "#6cb6ff", "#ff7ad9", "#00ffff", "#ffffff",
            "#c0c0c0", "#ff9a9a", "#9affb8", "#ffff9a",
            "#9ed5ff", "#ffb0e8", "#9affff", "#ffffff",
        ],
    },
}

THEME_NAMES = tuple(THEME_PRESETS)
KITTY_THEME_NAMES = ("kitty", "inherit", "auto")


def theme_preset(name):
    """Theme dict for a preset name, with the terminal prefs the caller supplies.
    Unknown names, and the kitty names, return None so the caller keeps its own."""
    key = str(name or "").strip().lower()
    if not key or key in KITTY_THEME_NAMES:
        return None
    preset = THEME_PRESETS.get(key)
    if preset is None:
        return None
    theme = json.loads(json.dumps(preset))
    theme["padding"] = 10
    theme["copy_on_select"] = True
    return theme


def theme_names():
    """Every accepted value for the theme setting, in display order."""
    return KITTY_THEME_NAMES[:1] + THEME_NAMES


def color_enabled(stream):
    """Color for terminals only; NO_COLOR turns it off, CLICOLOR_FORCE on."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    return bool(getattr(stream, "isatty", None) and stream.isatty())


def rgb(hex_color):
    text = str(hex_color or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return rgb(COLORS["fg"])


def paint(text, hex_color, enabled=True, bold=False):
    if not enabled or not text:
        return text
    r, g, b = rgb(hex_color)
    return "%s\x1b[38;2;%d;%d;%dm%s%s" % (BOLD if bold else "", r, g, b, text, RESET)


def gradient_at(stops, t):
    """Hex color at t in [0, 1] along evenly spaced color stops."""
    points = [rgb(stop) for stop in stops] or [rgb(GRADIENT[0])]
    if len(points) == 1:
        return "#%02x%02x%02x" % points[0]
    span = min(1.0, max(0.0, t)) * (len(points) - 1)
    i = min(int(span), len(points) - 2)
    local = span - i
    return "#%02x%02x%02x" % tuple(
        round(a + (b - a) * local) for a, b in zip(points[i], points[i + 1]))


def logo_lines(stops=GRADIENT, enabled=True):
    """The logo, shaded left to right across the gradient stops."""
    if not enabled:
        return list(LOGO)
    last = max(1, LOGO_WIDTH - 1)
    return ["".join(ch if ch == " " else paint(ch, gradient_at(stops, col / last))
                    for col, ch in enumerate(row)) for row in LOGO]


def banner(pane, name, color=None, stops=GRADIENT, dim=None, width=None, enabled=True):
    """Welcome text for a new pane session; falls back to a one-line wordmark."""
    color = color or COLORS["accent"]
    dim = dim or COLORS["dim"]
    width = width or shutil.get_terminal_size((80, 24)).columns
    if width >= LOGO_WIDTH + 4:
        art = ["  " + line for line in logo_lines(stops, enabled)]
    else:
        art = ["  " + paint(WORDMARK, stops[0] if stops else color, enabled, bold=True)]
    detail = "session %s · Ctrl+Shift+/ for shortcuts" % name
    if width < len(detail) + 14:
        detail = "session %s" % name
    info = "  %s %s  %s" % (
        paint("●", color, enabled),
        paint("pane %s" % pane, color, enabled, bold=True),
        paint(detail, dim, enabled),
    )
    return "\n".join([""] + art + [info, ""]) + "\n"


def split_tmux_new_session(parts):
    """(tmux head, command tail) for `tmux new-session ... [command]`, else None.
    Bundled flags such as -As are not parsed, so they return None."""
    if len(parts) < 2 or os.path.basename(parts[0]) != "tmux" or parts[1] not in ("new-session", "new"):
        return None
    i = 2
    while i < len(parts) and parts[i].startswith("-"):
        if len(parts[i]) != 2:
            return None
        i += 2 if parts[i] in TMUX_VALUE_FLAGS else 1
    if i > len(parts):
        return None
    return parts[:i], parts[i:]


def command_summary(cmd):
    """What a pane runs, for humans: the command inside its tmux session."""
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        return cmd or "shell"
    split = split_tmux_new_session(parts)
    if split is None:
        return " ".join(parts) or "shell"
    tail = split[1]
    if len(tail) >= 3 and os.path.basename(tail[0]) in ("bash", "sh") and tail[1] in ("-lc", "-c"):
        return tail[2]
    return " ".join(tail) or "shell"


HELP_SECTIONS = (
    ("WINDOW", (
        ("show | hide | toggle", "show, hide or flip the grid"),
        ("fit", "re-apply the window fit"),
        ("quit", "quit; tmux sessions keep running"),
    )),
    ("PANES", (
        ("focus N", "focus pane N"),
        ("zoom [N|off]", "fill the window with one pane"),
        ("swap A B", "swap the panes in positions A and B"),
        ("move A B", "move pane A into position B"),
        ("panes N", "set the pane count, 1-20"),
        ("rename N NAME", "rename pane N and its session"),
        ("remove [N]", "remove pane N, or the focused pane"),
    )),
    ("SESSIONS", (
        ("restart [N]", "reconnect a pane; its session is kept"),
        ("reset [N]", "end a pane's session, or every session"),
        ("all <command>", "run one command in every pane"),
        ("all --panes 1,3 <command>", "run it only in those panes"),
        ("reset --force | all --force ...", "from inside a pane: override the guard"),
        ("send N <text>", "type text into pane N, newline with --enter"),
        ("run N <command>", "type a command into pane N and press enter"),
    )),
    ("READ", (
        ("dump N [--lines K]", "the last K lines of pane N, scrollback included"),
        ("wait N --until RE", "block until pane N matches, then reply"),
        ("events | watch", "stream pane events as JSON lines until interrupted"),
        ("events --kinds bell,exit", "only those kinds; --since SEQ replays"),
        ("find TEXT", "search every pane and list the matches"),
        ("state", "what every pane is doing: idle, running, waiting"),
        ("log [K]", "the last K lines of the window's log"),
    )),
    ("LAYOUT", (
        ("layout [name]", "set the grid shape: auto, 2x2, 3x2, master, 1x6"),
        ("layout --list", "every shape"),
        ("stack A B ...", "put panes in one cell as tabs; stack --clear to undo"),
    )),
    ("WORKSPACES", (
        ("ws [name]", "switch to a workspace, or list them"),
        ("ws new NAME", "a workspace with the current panes"),
        ("ws save", "save the current panes into the active workspace"),
        ("ws rm NAME", "remove a workspace"),
        ("ws rename OLD NEW", "rename a workspace"),
    )),
    ("THEME", (
        ("theme [name]", "switch theme; no name lists them"),
        ("theme list", "the built in themes plus kitty"),
    )),
    ("DESK", (
        ("palette", "open the command palette (Ctrl+Shift+P)"),
        ("notify <text>", "show a toast in the grid, and a desktop notification"),
        ("keymap", "the active shortcuts and every action they can run"),
    )),
    ("INFO", (
        ("status [--json]", "window size, panes, state, memory"),
        ("doctor", "check the environment and say what to fix"),
        ("help [verb]", "this text, or one verb in detail"),
        ("version", "the version; also --version"),
        ("--version | --help", ""),
    )),
)

# Spellings the protocol accepts for the same action. `cligrid help fresh`
# shows the reset rows; the man page lists every alias beside its verb.
VERB_ALIASES = {
    "raise": "show", "windows": "panes", "close-window": "remove",
    "fresh": "reset", "new": "reset", "fill": "all", "run-all": "all",
    "workspace": "ws", "watch": "events",
}


def canonical_verb(verb):
    """The verb a help lookup should use: aliases fold onto their verb."""
    return VERB_ALIASES.get(verb, verb)


def documented_verbs():
    """Every verb that appears in HELP_SECTIONS, aliases included, so a test
    can hold the help table to the protocol's verb list."""
    verbs = set()
    for _title, items in HELP_SECTIONS:
        for spec, _desc in items:
            for part in spec.split("|"):
                head = part.strip().split()
                if head and not head[0].startswith("-"):
                    verbs.add(head[0])
    for alias, verb in VERB_ALIASES.items():
        if verb in verbs:
            verbs.add(alias)
    return verbs


def _spec(text, enabled):
    words = []
    for word in text.split(" "):
        if word == "|":
            words.append(paint(word, COLORS["dim"], enabled))
        elif word.replace("-", "").isalpha() and word.lower() == word:
            words.append(paint(word, COLORS["fg"], enabled, bold=True))
        else:
            words.append(paint(word, COLORS["accent"], enabled))
    return " ".join(words)


def help_text(version, enabled=True):
    lines = [""] + ["  " + line for line in logo_lines(GRADIENT, enabled)]
    lines[-1] += "  " + paint(version, COLORS["dim"], enabled)
    lines += [
        "  " + paint("Up to twenty terminals in one window, in the grid's own palette.",
                     COLORS["dim"], enabled),
        "",
        "  %s    %s" % (paint("USAGE", COLORS["accent"], enabled, bold=True),
                        _spec("cligrid [command]", enabled)),
        "           " + paint("With no command, start the grid or bring it forward.", COLORS["dim"], enabled),
    ]
    width = max(len(spec) for _title, rows in HELP_SECTIONS for spec, _desc in rows)
    for title, rows in HELP_SECTIONS:
        lines += ["", "  " + paint(title, COLORS["accent"], enabled, bold=True)]
        for spec, desc in rows:
            pad = " " * (width - len(spec) + 3)
            lines.append("    %s%s%s" % (_spec(spec, enabled), pad, paint(desc, COLORS["dim"], enabled)))
    return "\n".join(lines) + "\n\n"


def format_status(data, enabled=True):
    """A readable summary of `cligrid status` JSON."""
    panes = data.get("panes", [])
    header_px = data.get("headerbar_px") or [0, 0]
    body_px = data.get("scroller_px") or [0, 0]
    if header_px[0] and body_px[1]:
        size = "%d×%d" % (header_px[0], body_px[1] + header_px[1])
    else:
        size = "%d×%d" % tuple((data.get("window_px") or [0, 0])[:2])
    count = data.get("pane_count", len(panes))
    facts = [size, "%spt" % data.get("font_size", "?"), "%d pane%s" % (count, "" if count == 1 else "s")]
    if data.get("workspace"):
        facts.append(str(data["workspace"]))
    if data.get("layout") and data["layout"] != "auto":
        facts.append("layout %s" % data["layout"])
    if data.get("theme"):
        facts.append("theme %s" % data["theme"])
    if data.get("rss_mb"):
        facts.append("%.0f MB" % float(data["rss_mb"]))
    if data.get("zoom"):
        facts.append("zoomed")
    if data.get("visible") is False:
        facts.append("hidden")
    lines = ["%s %s   %s" % (
        paint("●", COLORS["ok"], enabled),
        paint("running", COLORS["ok"], enabled, bold=True),
        paint(" · ".join(facts), COLORS["dim"], enabled),
    )]
    waiting = [p for p in panes if p.get("state") == "waiting"]
    if waiting:
        names = ", ".join(str(p.get("name", "")) for p in waiting[:4])
        lines.append("  %s %s" % (
            paint("waiting:", COLORS["warn"], enabled, bold=True),
            paint(names, COLORS["fg"], enabled)))
    name_w = max([len(p.get("name", "")) for p in panes] + [4])
    size_w = max([len("%s×%s" % (p.get("cols"), p.get("rows"))) for p in panes] + [5])
    state_colors = {"running": COLORS["ok"], "waiting": COLORS["warn"],
                    "failed": COLORS["error"], "exited": COLORS["error"]}
    for pane in panes:
        color = pane.get("color") or COLORS["accent"]
        marker = paint("▸", color, enabled) if pane.get("focused") else " "
        grid = "%s×%s" % (pane.get("cols"), pane.get("rows"))
        state = str(pane.get("state") or "")
        badge = " " * 7
        if state:
            badge = paint(state[:7].ljust(7), state_colors.get(state, COLORS["dim"]), enabled)
        row = "  %s %s  %s  %s  %s %s  %s" % (
            marker,
            paint("%2d" % pane.get("position", 0), color, enabled, bold=True),
            paint(pane.get("name", "").ljust(name_w), COLORS["fg"], enabled),
            paint(grid.rjust(size_w), COLORS["dim"], enabled),
            badge,
            paint(command_summary(pane.get("cmd", "")), COLORS["fg"], enabled),
            paint(pane.get("cwd") or "", COLORS["dim"], enabled),
        )
        if pane.get("exited"):
            row += "  " + paint("exited", COLORS["error"], enabled, bold=True)
        lines.append(row)
    return "\n".join(lines) + "\n"


def error(message, enabled=True):
    return "%s %s\n" % (paint("cligrid:", COLORS["error"], enabled, bold=True), message)


def main(argv):
    parser = argparse.ArgumentParser(prog="cligrid_art.py")
    sub = parser.add_subparsers(dest="command", required=True)
    shown = sub.add_parser("banner", help="print the welcome banner for a new pane")
    shown.add_argument("--pane", default="1")
    shown.add_argument("--name", default="g1")
    shown.add_argument("--color")
    shown.add_argument("--gradient")
    shown.add_argument("--dim")
    args = parser.parse_args(argv[1:])
    try:
        stops = tuple(args.gradient.split(",")) if args.gradient else GRADIENT
        sys.stdout.write(banner(args.pane, args.name, args.color, stops, args.dim,
                                enabled=color_enabled(sys.stdout)))
        sys.stdout.flush()
    except Exception:
        pass  # a banner must never keep a pane from starting
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
