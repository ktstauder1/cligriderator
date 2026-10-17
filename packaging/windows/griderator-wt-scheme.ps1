#Requires -Version 5.1
<#
.SYNOPSIS
    Install the Griderator colour scheme into Windows Terminal.

.DESCRIPTION
    Windows Terminal reads JSON fragments from
    %LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\<name>\. This writes the
    grid's own palette, the same numbers cligrid_art.py uses, so a Windows
    Terminal tab looks like a cligrid pane. It does not touch settings.json.

    After running it, choose Griderator in Windows Terminal: Settings, your
    profile, Appearance, Color scheme. To make it the default for every
    profile, set "colorScheme": "Griderator" in profiles.defaults yourself.

.PARAMETER Uninstall
    Remove the fragment instead of writing it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File griderator-wt-scheme.ps1
#>
[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$fragmentDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows Terminal\Fragments\cligrid'
$fragment = Join-Path $fragmentDir 'griderator.json'

if ($Uninstall) {
    if (Test-Path $fragment) { Remove-Item $fragment -Force; Write-Host "Removed $fragment" }
    else { Write-Host 'Nothing to remove.' }
    exit 0
}

# The palette, copied from cligrid_art.py THEME_PRESETS["griderator"].
$scheme = [ordered]@{
    name                = 'Griderator'
    background          = '#15171b'
    foreground          = '#e6e8eb'
    cursorColor         = '#d8be86'
    selectionBackground = '#353b45'
    black               = '#1d2025'
    red                 = '#ff718b'
    green               = '#6ee7a0'
    yellow              = '#d8be86'
    blue                = '#66b7ff'
    purple              = '#d69aff'
    cyan                = '#43e0df'
    white               = '#d0d4da'
    brightBlack         = '#9ca3ae'
    brightRed           = '#ff9aac'
    brightGreen         = '#a0f5bd'
    brightYellow        = '#ffe49a'
    brightBlue          = '#9ed5ff'
    brightPurple        = '#edbcff'
    brightCyan          = '#98f6ee'
    brightWhite         = '#ffffff'
}

$fragment_json = [ordered]@{
    '$schema' = 'https://aka.ms/terminal-profiles-schema'
    schemes   = @($scheme)
}

if (-not (Test-Path $fragmentDir)) { New-Item -ItemType Directory -Path $fragmentDir -Force | Out-Null }
$fragment_json | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $fragment

if (-not (ConvertFrom-Json (Get-Content -Raw $fragment))) {
    Write-Host 'error: the written fragment did not parse as JSON' -ForegroundColor Red
    exit 1
}

Write-Host "Installed the Griderator scheme: $fragment"
Write-Host 'Windows Terminal picks fragments up on start; then select it under Settings, Appearance, Color scheme.'
