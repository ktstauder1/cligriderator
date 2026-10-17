# Changelog

## 4.3.0 — 2026-09-18

### Added
- Shortcuts editor: Ctrl+Shift+/ edits the keymap, refuses prefix collisions
  and duplicate keys, and writes only the override diff to `config.json`.
- Settings: prefix key and control-guard controls, with screen-reader names
  on the remaining unlabeled switches, combos, banner buttons and search Go.
- `cligrid_keymap.py`: merge, diff, invert, conflict detection.
- Twenty-pane soak in the suite; Broadway `--self-test` with 20 panes when
  `broadwayd` is installed.
- pipx metadata (`readme`, homepage URL) and `packaging/aur/PKGBUILD`.
- macOS installer: Finder progress notifications and a stop dialog on error.
- `docs/gtk4-spike.md`; `cligrid doctor` reports whether Gtk 4 / Vte 3.91
  typelibs are on disk without failing when they are not.

## 4.2.0 — 2026-09-18

### Security
- Refuse `reset`, `all`, `remove`, `quit` and their aliases when the request
  comes from inside a pane (a coding agent, typically). Override with
  `--force` after the verb, or set `"guard": "off"`.
- Bound control-socket request size and `wait` pattern length. A slow
  `events` reader is dropped instead of stalling the window.

### Fixed
- `cligrid all` quotes pane names that contain spaces, so a pane called
  `Build logs` keeps that session name.
- `dump` reads tmux scrollback, not only the visible VTE screen.
- Removing a pane answers any `wait` on it at once.
- `state.json` is written atomically; the window log is trimmed at launch.

### Changed
- Dispatch is a verb table, so adding a command cannot grow a 48-branch chain.
- Help, the man page and `cligrid help <verb>` are held to `control.VERBS`.
- `ruff check .` runs in CI.
- New `high-contrast` theme.
- Agents can drive the grid through the control API; see `docs/agent-skill.md`.

## 4.1.1 — 2026-09-13

### Security
- Remove the build account name and user/group IDs from portable archive metadata.
- Publish fresh versioned download URLs and checksums for the privacy-corrected release.

### Changed
- Add scrolling controls for the toolbar pane selector.

## 4.1.0 — 2026-09-12

### Changed
- Added a toolbar font-family selector and automatic font sizing that adapts to the window, pane layout, and zoom without restarting sessions.
- Added workspace menu actions to save the current setup, save it under a new name, and rename it for later use.
- Refined the workspace with graphite surfaces, platinum text, a champagne accent, spectrum pane badges, and precise focus outlines.
- Concentrated colored glow on focused panes and alerts, with quiet toolbar controls and a neutral command center that adapts to shorter windows.
- Enlarged pane controls and command-palette rows, improved typography, and added a title-bar command-search button.

## 4.0.1 — 2026-09-12

### Fixed
- Offline reset and subset broadcast respect the selected panes. Invalid selections are rejected before sessions or settings change.
- A failed control connection no longer retries a potentially destructive command offline.
- Wait commands honor positional and zero-second timeouts and reject invalid timeout values safely.
- Generated tmux commands preserve pane names containing spaces.
- Git branch labels support worktrees and submodules.
- Windows provisioning passes checkout paths directly, including names with apostrophes.
- macOS setup discovers Homebrew when launched outside a terminal.

### Security
- Control sockets are created with owner-only permissions even with a permissive system umask.

### Changed
- Updated product page, installation guidance, and download presentation.
- macOS and Windows installer packages remain unsigned; native platform smoke testing is pending.

## 4.0.0 (2026-09-12)

The 4.0 feature work, the interface craft pass, and the Linux, macOS and
Windows installers, cut as one downloadable release.

### Release

- Tagging `vX.Y.Z` runs the tests and the platform checks, builds
  `cligrid-X.Y.Z.tar.gz`, `cligrid-X.Y.Z.zip`, `cligrid_X.Y.Z_all.deb`,
  `cligrid-X.Y.Z.exe` and `cligrid-X.Y.Z.dmg`, writes `SHA256SUMS`, and
  publishes a GitHub Release. The tag must equal the version in
  `pyproject.toml`.
