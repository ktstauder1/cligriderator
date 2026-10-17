# Cli Griderator Windows installer.
# Built by packaging/windows/build-exe.sh. Pass -DVERSION= and -DOUTFILE=.
#
# The .exe unpacks the same payload as the zip, then runs install-windows.ps1.
# That script provisions WSL 2. There is no native Windows VTE build.

!ifndef VERSION
  !error "pass -DVERSION=x.y.z"
!endif
!ifndef OUTFILE
  !error "pass -DOUTFILE=path"
!endif
!ifndef PAYLOAD
  !error "pass -DPAYLOAD=dir"
!endif
!ifndef LICENSEFILE
  !error "pass -DLICENSEFILE=path"
!endif

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user

Name "Cli Griderator"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Cli Griderator"
BrandingText "Cli Griderator ${VERSION}"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ABORTWARNING
!ifdef ICONFILE
  !define MUI_ICON "${ICONFILE}"
  !define MUI_UNICON "${ICONFILE}"
!endif

!define MUI_WELCOMEPAGE_TITLE "Cli Griderator ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This installer copies Cli Griderator and sets it up inside WSL 2. The terminal widget needs a POSIX pty, so there is no native Windows build. WSLg shows the grid as a Windows window.$\r$\n$\r$\nYou need Windows 10 or 11 with WSL 2 and WSLg already installed."
!define MUI_FINISHPAGE_TITLE "Cli Griderator is installed"
!define MUI_FINISHPAGE_TEXT "Open a new terminal and run cligrid. Or double-click cligrid.cmd in your user bin folder.$\r$\n$\r$\nIf WSL was missing, install it from an elevated PowerShell (wsl --install), reboot, and run this installer again."
!define MUI_FINISHPAGE_RUN "$PROFILE\bin\cligrid.cmd"
!define MUI_FINISHPAGE_RUN_TEXT "Start Cli Griderator"
!define MUI_FINISHPAGE_RUN_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSEFILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "Cli Griderator"
VIAddVersionKey /LANG=1033 "FileDescription" "Cli Griderator installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 Kutty Stauder / Konatus Research Group"
VIAddVersionKey /LANG=1033 "CompanyName" "Konatus Research Group"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}/"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  DetailPrint "Provisioning WSL (this can take a few minutes the first time)..."
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\packaging\windows\install-windows.ps1" -Source "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION "The WSL installer reported an error (code $0). Read the log above. You still have the files in $INSTDIR and can run packaging\windows\install-windows.ps1 yourself."
  ${EndIf}

  CreateDirectory "$SMPROGRAMS"
  ${If} ${FileExists} "$PROFILE\bin\cligrid.cmd"
    CreateShortCut "$SMPROGRAMS\Cli Griderator.lnk" "$PROFILE\bin\cligrid.cmd"
  ${EndIf}

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "DisplayName" "Cli Griderator"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "Publisher" "Kutty Stauder / Konatus Research Group"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator" "URLInfoAbout" "https://kuttystauder.com/development/"
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\Cli Griderator.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CliGriderator"
  RMDir /r "$INSTDIR"
SectionEnd
