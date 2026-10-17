"""The control socket must never block the window on a client.

These tests run a real Unix socket pair through the same Gio streams the
window uses, with the client side deliberately not reading, and assert that
the window's side returns at once, drops the client, and stays usable.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

import cligrid  # noqa: E402
import cligrid_control as control  # noqa: E402


def gio_pair():
    """(server Gio.SocketConnection, client socket.socket) over one socketpair."""
    server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setblocking(False)
    gsock = Gio.Socket.new_from_fd(server.detach())
    gsock.set_blocking(False)
    return gsock.connection_factory_create_connection(), client


def spin(seconds=0.5, until=None):
    """Run the GLib main loop until `until()` is true or the time is up."""
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        # Bounded: another test may have left an always-ready source behind.
        for _ in range(64):
            if not context.iteration(False):
                break
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until is not None else True


def drain(client, limit=8 * 1024 * 1024):
    client.settimeout(0.2)
    chunks = []
    total = 0
    while total < limit:
        try:
            data = client.recv(65536)
        except (socket.timeout, OSError):
            break
        if not data:
            break
        chunks.append(data)
        total += len(data)
    return b"".join(chunks)


class ControlLinkTests(unittest.TestCase):
    def test_slow_reader_is_dropped_without_blocking(self):
        connection, client = gio_pair()
        gone = []
        link = cligrid.ControlLink(connection, on_gone=gone.append)
        payload = b"x" * (256 * 1024)
        started = time.monotonic()
        sent = 0
        while not link.gone and sent < 16 * 1024 * 1024:
            link.send(payload)
            sent += len(payload)
        elapsed = time.monotonic() - started
        self.assertTrue(link.gone, "the link should give up on a client that never reads")
        self.assertLess(elapsed, 2.0, "send() blocked the caller for %.1fs" % elapsed)
        self.assertEqual(gone, [link])
        self.assertIn("slow reader", link.reason)
        self.assertLessEqual(sent, control.MAX_PENDING_BYTES + 2 * len(payload))
        client.close()

    def test_reply_reaches_the_client_and_closes(self):
        connection, client = gio_pair()
        link = cligrid.ControlLink(connection)
        link.send("ok\n")
        link.finish()
        received = []
        spin(2.0, until=lambda: received.append(drain(client)) or received[-1].endswith(b"ok\n"))
        self.assertEqual(b"".join(received), b"ok\n")
        self.assertTrue(link.gone)
        client.settimeout(1.0)
        self.assertEqual(client.recv(16), b"", "the connection should close after the reply")
        client.close()

    def test_large_reply_streams_in_order(self):
        connection, client = gio_pair()
        link = cligrid.ControlLink(connection)
        body = "".join("%06d\n" % i for i in range(40000)).encode()  # 280 KB
        link.send(body)
        link.finish()
        got = bytearray()

        def pull():
            got.extend(drain(client))
            return len(got) >= len(body)

        self.assertTrue(spin(5.0, until=pull), "reply stalled at %d of %d bytes" % (len(got), len(body)))
        self.assertEqual(bytes(got), body)
        client.close()


class RequestBoundTests(unittest.TestCase):
    def make_app(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        app.quitting = False
        app.config = {}
        app.dispatch = Mock(return_value="ok\n")
        app.toast_reply = Mock(return_value=False)
        return app

    def test_overlong_request_is_refused(self):
        app = self.make_app()
        connection, client = gio_pair()
        app.on_incoming(None, connection, None)
        client.sendall(b"a" * (control.MAX_REQUEST_BYTES + 8192))
        got = bytearray()
        spin(5.0, until=lambda: got.extend(drain(client)) or b"\n" in got)
        self.assertIn(b"request is longer than", bytes(got))
        app.dispatch.assert_not_called()
        client.close()

    def test_normal_request_is_dispatched_once(self):
        app = self.make_app()
        connection, client = gio_pair()
        app.on_incoming(None, connection, None)
        client.sendall(b"status\nignored second line\n")
        got = bytearray()
        spin(5.0, until=lambda: got.extend(drain(client)) or got.endswith(b"ok\n"))
        self.assertEqual(bytes(got), b"ok\n")
        app.dispatch.assert_called_once_with("status")
        client.close()


CLIENT = """
import socket, sys
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect(sys.argv[1])
client.sendall(sys.argv[2].encode() + b"\\n")
chunks = []
while True:
    data = client.recv(65536)
    if not data:
        break
    chunks.append(data)
sys.stdout.write(b"".join(chunks).decode())
"""


class GuardTests(unittest.TestCase):
    """/proc/<pid>/environ is the environment a process was started with, so
    the guard is exercised with a real client subprocess whose CLIGRID marker
    is set or cleared, talking to a real listening control socket."""

    def make_app(self, guard="panes"):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        app.quitting = False
        app.config = {"guard": guard}
        app.dispatch = Mock(return_value="ok\n")
        app.toast_reply = Mock(return_value=False)
        app.toast = Mock()
        app.add_event = Mock()
        return app

    def request(self, app, line, inside_pane):
        env = {key: value for key, value in os.environ.items() if key != "CLIGRID"}
        if inside_pane:
            env["CLIGRID"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "control.sock")
            with patch.object(cligrid, "SOCKET_PATH", path):
                service = app.start_socket()
            self.assertIsNotNone(service)
            try:
                proc = subprocess.Popen([sys.executable, "-c", CLIENT, path, line], env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertTrue(spin(15.0, until=lambda: proc.poll() is not None),
                                "the client did not get a reply")
                out, err = proc.communicate(timeout=5)
            finally:
                service.close()
        self.assertEqual(proc.returncode, 0, err.decode())
        return out.decode()

    def test_peer_credentials_and_environment_are_readable(self):
        connection, client = gio_pair()
        self.assertEqual(cligrid.peer_pid(connection), os.getpid())
        self.assertIn("HOME", cligrid.process_environ(os.getpid()))
        self.assertEqual(cligrid.process_environ(None), {})
        self.assertEqual(cligrid.process_environ(2 ** 22 + 7), {})
        client.close()

    def test_destructive_verb_from_a_pane_is_refused(self):
        app = self.make_app()
        reply = self.request(app, "reset 2", inside_pane=True)
        self.assertIn("refused: reset", reply)
        app.dispatch.assert_not_called()
        app.toast.assert_called_once()
        self.assertEqual(app.add_event.call_args.args[0], "error")

    def test_force_and_observe_verbs_pass_from_a_pane(self):
        app = self.make_app()
        self.assertEqual(self.request(app, "reset --force 2", inside_pane=True), "ok\n")
        self.assertEqual(self.request(app, "status", inside_pane=True), "ok\n")
        self.assertEqual([c.args[0] for c in app.dispatch.call_args_list], ["reset 2", "status"])

    def test_outside_the_grid_and_guard_off_pass(self):
        self.assertEqual(self.request(self.make_app(), "reset 2", inside_pane=False), "ok\n")
        self.assertEqual(self.request(self.make_app(guard="off"), "reset 2", inside_pane=True),
                         "ok\n")


class WaitPatternBoundTests(unittest.TestCase):
    def test_pattern_length_is_capped(self):
        with self.assertRaises(ValueError):
            control.parse_wait(["1", "a" * (control.MAX_PATTERN_CHARS + 1)])
        control.parse_wait(["1", "a" * control.MAX_PATTERN_CHARS])


if __name__ == "__main__":
    unittest.main()
