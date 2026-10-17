# Mac preview validation — October 17, 2026

Application version: 4.3.0. CPU: arm64. Minimum macOS: 27.0.1.
Built with Python 3.14.7, PyInstaller 6.22.3, GTK 3.24.52, VTE 0.84.1 and tmux 3.7c.

## Passed

- Source lint and 166 focused application, standalone and release tests.
- Architecture and dependency-path checks for all 128 bundled Mach-O files.
- Bundle symlink containment and deep, strict ad-hoc signature verification.
- Relocated version, doctor (10 checks), banner, tmux and VTE shell-output tests.
- Two-pane shell input/output, zoom, restart, quit and relaunch tests.
- Session persistence, including a shell variable retained across relaunch.
- The runtime tests above deny Homebrew reads and use a minimal PATH.
- DMG integrity and SHA-256 checksum verification.
- Installation from the DMG, ejection, and repeating the full-grid tests on
  the installed app with Homebrew access denied.

## Limitations

- No Intel artifact has been built or tested yet; the workflow is prepared.
- Ad-hoc signing only. Developer ID signing and notarization are pending.
- Clean-machine Finder/Gatekeeper, clipboard, and physical Intel testing are pending.
- The complete upstream suite is not green on this Mac: Linux archive privacy
  checks fail on BSD tar metadata, some platform-specific tests fail, and an
  oversized-request streaming test stalled. The focused tests above passed.

## Mac fixes included

The entry point caps the process's soft file-descriptor limit at 65,536 to
avoid VTE's Darwin `fdwalk` overflowing its stack before executing the shell.
It preserves the hard limit and does not change system settings. Panes search
their supplied PATH to find bundled tmux. The app opts out of Cocoa window
restoration because it manages its own workspace state.

The builder also fixes Homebrew dependency enumeration, handles binary
resources without assuming UTF-8, checks native architectures, uses VTE's
current text API, and tests the complete grid before creating a DMG.
