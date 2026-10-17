@echo off
rem Cli Griderator on Windows.
rem The grid runs inside WSL, where GTK3, VTE and tmux live, and WSLg shows it
rem as a Windows window. install-windows.ps1 writes this file with your
rem distribution name filled in and puts it on PATH.
setlocal
set "DISTRO=__DISTRO__"
wsl.exe -d %DISTRO% --exec bash -lc "exec \"$HOME/bin/cligrid\" %*"
endlocal
