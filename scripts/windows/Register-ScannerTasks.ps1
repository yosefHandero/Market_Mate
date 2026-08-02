<#
.SYNOPSIS
    Register (or re-register) the three Market Mate Scanner wake-and-scan tasks
    in Windows Task Scheduler.
.DESCRIPTION
    Creates these tasks (Central Time assumed; uses local clock end times):
      MarketMate-Weekday-Market   Mon-Fri 08:12 -> ends 16:30
      MarketMate-Daily-Overnight  Daily   03:13 -> ends 03:45
      MarketMate-Weekend-Crypto   Sat-Sun 15:58 -> ends 16:30
    Each task:
      - Wakes the computer to run (WakeToRun).
      - Starts only if a network connection is available.
      - Runs on AC power only (DisallowStartIfOnBatteries) AND stops if the
        machine switches to battery (StopIfGoingOnBatteries).
      - Restarts up to 3 times, 1 minute apart, on failure.
      - Runs whether the user is logged on or not (S4U, no stored password).
    Run this in an ELEVATED PowerShell (Run as Administrator).
.PARAMETER PythonPath
    Full path to python.exe / venv python embedded into the task action.
    Strongly recommended because Task Scheduler usually lacks your user PATH.
.PARAMETER Unregister
    Remove the three tasks instead of creating them.
.EXAMPLE
    .\Register-ScannerTasks.ps1 -PythonPath "C:\Python312\python.exe"
.EXAMPLE
    .\Register-ScannerTasks.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Unregister,
    # Print what would be registered (task names, triggers, settings, action) and
    # exit without touching Task Scheduler. Safe to run non-elevated.
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

$taskNames = @(
    'MarketMate-Weekday-Market',
    'MarketMate-Daily-Overnight',
    'MarketMate-Weekend-Crypto',
    'MarketMate-Daily-Backup'
)

if ($Unregister) {
    foreach ($name in $taskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed task: $name"
        }
        else {
            Write-Host "Task not found (skipped): $name"
        }
    }
    return
}

$repo = Get-RepoRoot
$wakeScript = Join-Path $repo 'scripts\windows\Invoke-WakeWindow.ps1'
if (-not (Test-Path $wakeScript)) { throw "Cannot find $wakeScript" }

$python = Resolve-PythonPath -PythonPath $PythonPath
Write-Host "Using Python: $python"
Write-Host "Wake script:  $wakeScript"

function New-WakeAction {
    param(
        [string]$EndTime,
        [string]$TaskName
    )
    # -TaskName is passed through so the wake-window log records the run source
    # (scheduled_task=true, wake_window_task_name=...) for Phase 4 proof.
    $argLine = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', "`"$wakeScript`"",
        '-EndTime', $EndTime,
        '-PythonPath', "`"$python`"",
        '-TaskName', "`"$TaskName`""
    ) -join ' '
    return New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argLine -WorkingDirectory $repo
}

