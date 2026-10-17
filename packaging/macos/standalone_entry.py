"""PyInstaller entry point; the normal Linux/source entry point stays unchanged."""

import os
from pathlib import Path
import sys

import cligrid_art
import cligrid_doctor


def configure_macos_runtime():
    """Keep VTE's Darwin fdwalk stack allocation below the thread stack limit."""
    if sys.platform != "darwin":
        return
    import resource

    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft_limit == resource.RLIM_INFINITY or soft_limit > 65536:
        resource.setrlimit(resource.RLIMIT_NOFILE, (65536, hard_limit))


def helper(argv):
    """Handle the app's Python subprocesses without starting another window."""
    if len(argv) > 1 and Path(argv[1]).name == "cligrid_art.py":
        return cligrid_art.main(argv[1:])
    if len(argv) > 1 and argv[1] == "-c":
        # sys.executable is the frozen launcher, not a Python interpreter.
        # Only the two known diagnostic programs are accepted here.
        if len(argv) < 3 or argv[2] not in (cligrid_doctor.GI_PROBE, cligrid_doctor.PANGO_FAMILIES):
            raise ValueError("Unknown bundled Python diagnostic")
        previous = sys.argv
        try:
            sys.argv = ["-c", *argv[3:]]
            exec(argv[2], {"__name__": "__main__"})
        finally:
            sys.argv = previous
        return 0
    return None


def smoke():
    """Exercise bundled tmux and a real VTE child; failure blocks DMG creation."""
    import subprocess
    import uuid
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import GLib, Gtk, Vte

    session = "cligrid-check-" + uuid.uuid4().hex
    tmux = ["tmux", "-L", session, "-f", "/dev/null"]
    try:
        subprocess.run([*tmux, "new-session", "-d", "-s", "check", "/bin/sleep 30"],
                       check=True, timeout=10)
        subprocess.run([*tmux, "has-session", "-t", "check"], check=True, timeout=10)
    finally:
        subprocess.run([*tmux, "kill-server"], check=False, timeout=10)

    window = Gtk.Window()
    window.set_default_size(640, 240)
    terminal = Vte.Terminal()
    terminal.set_size(80, 24)
    window.add(terminal)
    window.show_all()
    window.present()
    state = {"ok": False, "status": None, "text": ""}

    def changed(widget):
        text = widget.get_text_format(Vte.Format.TEXT) or ""
        if "CLIGRID_VTE_OK" in text:
            state["text"] = text

    def exited(widget, status):
        changed(widget)
        state["status"] = status
        state["ok"] = status == 0 and "CLIGRID_VTE_OK" in state["text"]
        Gtk.main_quit()

    def expired():
        Gtk.main_quit()
        return False

    terminal.connect("child-exited", exited)
    terminal.connect("contents-changed", changed)
    terminal.spawn_async(
        Vte.PtyFlags.DEFAULT, str(Path.home()),
        ["/bin/sh", "-c", "/bin/sleep 1; printf 'CLIGRID_VTE_OK\\n'; /bin/sleep 2"],
        [f"{key}={value}" for key, value in os.environ.items()],
        GLib.SpawnFlags.DEFAULT, None, None, -1, None, None,
    )
    timer = GLib.timeout_add_seconds(15, expired)
    Gtk.main()
    if state["ok"]:
        GLib.source_remove(timer)
    window.destroy()
    if not state["ok"]:
        raise RuntimeError(f"Bundled VTE did not produce shell output: {state!r}")
    print("CLIGRID_BUNDLE_OK")
    return 0


def main():
    configure_macos_runtime()
    if getattr(sys, "frozen", False):
        resources = Path(sys._MEIPASS)
        os.environ["PATH"] = str(resources / "bin") + os.pathsep + os.environ.get(
            "PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        os.environ["TERMINFO_DIRS"] = str(resources / "share/terminfo") + ":/usr/share/terminfo"
    if sys.argv[1:] == ["--bundle-smoke"]:
        return smoke()
    result = helper(sys.argv)
    if result is not None:
        return result
    import cligrid
    if getattr(sys, "frozen", False):
        cligrid.ICON_PATH = str(Path(sys._MEIPASS) / "icons/cligrid.svg")
        cligrid.DEFAULT_CONFIG["font"] = "Menlo"
    return cligrid.main_entry()


if __name__ == "__main__":
    sys.exit(main())
