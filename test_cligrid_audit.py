"""Regression checks for session selection and control transport safety."""
from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
import io
import socket
import tempfile
from pathlib import Path
import os
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cligrid


class OfflineCommandTests(unittest.TestCase):
    def run_offline(self, args):
        cfg = {"panes": [cligrid.default_pane(i) for i in range(3)]}
        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(cligrid, "send_command", return_value=(False, "")))
            stack.enter_context(patch.object(cligrid, "load_config", return_value=deepcopy(cfg)))
            save = stack.enter_context(patch.object(cligrid, "save_config"))
            kill = stack.enter_context(patch.object(cligrid, "kill_tmux_session"))
            app = stack.enter_context(patch.object(cligrid, "CliGrid"))
            for name in ("log_to_file", "quiet_vte_warnings"):
                stack.enter_context(patch.object(cligrid, name))
            stack.enter_context(patch.object(cligrid, "install_signal_handlers"))
            stack.enter_context(patch.object(cligrid.Gtk, "main"))
            result = cligrid.main(["cligrid", *args])
        return result, kill, save, app, cfg

    def test_reset_one_does_not_end_other_sessions(self):
        code, kill, _, app, _ = self.run_offline(["reset", "2"])
        self.assertEqual(code, 0)
        kill.assert_called_once_with("g2")
        app.assert_called_once()

    def test_invalid_reset_never_ends_sessions_or_opens_window(self):
        for value in ("0", "-1", "4", "oops"):
            with self.subTest(value=value):
                code, kill, save, app, _ = self.run_offline(["reset", value])
                self.assertEqual(code, 1)
                kill.assert_not_called()
                save.assert_not_called()
                app.assert_not_called()

    def test_subset_broadcast_changes_and_ends_only_selected_sessions(self):
        code, kill, save, _, cfg = self.run_offline(["all", "--panes", "1,3", "htop"])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0] for c in kill.call_args_list], ["g1", "g3"])
        self.assertEqual(save.call_args.args[0]["panes"][1], cfg["panes"][1])

    def test_invalid_broadcast_never_changes_sessions(self):
        for spec in ("4", "bad", "focused", "", " "):
            with self.subTest(spec=spec):
                code, kill, save, app, _ = self.run_offline(["all", "--panes", spec, "htop"])
                self.assertEqual(code, 1)
                kill.assert_not_called()
                save.assert_not_called()
                app.assert_not_called()

    def test_empty_equals_selector_is_rejected(self):
        code, kill, save, app, _ = self.run_offline(["all", "--panes=", "htop"])
        self.assertEqual(code, 1)
        kill.assert_not_called()
        save.assert_not_called()
        app.assert_not_called()


class LiveSelectionTests(unittest.TestCase):
    def test_invalid_subset_is_an_error_instead_of_all_panes(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        app.order = [Mock(), Mock(), Mock()]
        app.populate_all = Mock()
        for request in ("all --panes bad htop", "all --panes '' htop", "all --panes= htop",
                        "all htop --panes"):
            self.assertIn("expects", app.dispatch(request))
        app.populate_all.assert_not_called()
        for pane in app.order:
            pane.restart.assert_not_called()

    def test_focused_subset_resolves_to_only_the_active_pane(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        app.order = [Mock(), Mock(), Mock()]
        app.active = app.order[1]
        self.assertEqual(app.split_fill(["--panes focused htop"]), ("htop", [2]))


class WaitTimeoutTests(unittest.TestCase):
    def test_positional_timeout_outlives_the_server_deadline(self):
        self.assertEqual(cligrid.request_timeout("wait 1 'build done' 120"), 126)

    def test_invalid_timeouts_do_not_crash_socket_configuration(self):
        for value in ("nan", "inf", "-1"):
            self.assertEqual(cligrid.request_timeout("wait 1 done --timeout " + value), 5)

    def test_zero_timeout_completes_immediately(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        pane = SimpleNamespace(poll_text="nothing", name="g1", dead=False)
        app.pane_arg = Mock(return_value=pane)
        app.panes = [pane]
        app.watch_connection = Mock(return_value=0)
        app.finish_waiter = Mock()
        app.waiters = []
        with patch.object(cligrid.time, "monotonic", return_value=100):
            app.start_wait({"args": ["1", "done", "0"]}, Mock())
        app.finish_waiter.assert_called_once_with(app.waiters[0], matched=False)

    def test_removed_pane_answers_its_waiter_at_once(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        pane = SimpleNamespace(poll_text="nothing", name="g1", dead=True)
        app.panes = []
        app.finish_waiter = Mock()
        waiter = {"pane": pane, "regex": cligrid.re.compile("done"), "deadline": 1e12}
        self.assertTrue(app.check_waiter(waiter))
        app.finish_waiter.assert_called_once_with(waiter, matched=False, line="pane removed")


class TransportTests(unittest.TestCase):
    def test_connected_timeout_is_not_reported_as_absent_server(self):
        client = Mock()
        client.recv.side_effect = socket.timeout("timed out")
        with patch.object(cligrid.socket, "socket", return_value=client):
            with self.assertRaises(OSError):
                cligrid.send_command("reset 2", quiet=True)
        client.close.assert_called_once()

    def test_connection_error_never_triggers_offline_reset(self):
        with patch.object(cligrid, "send_command", side_effect=socket.timeout()), \
                patch.object(cligrid, "wipe_configured_sessions") as wipe, \
                patch.object(cligrid, "CliGrid") as app, redirect_stderr(io.StringIO()):
            self.assertEqual(cligrid.main(["cligrid", "reset", "2"]), 1)
        wipe.assert_not_called()
        app.assert_not_called()


class ConfigurationTests(unittest.TestCase):
    def test_generated_session_target_preserves_spaces(self):
        cfg = cligrid.workspace.validate({"pane_count": 1, "panes": [{"name": "Build logs"}]})
        command = cfg["workspaces"][0]["panes"][0]["cmd"]
        self.assertEqual(cligrid.pane_argv(command), ["tmux", "new-session", "-A", "-s", "Build logs"])

    def test_broadcast_command_preserves_spaces_in_the_session_name(self):
        for cli in ("htop", "cd ~/src && nvim", ""):
            command = cligrid.pane_cmd_for_cli("Build logs", cli)
            argv = cligrid.pane_argv(command)
            self.assertEqual(argv[:5], ["tmux", "new-session", "-A", "-s", "Build logs"], command)
            self.assertEqual(cligrid.tmux_target(command, "fallback"), "Build logs")
        plain = cligrid.pane_cmd_for_cli("Build logs", "htop")
        self.assertEqual(cligrid.pane_argv(plain)[5:], ["htop"])
        self.assertEqual(cligrid.pane_cmd_for_cli("g3", "htop"), "tmux new-session -A -s g3 htop")

    def test_branch_label_follows_relative_worktree_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "metadata").mkdir()
            (root / "metadata" / "HEAD").write_text("ref: refs/heads/feature\n")
            work = root / "work"
            work.mkdir()
            (work / ".git").write_text("gitdir: ../metadata\n")
            self.assertEqual(cligrid.state.git_branch(work), "feature")

    def test_control_socket_is_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "control.sock")
            app = cligrid.CliGrid.__new__(cligrid.CliGrid)
            old = os.umask(0)
            service = None
            try:
                with patch.object(cligrid, "SOCKET_PATH", path):
                    service = app.start_socket()
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            finally:
                os.umask(old)
                if service:
                    service.close()


if __name__ == "__main__":
    unittest.main()
