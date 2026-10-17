#!/usr/bin/env bash
# Cli Griderator: verify the platform installs.
#
# The unittest suite covers the application. This covers what it cannot: the
# three installers, the built artifacts, and the launchers they generate. The
# macOS installer is driven here with a stubbed uname and brew, which walks it
# through its platform gate, dependency gate, interpreter probe, file install
# and bundle write. The Windows PowerShell script is checked structurally,
# since PowerShell is not present on Linux.
#
# Sections needing a desktop GTK stack (python3-gi, GdkPixbuf, Vte 2.91) skip
# cleanly where it is missing, so this also runs on a bare runner.
#
#   bash packaging/verify-platforms.sh
set -uo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
work=$(mktemp -d /tmp/cligrid-verify-XXXXXX)
trap 'rm -rf -- "$work"' EXIT

pass=0
fail=0
check() { # check <name> <command...>
    local name=$1
    shift
    if "$@" >"$work/out" 2>&1; then
        printf '  PASS  %s\n' "$name"
        pass=$((pass + 1))
    else
        printf '  FAIL  %s\n' "$name"
        sed 's/^/        /' "$work/out" | tail -12
        fail=$((fail + 1))
    fi
}
skip() { printf '  SKIP  %s\n' "$1"; }

verify_launcher_doctor() {
    local prefix=$1 font output status
    font=$(fc-match --format='%{family}' sans) || return 1
    mkdir -p "$prefix/.config/cligrid" || return 1
    /usr/bin/python3 - "$prefix/.config/cligrid/config.json" "${font%%,*}" <<'PY'
import json
import sys

with open(sys.argv[1], "w") as handle:
    json.dump({"font": sys.argv[2]}, handle)
PY
    output=$(env HOME="$prefix" XDG_CONFIG_HOME="$prefix/.config" \
        XDG_RUNTIME_DIR="$prefix" XDG_SESSION_TYPE=x11 \
        "$prefix/bin/cligrid" doctor)
    status=$?
    printf '%s\n' "$output"
    [[ $status == 0 ]] && grep -qx '10 ok, 0 failed' <<< "$output"
}

suite() { # suite <python>: the tests, with the gi guard the CI job uses
    local python=$1 guard
    guard=$(mktemp -d)
    cat > "$guard/sitecustomize.py" <<'PY'
import importlib.util
import unittest

if importlib.util.find_spec("gi") is None:
    original = unittest.TestLoader._get_module_from_name

    def guarded_import(self, name):
        try:
            return original(self, name)
        except ModuleNotFoundError as exc:
            if exc.name == "gi" or exc.name.startswith("gi."):
                raise unittest.SkipTest("PyGObject (gi) is unavailable") from exc
            raise

    unittest.TestLoader._get_module_from_name = guarded_import
PY
    PYTHONPATH="$guard" "$python" -m unittest discover -p 'test_*.py' 2>&1 | tail -3 | grep -q '^OK'
    local status=$?
    rm -rf "$guard"
    return $status
}

cd "$repo" || exit 1

# The one version: packaging/version.py reads pyproject.toml.
version=$(/usr/bin/python3 packaging/version.py)
root=cligrid-$version

have_gi=0
if /usr/bin/python3 -c 'import gi; gi.require_version("GdkPixbuf", "2.0"); gi.require_version("Vte", "2.91"); from gi.repository import GdkPixbuf, Vte' >/dev/null 2>&1; then
    have_gi=1
fi

echo 'suite and syntax'
check 'unittest discover, with top-level gi' suite /usr/bin/python3
if /usr/bin/python3 -m venv --without-pip "$work/venv" >/dev/null 2>&1; then
    check 'unittest discover, without gi (the CI path)' suite "$work/venv/bin/python3"
else
    skip 'unittest discover without gi (no venv module on this host)'
fi
for script in packaging/linux/build-tarball.sh packaging/macos/install-macos.sh \
              packaging/macos/build-dmg.sh packaging/windows/wsl-provision.sh \
              packaging/windows/build-exe.sh install.sh install \
              packaging/build-deb.sh packaging/verify-platforms.sh; do
    check "bash -n $script" bash -n "$script"
done
check 'every spaced assignment is quoted or a substitution' /usr/bin/python3 -c "
import glob, re, sys
bad = []
for path in glob.glob('packaging/*/*.sh'):
    for number, line in enumerate(open(path, encoding='utf-8'), 1):
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(\S.*)$', line.rstrip(chr(10)))
        if not match:
            continue
        value = match.group(2)
        if ' ' not in value or value[0] in (chr(34), chr(39), chr(36), chr(40)):
            continue
        bad.append(path + ':' + str(number) + ':' + line.rstrip())
if bad:
    print(chr(10).join(bad))
    sys.exit(1)
"
check 'powershell braces balance' bash -c \
    'for f in packaging/windows/*.ps1; do test $(tr -cd "{" < $f | wc -c) -eq $(tr -cd "}" < $f | wc -c) || exit 1; done'

