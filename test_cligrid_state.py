#!/usr/bin/env python3
"""Contract tests for pane activity classification and filesystem helpers."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Keep the standalone test run within the two-file workspace scope.
sys.dont_write_bytecode = True

import cligrid_state as state


class ClassificationTests(unittest.TestCase):
    def test_exited_overrides_all_activity(self):
        for status, expected in ((0, "exited"), (None, "exited"), (1, "failed"), (-9, "failed")):
            with self.subTest(status=status):
                self.assertEqual(state.classify_state("Allow", "codex", True, status, 0), expected)

    def test_exit_status_alone_does_not_mean_exited(self):
        self.assertEqual(state.classify_state("", exit_status=1), "idle")

    def test_waiting_overrides_recent_output_and_shell(self):
        self.assertEqual(state.classify_state("Continue?", "bash", output_age=0), "waiting")

    def test_recent_output_overrides_shell_and_unknown_command(self):
        for age in (0, 1.5):
            for command in (None, "bash"):
                with self.subTest(age=age, command=command):
                    self.assertEqual(state.classify_state("", command, output_age=age), "running")
        self.assertEqual(state.classify_state("", "bash", output_age=1.5001), "idle")

    def test_shells_are_idle_without_recent_output(self):
        for command in ("bash", "zsh", "sh", "fish", "dash", "tmux"):
            with self.subTest(command=command):
                self.assertIn(command, state.SHELL_COMMANDS)
                self.assertEqual(state.classify_state("", command), "idle")

    def test_any_nonempty_program_is_running(self):
        for command in ("codex", "claude", "node", "npm", "python3", "custom-tool"):
            with self.subTest(command=command):
                self.assertEqual(state.classify_state("", command, output_age=100), "running")

    def test_fallback_is_idle(self):
        for command in (None, ""):
            self.assertEqual(state.classify_state("ordinary output", command), "idle")

    def test_yes_no_patterns(self):
        for text in ("(y/n)", "[y/N]", "Yes/No", "Do you want to proceed"):
            with self.subTest(text=text):
                self.assertEqual(state.classify_state(text.swapcase()), "waiting")

    def test_numbered_menu_patterns(self):
        for text in ("❯ 1. Yes", "  2. No", "> 1. Yes"):
            with self.subTest(text=text):
                self.assertEqual(state.classify_state(text), "waiting")

    def test_keypress_patterns(self):
        for text in ("Press Enter", "press any key"):
            with self.subTest(text=text):
                self.assertEqual(state.classify_state(text.upper()), "waiting")

    def test_confirmation_patterns(self):
        for text in ("Overwrite?", "Allow", "Continue?", "Are you sure"):
            with self.subTest(text=text):
                self.assertEqual(state.classify_state(text.lower()), "waiting")

    def test_waiting_for_pattern(self):
        self.assertEqual(state.classify_state("Waiting for approval"), "waiting")

    def test_bare_prompt_excludes_shells(self):
        for command in state.SHELL_COMMANDS:
            self.assertEqual(state.classify_state("  >  \n", command), "idle")
        for command in ("codex", None):
            self.assertEqual(state.classify_state("  >  \n", command), "waiting")
        for text in ("output >", "> output", ">>", "Allowed", "Disallow"):
            self.assertEqual(state.classify_state(text), "idle")

    def test_only_last_three_nonempty_lines_are_checked(self):
        self.assertEqual(state.classify_state("Allow\n\nfirst\n \nsecond\n"), "waiting")
        self.assertEqual(state.classify_state("Allow\nfirst\nsecond\nthird\n\n"), "idle")

    def test_state_metadata(self):
        expected = (("idle", "", 0), ("running", "run", 1), ("waiting", "wait", 3),
                    ("exited", "end", 0), ("failed", "fail", 2), ("unknown", "", 0))
        for name, badge, rank in expected:
            with self.subTest(state=name):
                self.assertEqual(state.state_badge(name), badge)
                self.assertEqual(state.state_rank(name), rank)
                self.assertEqual(state.needs_input(name), name == "waiting")


class HelperTests(unittest.TestCase):
    def test_tail_empty_and_short(self):
        self.assertEqual(state.tail_lines(""), "")
        self.assertEqual(state.tail_lines("one\ntwo\n"), "one\ntwo")
        self.assertEqual(state.tail_lines("one\n\ntwo", 2), "\ntwo")

    def test_tail_limit(self):
        self.assertEqual(state.tail_lines("0\n1\n2\n3\n4\n5\n6"), "1\n2\n3\n4\n5\n6")
        self.assertEqual(state.tail_lines("one", 0), "")
        self.assertEqual(state.tail_lines("one", -1), "")

    def test_last_prompt_line(self):
        self.assertEqual(state.last_prompt_line(""), "")
        self.assertEqual(state.last_prompt_line(" \n\t"), "")
        self.assertEqual(state.last_prompt_line("output\n  prompt  \n\n"), "prompt")

    def test_elapsed_boundaries(self):
        for seconds, expected in ((0, "0s"), (59, "59s"), (60, "1m"), (3599, "59m"),
                                  (3600, "1h0m"), (86400, "24h0m"), (4800, "1h20m")):
            with self.subTest(seconds=seconds):
                self.assertEqual(state.elapsed_text(seconds), expected)

    def test_elapsed_unavailable_and_fractional(self):
        for value in (None, -1, float("nan"), float("inf")):
            self.assertEqual(state.elapsed_text(value), "-")
        self.assertEqual(state.elapsed_text(12.9), "12s")

    def test_git_branch_walks_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref: refs/heads/feature/state\n")
            child = root / "src" / "nested"
            child.mkdir(parents=True)
            self.assertEqual(state.git_branch(child), "feature/state")
            self.assertEqual(state.git_branch(root), "feature/state")

    def test_git_detached_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n")
            self.assertEqual(state.git_branch(root), "0123456")

    def test_git_missing_and_malformed_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(state.git_branch(root))
            (root / ".git").mkdir()
            for text in ("", "not a head", "ref: refs/heads/"):
                (root / ".git" / "HEAD").write_text(text)
                self.assertIsNone(state.git_branch(root))

    def test_foreground_bogus_pid(self):
        self.assertIsNone(state.foreground_command(999999999))

    def test_foreground_stat_with_parentheses_and_spaces(self):
        contents = {"/proc/123/stat": "123 (a tricky ) name) S 10 20 30 40 456 99",
                    "/proc/456/comm": "codex\n"}
        with patch("pathlib.Path.read_text", autospec=True,
                   side_effect=lambda path, **kwargs: contents[str(path)]):
            self.assertEqual(state.foreground_command(123), "codex")

    def test_foreground_failures(self):
        for stat in ("", "123 (broken", "123 (x) S 1", "123 (x) S 1 2 3 4 -1"):
            with self.subTest(stat=stat):
                with patch("pathlib.Path.read_text", return_value=stat):
                    self.assertIsNone(state.foreground_command(123))
        for error in (PermissionError(), ProcessLookupError(), UnicodeError()):
            with patch("pathlib.Path.read_text", side_effect=error):
                self.assertIsNone(state.foreground_command(123))


if __name__ == "__main__":
    unittest.main()
