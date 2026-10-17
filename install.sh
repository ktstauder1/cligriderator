#!/usr/bin/env bash
set -euo pipefail

if (( EUID == 0 )); then
    echo 'install.sh refuses to run as root; run as your desktop user.' >&2
    exit 1
fi
if [[ $(uname -s) == Darwin ]]; then
    echo 'On macOS use ./install or packaging/macos/install-macos.sh.' >&2
    exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
prefix=$HOME
while (( $# )); do
    case $1 in
        --prefix)
            if (( $# < 2 )) || [[ -z $2 ]]; then
                echo 'Usage: install.sh [--prefix DIRECTORY]' >&2
                exit 2
            fi
            prefix=$2
            shift 2
            ;;
        *) echo 'Usage: install.sh [--prefix DIRECTORY]' >&2; exit 2 ;;
    esac
done
mkdir -p -- "$prefix"
prefix=$(cd -- "$prefix" && pwd -P)
# Copy the application out of the extract / checkout so deleting that folder
# does not break the launcher. A HOME prefix uses ~/.local/share (FHS user
# data); any other prefix uses PREFIX/share, matching the macOS installer.
if [[ $prefix == "$HOME" ]]; then
    app_dir=$HOME/.local/share/cligrid
else
    app_dir=$prefix/share/cligrid
fi
mkdir -p -- "$app_dir"
if [[ $source_dir != "$app_dir" ]]; then
    for module in "$source_dir"/cligrid*.py; do
        install -m 644 -- "$module" "$app_dir/${module##*/}"
    done
    if [[ -f $source_dir/cligrid.1 ]]; then
        install -m 644 -- "$source_dir/cligrid.1" "$app_dir/cligrid.1"
    fi
fi
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT

# Generate everything before changing installed files.
printf '#!/usr/bin/env bash\nexec /usr/bin/python3 %q "$@"\n' \
    "$app_dir/cligrid.py" > "$stage/cligrid"
/usr/bin/python3 - "$prefix/bin/cligrid" > "$stage/cligrid.desktop" <<'PY'
import sys
path = sys.argv[1]
# Exec quoting has both desktop-string and command-line escaping layers.
path = path.replace("%", "%%")
path = "".join("\\" + c if c in '\\"`$' else c for c in path)
path = path.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
print('[Desktop Entry]\nType=Application\nName=Cli Griderator')
print('Comment=Persistent terminal grid\nExec="' + path + '"')
print('Icon=cligrid\nTerminal=false\nCategories=System;TerminalEmulator;')
print('StartupWMClass=cligrid')
PY
for icon in "$source_dir"/icons/cligrid-*.svg; do
    size=${icon##*/cligrid-}
    size=${size%.svg}
    [[ $size =~ ^[0-9]+$ ]] || continue
    /usr/bin/python3 - "$icon" "$stage/cligrid-$size.png" "$size" <<'PY'
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

install_file() {
    local source=$1 target=$2 mode=$3
    if [[ -f $target ]] && cmp -s -- "$source" "$target"; then
        if [[ $(stat -c '%a' -- "$target") != "$mode" ]]; then
            chmod "$mode" -- "$target"
            printf 'Updated mode: %s\n' "$target"
        fi
        return
    fi
    mkdir -p -- "$(dirname -- "$target")"
    install -m "$mode" -- "$source" "$target"
    printf 'Installed: %s\n' "$target"
}
install_file "$stage/cligrid" "$prefix/bin/cligrid" 755
install_file "$stage/cligrid.desktop" "$prefix/.local/share/applications/cligrid.desktop" 644
install_file "$stage/cligrid.desktop" "$prefix/Desktop/cli-griderator.desktop" 755
install_file "$source_dir/icons/cligrid.svg" \
    "$prefix/.local/share/icons/hicolor/scalable/apps/cligrid.svg" 644
for icon in "$stage"/cligrid-*.png; do
    size=${icon##*/cligrid-}
    size=${size%.png}
    install_file "$icon" "$prefix/.local/share/icons/hicolor/${size}x${size}/apps/cligrid.png" 644
done
install_file "$source_dir/cligrid.1" "$prefix/.local/share/man/man1/cligrid.1" 644
