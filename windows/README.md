# Cli Griderator for Windows

Native Windows edition using Electron, xterm.js and Windows ConPTY. The installer
bundles the application runtime and terminal libraries. Users do not install
Homebrew, WSL, Python, Node.js, Visual Studio or a package manager.

Target: **Windows 10 1903 or newer / Windows 11, x64 (Intel or AMD)**.
Windows on ARM is not a verified target of this build.

## Downloads and installation

The **Standalone Windows build** GitHub Actions workflow produces:

- `Cligriderator-4.3.0-windows-x64-Setup.exe`: offline per-user installer, with
  Start-menu and desktop shortcuts. No administrator access is required.
- `Cligriderator-4.3.0-windows-x64.zip`: portable application folder. Extract the
  entire archive, then open `Cli Griderator.exe`; keep its accompanying files.
- `SHA256SUMS.txt`: download checksums.

Artifacts are uploaded only after the packaged and installed applications pass
real Windows shell tests with development tools removed from PATH. Download the
`cligriderator-windows-x64` artifact from a successful workflow run. GitHub artifact
downloads require signing in. No automatic public release is made by this workflow.

The initial build is unsigned; Windows may display an unknown-publisher prompt.
Code signing is separate from bundling dependencies.

## Use

Six terminals open initially; add up to twenty per workspace. PowerShell and
Command Prompt come with Windows. Use a pane's **···** menu to set its name,
starting folder and startup command. Restart the pane to apply command changes.
Third-party programs (Codex, Claude Code, Git, Python, etc.) are not included and
need their own installation and credentials. The grid itself operates offline.

- Add/remove, rename, restart, drag-to-swap and zoom panes.
- Automatic, master and explicit row/column layouts, with scrolling for extra rows.
- Named workspaces; switching keeps existing terminal processes and displays alive.
- Search terminal scrollback, copy/paste, and Ctrl-click web links.
- Four themes, font selection, font size, scrollback and cursor settings.
- Activity markers, terminal-bell notifications, command palette and keyboard shortcuts.
- Send a command to all panes after reviewing a confirmation.

**Closing the window hides it to the system tray and keeps terminals running.**
Double-click the tray icon or launch the app again to show it. **Exit and stop
terminals** ends the processes. Settings, workspace layouts and startup commands
are saved; live processes and scrollback do not survive an application exit,
application-process crash, logout or reboot. This differs from the Linux tmux edition.

Saved settings are in `%APPDATA%/Cli Griderator/settings.json` (Electron's per-user
application data location). Terminal output is retained in memory only. Do not put
API keys in startup commands: those commands are saved as ordinary local settings.
Uninstalling retains settings. No telemetry, external CDN or local network server is used.

## Scope relative to the Linux edition

This is a separate Windows terminal implementation; it does not execute GTK/VTE
or use a hidden WSL installation. Linux control-socket commands, tmux attach and
crash persistence, stacked pane tabs, custom keymap editing, quiet-hour notification
rules and automatic font fitting are not implemented here. Existing Linux/macOS
configuration files are not imported. These differences must remain visible in
release notes; this build is not a claim of complete Linux feature parity.

## Build and verify (developers only)

From this folder on a Windows build machine with Node.js 22.12+:

```powershell
npm ci --ignore-scripts
node node_modules/electron/install.js
npm run check
npm test
npm run build
npx playwright install chromium
npm run test:ui
npm run dist
./scripts/verify-windows.ps1 -Executable 'out/win-unpacked/Cli Griderator.exe'
```

The lockfile pins dependencies. node-pty 1.2.0-beta.14 ships Windows x64 Node-API prebuilds;
the package preserves the native modules and their helpers outside the ASAR archive.
This exact node-pty prerelease includes the upstream Windows handle-race fix
(microsoft/node-pty#922); 1.1.0 crashed during concurrent terminal shutdown.
The app uses the included ConPTY DLL and waits for shell-exit callbacks at shutdown.
Do not turn on native rebuilds or remove helpers without testing the installed app.
Third-party notices are generated from the installed runtime dependencies.

UI tests run Chromium with a mock desktop bridge; they do not prove Windows shell
compatibility. The separate runtime test launches real shells from the packaged
application and verifies input/output, resizing and renderer isolation. GitHub
runs both and also installs the EXE into a directory containing spaces.

## Architecture and source references

- `src/model.js`: validated settings, workspace transitions and layout geometry.
- `src/sessions.js`: terminal processes and bounded replay buffers.
- `src/main.js`: isolated Electron window, validated IPC, system tray and persistence.
- `src/pane.js`, `src/renderer.js`: terminal rendering and desktop interactions.
- `scripts/`: build, notices, icons and packaged runtime verification.

Upstream references: [Electron security](https://www.electronjs.org/docs/latest/tutorial/security),
[node-pty](https://github.com/microsoft/node-pty), [xterm.js](https://xtermjs.org/),
[NSIS packaging](https://www.electron.build/nsis/).

Dependency audit: the initial full development dependency audit reports a moderate
`sprintf-js` denial-of-service advisory through electron-builder's proxy logger.
It is not included in the application runtime. CI checks runtime dependencies at
moderate severity; updating the build toolchain should re-evaluate this advisory.
