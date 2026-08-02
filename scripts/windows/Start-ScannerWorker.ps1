<#
.SYNOPSIS
    Start the Market Mate Scanner scheduler worker (and Coinbase WS).
.DESCRIPTION
    Launches `python -m app.worker` from services/scanner. The worker process owns
    var/run/worker.pid and rejects duplicate worker starts. Logs to
    var/logs/worker-*.log. Returns the process.
.PARAMETER PythonPath
    Full path to python.exe (or a venv python). Recommended for Task Scheduler.
.EXAMPLE
    .\Start-ScannerWorker.ps1 -PythonPath "C:\Python312\python.exe"
#>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$LogFile,
    [int]$StartupTimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

$scannerDir = Get-ScannerDir
$python = Resolve-PythonPath -PythonPath $PythonPath
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog = Join-Path (Get-LogDir) "worker-$stamp.out.log"
$errLog = Join-Path (Get-LogDir) "worker-$stamp.err.log"
$pidFile = Join-Path (Get-RunDir) 'worker.pid'

if ($StartupTimeoutSeconds -lt 1) {
    throw 'StartupTimeoutSeconds must be at least 1.'
}

function Get-StderrTail {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -Path $Path)) { return '' }
    return ((Get-Content -Path $Path -Tail 20 -ErrorAction SilentlyContinue) | Out-String).Trim()
}

function Get-PidFileText {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -Path $Path)) { return $null }
    $pidText = Get-Content -Path $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pidText) { return $null }
    return (($pidText | Out-String).Trim())
}

Write-Log -Message "Starting scanner worker: $python -m app.worker" -LogFile $LogFile
Write-Log -Message "Worker stdout -> $outLog" -LogFile $LogFile

$proc = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'app.worker') `
    -WorkingDirectory $scannerDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$ownsPidFile = $false
while ($true) {
    $proc.Refresh()
    if ($proc.HasExited) {
        $stderrTail = Get-StderrTail -Path $errLog
        $message = "Scanner worker failed to start before acquiring PID ownership (exit code $($proc.ExitCode))."
        if ($stderrTail) { $message = "$message Stderr: $stderrTail" }
        Write-Log -Message $message -Level ERROR -LogFile $LogFile
        throw $message
    }

    $pidText = Get-PidFileText -Path $pidFile
    $ownedPid = 0
    if ($pidText -and ([int]::TryParse($pidText, [ref]$ownedPid)) -and $ownedPid -eq $proc.Id) {
        $ownsPidFile = $true
        break
    }

    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Milliseconds 250
}

if (-not $ownsPidFile) {
    $proc.Refresh()
    if ($proc.HasExited) {
        $stderrTail = Get-StderrTail -Path $errLog
        $message = "Scanner worker failed to start before acquiring PID ownership (exit code $($proc.ExitCode))."
        if ($stderrTail) { $message = "$message Stderr: $stderrTail" }
        Write-Log -Message $message -Level ERROR -LogFile $LogFile
        throw $message
    }

    $pidText = Get-PidFileText -Path $pidFile
    $pidFileState = if ($pidText) { "worker.pid contains '$pidText'" } else { 'worker.pid is missing or unreadable' }
    $message = "Scanner worker startup could not be confirmed within $StartupTimeoutSeconds second(s): spawned PID $($proc.Id) did not acquire $pidFile ($pidFileState)."
    Write-Log -Message $message -Level ERROR -LogFile $LogFile
    throw $message
}

Write-Log -Message "Scanner worker started (PID $($proc.Id)); confirmed worker owns pid file $pidFile" -LogFile $LogFile
return $proc
