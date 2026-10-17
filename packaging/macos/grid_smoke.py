"""Exercise a relocated Mac app through its real terminal control socket."""

import json
import os
from pathlib import Path
import socket
import shlex
import subprocess
import sys
import tempfile
import time


def request(address, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(address)
        client.sendall((command + '\n').encode())
        chunks = []
        while data := client.recv(65536):
            chunks.append(data)
    return b''.join(chunks).decode()


def wait_for(probe, description):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError('Timed out: ' + description)


def verify(bundle, brew_prefix):
    executable = bundle / 'Contents/MacOS/cligrid'
    tmux = bundle / 'Contents/Frameworks/bin/tmux'
    profile = '(version 1)(allow default)(deny file-read* (subpath %s))' % json.dumps(brew_prefix)
    wrapper = ['/usr/bin/sandbox-exec', '-p', profile]
    with tempfile.TemporaryDirectory(prefix='cligrid-grid-', dir='/tmp') as temporary:
        directory = Path(temporary)
        home = directory / 'home'
        home.mkdir()
        (home / '.bash_profile').write_text("export PS1='cligrid> '\n")
        config = directory / 'cligrid'
        config.mkdir()
        (config / 'config.json').write_text(json.dumps({
            'pane_count': 2, 'cwd': temporary, 'banner': True,
        }))
        environment = {key: value for key, value in os.environ.items()
                       if key in ('USER', 'LOGNAME', 'TMPDIR', 'LANG')}
        address = str(directory / 'control.sock')
        environment.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', TERM='xterm-256color',
                           HOME=str(home), SHELL='/bin/bash', BASH_SILENCE_DEPRECATION_WARNING='1',
                           XDG_CONFIG_HOME=temporary, XDG_CACHE_HOME=temporary,
                           XDG_RUNTIME_DIR=temporary, TMUX_TMPDIR=temporary,
                           CLIGRID_SOCKET=address, NO_COLOR='1')
        process = None
        with (directory / 'process.log').open('w+') as log:
            try:
                for attempt in range(2):
                    process = subprocess.Popen([*wrapper, str(executable)], env=environment,
                                               cwd=temporary, stdout=log, stderr=log)
                    wait_for(lambda: json.loads(request(address, 'status'))['pane_count'] == 2,
                             'two-pane window')
                    wait_for(lambda: all(not pane['exited'] for pane in
                                         json.loads(request(address, 'status'))['panes']),
                             'live terminals')
                    time.sleep(2)
                    if attempt == 0:
                        request(address, 'run 1 ' + shlex.quote('export CLIGRID_SMOKE_VALUE=persisted'))
                    marker = f'CLIGRID_persisted_OK_{attempt}'
                    request(address, 'run 1 ' + shlex.quote(
                        f"printf 'CLIGRID_%s_OK_%s\\n' \"$CLIGRID_SMOKE_VALUE\" {attempt}"))
                    wait_for(lambda marker=marker: marker in request(address, 'dump 1 --lines 2000'),
                             'shell output and session persistence')
                    request(address, 'zoom 1')
                    wait_for(lambda: bool(json.loads(request(address, 'status'))['zoom']), 'zoom')
                    request(address, 'zoom off')
                    wait_for(lambda: not json.loads(request(address, 'status'))['zoom'], 'unzoom')
                    request(address, 'restart 1')
                    wait_for(lambda marker=marker: marker in request(address, 'dump 1 --lines 2000'),
                             'pane restart preserves output')
                    restart_marker = f'CLIGRID_persisted_RESTART_{attempt}'
                    time.sleep(2)
                    request(address, 'run 1 ' + shlex.quote(
                        f"printf 'CLIGRID_%s_RESTART_%s\\n' \"$CLIGRID_SMOKE_VALUE\" {attempt}"))
                    wait_for(lambda marker=restart_marker: marker in request(address, 'dump 1'),
                             'restarted pane accepts input and preserves shell state')
                    request(address, 'quit')
                    process.wait(timeout=10)
                    if process.returncode:
                        raise RuntimeError('Grid exited with code ' + str(process.returncode))
                    print('PASS: grid launch, shell input/output, zoom, restart, quit', attempt + 1,
                          flush=True)
                print('PASS: tmux session survives application relaunch without Homebrew', flush=True)
            except Exception:
                try:
                    print(request(address, 'status'), file=sys.stderr)
                    print(request(address, 'dump 1 --lines 2000'), file=sys.stderr)
                    print(request(address, 'log 30'), file=sys.stderr)
                except OSError:
                    pass
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
                app_log = directory / 'cligrid.log'
                if app_log.exists():
                    print(app_log.read_text(), file=sys.stderr)
                raise
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                subprocess.run([*wrapper, str(tmux), 'kill-server'], env=environment,
                               capture_output=True, check=False, timeout=10)


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve(strict=True), sys.argv[2])
