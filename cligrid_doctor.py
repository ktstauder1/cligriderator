"""Best-effort, plain-text diagnostics without importing the GUI in this process."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


DEFAULT_FONT = "JetBrainsMono Nerd Font"
ICON_SIZES = (16, 24, 32)
TIMEOUT = 3
MACOS_BUNDLE = "Applications/Cli Griderator.app/Contents/MacOS/cligrid"
# install-macos.sh defaults to ~/.local/bin; Linux install.sh uses ~/bin.
MACOS_LAUNCHERS = (".local/bin/cligrid", "bin/cligrid")


def first_existing(paths):
    """Return the first existing file path, or the first candidate if none exist."""
    found = next((path for path in paths if path.is_file()), None)
    return found if found is not None else paths[0]

# Pango is what the grid itself measures fonts with, so the font probe asks
# Pango rather than a fontconfig tool: macOS has no fc-match unless fontconfig
# was pulled in as a build dependency.
PANGO_FAMILIES = (
    "import sys\n"
    "import gi\n"
    "gi.require_version('Pango', '1.0')\n"
    "gi.require_version('PangoCairo', '1.0')\n"
    "from gi.repository import PangoCairo\n"
    "context = PangoCairo.font_map_get_default().create_context()\n"
    "families = {f.get_name().casefold() for f in context.list_families()}\n"
    "print('exact' if sys.argv[1].casefold() in families else 'missing')\n"
)
GI_PROBE = (
    "import gi; gi.require_version('Gtk', '3.0'); "
    "gi.require_version('Vte', '2.91'); from gi.repository import Gtk, Vte; "
    "print('Gtk 3.0, Vte 2.91')"
)


def default_config_path():
    """The config file the grid reads: XDG_CONFIG_HOME, else ~/.config."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "cligrid/config.json"


def read_config_into(config_path, config):
    """Read the config into `config` in place; (ok, detail) for a probe row."""
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.exists():
        return True, f"{path}: absent (defaults; created on first change)"
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        return False, f"{path}: expected a JSON object"
    config.update(value)
    return True, str(path)


def _plain(value):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    return " ".join("".join(c for c in text if c.isprintable() or c.isspace()).split())


def _run(command):
    executable = shutil.which(command[0])
    if not executable:
        return False, command[0] + " not found"
    result = subprocess.run(
        [executable, *command[1:]], capture_output=True, text=True, timeout=TIMEOUT, check=False,
    )
    return result.returncode == 0, _plain(result.stdout or result.stderr) or "no output"


def gtk_next_typelibs():
    """Whether Gtk 4 / Vte 3.91 typelibs sit on disk. The grid still runs 3.0."""
    names = ("Gtk-4.0.typelib", "Vte-3.91.typelib")
    roots = [path for path in os.environ.get("GI_TYPELIB_PATH", "").split(":") if path]
    roots += [
        "/usr/lib/girepository-1.0",
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
        "/usr/lib64/girepository-1.0",
        "/opt/homebrew/lib/girepository-1.0",
        "/usr/local/lib/girepository-1.0",
    ]
    found = {name: any(Path(root, name).is_file() for root in roots) for name in names}
    if all(found.values()):
        return "Gtk 4.0 and Vte 3.91 typelibs present (grid still runs Gtk 3.0)"
    missing = [name.split("-")[0] for name, ok in found.items() if not ok]
    return "Gtk 3.0 in use; %s typelib not installed" % ", ".join(missing)


def _gi_probe():
    ok, detail = _run([sys.executable, "-c", GI_PROBE])
    return ok, ("%s; %s" % (detail, gtk_next_typelibs())) if ok else detail


def checks(config_path=None) -> list[dict]:
    """Return ten diagnostic rows; failed probes include a one-line suggested fix."""
    if sys.platform == "darwin":
        return _macos_checks(config_path)
    rows = []
    config = {}

    def probe(name, action, fix):
        try:
            ok, detail = action()
        except Exception as exc:
            ok, detail = False, str(exc) or type(exc).__name__
        rows.append({"name": name, "ok": bool(ok), "detail": _plain(detail),
                     "fix": "" if ok else _plain(fix)})

    def read_config():
        return read_config_into(config_path, config)

    def font_check():
        font = config.get("font", DEFAULT_FONT)
        if not isinstance(font, str) or not font.strip():
            return False, "configured font must be a non-empty string"
        ok, family = _run(["fc-match", "--format=%{family}", "--", font])
        matched = any(font.casefold() == f.strip().casefold() for f in family.split(","))
        return ok and matched, f"{font}: {family}"

    def icons_check():
        root = Path.home() / ".local/share/icons/hicolor"
        paths = [root / "scalable/apps/cligrid.svg"] + [
            root / f"{size}x{size}/apps/cligrid.png" for size in ICON_SIZES
        ]
        missing = [str(path) for path in paths if not path.is_file()]
        return not missing, "missing: " + ", ".join(missing) if missing else str(root)

    def runtime_check():
        path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK), str(path)

    def session_check():
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session in ("wayland", "x11"):
            return True, session
        if not session:
            # WSLg and similar sessions set a display without XDG_SESSION_TYPE.
            display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
            if display:
                return True, "display %s (XDG_SESSION_TYPE is unset)" % display
        return False, session or "XDG_SESSION_TYPE is unset and no DISPLAY"

    probe("python", lambda: (sys.version_info >= (3, 10), sys.version.split()[0]),
          "Use Python 3.10 or newer.")
    probe("gi", _gi_probe,
          "Install python3-gi, gir1.2-gtk-3.0 and gir1.2-vte-2.91 for this Python.")
    probe("tmux", lambda: _run(["tmux", "-V"]), "Install tmux and put it on PATH.")
    probe("config", read_config, "Repair the config JSON object or move it aside for defaults.")
    probe("font", font_check,
          "Install the configured font or choose an installed font in settings.")
    probe("icons", icons_check, "Run install.sh to install all icon sizes.")
    probe("launcher", lambda: ((Path.home() / "bin/cligrid").is_file(),
          str(Path.home() / "bin/cligrid")), "Run install.sh to install ~/bin/cligrid.")
    probe("desktop", lambda: (
          (Path.home() / ".local/share/applications/cligrid.desktop").is_file(),
          str(Path.home() / ".local/share/applications/cligrid.desktop")),
          "Run install.sh to install the desktop entry.")
    probe("runtime", runtime_check, "Set XDG_RUNTIME_DIR to a writable directory you own.")
    probe("session", session_check, "Run from an X11 or Wayland desktop session.")
    return rows


