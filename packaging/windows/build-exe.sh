#!/usr/bin/env bash
# Cli Griderator: build the Windows installer .exe from Linux.
#
# Prefers makensis (a proper installer UI). If NSIS is not installed, builds
# a 7-Zip SFX from the official extra module: a real Windows PE that unpacks
# the payload and runs install-windows.ps1.
set -euo pipefail
umask 022

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
dist=$source_dir/packaging/dist
version=$(/usr/bin/python3 "$source_dir/packaging/version.py")
root=cligrid-$version
tarball=$dist/$root.tar.gz
outfile=$dist/$root.exe
cache=${CLIGRID_PACKAGING_CACHE:-$source_dir/packaging/.cache}

if [[ ! -f $tarball ]]; then
    bash "$source_dir/packaging/linux/build-tarball.sh"
fi

stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
tar -xzf "$tarball" -C "$stage"
payload=$stage/$root
[[ -f $payload/cligrid.py ]] || { echo "missing payload in $tarball" >&2; exit 1; }

cat > "$payload/setup.cmd" <<'CMD'
@echo off
setlocal
cd /d "%~dp0"
echo Cli Griderator
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\windows\install-windows.ps1" -Source "%~dp0"
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  echo.
  echo Install reported an error. See the messages above.
  pause
  exit /b %ERR%
)
echo.
echo Done. Open a new terminal and run: cligrid
pause
CMD

assert_pe() {
    /usr/bin/python3 -c "
from pathlib import Path
path = Path('$outfile')
data = path.read_bytes()[:2]
assert data == b'MZ', data
assert path.stat().st_size > 20000, path.stat().st_size
"
}

if command -v makensis >/dev/null 2>&1; then
    license=$stage/LICENSE.txt
    /usr/bin/python3 -c "
from pathlib import Path
text = Path('$source_dir/LICENSE').read_text(encoding='utf-8')
Path('$license').write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
"
    icon=
    if command -v rsvg-convert >/dev/null 2>&1; then
        icon=$stage/cligrid.ico
        /usr/bin/python3 - "$source_dir/icons/cligrid.svg" "$icon" <<'PY'
import struct, subprocess, sys
from pathlib import Path

svg, dest = sys.argv[1], sys.argv[2]
pngs = []
for size in (16, 32, 48, 256):
    raw = subprocess.check_output(["rsvg-convert", "-w", str(size), "-h", str(size), svg])
    pngs.append((size, raw))
offset = 6 + 16 * len(pngs)
entries, body = [], b""
for size, raw in pngs:
    entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(raw), offset))
    body += raw
    offset += len(raw)
Path(dest).write_bytes(struct.pack("<HHH", 0, 1, len(pngs)) + b"".join(entries) + body)
PY
        cp -- "$icon" "$payload/icons/cligrid.ico"
    fi
    args=(
        -DVERSION="$version"
        -DOUTFILE="$outfile"
        -DPAYLOAD="$payload"
        -DLICENSEFILE="$license"
    )
    [[ -n $icon ]] && args+=(-DICONFILE="$icon")
    makensis -V2 "${args[@]}" "$source_dir/packaging/windows/cligrid.nsi"
    assert_pe
    printf 'Built %s (NSIS)\n' "$outfile"
    exit 0
fi

command -v 7z >/dev/null 2>&1 || {
    echo 'error: need makensis (apt install nsis) or 7z (p7zip) to build the .exe' >&2
    exit 1
}

mkdir -p "$cache"
sfx=$cache/7zS.sfx
if [[ ! -f $sfx ]]; then
    extra=$cache/7z-extra.7z
    # Official 7-Zip extra package: Windows SFX modules. Cached after first fetch.
    # 9.20 extra still ships 7zS.sfx. Current 7-Zip extra packages dropped it.
    url=${CLIGRID_7Z_EXTRA_URL:-https://sourceforge.net/projects/sevenzip/files/7-Zip/9.20/7z920_extra.7z/download}
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$extra" "$url"
    else
        wget -q -O "$extra" "$url"
    fi
    7z e -y -o"$cache" "$extra" 7zS.sfx >/dev/null
    [[ -f $sfx ]] || { echo "7zS.sfx missing from $url" >&2; exit 1; }
    /usr/bin/python3 -c "
assert open('$sfx','rb').read(2)==b'MZ'
"
fi

archive=$stage/payload.7z
7z a -t7z -mx=9 "$archive" "$payload/." >/dev/null
config=$stage/config.txt
# No $version interpolation: the config language treats $ as its own syntax.
/usr/bin/python3 - "$version" "$config" <<'PY'
from pathlib import Path
import sys
version, dest = sys.argv[1], sys.argv[2]
Path(dest).write_text(
    ";!@Install@!UTF-8!\r\n"
    f'Title="Cli Griderator {version}"\r\n'
    'BeginPrompt="Install Cli Griderator? This copies the app and sets it up inside WSL 2. You need Windows 10 or 11 with WSL 2 and WSLg."\r\n'
    'ExecuteFile="setup.cmd"\r\n'
    ";!@InstallEnd@!\r\n",
    encoding="utf-8",
)
PY
cat -- "$sfx" "$config" "$archive" > "$outfile"
assert_pe
printf 'Built %s (7-Zip SFX)\n' "$outfile"
