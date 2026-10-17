Cli Griderator 4.3.0 — standalone Mac preview

## Download

1. Check **Apple menu > About This Mac**. This download requires **Apple Silicon
   (M-series) and macOS 27.0.1 or newer**; it does not support Intel Macs.
2. [Download the installer (.dmg)](https://github.com/ktstauder1/cligriderator/releases/download/macos-v4.3.0-preview.1/cligrid-4.3.0-macos-arm64-standalone.dmg)
   or select `cligrid-4.3.0-macos-arm64-standalone.dmg` under **Assets**.
   The source-code ZIP/TAR downloads are not app installers.
3. Open the DMG in Finder and drag **Cli Griderator.app** into **Applications**.
4. Eject the disk image and open **Cli Griderator** from **Applications**.

Homebrew and a separate Python installation are not required. The app includes
GTK, VTE and tmux.

## If macOS blocks the app

This preview is **not Developer ID signed or notarized**. Proceed only if you
trust this official download and accept the risks; approval does not certify
the app's security.

1. Try opening the installed app. For an unidentified-developer or
   cannot-check-for-malicious-software alert, dismiss it without deleting the app.
2. Open **Apple menu > System Settings > Privacy & Security**.
3. Under **Security**, find **Cli Griderator** and select **Open Anyway**.
4. Authenticate if asked and confirm **Open**.

If the button is absent, retry launching the app and check Settings again.
Managed Macs may require your administrator's approval. Never disable Gatekeeper
globally or use quarantine-removal commands. Stop if macOS reports malware,
damage, or that the app will damage your computer; report the message without
private data in [Issues](https://github.com/ktstauder1/cligriderator/issues).

[Apple's safe-opening instructions](https://support.apple.com/en-us/102445)
explain this per-app exception.

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
