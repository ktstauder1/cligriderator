# Self-contained macOS application

Native macOS packaging includes architecture checks and isolated runtime
tests. See `BUILD-REPORT.md` for the latest local results and remaining checks.
The older Linux-built `cligrid-4.3.0.dmg` still requires Homebrew.

## Contract

The recipient opens a real UDIF disk image, drags Cli Griderator.app to
Applications, and runs it without installing Homebrew, Python, GTK, VTE, or
tmux. The application carries its runtime. Existing Linux behavior and user
configuration remain intact. The bundled build uses macOS's Menlo font by
default; an existing configured font is respected.

Build on macOS for that machine's architecture. Homebrew is a build-time
dependency only. PyInstaller collects Python and native libraries; its GI
hooks collect GTK resources and typelibs, with an additional VTE hook.
`hdiutil` creates the disk image. Apple Silicon and Intel need separate builds
with matching dependencies. The workflow builds both architectures separately;
neither single-architecture DMG is a Universal app.

## Implementation and verification

1. Adapt frozen-process diagnostics and banner subprocesses, covered by unittest.
2. Collect the app, tmux, terminfo, GTK resources and dependency notices.
3. Validate Mach-O dependencies, relocate the bundle, test with a minimal PATH,
   run a real VTE shell smoke test, then create and verify the DMG.
4. Test installation and terminal interaction on a Mac without Homebrew.

Packaging lives here; regression tests live in `test_cligrid_standalone.py`.
Use Python snake_case, pathlib paths and checked subprocess calls, as in
`packaging/version.py`. No Linux runtime dependencies are added.

Build and tests:

```sh
# On the build Mac only:
brew install gtk+3 vte3 pygobject3 tmux ncurses gobject-introspection librsvg adwaita-icon-theme
bash packaging/macos/build-standalone.sh
python3 -B -m unittest test_cligrid_standalone
```

The builder creates a private Python environment, installs PyInstaller 6.22.3,
and keeps intermediate files in `packaging/.cache/standalone.*`. Output:
`packaging/dist/cligrid-<version>-macos-<architecture>-standalone.dmg` and a
SHA-256 sidecar. A previous image at that path must be moved before rebuilding.
The minimum macOS version is conservatively set to the builder's OS version.

The manual **Standalone macOS test build** GitHub Actions workflow is another
build route, using `macos-15` for Apple Silicon and `macos-15-intel` for Intel.
Each job verifies its CPU architecture and uploads separately named artifacts.
It uploads test artifacts; it does not publish a release. Open **Actions**,
select **Standalone macOS test build**, and choose **Run workflow**. Download
the resulting architecture-specific artifacts after both jobs finish.
Verified DMGs and their checksums can then be attached to a preview Release
for downloads without a GitHub account.

The build gate rejects non-system absolute dylib dependencies, external
rpaths, wrong-architecture native binaries, and symlinks escaping the app.
It verifies the ad-hoc signature and
runs version, diagnostics, banner, tmux-session and VTE shell checks from a
relocated app, with a minimal PATH and a macOS sandbox denying Homebrew reads.
`grid_smoke.py` also opens two real panes, runs shell commands, zooms and
restarts a pane, quits, and relaunches to verify tmux session persistence.
These tests use private configuration and tmux sockets. This still does not
replace testing Finder, Gatekeeper and interactive use on a clean Mac.

The standalone entry point caps the macOS process's soft file-descriptor
limit at 65,536, preserving its hard limit. VTE's Darwin `fdwalk` allocates a
stack buffer based on `sysconf(_SC_OPEN_MAX)`; inherited limits around a million
overflow the normal thread stack before the shell can execute. Regression
tests cover this startup fix. It does not change system-wide limits.
The bundle also opts out of Cocoa window persistence (`NSDisablePersistence`)
because workspace restoration is managed by Griderator itself. This avoids a
second restoration mechanism and modal recovery dialogs after a child crash.

Success requires a native build and clean-machine GUI verification, including
shell input/output, clipboard, pane restart, tmux persistence, and relaunch
after ejecting the DMG. Linux unit tests alone cannot establish this.

The first build is for local testing, with ad-hoc signing. Public distribution
also needs Developer ID signing/notarization and review of bundled libraries'
redistribution requirements. Do not publish or replace the existing download
until those checks pass.

References: [PyInstaller macOS support](https://pyinstaller.org/en/stable/feature-notes.html),
[GI hook configuration](https://pyinstaller.org/en/stable/hooks-config.html).
[GitHub macOS runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
