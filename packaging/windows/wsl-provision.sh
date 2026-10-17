#!/usr/bin/env bash
# Cli Griderator: provision inside WSL, the Linux distribution Windows runs.
#
# Called by install-windows.ps1, or by hand from a WSL shell:
#   bash wsl-provision.sh /mnt/c/Users/you/cligrid
#
# The grid is a GTK3 window with embedded VTE terminals. VTE has no Windows
# port (it needs a POSIX pty), so the Windows build is the Linux build running
# under WSL 2 with WSLg, which shows it as an ordinary Windows window.
set -euo pipefail

source_dir=${1:-}
if [[ -z $source_dir ]]; then
    echo 'usage: wsl-provision.sh <cligrid checkout, in WSL path form>' >&2
    exit 2
fi
source_dir=$(cd -- "$source_dir" && pwd -P)

install_font=1
while (( $# )); do
    case $1 in
        --no-font) install_font=0; shift ;;
        *) shift ;;
    esac
done

say() { printf '%s\n' "$*"; }

[[ -d /mnt/wslg ]] && say 'WSLg is present: grid windows appear on the Windows desktop.' \
    || say 'warning: /mnt/wslg is missing. Update WSL (wsl --update) for GUI windows; the grid needs a display.'

# ---- dependencies ----------------------------------------------------------
say 'Installing dependencies (sudo will ask for your WSL password once).'
sudo apt-get update
core=(python3-gi gir1.2-gtk-3.0 tmux)
if ! sudo apt-get install -y --no-install-recommends "${core[@]}" gir1.2-vte-2.91 fonts-jetbrains-mono; then
    say 'warning: the VTE bindings package was not found by that name; retrying without it.'
    sudo apt-get install -y --no-install-recommends "${core[@]}"
    say 'Install the VTE 2.91 typelib by hand (gir1.2-vte-2.91, or libvte-2.91-dev on some releases).'
fi

# ---- JetBrains Mono Nerd Font, the grid default ----------------------------
if (( install_font )); then
    font_dir=$HOME/.local/share/fonts/JetBrainsMonoNerdFont
    if [[ -d $font_dir ]]; then
        say 'Nerd Font already installed.'
    elif command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
        say 'Installing the JetBrains Mono Nerd Font'
        url=$(curl -fsSL --max-time 20 https://api.github.com/repos/ryanoasis/nerd-fonts/releases/latest \
              | python3 -c 'import json,sys
try:
    assets = json.load(sys.stdin).get("assets", [])
except Exception:
    raise SystemExit(0)
for asset in assets:
    if asset.get("name") == "JetBrainsMono.zip":
        print(asset.get("browser_download_url", ""))
        break' 2>/dev/null || true)
        if [[ -n $url ]]; then
            zip=$(mktemp)
            if curl -fsSL --max-time 120 "$url" -o "$zip"; then
                mkdir -p "$font_dir"
                unzip -o -q "$zip" -d "$font_dir" || true
                rm -f "$zip"
                command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true
                say "Font installed in $font_dir"
            else
                rm -f "$zip"
                say 'Font download failed; the grid will use a fallback. Pick a font in Settings.'
            fi
        else
            say 'Could not resolve the font release; skipping. Pick a font in Settings if the default looks wrong.'
        fi
    else
        say 'curl or unzip is missing; skipping the font. Pick a font in Settings if the default looks wrong.'
    fi
fi

# ---- application -----------------------------------------------------------
# Copy out of /mnt so the installed launcher does not depend on the Windows
# filesystem (slow over the 9p mount) and survives moving the checkout.
app_dir=$HOME/.local/share/cligrid
mkdir -p "$app_dir"
cp -f "$source_dir"/cligrid*.py "$app_dir"/
cp -f "$source_dir/cligrid.1" "$app_dir"/
cp -Rf "$source_dir/icons" "$app_dir"/
cp -f "$source_dir/install.sh" "$app_dir"/
chmod 755 "$app_dir/install.sh"
say "Installed $app_dir"

bash "$app_dir/install.sh"

# ---- verify ----------------------------------------------------------------
say ''
say 'Environment check:'
"$HOME/bin/cligrid" doctor || true
say ''
say 'Start the grid with: cligrid   (or the Windows launcher: cligrid.cmd)'
