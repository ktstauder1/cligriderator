#!/usr/bin/env bash
# Cli Griderator: build the macOS disk image from Linux.
#
# Prefers xorriso (HFS+ hybrid). Without it, writes a Joliet/Rock Ridge ISO
# that Finder still mounts when the file is named .dmg.
# Double-click "Install Cli Griderator" to run install-macos.sh. Homebrew
# is still required; this is not a self-contained GTK bundle.
set -euo pipefail
umask 022

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
dist=$source_dir/packaging/dist
version=$(/usr/bin/python3 "$source_dir/packaging/version.py")
root=cligrid-$version
tarball=$dist/$root.tar.gz
outfile=$dist/$root.dmg

have_xorriso=0
command -v xorriso >/dev/null 2>&1 && have_xorriso=1
iso_python=/usr/bin/python3
cache=${CLIGRID_PACKAGING_CACHE:-$source_dir/packaging/.cache}
if (( ! have_xorriso )); then
    if ! "$iso_python" -c 'import pycdlib' >/dev/null 2>&1; then
        venv=$cache/iso-venv
        if [[ ! -x $venv/bin/python3 ]]; then
            mkdir -p "$cache"
            /usr/bin/python3 -m venv "$venv"
            "$venv/bin/python3" -m ensurepip --upgrade >/dev/null 2>&1 || true
            "$venv/bin/python3" -m pip install --quiet pycdlib
        fi
        iso_python=$venv/bin/python3
    fi
    "$iso_python" -c 'import pycdlib' >/dev/null 2>&1 || {
        echo 'error: need xorriso (apt install xorriso) or pycdlib' >&2
        exit 1
    }
fi

if [[ ! -f $tarball ]]; then
    bash "$source_dir/packaging/linux/build-tarball.sh"
fi

stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
vol=$stage/volume
payload=$vol/Cli\ Griderator
app=$vol/Install\ Cli\ Griderator.app
mkdir -p "$payload" "$app/Contents/MacOS" "$app/Contents/Resources"

tar -xzf "$tarball" -C "$stage"
cp -a "$stage/$root"/. "$payload"/
[[ -f $payload/cligrid.py ]] || { echo "missing payload in $tarball" >&2; exit 1; }

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Install Cli Griderator</string>
    <key>CFBundleDisplayName</key>
    <string>Install Cli Griderator</string>
    <key>CFBundleIdentifier</key>
    <string>com.konatus.cligrid.installer</string>
    <key>CFBundleExecutable</key>
    <string>install</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$version</string>
    <key>CFBundleVersion</key>
    <string>$version</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.utilities</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

cat > "$app/Contents/MacOS/install" <<'EXEC'
#!/bin/bash
# Opens Terminal-less install: Homebrew, then the grid, then a Dock app.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd -P)
# Contents/MacOS -> volume root -> payload
root=$(cd -- "$here/../../.." && pwd -P)
payload="$root/Cli Griderator"
if [[ ! -x $payload/packaging/macos/install-macos.sh ]]; then
    osascript -e 'display dialog "This disk image is incomplete. Download it again from kuttystauder.com/development/" buttons {"OK"} default button 1' >/dev/null 2>&1 || true
    echo "missing $payload/packaging/macos/install-macos.sh" >&2
    exit 1
fi
exec /bin/bash "$payload/packaging/macos/install-macos.sh"
EXEC
chmod 755 "$app/Contents/MacOS/install"
cp -- "$source_dir/icons/cligrid.svg" "$app/Contents/Resources/cligrid.svg"
cp -- "$source_dir/LICENSE" "$vol/LICENSE.txt"

cat > "$vol/README.txt" <<README
Cli Griderator $version for macOS
=================================

Double-click "Install Cli Griderator". Homebrew is required
(https://brew.sh). The installer pulls gtk+3, vte3, pygobject3 and tmux,
then writes a Dock app under ~/Applications.

If macOS says the app is from an unidentified developer: right-click it,
choose Open, then Open again.

After install:  cligrid doctor
                cligrid

Official copies: https://kuttystauder.com/development/
README

if (( have_xorriso )); then
    xorriso -as mkisofs \
        -V "Cli Griderator" \
        -hfsplus \
        -apm-block-size 2048 \
        -hfsplus-file-creator-type APPL APPL \
        -chmod 0755 /Install\ Cli\ Griderator.app/Contents/MacOS/install -- \
        -chmod 0755 /Cli\ Griderator/install -- \
        -chmod 0755 /Cli\ Griderator/install.sh -- \
        -chmod 0755 /Cli\ Griderator/packaging/macos/install-macos.sh -- \
        -o "$outfile" \
        "$vol"
    method=xorriso
else
    "$iso_python" "$source_dir/packaging/macos/write_iso.py" \
        --volume "Cli Griderator" "$vol" "$outfile"
    method=iso
fi

/usr/bin/python3 -c "
from pathlib import Path
path = Path('$outfile')
assert path.stat().st_size > 20000, path.stat().st_size
data = path.read_bytes()
assert data[32769:32774] == b'CD001', data[32769:32775]
"
printf 'Built %s (%s)\n' "$outfile" "$method"