echo 'linux artifact'
check 'build-tarball.sh' bash packaging/linux/build-tarball.sh
tarball=packaging/dist/$root.tar.gz
zipfile=packaging/dist/$root.zip
deb=packaging/dist/cligrid_${version}_all.deb
check 'tarball and zip exist' bash -c "test -f $tarball && test -f $zipfile"
check 'archive carries the three platform installers' bash -c \
    "tar -tzf $tarball | grep -q '$root/install' &&
     tar -tzf $tarball | grep -q '$root/install.sh' &&
     tar -tzf $tarball | grep -q '$root/packaging/macos/install-macos.sh' &&
     tar -tzf $tarball | grep -q '$root/packaging/windows/install-windows.ps1' &&
     tar -tzf $tarball | grep -q '$root/icons/cligrid.svg'"
check 'archive carries pyproject.toml, LICENSE and version.py' bash -c \
    "tar -tzf $tarball | grep -q '$root/pyproject.toml' &&
     tar -tzf $tarball | grep -q '$root/LICENSE' &&
     tar -tzf $tarball | grep -q '$root/packaging/version.py'"
check 'archive carries every application module' /usr/bin/python3 -c "
import glob, os, tarfile
want = {'$root/' + os.path.basename(p) for p in glob.glob('cligrid*.py')}
with tarfile.open('$tarball') as archive:
    names = set(archive.getnames())
missing = want - names
assert not missing, missing
"
check 'zip lists the same installers' /usr/bin/python3 -c "
import zipfile
need = {'$root/install', '$root/install.sh',
        '$root/packaging/macos/install-macos.sh',
        '$root/packaging/windows/install-windows.ps1'}
with zipfile.ZipFile('$zipfile') as archive:
    names = set(archive.namelist())
missing = need - names
assert not missing, missing
"
exe=packaging/dist/$root.exe
dmg=packaging/dist/$root.dmg
check 'build-exe.sh' bash packaging/windows/build-exe.sh
check 'exe is a Windows PE' /usr/bin/python3 -c \
    "assert open('$exe','rb').read(2)==b'MZ'"
check 'build-dmg.sh' bash packaging/macos/build-dmg.sh
check 'dmg is an ISO 9660 image' /usr/bin/python3 -c \
    "assert open('$dmg','rb').read()[32769:32774]==b'CD001'"
if command -v xorriso >/dev/null 2>&1; then
    check 'dmg lists the installer app' bash -c \
        "xorriso -indev $dmg -ls 2>/dev/null | grep -q 'Install Cli Griderator.app'"
else
    check 'dmg contains the installer app name' /usr/bin/python3 -c "
data=open('$dmg','rb').read()
assert b'Install Cli Griderator' in data or b'INSTALL' in data
"
fi

if (( have_gi )); then
    check 'build-deb.sh builds' bash packaging/build-deb.sh
    check 'deb declares the VTE dependency' bash -c \
        "dpkg-deb -I $deb | grep -q gir1.2-vte-2.91"
    check 'deb carries every application module' bash -c \
        "for m in cligrid*.py; do dpkg-deb -c $deb | grep -q \"usr/lib/cligrid/\$m\" || exit 1; done"
else
    skip 'build-deb.sh (needs python3-gi with GdkPixbuf for the icons)'
fi

if (( have_gi )); then
    echo 'installed launcher, from the tarball'
    check 'extract' tar -xzf "$tarball" -C "$work"
    check 'install.sh --prefix' "$work/$root/install.sh" --prefix "$work/prefix"
    check 'launcher doctor with isolated desktop metadata reports 10 ok, 0 failed' \
        verify_launcher_doctor "$work/prefix"
    check 'launcher runs and reports the pyproject version' bash -c \
        "\"$work/prefix/bin/cligrid\" version | grep -qx 'cligrid $version'"
    check 'launcher survives deleting the extract' bash -c \
        "rm -rf -- '$work/$root' && \"$work/prefix/bin/cligrid\" version | grep -qx 'cligrid $version'"

    echo 'macos installer, driven by a stubbed uname and brew'
    shim=$work/shim
    bundle=$work/Applications/Cli\ Griderator.app
    mkdir -p "$shim"
    printf '#!/bin/sh\n[ "$1" = "-s" ] && { echo Darwin; exit 0; }\necho Darwin\n' > "$shim/uname"
    printf '#!/bin/sh\ncase "$*" in *"--prefix"*) echo %s/fakebrew ;; *) exit 0 ;; esac\n' "$work" > "$shim/brew"
    chmod +x "$shim/uname" "$shim/brew"
    check 'platform gate refuses a non-Mac' bash -c \
        'bash packaging/macos/install-macos.sh >/dev/null 2>&1; test $? -eq 1'
    check 'linux install.sh refuses a Mac' env PATH="$shim:$PATH" \
        bash -c 'bash install.sh --prefix "$1"; test $? -eq 1' _ "$work/should-not-install"
    check 'dispatcher on Linux runs the Linux installer' bash -c \
        "./install --bogus >/dev/null 2>&1; test \$? -eq 2"
    check 'installer runs to completion' env PATH="$shim:$PATH" bash packaging/macos/install-macos.sh \
        --prefix "$work/macos" --bundle-dir "$work/Applications" --no-font --no-verify
    check 'launcher is generated and valid shell' bash -n "$work/macos/bin/cligrid"
    check 'generated launcher runs the app' bash -c \
        "\"$work/macos/bin/cligrid\" version | grep -q '^cligrid '"
    check 'dock bundle written' test -f "$bundle/Contents/MacOS/cligrid"
    check 'bundle executable runs the app' bash -c \
        "\"$bundle/Contents/MacOS/cligrid\" version | grep -q '^cligrid '"
    check 'Info.plist parses and names the executable' /usr/bin/python3 -c "