- Consumer Windows and macOS downloads are now an installer `.exe` (NSIS,
  runs the WSL provisioner) and a `.dmg` (HFS+ hybrid with an installer
  app). Homebrew is still required on the Mac. There is still no native
  Windows VTE build.
- `pyproject.toml` is the one place the version lives: `cligrid version`, the
  Debian control file, the macOS `Info.plist`, the artifact names and CI all
  read it. The application reported `4.0` while every artifact said `4.0.0`.
- New `test_cligrid_release.py` fails the build when a module is missing from
  `pyproject.toml` or a packager, when the version is hardcoded anywhere, or
  when the changelog has no section for the version being shipped.

### Fixed

- Every artifact was dead on arrival: the tarball, the zip, the Debian package
  and the macOS bundle built from them all failed on `import cligrid_palette`,
  because three hand-written module lists were never updated. Packagers now
  copy `cligrid*.py` by glob, and `verify-platforms.sh` checks that every
  application module is inside the tarball and the deb.
- A built `.deb` was tracked in git while `packaging/dist/` was ignored.
- The Linux installer left the launcher pointing at the unzipped folder, so
  deleting the archive broke the app. It now copies `cligrid*.py` into
  `~/.local/share/cligrid` (or `PREFIX/share/cligrid`) and aims the launcher
  there, same as macOS and Windows. The archive can be deleted after install.
- The published license is no longer MIT. Use stays free of charge; the
  source, name and artwork stay with Kutty Stauder / Konatus Research Group.
  Official copies come from https://kuttystauder.com/development/.
- The release archive omitted `pyproject.toml`, so the macOS installer could
  not read the version from an extracted download. The tarball now carries
  `pyproject.toml`, `LICENSE`, `CHANGELOG.md` and `packaging/version.py`.
