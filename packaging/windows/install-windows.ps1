#Requires -Version 5.1
<#
.SYNOPSIS
    Install Cli Griderator on Windows.

.DESCRIPTION
    The grid embeds VTE terminals. VTE needs a POSIX pty and has no Windows
    build, so the Windows install is the Linux application running under WSL 2
    with WSLg, where it appears as a normal Windows window with Start-menu and
    taskbar integration.

    This script installs the WSL dependencies, copies the application inside
    the distribution, installs the launcher, and adds a cligrid.cmd on PATH.

.PARAMETER Distro
    WSL distribution to install into. Defaults to the WSL default distribution.

.PARAMETER Source
    Path to the cligrid checkout. Defaults to the repository containing this
    script.

.PARAMETER InstallWsl
    Install WSL itself (needs an elevated PowerShell and a reboot).

.PARAMETER NoFont
    Skip the JetBrains Mono Nerd Font download.

.PARAMETER NoVerify
    Skip the environment check at the end.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$Distro = '',
    [string]$Source = '',
    [switch]$InstallWsl,
    [switch]$NoFont,
    [switch]$NoVerify
)

$ErrorActionPreference = 'Stop'

function Step([string]$Text) { Write-Host $Text }
function Fail([string]$Text) { Write-Host "error: $Text" -ForegroundColor Red; exit 1 }

if ($env:OS -ne 'Windows_NT') { Fail 'this installer is for Windows.' }

# WSL prints UTF-16 to a console handle; WSL_UTF8 makes the output usable.
$env:WSL_UTF8 = '1'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    if (-not $InstallWsl) {
        Fail 'wsl.exe is not installed. Run "wsl --install" from an elevated PowerShell (it reboots), then re-run this script, or re-run with -InstallWsl.'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail '-InstallWsl needs an elevated PowerShell: run "wsl --install" yourself, reboot, then re-run this script.'
    }
    Step 'Installing WSL; Windows will ask you to reboot.'
    wsl.exe --install
    Step 'Reboot, then re-run this script.'
    exit 0
}

# ---- pick the distribution -------------------------------------------------
$distros = @(wsl.exe --list --quiet | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if ($distros.Count -eq 0) {
    Fail 'no WSL distribution is installed. From an elevated PowerShell: wsl --install -d Ubuntu, reboot, then re-run this script.'
}
if ($Distro -eq '') {
    $verbose = @(wsl.exe --list --verbose | ForEach-Object { ($_ -replace "`0", '') })
    $default = $verbose | Where-Object { $_ -match '^\s*\*' } | Select-Object -First 1
    if ($default) {
        $Distro = ($default -replace '^\s*\*\s*', '' -split '\s+')[0]
    } else {
        $Distro = $distros[0]
    }
}
if ($distros -notcontains $Distro) {
    Fail "WSL has no distribution named '$Distro'. Installed: $($distros -join ', ')."
}
Step "WSL distribution: $Distro"

# ---- WSL 2 and a display ---------------------------------------------------
$kernel = (wsl.exe -d $Distro --exec uname -r) -join ''
if ($kernel -match '^\s*4\.') {
    Fail "$Distro is WSL 1. GUI windows need WSL 2: run 'wsl --set-version $Distro 2'."
}
wsl.exe -d $Distro --exec test -d /mnt/wslg
if ($LASTEXITCODE -ne 0) {
    Step 'warning: /mnt/wslg is missing, so GUI windows may not appear. Run "wsl --update" and restart WSL.'
} else {
    Step 'WSLg is present.'
}

# ---- the source checkout ---------------------------------------------------
$repo = $Source
if ($repo -eq '') {
    $repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
if (-not (Test-Path (Join-Path $repo 'cligrid.py'))) {
    Fail "cligrid.py is not in '$repo'. Pass -Source <checkout path>."
}
$repoInWsl = ((wsl.exe -d $Distro --exec wslpath -u $repo) -join '').Trim()
if ($LASTEXITCODE -ne 0 -or $repoInWsl -eq '') { Fail "could not translate '$repo' into a WSL path." }
Step "Source: $repo ($repoInWsl)"

# ---- provision the distribution -------------------------------------------
$provisionInWsl = "$repoInWsl/packaging/windows/wsl-provision.sh"
$provisionArgs = @($provisionInWsl, $repoInWsl)
if ($NoFont) { $provisionArgs += '--no-font' }
Step 'Provisioning the distribution: packages, font, application, launcher.'
wsl.exe -d $Distro --exec bash @provisionArgs
if ($LASTEXITCODE -ne 0) { Fail 'provisioning failed; the output above says where.' }

# ---- the Windows launcher --------------------------------------------------
$binDir = Join-Path $env:USERPROFILE 'bin'
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
$template = Join-Path $PSScriptRoot 'cligrid.cmd'
if (-not (Test-Path $template)) { Fail "missing $template" }
$launcher = Join-Path $binDir 'cligrid.cmd'
(Get-Content -Raw $template).Replace('__DISTRO__', $Distro) | Set-Content -Encoding ASCII $launcher
Step "Installed $launcher"

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$binDir*") {
    $newPath = if ($userPath) { $userPath.TrimEnd(';') + ';' + $binDir } else { $binDir }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Step "Added $binDir to your user PATH (open a new terminal to pick it up)."
}

# ---- verify ----------------------------------------------------------------
if (-not $NoVerify) {
    Step ''
    Step 'Environment check:'
    wsl.exe -d $Distro --exec bash -lc '$HOME/bin/cligrid doctor'
    Step ''
}
Step 'Start the grid:  cligrid        (or double-click %USERPROFILE%\bin\cligrid.cmd)'
Step "Inside WSL it is: ~/bin/cligrid, application in ~/.local/share/cligrid"
Step "WSLg also lists the installed grid in the Windows Start menu under $Distro once the entry is refreshed."
