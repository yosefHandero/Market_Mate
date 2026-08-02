<#
.SYNOPSIS
    Start the Market Mate Scanner FastAPI backend (unattended, no --reload).
.DESCRIPTION
    Launches `python -m uvicorn app.main:app --host 127.0.0.1 --port <port>` from
    services/scanner. Writes the process id to var/run/api.pid and logs to
    var/logs/api-*.log. Returns the started process object.
.PARAMETER PythonPath
    Full path to python.exe (or a venv python). Recommended for Task Scheduler,
    which often runs without your user PATH. Falls back to a local venv or PATH.
.PARAMETER Port
    Backend port. Default 8005.
.EXAMPLE
    .\Start-ScannerApi.ps1 -PythonPath "C:\Python312\python.exe"
#>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [int]$Port = 8005,
    [string]$LogFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

$scannerDir = Get-ScannerDir
if (Test-PortInUse -Port $Port) {
    throw "Port $Port is already in use. Stop the existing scanner API or choose a different -Port."
}
$python = Resolve-PythonPath -PythonPath $PythonPath
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog = Join-Path (Get-LogDir) "api-$stamp.out.log"
$errLog = Join-Path (Get-LogDir) "api-$stamp.err.log"
$pidFile = Join-Path (Get-RunDir) 'api.pid'

Write-Log -Message "Starting scanner API: $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port" -LogFile $LogFile
Write-Log -Message "API stdout -> $outLog" -LogFile $LogFile

$proc = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port") `
    -WorkingDirectory $scannerDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
Write-Log -Message "Scanner API started (PID $($proc.Id)); pid file $pidFile" -LogFile $LogFile
return $proc
