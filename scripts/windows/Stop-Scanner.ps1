<#
.SYNOPSIS
    Stop the Market Mate Scanner worker and API cleanly (manual/safety stop).
.DESCRIPTION
    1) Asks the backend to disable the scheduler (POST /scan/scheduler/stop) so the
       DB state is clean and /readyz reflects scheduler off.
    2) Stops ONLY the scanner worker and API processes, identified by their PID
       files and command-line signatures. Unrelated python.exe processes are
       never touched.
.PARAMETER Port
    Backend port. Default 8005.
.PARAMETER SkipSchedulerStop
    Skip the scheduler-disable call (just stop processes).
#>
[CmdletBinding()]
param(
    [int]$Port = 8005,
    [switch]$SkipSchedulerStop,
    [string]$LogFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\Common.ps1"

$baseUrl = "http://127.0.0.1:$Port"

if (-not $SkipSchedulerStop) {
    $auth = Get-ScannerAdminAuth
    Write-Log -Message $auth.Note -LogFile $LogFile
    if ($auth.AuthRequired -and -not $auth.Token) {
        Write-Log -Message 'Scheduler stop skipped: admin auth required but no token available.' -Level WARN -LogFile $LogFile
    }
    else {
        try {
            Invoke-ScannerRequest -Method Post -Url "$baseUrl/scan/scheduler/stop" -Headers $auth.Headers | Out-Null
            Write-Log -Message 'Scheduler disabled via /scan/scheduler/stop.' -LogFile $LogFile
        }
        catch {
            Write-Log -Message "Could not reach /scan/scheduler/stop (backend may already be down): $($_.Exception.Message)" -Level WARN -LogFile $LogFile
        }
    }
}

# Stop worker first (so it finishes/aborts its loop), then the API.
$workerPid = Join-Path (Get-RunDir) 'worker.pid'
$apiPid = Join-Path (Get-RunDir) 'api.pid'

Stop-MarketMateProcess -PidFile $workerPid -CommandLineRegex (Get-WorkerCommandLineRegex) -Label 'scanner worker' -LogFile $LogFile | Out-Null
Stop-MarketMateProcess -PidFile $apiPid -CommandLineRegex (Get-ApiCommandLineRegex) -Label 'scanner API' -LogFile $LogFile | Out-Null

Write-Log -Message 'Stop-Scanner complete.' -LogFile $LogFile
