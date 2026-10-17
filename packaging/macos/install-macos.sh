#!/usr/bin/env bash
# Cli Griderator: install on macOS.
#
# The grid is GTK3 plus VTE plus tmux. All three ship through Homebrew with
# macOS builds, so the same source runs unchanged: no port, no fork. This
# script installs the dependencies, the application, a launcher, and an
# application bundle you can put in the Dock.
#
#   packaging/macos/install-macos.sh [--prefix DIR] [--no-font] [--no-verify]
#
# Homebrew: https://brew.sh
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
prefix=${CLIGRID_PREFIX:-$HOME/.local}
bundle_root=${CLIGRID_BUNDLE_DIR:-$HOME/Applications}
install_font=1
verify=1

usage() {
    cat <<'USAGE'
Usage: install-macos.sh [--prefix DIR] [--bundle-dir DIR] [--no-font] [--no-verify]

  --prefix DIR       install under DIR (default ~/.local)
  --bundle-dir DIR   write the .app bundle under DIR (default ~/Applications)
  --no-font          skip the JetBrains Mono Nerd Font cask
  --no-verify        skip the dependency check at the end
USAGE
}

while (( $# )); do
    case $1 in
        --prefix)
            if (( $# < 2 )) || [[ -z $2 ]]; then
                echo 'Usage: install-macos.sh [--prefix DIR]' >&2
                exit 2
            fi
            prefix=$2
            shift 2
            ;;
        --bundle-dir)
            if (( $# < 2 )) || [[ -z $2 ]]; then
                echo 'Usage: install-macos.sh [--bundle-dir DIR]' >&2
                exit 2
            fi
            bundle_root=$2
            shift 2
            ;;
        --no-font) install_font=0; shift ;;
        --no-verify) verify=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }

# Finder (no tty) gets progress notifications and a stop dialog on failure.
# osascript is only present on a real Mac, so the Linux platform stub stays quiet.
ui=0
if [[ -z ${CLIGRID_NO_UI:-} ]] && [[ ! -t 1 ]] && command -v osascript >/dev/null 2>&1; then
    ui=1
fi

as_quote() {
    local s=$1
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    printf '"%s"' "$s"
}

notify_ui() {
    (( ui )) || return 0
    osascript -e "display notification $(as_quote "$1") with title \"Cli Griderator\"" >/dev/null 2>&1 || true
}

dialog_ui() {
    (( ui )) || return 0
    osascript -e "display dialog $(as_quote "$1") buttons {\"OK\"} default button 1 with title \"Cli Griderator\" with icon stop" >/dev/null 2>&1 || true
}

progress() {
    printf '%s\n' "$*"
    notify_ui "$*"
}

die() {
    printf 'error: %s\n' "$*" >&2
    dialog_ui "$*"
    exit 1
}

[[ $(uname -s) == Darwin ]] || die 'this installer is for macOS; on Linux use install.sh'
# Finder does not inherit a terminal's shell initialization.
if ! command -v brew >/dev/null 2>&1; then
    for brew_bin in /opt/homebrew/bin /usr/local/bin; do
        if [[ -x $brew_bin/brew ]]; then
            export PATH="$brew_bin:$PATH"
            break
        fi
    done
fi
command -v brew >/dev/null 2>&1 || die 'Homebrew is required: https://brew.sh (install it, then re-run this script)'

brew_prefix=$(brew --prefix)
progress "Homebrew: $brew_prefix"

# ---- dependencies ----------------------------------------------------------
formulas=(gtk+3 vte3 pygobject3 tmux)
missing=()
for formula in "${formulas[@]}"; do
    brew list --formula "$formula" >/dev/null 2>&1 || missing+=("$formula")
done
if (( ${#missing[@]} )); then
    progress "Installing: ${missing[*]}"
    say 'A formula with no bottle for this macOS version builds from source and can take a long time.'
    brew install "${missing[@]}"
else
    say 'Dependencies already installed.'
fi

if (( install_font )); then
    if ! brew list --cask font-jetbrains-mono-nerd-font >/dev/null 2>&1; then
        say 'Installing the JetBrains Mono Nerd Font (the grid default font)'
        brew install --cask font-jetbrains-mono-nerd-font || \
            say 'Font cask failed; the grid will use a fallback. Pick a font in Settings.'
    fi
fi

# ---- homebrew environment, resolved once and baked into the launcher -------
typelib_dir=$brew_prefix/lib/girepository-1.0
schema_dir=$brew_prefix/share/glib-2.0/schemas
pixbuf_cache=
if pixbuf_prefix=$(brew --prefix gdk-pixbuf 2>/dev/null); then
    candidate=$pixbuf_prefix/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache
    [[ -f $candidate ]] && pixbuf_cache=$candidate
fi

# ---- the Python that can actually see GTK and VTE -------------------------
export GI_TYPELIB_PATH="$typelib_dir${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
export XDG_DATA_DIRS="$brew_prefix/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

probe='import gi; gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91"); from gi.repository import Gtk, Vte; print("ok")'
python=
for candidate in \
    "$brew_prefix"/opt/python@3.14/bin/python3.14 \
    "$brew_prefix"/opt/python@3.13/bin/python3.13 \
    "$brew_prefix"/bin/python3 \
    /usr/bin/python3; do
    [[ -x $candidate ]] || continue
    if "$candidate" -c "$probe" >/dev/null 2>&1; then
        python=$candidate
        break
    fi
done
[[ -n $python ]] || die "no Python can import GTK 3 and VTE 2.91. Check the install with:
  $brew_prefix/bin/python3 -c '$probe'
If that fails, reinstall the bindings: brew reinstall pygobject3 vte3 gtk+3"
progress "Python: $python"

# ---- application files -----------------------------------------------------
app_dir=$prefix/share/cligrid
mkdir -p "$app_dir" "$prefix/bin" "$HOME/.config/cligrid"
# Every application module, by glob, so a new module cannot be left out.
for module in "$source_dir"/cligrid*.py; do
    install -m 644 "$module" "$app_dir/${module##*/}"
done
version=$("$python" "$source_dir/packaging/version.py")
install -m 644 "$source_dir/cligrid.1" "$app_dir/cligrid.1"
cp -R "$source_dir/icons" "$app_dir/icons"
progress "Installed $app_dir"

# ---- launcher --------------------------------------------------------------
launcher=$prefix/bin/cligrid
cat > "$launcher" <<LAUNCHER
#!/usr/bin/env bash
# Cli Griderator launcher, written by install-macos.sh. Opens the grid, or
# talks to the running instance, exactly like the Linux launcher.
set -eu
HOMEBREW_PREFIX='$brew_prefix'
CLIGRID_PYTHON='$python'
export PATH="\$HOMEBREW_PREFIX/bin:\$PATH"
export GI_TYPELIB_PATH='$typelib_dir'\${GI_TYPELIB_PATH:+:\$GI_TYPELIB_PATH}
export XDG_DATA_DIRS="\$HOMEBREW_PREFIX/share:\${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export GSETTINGS_SCHEMA_DIR='$schema_dir'
$( [[ -n $pixbuf_cache ]] && printf 'export GDK_PIXBUF_MODULE_FILE=%q\n' "$pixbuf_cache" )
export TERM=xterm-256color
exec "\$CLIGRID_PYTHON" '$app_dir/cligrid.py' "\$@"
LAUNCHER
chmod 755 "$launcher"
progress "Installed $launcher"

# ---- application bundle ----------------------------------------------------
bundle="$bundle_root/Cli Griderator.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
cat > "$bundle/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Cli Griderator</string>
    <key>CFBundleDisplayName</key>
    <string>Cli Griderator</string>
    <key>CFBundleIdentifier</key>
    <string>com.konatus.cligrid</string>
    <key>CFBundleExecutable</key>
    <string>cligrid</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$version</string>
    <key>CFBundleVersion</key>
    <string>$version</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST
cp "$launcher" "$bundle/Contents/MacOS/cligrid"
chmod 755 "$bundle/Contents/MacOS/cligrid"
cp "$source_dir/icons/cligrid.svg" "$bundle/Contents/Resources/cligrid.svg"

if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$bundle/Contents/Info.plist" >/dev/null || die 'the generated Info.plist is invalid'
fi

# An .icns needs an SVG rasteriser; it is cosmetic, so it stays best effort.
if command -v rsvg-convert >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
    iconset=$(mktemp -d)
    if rsvg-convert -w 512 -h 512 "$source_dir/icons/cligrid.svg" -o "$iconset/icon.png" 2>/dev/null; then
        for size in 16 32 64 128 256 512; do
            sips -z "$size" "$size" "$iconset/icon.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null 2>&1 || true
        done
        mkdir -p "$iconset/cligrid.iconset"
        for size in 16 32 128 256 512; do
            cp "$iconset/icon_${size}x${size}.png" "$iconset/cligrid.iconset/icon_${size}x${size}.png" 2>/dev/null || true
            cp "$iconset/icon_${size}x${size}.png" "$iconset/cligrid.iconset/icon_${size}x${size}@2x.png" 2>/dev/null || true
        done
        iconutil -c icns "$iconset/cligrid.iconset" -o "$bundle/Contents/Resources/cligrid.icns" 2>/dev/null || true
    fi
    rm -rf "$iconset"
fi
progress "Installed $bundle"

# ---- verify ----------------------------------------------------------------
if (( verify )); then
    say ''
    say 'Environment check:'
    "$launcher" doctor || true
    say ''
    say "Add $prefix/bin to PATH if it is not there already, then run: cligrid"
    say "Dock: drag $bundle into the Dock."
    progress "Cli Griderator is installed."
else
    say "Run: $launcher"
fi