def summary(rows) -> dict:
    """Return counts of successful and failed diagnostic rows."""
    good = sum(bool(row.get("ok")) for row in rows)
    return {"ok": good, "failed": len(rows) - good}


def _macos_checks(config_path=None) -> list[dict]:
    """The same ten-row report with the checks macOS needs instead of the
    Linux ones: Homebrew formulas and the application bundle replace the
    hicolor icon set and the .desktop entry, which macOS does not use."""
    rows = []
    config = {}
    frozen = bool(getattr(sys, "frozen", False))
    contents = Path(sys.executable).parent.parent
    resources = Path(getattr(sys, "_MEIPASS", contents / "Resources"))
    reinstall = "Replace Cli Griderator.app with a fresh copy from the disk image."

    def probe(name, action, fix):
        try:
            ok, detail = action()
        except Exception as exc:
            ok, detail = False, str(exc) or type(exc).__name__
        rows.append({"name": name, "ok": bool(ok), "detail": _plain(detail),
                     "fix": "" if ok else _plain(fix)})

    def font_check():
        font = config.get("font", "Menlo" if frozen else DEFAULT_FONT)
        if not isinstance(font, str) or not font.strip():
            return False, "configured font must be a non-empty string"
        ok, result = _run([sys.executable, "-c", PANGO_FAMILIES, font])
        return ok and result == "exact", f"{font}: {result}"

    def launcher_check():
        path = (Path(sys.executable) if frozen else
                first_existing([Path.home() / relative for relative in MACOS_LAUNCHERS]))
        return path.is_file(), str(path)

    def bundle_check():
        path = contents / "Info.plist" if frozen else Path.home() / MACOS_BUNDLE
        return path.is_file(), str(path)

    def runtime_check():
        path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK), str(path)

    probe("python", lambda: (sys.version_info >= (3, 10), sys.version.split()[0]),
          "Use Python 3.10 or newer.")
    probe("gi", _gi_probe,
          reinstall if frozen else "brew install gtk+3 vte3 pygobject3, then run the grid with the "
          "Homebrew Python that has the bindings.")
    tmux = str(resources / "bin/tmux") if frozen else "tmux"
    probe("tmux", lambda: _run([tmux, "-V"]), reinstall if frozen else "brew install tmux.")
    probe("config", lambda: read_config_into(config_path, config),
          "Repair the config JSON object or move it aside for defaults.")
    probe("font", font_check,
          "Choose an installed font in settings." if frozen else
          "Install the font (brew install --cask font-jetbrains-mono-nerd-font) "
          "or choose an installed font in settings.")
    if frozen:
        probe("bundled-runtime", lambda: (resources.is_dir(), str(resources)), reinstall)
    else:
        probe("homebrew", lambda: _run(["brew", "--prefix"]),
              "Install Homebrew from https://brew.sh.")
    probe("launcher", launcher_check, reinstall if frozen else "Run packaging/macos/install-macos.sh.")
    probe("bundle", bundle_check, reinstall if frozen else "Run packaging/macos/install-macos.sh.")
    probe("runtime", runtime_check, "Set XDG_RUNTIME_DIR to a writable directory you own.")
    probe("session", lambda: (True, "Aqua (macOS)"), "")
    return rows


def report_text(rows) -> str:
    """Return aligned plain text with failed-row remedies and a count summary."""
    width = max((len(_plain(row["name"])) for row in rows), default=0)
    lines = []
    for row in rows:
        status = "OK" if row["ok"] else "FAIL"
        lines.append(f"{status:<4}  {_plain(row['name']):<{width}}  {_plain(row['detail'])}")
        if not row["ok"]:
            lines.append(" " * (width + 8) + "Fix: " + _plain(row["fix"]))
    counts = summary(rows)
    lines.append(f"{counts['ok']} ok, {counts['failed']} failed")
    return "\n".join(lines)