- tmux printed `bad colour: #{@blue}` into every pane when the user's
  `~/.tmux.conf` styled colour-only options with `#{@name}` formats. Each pane
  session is now restyled with literal hex from the active theme, its status
  bar is turned off (the grid's title strip already shows the same facts), and
  its messages follow the theme instead of tmux's default yellow bar.

### Interface craft pass

Craft, not features. The grid keeps its behaviour and gains the finish: one
motion scale, elevation, a feedback channel, and a palette that ranks.

### Feedback

- A toast layer over the grid says what just happened: theme, layout and
  workspace switches, paste-into-every-pane, run-in-all, and every command the
  window refuses. Failures are no longer silent for a caller driving the grid
  over the socket.
- `cligrid notify <text>` posts a message to the person at the grid, and the
  `toast` event kind carries it to `events` subscribers.
- Toasts slide up, stack three deep, and pass clicks through to the panes.

### Command palette

- New `cligrid_palette.py`: subsequence scoring with word-start, adjacency and
  case bonuses, a leading-offset penalty, deterministic ranking, section
  grouping, and match spans. GTK-free, with its own test file.
- The palette groups rows under ACTION, PANE, WORKSPACE, THEME and LAYOUT
  headings, picks the matched letters out of each label, floats recently run
  rows to the top, and shows a key-hint footer with a row count.
- The card fades and slides open instead of appearing at once.

### Chrome

- One easing curve and three durations drive every transition: hover, focus,
  pane elevation, the switcher, scrollbars and overlays.
- Pane cards sit on a layered board: an ambient shadow when idle, an accent
  ring and a soft glow when focused, and a gradient on the title strip.
- The alert pulse animates the pane's box shadow, so a bell breathes instead
  of snapping.
- The header bar names the active workspace; clicking it lists every workspace
  and switches.
- Tertiary text moved from 3.7:1 to 5.0:1 contrast against the board; every
  theme is checked by loading the generated stylesheet into a real GTK parser.

### Fixed

- `cligrid status --json` reported `toolbar_px` as the window height minus the
  grid height, a negative number. It now reports the header bar's height.
- An invalid `max-width` rule made GTK reject the entire stylesheet, which
  would have dropped the window back to an unstyled build.

### Linux, macOS and Windows installs

- `./install` picks the installer for this machine. Linux and macOS run
  in place; Windows prints (or launches) the PowerShell installer.
- `packaging/linux/build-tarball.sh` builds `cligrid-4.0.0.tar.gz` and
  `cligrid-4.0.0.zip` with the source and all three platform installers;
  the Debian package build is unchanged.
- `packaging/macos/install-macos.sh` installs Homebrew's gtk+3, vte3,
  pygobject3 and tmux, picks the Python that can import Gtk 3 and Vte 2.91,
  writes a launcher with the Homebrew paths and typelib directory baked in, and
  builds `~/Applications/Cli Griderator.app` for the Dock.
- `packaging/windows/install-windows.ps1` installs the same application inside
  WSL 2 and WSLg, copies it out of `/mnt` so the launcher survives moving the
  checkout, and adds `cligrid.cmd` to the Windows PATH.
- `griderator-wt-scheme.ps1` imports the grid's palette into Windows Terminal.
- Portability fixes in the application: `resident_mb` reads `resource` on macOS,
  desktop notifications go through `osascript` where there is no session D-Bus,
  and `cligrid doctor` has a macOS check set and accepts a session that sets
  `DISPLAY` or `WAYLAND_DISPLAY` without `XDG_SESSION_TYPE` (WSLg).

### Tests

279 tests across nine suites, plus `packaging/verify-platforms.sh` (42 checks:
the artifacts, the installed launchers, the macOS installer driven by a
stubbed `uname` and `brew`, the Windows assets). `--self-test` reports the
window, grid and per-pane geometry on the new stylesheet.

## 4.0

Five new modules, each with its own test file, plus a rewritten control channel.

### Workspaces

Named pane sets in `~/.config/cligrid/config.json`, schema 2. `ws new agents`,
`ws save`, `ws rename old new`, `ws rm agents`, `ws next`. Switching writes the
live pane list first, then rebuilds the window on the target list; tmux sessions
in both workspaces keep running because only the clients are detached. A schema 1
config migrates on read and keeps every pane and preference.

### Layout

`layout` accepts auto, master, `1xN`, `Nx1`, `2x2` through `4x2`, and remembers
the choice per workspace. `stack 1 2` puts panes in one cell as tabs; focusing
either one brings it to the front. The geometry lives in cligrid_layout.py.

### Control API

New verbs: `send`, `run`, `dump`, `wait --until`, `events`, `watch`, `find`,
`state`, `keymap`, `doctor`, `log`, `stack`, `move`, `rename`, `layout`, `theme`,
`ws`, `palette`, and subset broadcast (`all --panes 1,3 htop`). `wait` and
`events` hold their connection open and answer later. `CLIGRID_SOCKET` runs a
second grid on its own socket.

### Window

- Command palette (Ctrl+Shift+P) over every action, pane, workspace, theme and
  layout.
- Agent state per pane (idle, running, waiting, exited, failed) as a title-strip
  badge, a waiting count in the header, jump to the next blocked pane, and a
  desktop notification only when a pane asks.
- Title strip shows the git branch beside the directory.
- Themes: the house palette plus eight stock ones, applied to terminals and
  chrome together, switchable at runtime and remembered.
- Search every pane, paste into every pane, restore the last arrangement on
  launch, notify rules per pane, quiet hours.
- Remappable keymap with a two-stroke prefix mode, screen reader names on every
  icon button, and the resident memory reported in `status`.
- The state poll reads a pane only when VTE marked it dirty, so an idle grid of
  twenty panes costs almost nothing.

### Tooling

`install.sh`, `cligrid.1`, `pyproject.toml` for pipx, a GitHub Actions workflow,
and `packaging/build-deb.sh` producing `cligrid_4.0.0_all.deb`.

### Fixed

- `send` and `run` failed with a TypeError: VTE's `feed_child` takes the text
  alone through GI.
- Startup crashed on GTK3, where `set_accessible_name` does not exist.
- An unknown theme name reset the setting to the fallback instead of leaving it.
- Panes showed an empty directory until the shell reported one.
- Multi-word text sent from the client was split on the way to the server.
- VTE's per-call deprecation warning filled `~/.cache/cligrid.log`.

## 3.3

Attention alerts: panes that ring the bell pulse, background panes with new
output are marked, and Ctrl+Shift+A goes to the next one.

## 3.0

UI polish, an adaptive grid, and the header bar as the window's only chrome.