function New-CommonSettings {
    param([timespan]$ExecutionTimeLimit)
    # New-ScheduledTaskSettingsSet defaults to DisallowStartIfOnBatteries=$true and
    # StopIfGoingOnBatteries=$true (AC-only + stop-on-battery), which is exactly what
    # we want. We therefore do NOT pass -AllowStartIfOnBatteries or
    # -DontStopIfGoingOnBatteries (those switches would opt out of that behavior).
    # StartWhenAvailable=$true so a window missed while the PC was asleep/off is
    # still run once the machine returns, instead of being silently skipped. This
    # is the scheduler-side half of Phase 4 missed-window recovery (the backend
    # then catches up any due outcomes on the next scan).
    return New-ScheduledTaskSettingsSet `
        -WakeToRun `
        -RunOnlyIfNetworkAvailable `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit $ExecutionTimeLimit
}

# Run whether logged on or not, without storing a password (S4U).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

$definitions = @(
    @{
        Name        = 'MarketMate-Weekday-Market'
        Description = 'Market Mate: weekday market window 08:15-16:30 CT (equities + crypto, 5-min scans).'
        Trigger     = (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At '8:12AM')
        EndTime     = '16:30'
        Limit       = (New-TimeSpan -Hours 9)
    },
    @{
        Name        = 'MarketMate-Daily-Overnight'
        Description = 'Market Mate: daily overnight crypto + health window 03:15-03:45 CT.'
        Trigger     = (New-ScheduledTaskTrigger -Daily -At '3:13AM')
        EndTime     = '03:45'
        Limit       = (New-TimeSpan -Minutes 50)
    },
    @{
        Name        = 'MarketMate-Weekend-Crypto'
        Description = 'Market Mate: weekend midday crypto snapshot 16:00-16:30 CT.'
        Trigger     = (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At '3:58PM')
        EndTime     = '16:30'
        Limit       = (New-TimeSpan -Minutes 50)
    }
)

foreach ($def in $definitions) {
    $action = New-WakeAction -EndTime $def.EndTime -TaskName $def.Name
    $settings = New-CommonSettings -ExecutionTimeLimit $def.Limit

    if ($DryRun) {
        Write-Host ''
        Write-Host "DRY RUN - would register: $($def.Name)"
        Write-Host "  Description : $($def.Description)"
        Write-Host "  Trigger     : $($def.Trigger.StartBoundary) (ends $($def.EndTime), limit $($def.Limit))"
        Write-Host "  Action      : powershell.exe $($action.Arguments)"
        Write-Host '  Settings    : WakeToRun, RunOnlyIfNetworkAvailable, AC-only (DisallowStartIfOnBatteries),'
        Write-Host '                StopIfGoingOnBatteries, StartWhenAvailable=true, MultipleInstances=IgnoreNew,'
        Write-Host "                RestartCount=3 @1min, ExecutionTimeLimit=$($def.Limit)"
        continue
    }

    Register-ScheduledTask `
        -TaskName $def.Name `
        -Description $def.Description `
        -Action $action `
        -Trigger $def.Trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host "Registered task: $($def.Name) (ends $($def.EndTime))"
}

# --- Daily SQLite backup task ------------------------------------------------
# Separate action (Backup-ScannerDb.ps1, not the wake-window script); AC-agnostic
# and does not need the network, so it uses lighter settings than the scan tasks.
$backupScript = Join-Path $repo 'scripts\windows\Backup-ScannerDb.ps1'
if (-not (Test-Path $backupScript)) { throw "Cannot find $backupScript" }
$backupArgs = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', "`"$backupScript`"",
    '-PythonPath', "`"$python`""
) -join ' '
$backupAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $backupArgs -WorkingDirectory $repo
$backupTrigger = New-ScheduledTaskTrigger -Daily -At '4:10AM'
$backupSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

if ($DryRun) {
    Write-Host ''
    Write-Host 'DRY RUN - would register: MarketMate-Daily-Backup'
    Write-Host '  Description : daily SQLite backup + integrity verification (04:10 CT).'
    Write-Host "  Action      : powershell.exe $backupArgs"
    Write-Host '  Settings    : StartWhenAvailable, MultipleInstances=IgnoreNew, RestartCount=2 @2min, ExecutionTimeLimit=15m'
}
else {
    Register-ScheduledTask `
        -TaskName 'MarketMate-Daily-Backup' `
        -Description 'Market Mate: daily SQLite backup with integrity verification and rotation.' `
        -Action $backupAction `
        -Trigger $backupTrigger `
        -Settings $backupSettings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host 'Registered task: MarketMate-Daily-Backup (04:10 CT)'
}

if ($DryRun) {
    Write-Host ''
    Write-Host 'DRY RUN complete - nothing was registered.'
    return
}

Write-Host ''
Write-Host 'Done. Verify with:  Get-ScheduledTask MarketMate-* | Get-ScheduledTaskInfo'
Write-Host 'Confirm wake timers: powercfg /waketimers'
Write-Host ''
Write-Host 'Enable Task Scheduler History (one-time, elevated; History is a global setting):'
Write-Host '  wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true'
