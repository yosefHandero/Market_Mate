<#
.SYNOPSIS
    Verify the Market Mate Scanner is healthy during a wake window.
.DESCRIPTION
    Checks, and prints PASS/FAIL for each:
      - Backend live            (GET /livez)
      - Readiness + automation  (GET /readyz: scheduler_enabled, scheduler_running,
                                  worker_alive, scan_fresh, last_scan_age_minutes)
      - Scan results exist      (GET /scan/latest)
      - Coinbase WS active      (GET /market/crypto/latest, if COINBASE_WS_ENABLED)
      - Paper-only invariant     (.env EXECUTION_ENABLED / ALLOW_LIVE_TRADING off;
                                  true would prevent the backend from starting)
    Exits 0 if all required checks pass, else 1.
.PARAMETER Port
    Backend port. Default 8005.
.PARAMETER MaxScanAgeMinutes
    Freshness threshold for last scan. Default 30.
.PARAMETER ExpectScheduler
    Require scheduler_running/worker_alive/fresh scan (use during a window). Default $true.
#>
[CmdletBinding()]
param(
    [int]$Port = 8005,
    [int]$MaxScanAgeMinutes = 30,
    [bool]$ExpectScheduler = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\Common.ps1"

$baseUrl = "http://127.0.0.1:$Port"
$failures = 0

function Resolve-ReadHeaders {
    # Reads are public when PUBLIC_READ_ACCESS_ENABLED=true; otherwise a token is needed.
    $readToken = Get-DotEnvValue -Name 'READ_API_TOKEN'
    $adminToken = Get-DotEnvValue -Name 'ADMIN_API_TOKEN'
    $token = $null
    if ($readToken) { $token = $readToken } elseif ($adminToken) { $token = $adminToken }
    if ($token) { return @{ 'X-API-Key' = $token } }
    return @{}
}

function Report {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $tag = if ($Ok) { 'PASS' } else { 'FAIL' }
    $color = if ($Ok) { 'Green' } else { 'Red' }
    Write-Host ('[{0}] {1}{2}' -f $tag, $Name, ($(if ($Detail) { " - $Detail" } else { '' }))) -ForegroundColor $color
    if (-not $Ok) { $script:failures++ }
}

$readHeaders = Resolve-ReadHeaders

# 1) Backend live
try {
    $livez = Invoke-ScannerRequest -Method Get -Url "$baseUrl/livez"
    Report -Name 'Backend live (/livez)' -Ok ([bool]$livez.live) -Detail "ok=$($livez.ok)"
}
catch {
    Report -Name 'Backend live (/livez)' -Ok $false -Detail $_.Exception.Message
}

# 2) Readiness + automation
try {
    $r = Invoke-ScannerRequest -Method Get -Url "$baseUrl/readyz"
    Report -Name 'Readiness (/readyz ok)' -Ok ([bool]$r.ok) -Detail "ready=$($r.ready) schema_ok=$($r.schema_ok)"
    Report -Name 'Scheduler enabled' -Ok ((-not $ExpectScheduler) -or [bool]$r.scheduler_enabled) -Detail "enabled=$($r.scheduler_enabled)"
    Report -Name 'Scheduler running' -Ok ((-not $ExpectScheduler) -or [bool]$r.scheduler_running) -Detail "running=$($r.scheduler_running)"
    Report -Name 'Worker alive' -Ok ((-not $ExpectScheduler) -or [bool]$r.worker_alive) -Detail "worker_alive=$($r.worker_alive)"

    $age = $r.last_scan_age_minutes
    $ageOk = $true
    if ($ExpectScheduler) {
        $ageOk = ($null -ne $age) -and ($age -le $MaxScanAgeMinutes)
    }
    Report -Name "Latest scan age < $MaxScanAgeMinutes min" -Ok $ageOk -Detail "age=$age fresh=$($r.scan_fresh) last_scan_at=$($r.last_scan_at)"
}
catch {
    Report -Name 'Readiness (/readyz)' -Ok $false -Detail $_.Exception.Message
}

# 3) Scan results exist
try {
    $latest = Invoke-ScannerRequest -Method Get -Url "$baseUrl/scan/latest" -Headers $readHeaders
    $hasRun = ($null -ne $latest) -and ($null -ne $latest.id)
    $rowCount = 0
    if ($hasRun -and ($latest.PSObject.Properties.Name -contains 'results') -and $latest.results) { $rowCount = @($latest.results).Count }
    Report -Name 'Latest scan exists (/scan/latest)' -Ok $hasRun -Detail "run_id=$($latest.id) rows=$rowCount"
}
catch {
    Report -Name 'Latest scan exists (/scan/latest)' -Ok $false -Detail $_.Exception.Message
}

# 4) Coinbase WS (only if enabled)
$wsEnabled = (Get-DotEnvValue -Name 'COINBASE_WS_ENABLED')
if ($wsEnabled -and $wsEnabled.ToLower() -eq 'true') {
    try {
        $snap = Invoke-ScannerRequest -Method Get -Url "$baseUrl/market/crypto/latest" -Headers $readHeaders
        $prices = @()
        if ($snap.PSObject.Properties.Name -contains 'prices' -and $snap.prices) { $prices = @($snap.prices) }
        Report -Name 'Coinbase WS snapshot (/market/crypto/latest)' -Ok ($prices.Count -gt 0) -Detail "products=$($prices.Count)"
    }
    catch {
        Report -Name 'Coinbase WS snapshot (/market/crypto/latest)' -Ok $false -Detail $_.Exception.Message
    }
}
else {
    Write-Host '[SKIP] Coinbase WS - COINBASE_WS_ENABLED is not true' -ForegroundColor DarkGray
}

# 5) Paper-only invariant: live-execution flags must be OFF.
# In this build EXECUTION_ENABLED=true or ALLOW_LIVE_TRADING=true is not merely
# ignored - it makes the backend refuse to start (Settings.forbid_live_execution),
# so a running backend already implies these are off. This .env pre-flight catches
# a misconfiguration before you attempt a wake window.
$execEnabled = (Get-DotEnvValue -Name 'EXECUTION_ENABLED')
$liveEnabled = (Get-DotEnvValue -Name 'ALLOW_LIVE_TRADING')
$safe = ((-not $execEnabled) -or $execEnabled.ToLower() -ne 'true') -and ((-not $liveEnabled) -or $liveEnabled.ToLower() -ne 'true')
Report -Name 'Paper-only invariant (live flags off)' -Ok $safe -Detail "EXECUTION_ENABLED=$execEnabled ALLOW_LIVE_TRADING=$liveEnabled (true = backend will not start)"

# 6) Wake timers present: a Market Mate task must be able to wake the PC, else a
# missed overnight/weekend window will never fire while asleep.
try {
    $wake = (& powercfg /waketimers 2>&1 | Out-String)
    $hasMarketMate = $wake -match 'MarketMate'
    if ($hasMarketMate) {
        Report -Name 'Wake timers armed (powercfg /waketimers)' -Ok $true -Detail 'MarketMate wake timer present'
    }
    else {
        # No armed timer is only a warning: it is expected outside the pre-window
        # arming period, so do not fail the run on this alone.
        Write-Host '[WARN] Wake timers - no MarketMate wake timer currently armed (expected only near a window start).' -ForegroundColor Yellow
    }
}
catch {
    Write-Host "[WARN] Wake timers - could not query powercfg: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 7) Database integrity: PRAGMA quick_check + immutable-record hash verification.
try {
    $adminAuth = Get-ScannerAdminAuth
    $dbCheck = Invoke-ScannerRequest -Method Post -Url "$baseUrl/system/db/check" -Headers $adminAuth.Headers
    $mismatches = 0
    if ($dbCheck.PSObject.Properties.Name -contains 'hash_mismatches' -and $dbCheck.hash_mismatches) {
        $mismatches = @($dbCheck.hash_mismatches).Count
    }
    Report -Name 'Database integrity (/system/db/check)' -Ok ([bool]$dbCheck.ok) -Detail "quick_check=$($dbCheck.quick_check) checked=$($dbCheck.checked_snapshots) mismatches=$mismatches trigger=$($dbCheck.trigger_present)"
}
catch {
    Report -Name 'Database integrity (/system/db/check)' -Ok $false -Detail $_.Exception.Message
}

# 8) Scan-window ledger / catch-up: surface missed expected windows and pending resolutions.
try {
    $adminAuth = Get-ScannerAdminAuth
    $windows = Invoke-ScannerRequest -Method Get -Url "$baseUrl/scan/windows?limit=10" -Headers $adminAuth.Headers
    $missed = 0
    if ($windows.PSObject.Properties.Name -contains 'missed_count_14d') { $missed = [int]$windows.missed_count_14d }
    Report -Name 'Scan-window ledger (/scan/windows)' -Ok ($missed -eq 0) -Detail "missed_14d=$missed"
}
catch {
    Report -Name 'Scan-window ledger (/scan/windows)' -Ok $false -Detail $_.Exception.Message
}

try {
    $readAuth = Get-ScannerReadAuth
    $ready = Invoke-ScannerRequest -Method Get -Url "$baseUrl/system/readiness" -Headers $readAuth.Headers
    $pending = 0
    if ($ready.diagnostics -and $ready.diagnostics.PSObject.Properties.Name -contains 'pending_prediction_resolutions') {
        $pending = [int]$ready.diagnostics.pending_prediction_resolutions
    }
    Report -Name 'Catch-up pending predictions' -Ok $true -Detail "pending_prediction_resolutions=$pending"
}
catch {
    Write-Host "[WARN] Catch-up pending predictions - $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ''
if ($failures -eq 0) {
    Write-Host 'ALL CHECKS PASSED' -ForegroundColor Green
    exit 0
}
Write-Host "$failures CHECK(S) FAILED" -ForegroundColor Red
exit 1
