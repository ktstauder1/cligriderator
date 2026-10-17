# Cli Griderator

## Linux downloads

[Download Cli Griderator 4.3.0 for Linux](https://github.com/ktstauder1/cligriderator/releases/tag/linux-v4.3.0).

**Debian, Ubuntu, and Pop!_OS:** download
[`cligrid_4.3.0_all.deb`](https://github.com/ktstauder1/cligriderator/releases/download/linux-v4.3.0/cligrid_4.3.0_all.deb),
then run this from the download directory:

```bash
sudo apt install ./cligrid_4.3.0_all.deb
cligrid
```

**Other Linux distributions:** download
[`cligrid-4.3.0.tar.gz`](https://github.com/ktstauder1/cligriderator/releases/download/linux-v4.3.0/cligrid-4.3.0.tar.gz).
Install Python 3.10 or newer, PyGObject, GTK3, VTE 0.76 or newer, and tmux
using your distribution's package manager, then run:

```bash
tar -xzf cligrid-4.3.0.tar.gz
cd cligrid-4.3.0
./install
~/bin/cligrid
```

The archive installer runs as your normal desktop user and installs into your
home directory. The Linux packages use system dependencies; they are not
self-contained executables. Download `SHA256SUMS` from the same release to
verify your files with `sha256sum -c SHA256SUMS --ignore-missing`.

## Mac downloads

[Download the Mac preview](https://github.com/ktstauder1/cligriderator/releases/tag/macos-v4.3.0-preview.1)
or browse [all releases](https://github.com/ktstauder1/cligriderator/releases).
Choose the `.dmg` under **Assets**; GitHub's automatic source-code ZIP is for
developers and is not an application installer.

| Download | Processor | Minimum macOS | Status |
| --- | --- | --- | --- |
| `cligrid-4.3.0-macos-arm64-standalone.dmg` | Apple Silicon (M-series) | 27.0.1 | Local preview build verified |
| Intel standalone DMG | Intel (x86_64) | Determined by the build runner | Build pending |

### Download and install

1. Choose **Apple menu > About This Mac**. This preview requires an Apple
   Silicon (M-series) Mac running **macOS 27.0.1 or newer**. Intel Macs and older
   macOS versions are not supported by this download.
2. [Download the Apple Silicon installer (.dmg)](https://github.com/ktstauder1/cligriderator/releases/download/macos-v4.3.0-preview.1/cligrid-4.3.0-macos-arm64-standalone.dmg),
   or open the release page above and choose that file under **Assets**.
   Do not choose **Source code (zip)** or **Source code (tar.gz)**.
3. Open the downloaded `.dmg` in Finder and drag **Cli Griderator.app** into
   **Applications**.
4. Eject the disk image, open **Applications**, and double-click
   **Cli Griderator**. If macOS blocks it, follow the steps below.

The standalone app includes Python, GTK, VTE and tmux; no Homebrew or separate
Python installation is needed. Tools you run inside its terminals are installed
separately.

### Allow this preview in macOS Settings

This preview is **not Developer ID signed or notarized by Apple**. Only proceed
if you trust this project's official download and accept the preview's risks.
Approval is not a security certification.

1. Try opening the installed app first. If macOS says the developer cannot be
   verified or Apple cannot check the app for malicious software, dismiss the
   alert without moving the app to Trash.
2. Choose **Apple menu > System Settings > Privacy & Security**.
3. Scroll to **Security**, find the message about **Cli Griderator**, and click
   **Open Anyway**.
4. Authenticate if prompted, then choose **Open** in the confirmation dialog.

Future launches of that approved copy should open normally. If **Open Anyway**
is missing, try opening the installed app again and return to Settings; the
option is normally available for about an hour after a blocked launch. On a
managed work or school Mac, contact your administrator if approval is disabled.

Do **not** disable Gatekeeper globally or remove quarantine with Terminal
commands. If macOS reports that the app **will damage your computer**, contains
malware, or is **damaged**, stop rather than bypassing that warning. Report the
exact message through [GitHub Issues](https://github.com/ktstauder1/cligriderator/issues)
without including secrets or private terminal output.

See Apple's [safe-opening guidance](https://support.apple.com/en-us/102445) and
[app-specific approval instructions](https://support.apple.com/guide/mac-help/open-an-app-by-overriding-security-settings-mh40617/mac).

**Preview status:** the Mac app is ad-hoc signed, not Developer ID signed or
notarized. Gatekeeper may block a downloaded copy. Clean-machine testing is
still pending; this is not a notarized production release. The Apple Silicon
download does not run on Intel Macs.

For build instructions and verification details, see
[Standalone macOS](packaging/macos/STANDALONE.md) and
[Mac build report](packaging/macos/BUILD-REPORT.md). GitHub Actions includes
separate Apple Silicon and Intel builds.

This repository and its Releases are designated official distribution
locations under section 4 of [LICENSE](LICENSE). The application remains
freeware under that license; making the source visible does not relicense it
as open source. Bundled third-party components retain their own licenses.

## About

Up to twenty terminals in one window, in the grid's own dark palette (six by
default). Each pane is a persistent tmux session, so work survives hide,
restart, and quit. Rows beyond the first two sit below the visible grid; scroll
or use the header-bar arrows to reach them.

Built for Pop!_OS 24.04 with COSMIC on Wayland, where `wmctrl` and `xdotool`
do not exist and the compositor will not hand a foreign window to another app.
The grid therefore owns its terminals rather than adopting existing ones.

## Install locations

    ~/.local/share/cligrid/cligrid.py               the application after `./install`
    ~/bin/cligrid                                   launcher / control client
    the checkout                                    source; install copies it out so the
                                                    extract or checkout can move or go
    ~/.local/share/applications/cligrid.desktop     app launcher entry
    ~/.local/share/icons/hicolor/scalable/apps/cligrid.svg        app icon (from icons/cligrid.svg)
    ~/.local/share/icons/hicolor/{16x16,24x24,32x32}/apps/cligrid.png   small sizes (from icons/cligrid-N.svg)
    ~/Desktop/cli-griderator.desktop                copy of the launcher entry for the desktop
    ~/.config/cligrid/config.json                   settings (created on first change)

The small icon sizes are separate pixel-aligned drawings. To rebuild them after
editing `icons/`, render each `icons/cligrid-N.svg` to an N×N PNG in the matching
hicolor folder and copy `icons/cligrid.svg` to `scalable/apps`.

No dependencies beyond what the desktop already ships: GTK3, VTE 0.76
(`gir1.2-vte-2.91`), tmux, python3-gi.

## Linux, macOS, Windows

One source tree, three installs, one palette. The details, and what was verified
where, are in `packaging/PLATFORMS.md`.

    Any       ./install                         picks the installer for this machine
    Linux     install.sh                        native, GTK3 + VTE + tmux
              packaging/linux/build-tarball.sh  portable tar.gz + zip, no root
              packaging/build-deb.sh            Debian package
              pipx install .                    Python modules only; GTK/VTE/tmux
                                                still come from the system
              packaging/aur/PKGBUILD            Arch system package
    macOS     packaging/macos/install-macos.sh  native, dependencies via Homebrew,
                                                plus an application bundle for the Dock
                                                Finder progress and an error dialog when
                                                launched without a terminal
    Windows   packaging/windows/install-windows.ps1
                                                the Linux build under WSL 2 + WSLg,
                                                launched from Windows with cligrid.cmd

The release archive (`cligrid-<version>.tar.gz` or `.zip`) is the same source
for all three. Extract it and run `./install`, or on Windows run the PowerShell
script above.

Official consumer downloads and the license live at
https://kuttystauder.com/development/. Free for personal and commercial use
under the terms in LICENSE.

### Legacy cross-platform downloads

The legacy cross-platform release workflow publishes these files. Its plain
`cligrid-<version>.dmg` requires Homebrew; the standalone Mac preview above is
a different download.

    cligrid-<version>.exe          Windows installer (WSL 2 + WSLg)
    cligrid-<version>.dmg          macOS disk image (Homebrew required)
    cligrid-<version>.tar.gz       Linux and macOS: extract, ./install
    cligrid-<version>.zip          the same archive, for Windows
    cligrid_<version>_all.deb      Debian and Ubuntu: sudo apt install ./cligrid_<version>_all.deb
    SHA256SUMS                     verify: sha256sum -c SHA256SUMS --ignore-missing

A release is cut by tagging: `git tag v4.1.0 && git push --tags`. The Release
workflow refuses a tag that differs from the version in `pyproject.toml`,
runs the tests and `packaging/verify-platforms.sh`, builds the four files and
publishes them. To build them locally instead:

    bash packaging/verify-platforms.sh        # builds and checks everything
    ls packaging/dist/

`cligrid version` prints the same version; `test_cligrid_release.py` fails
when any file disagrees, or when a module is missing from an artifact.

VTE needs a POSIX pty and has no Windows port, so there is no native Windows
build: on Windows the grid runs inside WSL and WSLg shows it as a Windows
window. On macOS it is the same source with Homebrew's GTK3, VTE, pygobject3 and
tmux. `cligrid doctor` reports which of the two environments it is running in.

Windows Terminal users can also import the grid's palette as a colour scheme:

    powershell -ExecutionPolicy Bypass -File packaging\windows\griderator-wt-scheme.ps1

## Use

    cligrid                 start, or raise the grid if it is already running
    cligrid toggle          minimize / restore the grid
    cligrid show | hide
    cligrid zoom [N|off]    one pane fills the window; N focuses pane N
    cligrid focus N         focus pane N
    cligrid swap A B        swap the panes in positions A and B
    cligrid restart [N]     reconnect pane N, or the focused pane (sessions kept)
    cligrid reset           end every pane's session and start empty terminals
    cligrid reset N         same, for pane N only   (fresh / new still work)
    cligrid panes N         set the pane count, 1-20 (default 6)
    cligrid all <command>   run one command in every pane, replacing their sessions
                            example: cligrid all htop
    cligrid remove [N]      remove pane N, or the focused pane
    cligrid fit             re-apply the configured fit
    cligrid status          summary in a terminal; JSON when piped or with --json
    cligrid --help          colored overview of every command
    cligrid notify <text>   post a message to the person at the grid, as a toast
    cligrid quit            quit (tmux sessions keep running)

The rest of the control API: `send N <text>`, `run N <cmd>`, `dump N [--lines K]`
(scrollback included for tmux panes), `wait N --until <regex>`, `events`,
`watch`, `find`, `state`, `keymap`, `log`, `doctor`, `palette`, `ws`, `theme`,
`layout`, `stack`, `move`, `rename`, and subset broadcast (`cligrid all --panes
1,3 htop`). `cligrid help <verb>` explains one verb; `cligrid events --kinds
toast,exit` streams what happens. A client that stops reading `events` is
disconnected once it holds a megabyte of unread output, so a stuck script
cannot stall the window.

Agents inside the grid can drive it too, since every pane carries
`CLIGRID=1`. Commands that end work (`reset`, `all`, `remove`, `quit` and
their aliases) are refused when they come from inside a pane, unless
`--force` follows the verb: `cligrid reset --force 2`. The refusal shows as a
toast. `"guard": "off"` in the config turns this off.

The header bar is the window's only bar:

    Zoom                    fill the window with the focused pane
    default                 the active workspace; click it to switch
    1 2 3 … +               pane switcher; + adds a pane, right-click a number to remove it
    74×15 · 8pt             focused pane size and the current font size
    ☰                       run in all panes, reset all, fit, settings, shortcuts, about, quit

Pane title strips show the pane number, name, and working directory. Their
zoom, find, and ⋮ buttons appear on the focused or hovered pane.

Mouse:

    drag a pane title onto another pane    swap the two panes
    double-click a pane title              zoom that pane
    right-click a pane, or its ⋮ button    zoom, find, copy/paste, rename, edit command,
                                           attach tmux, restart, reset, remove
    Shift+wheel                            scroll the grid
    Ctrl-click a URL                       open the link

Keys, all pressed with Ctrl+Shift:

    Left/Right/Up/Down      move focus between panes
    1..9 / 0                focus pane 1-10
    Page Up / Page Down     scroll to more panes
    Z                       zoom the focused pane
    A                       jump to a pane that rang its bell or has new output
    E                       run one command in every pane…
    N                       reset all panes…
    R                       reset the focused pane…
    -                       remove the focused pane
    C / V                   copy / paste (Ctrl+C copies a selection; Ctrl+V pastes)
    G                       find in the focused pane
    F                       re-fit
    W                       hide the grid
    ,                       settings
    /                       shortcuts
    Q                       quit

Anything running inside a pane survives a crash, a restart, or `cligrid quit`,
because every pane is a tmux client. Reattach from any terminal with
`tmux attach -t g3`. **Reset** and **Run in all panes** are the exceptions:
they end those sessions, so the grid asks first (Enter cancels a reset).

A pane whose command exits is started again in place. If it exits within two
seconds of starting three times in a row, the pane stops and shows the exit
status with Restart and Edit command buttons instead of looping.

## Layout

Panes fill rows of up to three: 1, 2, and 3 panes share one row, 4 is a 2×2
grid, and 5 is three over two. A short last row stretches so there are no
empty cells. Beyond six panes, extra rows scroll.

## Alerts

When a pane you are not looking at rings its terminal bell, its border, title
dot and switcher number blink in the pane's color until you focus it. A quieter
underline on the switcher number marks panes that printed new output; the
clock in tmux's status line does not count. Ctrl+Shift+A jumps to the next
pane that needs you.

While the grid is not the focused window, a bell also sends a desktop
notification, at most one per pane every 30 seconds. Clicking it shows the
pane. Settings → Alerts turns each of these off.

Claude Code rings the bell only when its notifications go to the terminal
bell: inside claude, open `/config` and set notifications to the terminal bell.

## Feedback, and the command palette

An action that changes something says so. A toast slides up over the bottom of
the grid for a theme, layout or workspace switch, for a paste into every pane,
and for anything the window refuses: a bad verb over the socket, a number out
of range, a theme that does not exist. Toasts stack three deep, pass clicks
through to the panes underneath, and stay for about three seconds. `cligrid
notify <text>` raises one from any script, and `events` subscribers see the
same message as a `toast` event.

The command palette (Ctrl+Shift+P) ranks rather than filters: letters that
appear in order match, a match at a word start scores higher, and the matched
letters are picked out in the accent colour. Rows are grouped under ACTION,
PANE, WORKSPACE, THEME and LAYOUT headings, the last few rows you ran float to
the top while the filter is empty, and the footer shows the keys and how many
rows the filter kept. Up and Down move, Enter runs, Escape closes.

## Colors, motion and the welcome banner

Pane positions take their colors from the grid's own palette: 1 blue, 2 plum,
3 teal, 4 green, 5 brass, 6 red, then repeating. The color marks the pane
number, a strip along its title, its border when focused, and its switcher
button. An exited pane turns red.

When a pane creates a new tmux session (not when it reattaches to one), it
prints the Cli Griderator logo with the pane number and session name, then
starts the configured command or a login shell. Turn it off in Settings →
Welcome banner, or with `"banner": false` in the config.

`cligrid --help` and `cligrid status` use the same logo and colors in a
terminal. Output is plain when piped, `NO_COLOR=1` turns color off, and
errors go to stderr with exit status 1.

## Config: ~/.config/cligrid/config.json

Written on first change, with these defaults. The Settings window edits the
same file.

    fit            "maximized"     maximized | workarea | "WxH"
    font           "JetBrainsMono Nerd Font"
    min_cols       60              column floor per pane
    min_rows       15              row floor per pane
    scrollback     10000
    cursor_blink   false
    banner         true            ASCII welcome when a pane starts a new session
    bell_alerts    true            blink a background pane that rings its bell
    activity_marks true            mark background panes with new output
    notify_desktop true            desktop notification for a bell while unfocused
    guard          "panes"         refuse reset/all/remove/quit from inside a pane; "off"
    cwd            $HOME
    pane_count     6               panes on screen, 1-20
    panes          pane_count entries, each {"name": ..., "cmd": ...}
                   default cmd: tmux new-session -A -s gN

`min_cols` is the practical dial. Font size is selected automatically between
7 and 22 points for the current window, layout, and zoom. Use the toolbar font
selector to change the family. Legacy `font_size`, `min_font_size`, and
`auto_font` settings are retained in existing files but no longer control sizing. Set `panes[n].cmd` to anything, for
example `htop`, or `tmux new-session -A -s codex` to attach an existing session.

The grid ships its own palette: graphite (`#15171b`), platinum
text and a champagne accent, with sixteen terminal colours tuned to read on it. That
is the `griderator` theme, the default, and no published terminal theme shares
it. `cligrid theme set <name>` switches at runtime; `cligrid theme list` shows
the presets, including `high-contrast`. Set `theme` to `kitty` in the config to inherit colours from
`~/.config/kitty/kitty.conf` instead, or to any of the stock presets (Tokyo
Night, Gruvbox, Nord, Dracula, Catppuccin, Solarized, high-contrast).

The window chrome (header bar, pane cards, dialogs, menus, toasts) derives
from the active palette, and its stylesheet sits above COSMIC's generated
gtk.css so the system accent does not leak in. One easing curve and three
durations (`MOTION_FAST`, `MOTION_BASE`, `MOTION_SLOW`) drive every transition,
the focused pane gets an accent ring and a soft glow over an ambient shadow,
and an alerted pane's pulse animates its shadow so the blink breathes. The
window is a layered board: the board itself carries a gradient, and each pane is
a card on it. Every generated stylesheet is loaded into a real GTK CSS parser by
the test suite, because a single unsupported property makes GTK reject the whole
sheet and the window falls back to an unstyled build. Font family, size and scrollback come from
`~/.config/cligrid/config.json`; padding and copy-on-select follow kitty.conf
when it exists. COSMIC on Wayland cannot embed a real kitty window inside
another app, so each cell is VTE running the grid's colours.

## Design constraints on COSMIC / Wayland

Verified by experiment on this machine, not assumed:

1. `gtk_window_resize()` is ignored outright after the window is mapped.
2. Before mapping, the window takes the child natural size; a `set_size_request`
   on the grid is honored at map time and fixes the window size.
3. `maximize()` works and is the only runtime way to change the window size.
4. `Gdk.Monitor.get_workarea()` reports the full screen and does not subtract
   COSMIC's panel or dock, so a workarea-sized window has its bottom row hidden
   behind the dock. Compositor maximize does subtract them, hence the default
   `fit: "maximized"` (a 1366x648 frame on a 1366x768 screen here: the 45px
   header bar plus 603px of grid). GTK keeps its 35px shadow margins in the
   surface even when maximized, so `window_px` in `cligrid status` reads wider
   than the screen; `headerbar_px` and `scroller_px` are the visible sizes.
5. Font metrics do not scale linearly with point size, so the auto font sizes
   each candidate size with Pango and corrects against VTE's actual grid.
6. VTE installs its own `padding: 1px` style at application priority, which
   beats an application stylesheet at the same priority; the grid's stylesheet
   is installed one step above user priority.

Consequence: after moving the window to a different monitor, relaunch it to pick
up that monitor's geometry. `cligrid fit` re-requests the size, which X11
sessions honor and Wayland sessions ignore.

## Test

    python3 -m unittest discover -p 'test_*.py'     # from the checkout

`test_cligrid_stream.py` drives the control socket with real client
processes, including one that never reads; `test_cligrid_headless.py`
starts the whole grid under GTK's Broadway backend and is skipped when
`broadwayd` is not installed. `ruff check .` runs the lint rules in
`pyproject.toml`; CI runs both.

`--self-test` builds the grid, runs for three seconds, prints JSON with the
window, grid, and per-pane geometry, then exits. It only works when no grid is
running; otherwise the command is sent to the running instance.
