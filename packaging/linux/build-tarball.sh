#!/usr/bin/env bash
# Cli Griderator: build the portable source archive for Linux, macOS, and Windows.
#
# There is nothing to compile. The archive carries the application, the three
# platform installers, and the icons. Runtime dependencies (GTK3, VTE, tmux)
# come from the destination OS.
set -euo pipefail
umask 022

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
dist=$source_dir/packaging/dist
version=$(/usr/bin/python3 "$source_dir/packaging/version.py")

# Every application module, by glob: a hand-written list once left a module
# out of every artifact. Tests are test_*.py, so cligrid*.py is exactly the app.
modules=("$source_dir"/cligrid*.py)
[[ -f $source_dir/cligrid.py ]] || { echo "missing cligrid.py" >&2; exit 1; }

root=cligrid-$version
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
payload=$stage/$root
mkdir -p "$payload/packaging/macos" "$payload/packaging/windows" "$dist"

for module in "${modules[@]}"; do
    install -m 644 -- "$module" "$payload/${module##*/}"
done
install -m 644 -- "$source_dir/cligrid.1" "$payload/cligrid.1"
install -m 644 -- "$source_dir/README.md" "$payload/README.md"
install -m 644 -- "$source_dir/CHANGELOG.md" "$payload/CHANGELOG.md"
install -m 644 -- "$source_dir/LICENSE" "$payload/LICENSE"
install -m 644 -- "$source_dir/pyproject.toml" "$payload/pyproject.toml"
install -m 644 -- "$source_dir/packaging/PLATFORMS.md" "$payload/packaging/PLATFORMS.md"
install -m 644 -- "$source_dir/packaging/version.py" "$payload/packaging/version.py"
mkdir -p "$payload/packaging/aur"
install -m 644 -- "$source_dir/packaging/aur/PKGBUILD" "$payload/packaging/aur/PKGBUILD"
install -m 755 -- "$source_dir/install.sh" "$payload/install.sh"
install -m 755 -- "$source_dir/install" "$payload/install"
install -m 755 -- "$source_dir/packaging/macos/install-macos.sh" \
    "$payload/packaging/macos/install-macos.sh"
install -m 644 -- "$source_dir/packaging/windows/install-windows.ps1" \
    "$payload/packaging/windows/install-windows.ps1"
install -m 644 -- "$source_dir/packaging/windows/cligrid.cmd" \
    "$payload/packaging/windows/cligrid.cmd"
install -m 755 -- "$source_dir/packaging/windows/wsl-provision.sh" \
    "$payload/packaging/windows/wsl-provision.sh"
install -m 644 -- "$source_dir/packaging/windows/griderator-wt-scheme.ps1" \
    "$payload/packaging/windows/griderator-wt-scheme.ps1"
cp -R -- "$source_dir/icons" "$payload/icons"

cat > "$payload/INSTALL-NOTES.txt" <<'NOTES'
Cli Griderator — Linux, macOS, Windows
======================================

One archive, three installers. From the extracted directory:

    Linux     ./install
              or: ./install.sh

    macOS     ./install
              or: packaging/macos/install-macos.sh
              Homebrew is required: https://brew.sh

    Windows   powershell -ExecutionPolicy Bypass -File packaging\windows\install-windows.ps1
              Needs WSL 2 and WSLg. VTE has no native Windows port.

After install:

    cligrid doctor     check the environment, no window opened
    cligrid            start the grid

Linux dependencies (already on a normal desktop): GTK3, VTE 0.76 or newer
(gir1.2-vte-2.91), tmux, python3-gi, Python 3.10 or newer.

    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91 tmux

After any of the three installs the application lives in
~/.local/share/cligrid (or PREFIX/share/cligrid). The archive can be deleted.

Free for personal and commercial use under the terms in LICENSE.
Official downloads:
https://kuttystauder.com/development/

The default theme is "griderator". Details: packaging/PLATFORMS.md
NOTES

# Archive metadata is public too: never include the build machine's account.
tar --owner=0 --group=0 --numeric-owner -C "$stage" -czf "$dist/$root.tar.gz" "$root"
/usr/bin/python3 - "$stage/$root" "$dist/$root.zip" <<'PY'
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root.parent).as_posix())
PY
count=$(tar -tzf "$dist/$root.tar.gz" | wc -l)
printf 'Built %s and %s (%s tarball entries)\n' \
    "$dist/$root.tar.gz" "$dist/$root.zip" "$count"
