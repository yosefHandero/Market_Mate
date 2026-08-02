<#
.SYNOPSIS
    Run one Market Mate Scanner wake window: start backend + worker, enable the
    scheduler, run 5-minute scans for a fixed duration, then stop everything and
    let the PC sleep again. This is the single command Task Scheduler runs.
.DESCRIPTION
    Lifecycle (teardown always runs, even on error):
      1. Suppress system sleep for the window (display may still sleep).
      2. Start the FastAPI backend (no --reload) and wait until /livez is OK.
      3. Start the scheduler worker (python -m app.worker).
      4. Enable the scheduler via POST /scan/scheduler/start (admin route).
      5. Optionally trigger one immediate scan so data is fresh at window start.
      6. Idle until the window ends; the worker auto-scans every SCAN_INTERVAL_SECONDS.
      7. Disable the scheduler, stop worker + API, re-allow sleep.
.PARAMETER DurationMinutes
    How long the window runs. Required unless -EndTime is given.
.PARAMETER EndTime
    Local clock end time "HH:mm" (today; if already past, next day). Overrides DurationMinutes.
.PARAMETER PythonPath
    Full path to python.exe / venv python. Recommended for Task Scheduler.
.PARAMETER Port
    Backend port. Default 8005.
.PARAMETER EnableScheduler
    Enable auto-scans for the window. Default $true.
.PARAMETER TriggerImmediateScan
    Fire one scan right after startup. Default $true.
.EXAMPLE
    .\Invoke-WakeWindow.ps1 -DurationMinutes 498 -PythonPath "C:\Python312\python.exe"