import xml.etree.ElementTree as ET
root = ET.parse('$bundle/Contents/Info.plist').getroot()
pairs = {}
for parent in root.iter('dict'):
    children = list(parent)
    for index, child in enumerate(children):
        if child.tag == 'key' and index + 1 < len(children):
            pairs[child.text] = children[index + 1].text
assert pairs['CFBundleExecutable'] == 'cligrid', pairs
assert pairs['CFBundleIdentifier'] == 'com.konatus.cligrid', pairs
assert pairs['CFBundleName'] == 'Cli Griderator', pairs
"
else
    skip 'the installers end to end (needs a desktop GTK stack)'
fi

echo 'windows assets'
check 'terminal scheme matches cligrid_art.py exactly' /usr/bin/python3 -c "
import re, sys
sys.path.insert(0, '.')
import cligrid_art as art
text = open('packaging/windows/griderator-wt-scheme.ps1', encoding='utf-8').read()
scheme = dict(re.findall(r\"^\s{4}(\w+)\s+=\s+'#([0-9a-fA-F]{6})'\", text, re.M))
preset = art.theme_preset('griderator')
expected = {'background': preset['background'], 'foreground': preset['foreground'],
            'cursorColor': preset['cursor'], 'selectionBackground': preset['selection_bg']}
names = ['black','red','green','yellow','blue','purple','cyan','white',
         'brightBlack','brightRed','brightGreen','brightYellow','brightBlue',
         'brightPurple','brightCyan','brightWhite']
expected.update(dict(zip(names, preset['palette'])))
mismatch = {k: (v, expected[k]) for k, v in scheme.items() if expected[k].lstrip('#') != v}
assert len(scheme) == 20 and not mismatch, (len(scheme), mismatch)
"
check 'cligrid.cmd keeps the distro placeholder' bash -c \
    'grep -q __DISTRO__ packaging/windows/cligrid.cmd'
check 'installer writes cligrid.cmd and adds the user PATH' bash -c \
    'grep -q "cligrid.cmd" packaging/windows/install-windows.ps1 &&
     grep -q "SetEnvironmentVariable" packaging/windows/install-windows.ps1 &&
     grep -q "GetEnvironmentVariable(.Path., .User.)" packaging/windows/install-windows.ps1'
check 'installer detects WSLg and refuses WSL 1' bash -c \
    'grep -q /mnt/wslg packaging/windows/install-windows.ps1 &&
     grep -q "WSL 1" packaging/windows/install-windows.ps1'
check 'provisioner installs the VTE bindings and the Nerd Font' bash -c \
    'grep -q gir1.2-vte-2.91 packaging/windows/wsl-provision.sh &&
     grep -q nerd-fonts packaging/windows/wsl-provision.sh'

echo 'portability code'
check 'resident_mb has the macOS branch' bash -c \
    'grep -q ru_maxrss cligrid.py && grep -q "sys.platform == \"darwin\"" cligrid.py'
check 'desktop notifications fall back to osascript' bash -c \
    'grep -q "def osascript_notify" cligrid.py && grep -q "if osascript_notify(summary, body)" cligrid.py'
check 'macos installer talks to Finder when it has no tty' bash -c \
    'grep -q "display notification" packaging/macos/install-macos.sh &&
     grep -q "display dialog" packaging/macos/install-macos.sh &&
     grep -q CLIGRID_NO_UI packaging/macos/install-macos.sh'
check 'doctor carries a macOS check set' bash -c \
    'grep -q "def _macos_checks" cligrid_doctor.py && grep -q MACOS_BUNDLE cligrid_doctor.py'
check 'doctor accepts the Homebrew launcher path' bash -c \
    'grep -q ".local/bin/cligrid" cligrid_doctor.py'
check 'dispatcher names all three installers' bash -c \
    'grep -q install-macos.sh install && grep -q install.sh install &&
     grep -q install-windows.ps1 install'

printf '\nPLATFORM VERIFICATION: %d checks, %d failed\n' "$((pass + fail))" "$fail"
exit $(( fail > 0 ))
