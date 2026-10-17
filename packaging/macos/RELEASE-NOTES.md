Cli Griderator 4.3.0 — standalone Mac preview

## Download

Download `cligrid-4.3.0-macos-arm64-standalone.dmg` from Assets.
This build requires **Apple Silicon and macOS 27.0.1 or newer**.
The source-code ZIP/TAR downloads are not app installers.

Open the DMG, drag Cli Griderator.app into Applications, eject the image,
and open the installed app. Homebrew and a separate Python installation are
not required. The app includes GTK, VTE and tmux.

## Preview limitations

- Ad-hoc signed, not Developer ID signed or notarized. Gatekeeper may block
  this downloaded app; this is a testing preview.
- Intel builds are being prepared and are not included in this release.
- Clean-machine Finder/Gatekeeper and clipboard validation remain pending.

## Verification

The installed app passed shell input/output, zoom, pane restart and tmux
session persistence across relaunch after ejecting the DMG, with Homebrew
access blocked. All 128 native binaries passed architecture/dependency checks,
and 166 focused tests passed. See `packaging/macos/BUILD-REPORT.md` for details
and the broader suite's known failures.

Verify the download in Terminal with:

```sh
shasum -a 256 -c cligrid-4.3.0-macos-arm64-standalone.dmg.sha256
```

The application retains its freeware license. Third-party library notices
and the build dependency inventory are included inside the app bundle.
