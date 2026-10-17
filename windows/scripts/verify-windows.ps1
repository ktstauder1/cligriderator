param([Parameter(Mandatory=$true)][string]$Executable, [string]$Report = 'test-results\packaged')
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path $Executable).Path
New-Item -ItemType Directory -Force $Report | Out-Null
$Report = (Resolve-Path $Report).Path
$originalPath = $env:PATH
$originalNodePath = $env:NODE_PATH
try {
    # Simulate a consumer machine: only Windows tools are on PATH.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:NODE_PATH = ''
    $env:CLIGRID_SMOKE_DIR = $Report
    $process = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -PassThru -RedirectStandardOutput "$Report\stdout.log" -RedirectStandardError "$Report\stderr.log"
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        throw 'Packaged application timed out.'
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        Get-Content "$Report\stderr.log"
        throw "Packaged application exited with $($process.ExitCode)."
    }
    $result = Get-Content "$Report\result.json" -Raw | ConvertFrom-Json
    if (-not $result.passed -or $result.platform -ne 'win32') { throw 'Windows runtime proof is missing.' }
    Write-Host 'Packaged Windows app passed with development tools removed from PATH.'
} finally {
    $env:PATH = $originalPath
    $env:NODE_PATH = $originalNodePath
    Remove-Item Env:CLIGRID_SMOKE_DIR -ErrorAction SilentlyContinue
}
