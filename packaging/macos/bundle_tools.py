"""Native build notices and fail-closed checks for the standalone Mac bundle."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile


def output(*argv):
    return subprocess.check_output(argv, text=True).strip()


def notices(destination):
    destination.mkdir(parents=True)
    formulas = ['gtk+3', 'vte3', 'pygobject3', 'tmux', 'ncurses', 'adwaita-icon-theme', 'librsvg']
    formulas = sorted(set(formulas + output('brew', 'deps', '--installed',
                                            *formulas).splitlines()))
    manifest = json.loads(output('brew', 'info', '--json=v2', *formulas))
    (destination / 'homebrew-formulas.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for formula in formulas:
        prefix = Path(output('brew', '--prefix', formula)).resolve()
        for pattern in ('LICENSE*', 'COPYING*', 'NOTICE*', 'AUTHORS*', 'share/licenses/**/*'):
            for source in prefix.glob(pattern):
                if source.is_file():
                    target = destination / formula / source.relative_to(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    # Record Python/package versions and any wheel-provided license files too.
    packages = []
    for package in importlib.metadata.distributions():
        name = package.metadata['Name']
        packages.append({'name': name, 'version': package.version})
        for entry in package.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
                source = Path(package.locate_file(entry))
                if source.is_file():
                    target = destination / 'python-packages' / name / entry.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (destination / 'python-packages.json').write_text(json.dumps(packages, indent=2) + '\n')
    (destination / 'README.txt').write_text(
        'Build dependency inventory and available notices. Libraries retain their own licenses.\n'
        'This inventory can include build-only packages; review redistribution obligations\n'
        'and corresponding-source availability before public distribution.\n'
    )


def validate_load_paths(dependencies, rpaths):
    """A bundle may link only to itself or Apple's system libraries."""
    relative = ('@rpath/', '@loader_path/', '@executable_path/')
    system = ('/usr/lib/', '/System/Library/')
    for path in dependencies:
        if not path.startswith((*relative, *system)):
            raise ValueError('External library: ' + path)
    for path in rpaths:
        if not path.startswith(('@loader_path', '@executable_path', *system)):
            raise ValueError('External rpath: ' + path)


def audit_binaries(bundle):
    count = 0
    mach_headers = {
        b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
        b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
        b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
        b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca',
    }
    for path in bundle.rglob('*'):
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(bundle):
                raise ValueError('Symlink escapes app: ' + str(path))
            continue
        if not path.is_file():
            continue
        with path.open('rb') as binary:
            if binary.read(4) not in mach_headers:
                continue
        count += 1
        architectures = output('/usr/bin/lipo', '-archs', str(path)).split()
        if platform.machine() not in architectures:
            raise ValueError('Wrong architecture: ' + str(path))
        linked = output('/usr/bin/otool', '-L', str(path))
        dependencies = re.findall(r'^\s+(.+?) \(compatibility version', linked, re.M)
        commands = output('/usr/bin/otool', '-l', str(path))
        rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset', commands)
        validate_load_paths(dependencies, rpaths)
    if not count:
        raise ValueError('No native binaries found')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    print(f'Checked {count} Mach-O files and the bundle signature', flush=True)


def verify(bundle, brew_prefix):
    bundle = bundle.resolve(strict=True)
    audit_binaries(bundle)
    contents = bundle / 'Contents'
    executable = contents / 'MacOS/cligrid'
    version = plistlib.loads((contents / 'Info.plist').read_bytes())['CFBundleShortVersionString']
    if not Path('/usr/bin/sandbox-exec').exists():
        raise RuntimeError('sandbox-exec is required to verify without access to Homebrew')
    # Removing PATH alone can hide accidental absolute-path library loads.
    # Deny reads of the real Homebrew tree during all runtime checks.
    profile = '(version 1)(allow default)(deny file-read* (subpath %s))' % json.dumps(
        str(Path(brew_prefix).resolve()))
    wrapper = ['/usr/bin/sandbox-exec', '-p', profile, str(executable)]
    with tempfile.TemporaryDirectory(prefix='cligrid-check-', dir='/tmp') as tmp:
        env = {key: value for key, value in os.environ.items()
               if key in ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG')}
        env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', TERM='xterm-256color',
                   XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp, XDG_RUNTIME_DIR=tmp,
                   TMUX_TMPDIR=tmp, CLIGRID_SOCKET=tmp + '/control.sock', NO_COLOR='1')
        for args, expected in [(['version'], 'cligrid ' + version),
                               (['doctor'], '10 ok, 0 to fix'),
                               (['cligrid_art.py', 'banner', '--name', 'bundle-check'], 'bundle-check'),
                               (['--bundle-smoke'], 'CLIGRID_BUNDLE_OK')]:
            result = subprocess.run([*wrapper, *args], env=env, cwd=tmp, capture_output=True,
                                    text=True, timeout=60, check=False)
            if result.returncode:
                raise RuntimeError(f'{args}: exit {result.returncode}\n'
                                   f'{result.stdout}\n{result.stderr}')
            if expected not in result.stdout:
                raise ValueError(f'{args}: expected {expected!r}, got {result.stdout!r}')
            print('PASS:', ' '.join(args), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('notices', 'verify'))
    parser.add_argument('path', type=Path)
    parser.add_argument('brew_prefix', nargs='?')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Native bundle operations require macOS')
    if args.action == 'notices':
        notices(args.path)
    elif not args.brew_prefix:
        parser.error('verify requires the Homebrew prefix to deny during testing')
    else:
        verify(args.path, args.brew_prefix)


if __name__ == '__main__':
    main()
