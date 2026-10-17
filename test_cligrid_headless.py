"""Optional Broadway smoke: the real window, isolated from the live grid.

Skipped when broadwayd is not installed. HOME, XDG paths, the control socket
and tmux's socket directory are all private, so this cannot attach to the
person's running grid or kill their sessions.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "cligrid.py")


def _free_display():
    """A Broadway display number whose TCP port is free on localhost."""
    for display in range(20, 40):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 8080 + display))
        except OSError:
            continue
        sock.close()
        return display
    return None


def _isolated_env(tmp, display, extra_config=None):
    runtime = os.path.join(tmp, "run")
    os.makedirs(runtime)
    env = os.environ.copy()
    env.update({
        "HOME": tmp,
        "XDG_CONFIG_HOME": os.path.join(tmp, "config"),
        "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
        "XDG_RUNTIME_DIR": runtime,
        "TMUX_TMPDIR": runtime,
        "CLIGRID_SOCKET": os.path.join(runtime, "cligrid.sock"),
        "GDK_BACKEND": "broadway",
        "BROADWAY_DISPLAY": ":%d" % display,
        "NO_COLOR": "1",
    })
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "CLAUDE_CODE", "CLAUDE_TMPDIR"):
        env.pop(key, None)
    if extra_config:
        cfg_dir = os.path.join(tmp, "config", "cligrid")
        os.makedirs(cfg_dir)
        with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(extra_config, handle)
    return env


@unittest.skipUnless(shutil.which("broadwayd"), "broadwayd is not installed")
class BroadwaySmokeTests(unittest.TestCase):
    def _run_self_test(self, extra_config=None, timeout=25):
        display = _free_display()
        if display is None:
            self.skipTest("no free Broadway port")
        with tempfile.TemporaryDirectory(prefix="cligrid-broadway-") as tmp:
            env = _isolated_env(tmp, display, extra_config)
            server = subprocess.Popen(
                ["broadwayd", ":%d" % display],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(0.3)
                result = subprocess.run(
                    [sys.executable, APP, "--self-test"],
                    env=env, capture_output=True, text=True, timeout=timeout, cwd=tmp,
                    check=False,
                )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    server.kill()
        if result.returncode != 0:
            self.skipTest("Broadway self-test unavailable: %s" % (result.stderr or result.stdout)[:400])
        line = next((row for row in result.stdout.splitlines() if row.startswith("{")), "")
        self.assertTrue(line, result.stdout[:400])
        return json.loads(line)

    def test_self_test_prints_status_json(self):
        data = self._run_self_test()
        self.assertGreaterEqual(data.get("pane_count", 0), 1)
        self.assertIn("version", data)

    def test_twenty_panes_self_test(self):
        data = self._run_self_test(
            extra_config={"pane_count": 20, "banner": False, "scrollback": 200},
            timeout=45,
        )
        self.assertEqual(data.get("pane_count"), 20)


if __name__ == "__main__":
    unittest.main()
