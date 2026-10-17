# Cli Griderator on Linux, Windows, and macOS

One source tree, three platform installs. From a checkout or the release
archive, `./install` picks the right one. The application embeds VTE terminals,
and VTE needs a POSIX pty, so the honest split is this:

    Linux    native: GTK3 + VTE + tmux from the distribution
    macOS    native: the same source, dependencies from Homebrew
    Windows  the Linux build under WSL 2 + WSLg, in a Windows window

There is no native Windows build and there cannot be one without replacing VTE.
VTE has no Windows port; MSYS2 packages GTK3 but not VTE. VTE on Windows would
mean writing a ConPTY-backed terminal widget, which is a different product, not
a port of this one.

Everything here was written and verified on the Linux machine; the macOS and
Windows installers were written from the verified facts in the table below and
have not been executed on those systems. Each one ends by running
`cligrid doctor`, which checks the environment on the machine it is installed
on. That output is the real test.

    bash packaging/verify-platforms.sh

runs the checks this document describes: the unittest suite with and without
gi, the installer syntax, the tarball and deb builds, a stubbed `uname`/`brew`
run of the macOS installer with the launcher and bundle it generates, and the
Windows Terminal palette. It is the "Platform installers" step in CI, and it
skips the sections that need a desktop GTK stack rather than failing on them.

## What was verified, and how

    macOS  brew formula vte3 0.84.1   exists, builds with -Dgir=true, so the
                                      Vte-2.91 typelib is produced; macOS
                                      bottles for arm64 sonoma, sequoia,
                                      tahoe, golden gate, and x86_64 sonoma
          brew formula gtk+3 3.24.52  arm64 macOS bottles only: an Intel Mac
                                      builds it from source, which is slow
          brew formula pygobject3 3.58.0   built against python@3.13 and 3.14
          brew formula tmux 3.7c      fine
          brew cask font-jetbrains-mono-nerd-font 3.5.1   exists
    Windows  WSLg runs Linux GUI apps in integrated Windows windows, WSL 2
             only, documented by Microsoft; Start-menu integration comes from
             the .desktop entry recorded in the WSL distribution
             MSYS2 has no VTE package (searched: only mingw-w64-libvterm, a
             different library)

## Linux

    ./install                             picks the installer for this machine
    packaging/linux/build-tarball.sh      portable tar.gz + zip for all three OSes
    packaging/build-deb.sh                Debian package for system-wide install
    install.sh                            per-user Linux install from a checkout

From a checkout, or from the extracted tarball:

    install.sh

That copies the application into ~/.local/share/cligrid (or PREFIX/share/cligrid
when you pass --prefix), then writes ~/bin/cligrid, the desktop entry, the
hicolor icons, and the man page. The extract or checkout can be deleted after.

    packaging/linux/build-tarball.sh
    # -> packaging/dist/cligrid-<version>.tar.gz
    # -> packaging/dist/cligrid-<version>.zip
    #    source, ./install, and the Linux / macOS / Windows installers
    #    <version> is read from pyproject.toml; every packager copies
    #    cligrid*.py by glob so a new module cannot be left behind

Dependencies, all shipped by a normal desktop: python3-gi, gir1.2-gtk-3.0,
gir1.2-vte-2.91, tmux, Python 3.10 or newer. Debian and Ubuntu:

    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91 tmux

## macOS

    packaging/macos/build-dmg.sh              disk image: packaging/dist/cligrid-<version>.dmg
    packaging/macos/install-macos.sh [--prefix DIR] [--no-font] [--no-verify]

Requires Homebrew, which this script does not install. It then:

    brew install gtk+3 vte3 pygobject3 tmux
    brew install --cask font-jetbrains-mono-nerd-font       (the grid default)
    picks the Homebrew Python that can import Gtk 3 and Vte 2.91
    installs the application to ~/.local/share/cligrid
    installs a launcher to ~/.local/bin/cligrid, with the Homebrew paths,
      GI_TYPELIB_PATH, XDG_DATA_DIRS, GSETTINGS_SCHEMA_DIR and the gdk-pixbuf
      loader cache baked in, because a Homebrew GTK app needs all of them
    builds ~/Applications/Cli Griderator.app (Info.plist validated with plutil),
      launchable from Finder and pinnable to the Dock
    when launched without a terminal, posts progress notifications and a stop
      dialog on error (osascript). Set CLIGRID_NO_UI=1 to keep it silent.
    runs cligrid doctor

Notes that matter on a Mac:

    - Apple Silicon on sonoma or newer downloads bottles. Intel Macs, and
      Apple Silicon on older releases, build gtk+3 from source: expect a long
      first install and Xcode command line tools.
    - Desktop notifications have no session D-Bus on macOS, so they go through
      osascript instead. macOS may attribute them to the process that raised
      them the first time; allow notifications when it asks.
    - The config lives in ~/.config/cligrid/config.json, as on Linux. The theme
      is griderator, the same palette.
    - macOS will not hand another application's window to an app, exactly as
      COSMIC does not on Wayland. The grid therefore owns its terminals, and
      the design constraints in the README keep applying.

## Windows

    packaging/windows/build-exe.sh            installer: packaging/dist/cligrid-<version>.exe
    powershell -ExecutionPolicy Bypass -File packaging\windows\install-windows.ps1

Options: -Distro <name> to choose the WSL distribution, -Source <path> for the
checkout, -InstallWsl if WSL is missing (elevated, reboots), -NoFont, -NoVerify.

The script checks wsl.exe, refuses WSL 1, checks /mnt/wslg, translates the
checkout path with wslpath, then runs packaging/windows/wsl-provision.sh inside
the distribution:

    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91 tmux
    installs the JetBrains Mono Nerd Font from the upstream release
    copies the application to ~/.local/share/cligrid (not a /mnt path, which is
      slow and would break if the checkout moved) and runs install.sh
    runs cligrid doctor

Back on Windows it writes %USERPROFILE%\bin\cligrid.cmd with your distribution
name, adds that directory to the user PATH, and prints the check output.

    cligrid            start the grid, from any terminal
    cligrid status     the same verbs as Linux; they cross WSL untouched

You will be asked for your WSL password once, by sudo, during provisioning.

    packaging/windows/griderator-wt-scheme.ps1

installs the Griderator palette into Windows Terminal as a JSON fragment, for
the case where you are working in Windows Terminal rather than in the grid.
It does not edit settings.json; select Griderator under Settings, Appearance,
Color scheme. Windows Terminal reads fragments at start.

## The same palette everywhere

`griderator` is the grid's own theme and the default on all three platforms:
background #15171b, foreground #e6e8eb, accent #d8be86, sixteen terminal
colors. `cligrid theme list` shows the presets, `cligrid theme set <name>`
switches at runtime, and `theme: "kitty"` inherits from kitty.conf instead.

## One source, three launchers

    Linux     ~/bin/cligrid            -> /usr/bin/python3 <app>/cligrid.py
    macOS     ~/.local/bin/cligrid     -> Homebrew python + Homebrew env
    Windows   %USERPROFILE%\bin\cligrid.cmd -> wsl -d <distro> -> ~/bin/cligrid

The command verbs, the config file, the theme, and the tmux sessions are
identical on all three, because it is one program.
