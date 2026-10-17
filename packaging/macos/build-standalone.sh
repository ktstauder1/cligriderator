#!/usr/bin/env bash
# Homebrew is used on the builder only. Nothing is installed on the recipient's Mac.
set -euo pipefail
[[ $(uname -s) == Darwin ]] || {
    echo 'Build this self-contained application on macOS, not Linux.' >&2
    exit 1
}
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
command -v brew >/dev/null || { echo 'The build machine needs Homebrew; see STANDALONE.md.' >&2; exit 1; }
prefix=$(brew --prefix)
export PATH="$prefix/bin:$PATH"
export GI_TYPELIB_PATH="$prefix/lib/girepository-1.0"
export XDG_DATA_DIRS="$prefix/share"
for tool in tmux g-ir-compiler rsvg-convert iconutil hdiutil codesign; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool. See STANDALONE.md." >&2; exit 1; }
done
probe='import gi; gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91"); from gi.repository import Gtk, Vte'
python=
for candidate in "$prefix"/opt/python@*/bin/python3.* "$prefix/bin/python3"; do
    [[ ${candidate##*/} =~ ^python3(\.[0-9]+)?$ && -x $candidate ]] || continue
    if "$candidate" -c "$probe"; then python=$candidate; break; fi
done
[[ -n $python ]] || { echo 'No build Python can import GTK3 and VTE 2.91.' >&2; exit 1; }
mkdir -p "$root/packaging/.cache" "$root/packaging/dist"
build=$(mktemp -d "$root/packaging/.cache/standalone.XXXXXX")
export CLIGRID_BUILD_ROOT=$build
"$python" -m venv --system-site-packages "$build/venv"
python=$build/venv/bin/python3
"$python" -m pip install 'pyinstaller==6.22.3' 'ruff==0.17.1'
"$python" -c "$probe"
(cd "$root" && "$python" -m ruff check . && "$python" -B -m unittest test_cligrid_standalone)
"$python" "$root/packaging/macos/bundle_tools.py" notices "$build/notices"

mkdir -p "$build/cligrid.iconset"
for size in 16 32 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$root/icons/cligrid.svg" \
        -o "$build/cligrid.iconset/icon_${size}x${size}.png"
    double=$((size * 2))
    rsvg-convert -w "$double" -h "$double" "$root/icons/cligrid.svg" \
        -o "$build/cligrid.iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$build/cligrid.iconset" -o "$build/cligrid.icns"
export PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1
"$python" -m PyInstaller --noconfirm --clean --distpath "$build/dist" \
    --workpath "$build/work" "$root/packaging/macos/standalone.spec"

# Test the relocated copy that will go into the disk image, including spaces.
stage=$build/image
mkdir -p "$stage"
ditto "$build/dist/Cli Griderator.app" "$stage/Cli Griderator.app"
"$python" "$root/packaging/macos/bundle_tools.py" verify "$stage/Cli Griderator.app" "$prefix"
"$python" "$root/packaging/macos/grid_smoke.py" "$stage/Cli Griderator.app" "$prefix"
ln -s /Applications "$stage/Applications"
cp "$root/packaging/macos/INSTALL-STANDALONE.txt" "$stage/READ-ME.txt"
version=$("$python" "$root/packaging/version.py")
outfile="$root/packaging/dist/cligrid-$version-macos-$(uname -m)-standalone.dmg"
# Refuse to replace a previous artifact silently.
[[ ! -e $outfile ]] || { echo "Already exists: $outfile. Move it before rebuilding." >&2; exit 1; }
hdiutil create -volname 'Cli Griderator' -srcfolder "$stage" -format UDZO "$outfile"
hdiutil verify "$outfile"
(cd "$(dirname "$outfile")" && shasum -a 256 "$(basename "$outfile")" > "$(basename "$outfile").sha256")
printf 'Built %s\nBuild logs and runtime manifest: %s\n' "$outfile" "$build"
