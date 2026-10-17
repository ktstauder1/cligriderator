"""Isolated diagnostics tests; no desktop or external programs required."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cligrid_doctor as doctor


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for patcher in (
            patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home),
                                   "XDG_RUNTIME_DIR": str(self.home),
                                   "XDG_SESSION_TYPE": "wayland"}),
            patch.object(doctor.shutil, "which", side_effect=lambda name: name),
            patch.object(doctor.subprocess, "run", side_effect=self.command),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = self.home / "config.json"

    def command(self, argv, **kwargs):
        self.assertLessEqual(kwargs["timeout"], 3)
        output = doctor.DEFAULT_FONT if argv[0] == "fc-match" else "version 1"
        return subprocess.CompletedProcess(argv, 0, output, "")

    def rows(self):
        return {row["name"]: row for row in doctor.checks(self.config)}

    def test_summary_counts(self):
        self.assertEqual(doctor.summary([{"ok": True}, {"ok": False}, {"ok": True}]),
                         {"ok": 2, "failed": 1})

    def test_empty_summary_and_report(self):
        self.assertEqual(doctor.summary([]), {"ok": 0, "failed": 0})
        self.assertEqual(doctor.report_text([]), "0 ok, 0 failed")

    def test_failing_row_has_fix(self):
        row = self.rows()["launcher"]
        self.assertFalse(row["ok"])
        self.assertTrue(row["fix"])
        self.assertIn("Fix:", doctor.report_text([row]))

    def test_report_alignment(self):
        rows = [{"name": name, "ok": ok, "detail": "DETAIL", "fix": "repair"}
                for name, ok in (("a", True), ("long name", False))]
        lines = doctor.report_text(rows).splitlines()
        self.assertEqual(lines[0].index("DETAIL"), lines[1].index("DETAIL"))
        self.assertEqual(lines[2].index("Fix:"), lines[1].index("DETAIL"))

    def test_report_strips_color_and_newlines(self):
        row = {"name": "test", "ok": False, "detail": "\x1b[31mred\nline", "fix": "x\ny"}
        report = doctor.report_text([row])
        self.assertNotIn("\x1b", report)
        self.assertIn("red line", report)

    def test_missing_config_uses_defaults(self):
        self.assertTrue(self.rows()["config"]["ok"])
        self.assertTrue(self.rows()["font"]["ok"])

    def test_invalid_config(self):
        for text in ("{broken", "[]", "null"):
            with self.subTest(text=text):
                self.config.write_text(text)
                self.assertFalse(self.rows()["config"]["ok"])

    def test_configured_font_and_fallback(self):
        self.config.write_text(json.dumps({"font": "Missing Font"}))
        self.assertFalse(self.rows()["font"]["ok"])

    def test_missing_programs(self):
        with patch.object(doctor.shutil, "which", return_value=None):
            rows = self.rows()
        for name in ("gi", "tmux", "font"):
            self.assertFalse(rows[name]["ok"])

    def test_timeout_and_os_errors_never_escape(self):
        for error in (subprocess.TimeoutExpired("probe", 3), OSError("denied")):
            with patch.object(doctor.subprocess, "run", side_effect=error):
                rows = self.rows()
            self.assertEqual(len(rows), 10)
            self.assertFalse(rows["gi"]["ok"])

    def test_icons_require_every_size(self):
        root = self.home / ".local/share/icons/hicolor"
        for relative in ("scalable/apps/cligrid.svg", "16x16/apps/cligrid.png",
                         "24x24/apps/cligrid.png", "32x32/apps/cligrid.png"):
            path = root / relative
            path.parent.mkdir(parents=True)
            path.touch()
        self.assertTrue(self.rows()["icons"]["ok"])
        path.unlink()
        self.assertFalse(self.rows()["icons"]["ok"])

    def test_runtime_and_session_failure(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.home / "missing"),
                                     "XDG_SESSION_TYPE": "tty"}):
            rows = self.rows()
        self.assertFalse(rows["runtime"]["ok"])
        self.assertFalse(rows["session"]["ok"])

    def test_nonzero_command(self):
        with patch.object(doctor.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 1, "", "failed")):
            self.assertFalse(self.rows()["tmux"]["ok"])

    def test_gtk_next_typelibs_is_a_plain_sentence(self):
        text = doctor.gtk_next_typelibs()
        self.assertTrue(text.startswith("Gtk "))
        self.assertNotIn("\x1b", text)

    def test_gi_row_mentions_the_gtk4_probe(self):
        self.assertIn("Gtk", self.rows()["gi"]["detail"])


if __name__ == "__main__":
    unittest.main()