#>
[CmdletBinding()]
param(
    [int]$DurationMinutes,
    [string]$EndTime,
    [string]$PythonPath,
    [int]$Port = 8005,
    [bool]$EnableScheduler = $true,
    [bool]$TriggerImmediateScan = $true,
    # Post-wake cold starts (uvicorn import + schema check) have been observed to
    # take ~2 minutes; a 120s health timeout aborts the window seconds before the
    # API is ready. Default to 300s so a slow wake still gets a healthy backend.
    [int]$HealthTimeoutSeconds = 300,
    [int]$NetworkTimeoutSeconds = 120,
    # How long to wait for a NEW scan run to appear before marking the window
    # failed. Must comfortably exceed one full scan (universe fetch + resolve).
    [int]$ScanConfirmTimeoutMinutes = 15,
    # Name of the scheduled task that launched this window (run-source proof).
    [string]$TaskName,
    # Log the full intended lifecycle without starting processes or scanning.
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

# --- Resolve window end ------------------------------------------------------

$now = Get-Date
if ($EndTime) {
    $parsed = [datetime]::ParseExact($EndTime, 'HH:mm', $null)
    $end = (Get-Date -Hour $parsed.Hour -Minute $parsed.Minute -Second 0)
    if ($end -le $now) { $end = $end.AddDays(1) }
}
elseif ($DurationMinutes -gt 0) {
    $end = $now.AddMinutes($DurationMinutes)
}
else {
    throw 'Provide -DurationMinutes or -EndTime.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path (Get-LogDir) "wake-window-$stamp.log"
$baseUrl = "http://127.0.0.1:$Port"
$exitCode = 0
$startedAtIso = (Get-Date).ToString('o')
$taskLabel = if ($TaskName) { $TaskName } else { 'manual/unspecified' }

# Run-source markers (Phase 4 proof). These let logs prove a scan was produced by
# the scheduled wake task, not by a manual worker, via timestamp correlation.
Write-Log -Message "=== Wake window start === end target: $($end.ToString('yyyy-MM-dd HH:mm:ss'))" -LogFile $logFile
Write-Log -Message "scheduled_task=$([bool]$TaskName) wake_window_task_name=$taskLabel wake_window_started_at=$startedAtIso" -LogFile $logFile
Write-Log -Message "Repo root: $(Get-RepoRoot)" -LogFile $logFile

if ($DryRun) {
    Write-Log -Message 'DRY RUN: no processes will start, no scheduler enabled, no scan triggered.' -Level WARN -LogFile $logFile
    Write-Log -Message "DRY RUN plan: start API (port $Port) -> wait /livez -> start worker -> wait worker_alive -> Wait-ForNetwork (timeout ${NetworkTimeoutSeconds}s) -> POST /scan/scheduler/start -> POST /scan/run -> confirm new scan run -> idle until $($end.ToString('HH:mm:ss')) -> stop scheduler/worker/API." -LogFile $logFile
    Write-Log -Message '=== Wake window end (dry run, exit 0) ===' -LogFile $logFile
    exit 0
}

Set-StayAwake -LogFile $logFile

try {
    # 1) Backend
    & "$PSScriptRoot\Start-ScannerApi.ps1" -PythonPath $PythonPath -Port $Port -LogFile $logFile | Out-Null
    if (-not (Wait-ForHealthy -BaseUrl $baseUrl -TimeoutSeconds $HealthTimeoutSeconds -LogFile $logFile)) {
        throw "Backend failed health check at $baseUrl/livez."
    }

    # 2) Worker
    & "$PSScriptRoot\Start-ScannerWorker.ps1" -PythonPath $PythonPath -LogFile $logFile | Out-Null
    if (-not (Wait-ForWorkerAlive -BaseUrl $baseUrl -TimeoutSeconds 90 -LogFile $logFile)) {
        Write-Log -Message 'Worker heartbeat not confirmed before enabling scheduler; continuing with warning.' -Level WARN -LogFile $logFile
    }

    # 3) Network/provider readiness gate. Backend + worker may have started before
    #    the network was up; the scan must NOT run until connectivity is confirmed.
    $networkReady = $false
    if ($EnableScheduler) {
        $networkReady = Wait-ForNetwork -TimeoutSeconds $NetworkTimeoutSeconds -LogFile $logFile
        if (-not $networkReady) {
            $exitCode = 1
            Write-Log -Message 'Skipping scheduler/scan: network not ready. Marking window FAILED.' -Level ERROR -LogFile $logFile
        }
    }

    # 4) Enable scheduler + trigger a confirmed scan (only after network is ready).
    if ($EnableScheduler -and $networkReady) {
        $auth = Get-ScannerAdminAuth
        Write-Log -Message $auth.Note -LogFile $logFile
        if ($auth.AuthRequired -and -not $auth.Token) {
            throw 'Cannot enable scheduler: admin auth required but ADMIN_API_TOKEN is blank. Set it in services/scanner/.env.'
        }

        # Baseline latest scan id so we can prove a NEW run was created this window.
        $baselineScanId = $null
        try {
            $baseline = Invoke-ScannerRequest -Method Get -Url "$baseUrl/scan/latest" -Headers $auth.Headers
            if ($baseline -and $baseline.id) { $baselineScanId = $baseline.id }
        }
        catch { }
        Write-Log -Message "Baseline latest scan id before window: $baselineScanId" -LogFile $logFile

        Invoke-ScannerRequest -Method Post -Url "$baseUrl/scan/scheduler/start" -Headers $auth.Headers | Out-Null
        Write-Log -Message 'Scheduler enabled via /scan/scheduler/start (after network ready).' -LogFile $logFile

        if ($TriggerImmediateScan) {
            try {
                $run = Invoke-ScannerRequest -Method Post -Url "$baseUrl/scan/run" -Headers $auth.Headers -TimeoutSec 300
                $runId = if ($run) { $run.id } else { $null }
                $runCreated = if ($run) { $run.created_at } else { $null }
                Write-Log -Message "Immediate scan triggered via /scan/run (run_id=$runId created_at=$runCreated)." -LogFile $logFile
            }
            catch {
                Write-Log -Message "Immediate /scan/run failed; will wait for the worker's scheduled scan instead: $($_.Exception.Message)" -Level WARN -LogFile $logFile
            }
        }

        # Confirm scan COMPLETION (do not trust elapsed time): poll /scan/latest
        # until a run newer than the baseline appears, within the window.
        $confirmLimit = (Get-Date).AddMinutes($ScanConfirmTimeoutMinutes)
        if ($confirmLimit -gt $end) { $confirmLimit = $end }
        $scanConfirmed = $false
        while ((Get-Date) -lt $confirmLimit) {
            try {
                $latest = Invoke-ScannerRequest -Method Get -Url "$baseUrl/scan/latest" -Headers $auth.Headers
                if ($latest -and $latest.id -and ($latest.id -ne $baselineScanId)) {
                    Write-Log -Message "confirmed scan completion: run_id=$($latest.id) created_at=$($latest.created_at) (baseline was $baselineScanId)." -LogFile $logFile
                    $scanConfirmed = $true
                    break
                }
            }
            catch { }
            Start-Sleep -Seconds 10
        }
        if (-not $scanConfirmed) {
            $exitCode = 1
            Write-Log -Message 'No new scan completed within the confirmation window. Marking window FAILED.' -Level ERROR -LogFile $logFile
        }
    }
    elseif (-not $EnableScheduler) {
        Write-Log -Message 'EnableScheduler=$false; backend/worker running without auto-scans.' -Level WARN -LogFile $logFile
    }

    # 5) Idle until the window ends, with periodic heartbeat logging. If the
    #    scheduler was requested but the network never came up, skip the idle and
    #    tear down promptly (the window already failed).
    if ($EnableScheduler -and -not $networkReady) {
        Write-Log -Message 'Network never ready; skipping idle loop and tearing down early.' -Level WARN -LogFile $logFile
    }
    else {
        Write-Log -Message "Running until $($end.ToString('HH:mm:ss')). Worker auto-scans every SCAN_INTERVAL_SECONDS." -LogFile $logFile
        $nextHeartbeat = (Get-Date)
        while ((Get-Date) -lt $end) {
            if ((Get-Date) -ge $nextHeartbeat) {
                $remaining = [int]([math]::Max(0, ($end - (Get-Date)).TotalMinutes))
                Write-Log -Message "Heartbeat: $remaining min remaining in window." -LogFile $logFile
                $nextHeartbeat = (Get-Date).AddMinutes(10)
            }
            Start-Sleep -Seconds 30
        }
        Write-Log -Message 'Window elapsed; beginning teardown.' -LogFile $logFile
    }
}
catch {
    $exitCode = 1
    Write-Log -Message "Wake window error: $($_.Exception.Message)" -Level ERROR -LogFile $logFile
}
finally {
    # Disable scheduler so /readyz shows it off between windows.
    try {
        $auth = Get-ScannerAdminAuth
        if (-not ($auth.AuthRequired -and -not $auth.Token)) {
            Invoke-ScannerRequest -Method Post -Url "$baseUrl/scan/scheduler/stop" -Headers $auth.Headers | Out-Null
            Write-Log -Message 'Scheduler disabled via /scan/scheduler/stop.' -LogFile $logFile
        }
    }
    catch {
        Write-Log -Message "Scheduler stop call failed (continuing teardown): $($_.Exception.Message)" -Level WARN -LogFile $logFile
    }

    Stop-MarketMateProcess -PidFile (Join-Path (Get-RunDir) 'worker.pid') -CommandLineRegex (Get-WorkerCommandLineRegex) -Label 'scanner worker' -LogFile $logFile | Out-Null
    Stop-MarketMateProcess -PidFile (Join-Path (Get-RunDir) 'api.pid') -CommandLineRegex (Get-ApiCommandLineRegex) -Label 'scanner API' -LogFile $logFile | Out-Null

    Clear-StayAwake -LogFile $logFile
    Write-Log -Message "=== Wake window end (exit $exitCode) ===" -LogFile $logFile
}

exit $exitCode
