"""Portability tests: the macOS paths in cligrid.py and cligrid_doctor.py.

Linux behaviour is covered by the other suites; these tests pin down the macOS
branches without needing a Mac, and assert that they stay inactive elsewhere.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import cligrid
import cligrid_doctor as doctor


class AppleScriptNotificationTests(unittest.TestCase):
    def test_quotes_and_backslashes_are_escaped(self):
        self.assertEqual(cligrid.applescript_string('say "hi" \\ bye'),
                         '"say \\"hi\\" \\\\ bye"')

    def test_newlines_are_flattened(self):
        self.assertEqual(cligrid.applescript_string("one\ntwo\r\nthree"), '"one two three"')

    def test_not_used_off_macos(self):
        with patch.object(cligrid.sys, "platform", "linux"), \
             patch.object(cligrid.subprocess, "Popen") as popen:
            self.assertFalse(cligrid.osascript_notify("Pane 1", "bell"))
        popen.assert_not_called()

    def test_on_macos_it_calls_osascript(self):
        with patch.object(cligrid.sys, "platform", "darwin"), \
             patch.object(cligrid.subprocess, "Popen") as popen:
            self.assertTrue(cligrid.osascript_notify("Pane 1 · g1", "htop rang its bell"))
        argv = popen.call_args[0][0]
        self.assertEqual(argv[:2], ["osascript", "-e"])
        self.assertIn("display notification", argv[2])
        self.assertIn("htop rang its bell", argv[2])
        self.assertIn("Pane 1 · g1", argv[2])

    def test_missing_osascript_is_not_an_error(self):
        with patch.object(cligrid.sys, "platform", "darwin"), \
             patch.object(cligrid.subprocess, "Popen", side_effect=OSError("not found")):
            self.assertFalse(cligrid.osascript_notify("Pane 1", "bell"))


class ResidentMemoryTests(unittest.TestCase):
    def test_linux_reads_proc(self):
        value = cligrid.resident_mb()
        self.assertIsInstance(value, float)
        self.assertGreater(value, 0.0)

    def test_macos_reports_ru_maxrss_in_bytes(self):
        fake = types.ModuleType("resource")
        fake.RUSAGE_SELF = 0
        fake.getrusage = lambda _who: types.SimpleNamespace(ru_maxrss=157_286_400)
        with patch.object(cligrid.sys, "platform", "darwin"), \
             patch.dict(sys.modules, {"resource": fake}), \
             patch("builtins.open", side_effect=OSError("no /proc on macOS")):
            self.assertEqual(cligrid.resident_mb(), 150.0)

    def test_no_measurement_returns_none(self):
        fake = types.ModuleType("resource")
        fake.RUSAGE_SELF = 0
        fake.getrusage = lambda _who: types.SimpleNamespace(ru_maxrss=0)
        with patch.object(cligrid.sys, "platform", "darwin"), \
             patch.dict(sys.modules, {"resource": fake}), \
             patch("builtins.open", side_effect=OSError("no /proc")):
            self.assertIsNone(cligrid.resident_mb())


class SessionProbeTests(unittest.TestCase):
    """The display fallback covers WSLg, which sets a display but no session type."""

    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in
                      ("XDG_SESSION_TYPE", "DISPLAY", "WAYLAND_DISPLAY")}
        self.addCleanup(self.restore)
        for patcher in (
            patch.object(doctor.shutil, "which", side_effect=lambda name: name),
            patch.object(doctor.subprocess, "run", side_effect=lambda argv, **kwargs:
                          subprocess.CompletedProcess(argv, 0, "version 1", "")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def restore(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def session_row(self, environ):
        for key in ("XDG_SESSION_TYPE", "DISPLAY", "WAYLAND_DISPLAY"):
            os.environ.pop(key, None)
        os.environ.update(environ)
        rows = {row["name"]: row for row in doctor.checks()}
        return rows["session"]

    def test_session_type_wins(self):
        self.assertTrue(self.session_row({"XDG_SESSION_TYPE": "wayland"})["ok"])

    def test_display_without_session_type_passes(self):
        row = self.session_row({"DISPLAY": ":0"})
        self.assertTrue(row["ok"])
        self.assertIn(":0", row["detail"])

    def test_wayland_display_without_session_type_passes(self):
        self.assertTrue(self.session_row({"WAYLAND_DISPLAY": "wayland-0"})["ok"])

    def test_no_display_and_no_session_type_fails(self):
        self.assertFalse(self.session_row({})["ok"])

    def test_a_tty_session_still_fails_even_with_a_display(self):
        self.assertFalse(self.session_row({"XDG_SESSION_TYPE": "tty",
                                           "DISPLAY": ":0"})["ok"])


class MacOSDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for patcher in (
            patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home),
                                    "XDG_RUNTIME_DIR": str(self.home)}),
            patch.object(doctor.shutil, "which", side_effect=lambda name: name),
            patch.object(doctor.subprocess, "run", side_effect=self.command),
            patch.object(doctor.sys, "platform", "darwin"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = self.home / "config.json"

    def command(self, argv, **kwargs):
        self.assertLessEqual(kwargs["timeout"], 3)
        if argv[0] == "tmux":
            return subprocess.CompletedProcess(argv, 0, "tmux 3.7c", "")
        if argv[0] == "brew":
            return subprocess.CompletedProcess(argv, 0, "/opt/homebrew", "")
        if argv[0] == sys.executable:
            script = argv[2]
            if "PANGO_FAMILIES" in script or "PangoCairo" in script:
                return subprocess.CompletedProcess(argv, 0, "exact", "")
            return subprocess.CompletedProcess(argv, 0, "Gtk 3.0, Vte 2.91", "")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    def rows(self, config_path=None):
        return {row["name"]: row for row in doctor.checks(config_path or self.config)}

    def test_report_has_ten_macos_rows(self):
        rows = self.rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual(set(rows), {"python", "gi", "tmux", "config", "font",
                                     "homebrew", "launcher", "bundle", "runtime",
                                     "session"})

    def test_linux_only_rows_are_absent(self):
        rows = self.rows()
        for name in ("icons", "desktop"):
            self.assertNotIn(name, rows)

    def test_missing_launcher_and_bundle_point_at_the_installer(self):
        rows = self.rows()
        for name in ("launcher", "bundle"):
            self.assertFalse(rows[name]["ok"])
            self.assertIn("install-macos.sh", rows[name]["fix"])

    def test_installed_launcher_and_bundle_pass(self):
        launcher = self.home / "bin/cligrid"
        launcher.parent.mkdir(parents=True)
        launcher.touch()
        bundle = self.home / doctor.MACOS_BUNDLE
        bundle.parent.mkdir(parents=True)
        bundle.touch()
        rows = self.rows()
        self.assertTrue(rows["launcher"]["ok"])
        self.assertTrue(rows["bundle"]["ok"])

    def test_macos_launcher_accepts_homebrew_prefix(self):
        """install-macos.sh writes ~/.local/bin/cligrid, not ~/bin."""
        launcher = self.home / ".local/bin/cligrid"
        launcher.parent.mkdir(parents=True)
        launcher.touch()
        rows = self.rows()
        self.assertTrue(rows["launcher"]["ok"])
        self.assertIn(".local/bin/cligrid", rows["launcher"]["detail"])

    def test_homebrew_failure_is_reported(self):
        with patch.object(doctor.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 1, "", "no brew")):
            rows = self.rows()
        self.assertFalse(rows["homebrew"]["ok"])
        self.assertTrue(rows["homebrew"]["fix"])

    def test_report_text_works_on_the_macos_rows(self):
        report = doctor.report_text(list(self.rows().values()))
        self.assertIn("failed", report)
        self.assertIn("homebrew", report)

    def test_config_row_reads_the_given_file(self):
        self.config.write_text(json.dumps({"font": "Menlo"}))
        rows = self.rows()
        self.assertTrue(rows["config"]["ok"])
        self.assertIn(str(self.config), rows["config"]["detail"])


class MacOSInstallerUiTests(unittest.TestCase):
    def test_finder_path_has_progress_and_a_stop_dialog(self):
        text = Path(__file__).resolve().parent.joinpath(
            "packaging/macos/install-macos.sh").read_text(encoding="utf-8")
        self.assertIn("display notification", text)
        self.assertIn("display dialog", text)
        self.assertIn("with icon stop", text)
        self.assertIn("command -v osascript", text)
        self.assertIn("CLIGRID_NO_UI", text)
        self.assertIn("as_quote", text)


if __name__ == "__main__":
    unittest.main()
