#!/usr/bin/env bash
set -euo pipefail
umask 022
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
root=$stage/cligrid
version=$(/usr/bin/python3 "$source_dir/packaging/version.py")
mkdir -p "$root/DEBIAN" "$root/usr/bin" "$root/usr/lib/cligrid" \
    "$root/usr/share/applications" "$root/usr/share/man/man1"
cat > "$root/DEBIAN/control" <<CONTROL
Package: cligrid
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: Cli Griderator contributors <cligrid@localhost>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-vte-2.91, tmux
Description: GTK3 and VTE terminal grid
 Persistent tmux terminals in a single desktop window.
CONTROL
# Every application module, by glob, so a new module cannot be left out.
for module in "$source_dir"/cligrid*.py; do
    install -m 644 "$module" "$root/usr/lib/cligrid/${module##*/}"
done
cat > "$root/usr/bin/cligrid" <<'LAUNCHER'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/cligrid/cligrid.py "$@"
LAUNCHER
chmod 755 "$root/usr/bin/cligrid"
cat > "$root/usr/share/applications/cligrid.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Cli Griderator
Comment=Persistent terminal grid
Exec=/usr/bin/cligrid
Icon=cligrid
Terminal=false
Categories=System;TerminalEmulator;
StartupWMClass=cligrid
DESKTOP
install -m 644 "$source_dir/cligrid.1" "$root/usr/share/man/man1/cligrid.1"
gzip -n "$root/usr/share/man/man1/cligrid.1"
icon_root=$root/usr/share/icons/hicolor
mkdir -p "$icon_root/scalable/apps"
install -m 644 "$source_dir/icons/cligrid.svg" "$icon_root/scalable/apps/cligrid.svg"
for icon in "$source_dir"/icons/cligrid-*.svg; do
    size=${icon##*/cligrid-}
    size=${size%.svg}
    [[ $size =~ ^[0-9]+$ ]] || continue
    mkdir -p "$icon_root/${size}x${size}/apps"
    /usr/bin/python3 - "$icon" "$icon_root/${size}x${size}/apps/cligrid.png" "$size" <<'PY'
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
try:
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        sys.argv[1], int(sys.argv[3]), int(sys.argv[3]), True)
    pixbuf.savev(sys.argv[2], "png", [], [])
except Exception as exc:
    raise SystemExit("Icon rendering requires GdkPixbuf SVG support: " + str(exc))
PY
done
mkdir -p "$source_dir/packaging/dist"
dpkg-deb --root-owner-group --build "$root" "$source_dir/packaging/dist/cligrid_${version}_all.deb"
