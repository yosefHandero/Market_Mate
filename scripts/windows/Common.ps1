# Common.ps1
# Shared helpers for the Market Mate Scanner Windows wake-and-scan scripts.
# Dot-source this file from the other scripts:  . "$PSScriptRoot\Common.ps1"

Set-StrictMode -Version Latest

# --- Paths -------------------------------------------------------------------

function Get-RepoRoot {
    # scripts/windows/Common.ps1 -> repo root is two levels up.
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-ScannerDir {
    return (Join-Path (Get-RepoRoot) 'services\scanner')
}

function Get-VarDir {
    # services/scanner/var is already gitignored.
    $dir = Join-Path (Get-ScannerDir) 'var'
    return $dir
}

function Get-LogDir {
    $dir = Join-Path (Get-VarDir) 'logs'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Get-RunDir {
    $dir = Join-Path (Get-VarDir) 'run'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

# --- Logging -----------------------------------------------------------------

function Write-Log {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR')][string]$Level = 'INFO',
        [string]$LogFile
    )
    $line = ('{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message)
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        default { Write-Host $line }
    }
    if ($LogFile) {
        try { Add-Content -Path $LogFile -Value $line -Encoding utf8 } catch { }
    }
}

# --- .env reader -------------------------------------------------------------

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$EnvFile
    )
    if (-not $EnvFile) { $EnvFile = Join-Path (Get-ScannerDir) '.env' }
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($raw in (Get-Content -Path $EnvFile -Encoding utf8)) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        if ($key -ne $Name) { continue }
        $value = $line.Substring($idx + 1).Trim()
        # Strip optional surrounding quotes.
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    return $null
}

# --- Python / venv resolution ------------------------------------------------

function Resolve-PythonPath {
    param([string]$PythonPath)

    $candidates = @()
    if ($PythonPath) { $candidates += $PythonPath }
    if ($env:MARKETMATE_PYTHON) { $candidates += $env:MARKETMATE_PYTHON }

    $repo = Get-RepoRoot
    $scanner = Get-ScannerDir
    # Common local virtual-environment layouts.
    $candidates += @(
        (Join-Path $scanner '.venv\Scripts\python.exe'),
        (Join-Path $repo '.venv\Scripts\python.exe'),
        (Join-Path $scanner 'venv\Scripts\python.exe'),
        (Join-Path $repo 'venv\Scripts\python.exe')
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    # Fall back to python / py on PATH.
    foreach ($name in @('python', 'python3', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }

    throw "Could not find a Python interpreter. Pass -PythonPath '<full path to python.exe>' or set MARKETMATE_PYTHON. Task Scheduler often runs without your user PATH, so an explicit path is recommended."
}

# --- Admin auth resolution ---------------------------------------------------

function Get-ScannerAdminAuth {
    <#
      Returns a hashtable:
        Token        : the admin token string (may be empty)
        Headers      : hashtable of headers to send (empty if no token)
        AuthRequired : $true if the server will require a token for admin routes
        AppEnv       : value of APP_ENV
        Note         : human-readable explanation
      Auth model (services/scanner/app/config.py admin_auth_required):
        required = is_production OR bool(ADMIN_API_TOKEN)
        - token set            -> header required
        - blank + development  -> admin routes are OPEN (no token needed)
        - blank + production   -> server refuses to start (handled there)
    #>
    $token = Get-DotEnvValue -Name 'ADMIN_API_TOKEN'
    $appEnv = Get-DotEnvValue -Name 'APP_ENV'
    if (-not $appEnv) { $appEnv = 'development' }
    $isProd = @('production') -contains $appEnv.ToLower()

    $tokenValue = ''
    if ($token) { $tokenValue = $token }
    $result = @{
        Token        = $tokenValue
        Headers      = @{}
        AuthRequired = $false
        AppEnv       = $appEnv
        Note         = ''
    }

    if ($token) {
        $result.Headers = @{ 'X-API-Key' = $token }
        $result.AuthRequired = $true
        $result.Note = 'ADMIN_API_TOKEN is set; sending X-API-Key on admin requests.'
    }
    elseif ($isProd) {
        $result.AuthRequired = $true
        $result.Note = 'ADMIN_API_TOKEN is BLANK while APP_ENV=production. The scanner will not start without a token; set ADMIN_API_TOKEN in services/scanner/.env.'
    }
    else {
        $result.AuthRequired = $false
        $result.Note = "ADMIN_API_TOKEN is blank and APP_ENV=$appEnv (local dev). Admin routes are unauthenticated in this mode, so the scheduler can be toggled without a token. Set ADMIN_API_TOKEN to require auth."
    }
    return $result
}

# --- Read auth resolution ----------------------------------------------------

function Get-ScannerReadAuth {
    <#
      Returns a hashtable:
        Token        : the read token string used (may be empty)
        Headers      : hashtable of headers to send (empty if no token)
        AuthRequired : $true if the server will require a token for read routes
        AppEnv       : value of APP_ENV
        Note         : human-readable explanation
      Auth model (services/scanner/app/config.py read_auth_required):
        required = (NOT PUBLIC_READ_ACCESS_ENABLED) OR bool(READ_API_TOKEN)
        The server accepts READ_API_TOKEN or ADMIN_API_TOKEN on protected reads,
        so we prefer the read token and fall back to the admin token.
    #>
    $readToken = Get-DotEnvValue -Name 'READ_API_TOKEN'
    $adminToken = Get-DotEnvValue -Name 'ADMIN_API_TOKEN'
    $publicRead = Get-DotEnvValue -Name 'PUBLIC_READ_ACCESS_ENABLED'
    $appEnv = Get-DotEnvValue -Name 'APP_ENV'
    if (-not $appEnv) { $appEnv = 'development' }
    $publicReadEnabled = ($publicRead -and $publicRead.ToLower() -eq 'true')

    $token = ''
    if ($readToken) { $token = $readToken } elseif ($adminToken) { $token = $adminToken }

    $result = @{
        Token        = $token
        Headers      = @{}
        AuthRequired = ((-not $publicReadEnabled) -or [bool]$readToken)
        AppEnv       = $appEnv
        Note         = ''
    }

    if ($token) {
        $result.Headers = @{ 'X-API-Key' = $token }
        $result.Note = 'Sending X-API-Key on protected read requests (READ_API_TOKEN, or ADMIN_API_TOKEN fallback).'
    }
    elseif ($publicReadEnabled) {
        $result.Note = 'PUBLIC_READ_ACCESS_ENABLED=true and no token set; protected reads are unauthenticated.'
    }
    else {
        $result.Note = 'No READ_API_TOKEN/ADMIN_API_TOKEN set while PUBLIC_READ_ACCESS_ENABLED is not true; protected reads will be rejected. Set READ_API_TOKEN in services/scanner/.env.'
    }
    return $result
}

# --- HTTP helpers ------------------------------------------------------------

function Invoke-ScannerRequest {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Url,
        [hashtable]$Headers,
        [int]$TimeoutSec = 30
    )
    $params = @{
        Method      = $Method
        Uri         = $Url
        TimeoutSec  = $TimeoutSec
        ErrorAction = 'Stop'
    }
    if ($Headers -and $Headers.Count -gt 0) { $params['Headers'] = $Headers }
    return Invoke-RestMethod @params
}

function Test-PortInUse {
    param(
        [Parameter(Mandatory)][int]$Port,
        [string]$HostName = '127.0.0.1'
    )
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(500)
        if ($connected -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
    }
    catch {
        # Port is free when connect fails.
    }
    return $false
}

function Wait-ForWorkerAlive {
    param(
        [string]$BaseUrl = 'http://127.0.0.1:8005',
        [int]$TimeoutSeconds = 90,
        [int]$PollSeconds = 3,
        [string]$LogFile
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri "$BaseUrl/readyz" -TimeoutSec 10 -ErrorAction Stop
            if ($resp.worker_alive -eq $true) {
                Write-Log -Message "Worker heartbeat confirmed at $BaseUrl/readyz" -LogFile $LogFile
                return $true
            }
        }
        catch {
            # Worker or API not ready yet.
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Log -Message "Worker did not report worker_alive=true within $TimeoutSeconds s." -Level WARN -LogFile $LogFile
    return $false
}

function Wait-ForHealthy {
    param(
        [string]$BaseUrl = 'http://127.0.0.1:8005',
        [int]$TimeoutSeconds = 120,
        [int]$PollSeconds = 3,
        [string]$LogFile
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri "$BaseUrl/livez" -TimeoutSec 10 -ErrorAction Stop
            if ($resp.ok -eq $true -or $resp.live -eq $true) {
                Write-Log -Message "Backend healthy at $BaseUrl/livez" -LogFile $LogFile
                return $true
            }
        }
        catch {
            # Not up yet; keep polling.
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Log -Message "Backend did not become healthy within $TimeoutSeconds s." -Level ERROR -LogFile $LogFile
    return $false
}

# --- Network / provider readiness --------------------------------------------

function Wait-ForNetwork {
    <#
      Block until real internet + provider reachability is confirmed, or a timeout
      elapses. The backend may start before the network is up (so /livez can come
      up offline); this gate is what scheduler-start and /scan/run wait on, so a
      scan is never attempted before the network is ready.

      Any HTTP response (even 4xx/5xx) counts as connectivity: it proves DNS +
      TCP + TLS to the provider succeeded. Returns $true once reachable, $false on
      timeout. On success it logs a single 'network ready' line with a timestamp.
    #>
    param(
        [int]$TimeoutSeconds = 120,
        [int]$PollSeconds = 5,
        [string[]]$TestUrls,
        [string]$LogFile
    )
    if (-not $TestUrls -or $TestUrls.Count -eq 0) {
        # Provider reachability: Alpaca (market data) + CoinGecko (crypto). Either
        # reachable proves usable connectivity for the scanner's providers.
        $TestUrls = @(
            'https://api.alpaca.markets',
            'https://api.coingecko.com/api/v3/ping'
        )
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $attempt = 0
    while ((Get-Date) -lt $deadline) {
        $attempt++
        foreach ($url in $TestUrls) {
            try {
                Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop | Out-Null
                Write-Log -Message "network ready (reachable: $url) after $attempt attempt(s)." -LogFile $LogFile
                return $true
            }
            catch {
                # A returned HTTP status (4xx/5xx) still proves connectivity.
                $status = $null
                try { $status = $_.Exception.Response.StatusCode.value__ } catch { }
                if ($status) {
                    Write-Log -Message "network ready (HTTP $status from $url) after $attempt attempt(s)." -LogFile $LogFile
                    return $true
                }
            }
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Log -Message "network NOT ready within $TimeoutSeconds s; provider endpoints unreachable. Scan will be skipped." -Level ERROR -LogFile $LogFile
    return $false
}

# --- Sleep management (keep system awake during a wake window) ----------------

if (-not ([System.Management.Automation.PSTypeName]'MarketMate.Power').Type) {
    Add-Type -Namespace 'MarketMate' -Name 'Power' -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
}

# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
# Note: ES_DISPLAY_REQUIRED is intentionally omitted so the screen may still turn off.
$script:ES_CONTINUOUS = [uint32]'0x80000000'
$script:ES_SYSTEM_REQUIRED = [uint32]'0x00000001'

function Set-StayAwake {
    param([string]$LogFile)
    [void][MarketMate.Power]::SetThreadExecutionState($script:ES_CONTINUOUS -bor $script:ES_SYSTEM_REQUIRED)
    Write-Log -Message 'System sleep suppressed for this wake window (display may still sleep).' -LogFile $LogFile
}

function Clear-StayAwake {
    param([string]$LogFile)
    [void][MarketMate.Power]::SetThreadExecutionState($script:ES_CONTINUOUS)
    Write-Log -Message 'System sleep suppression cleared; PC may sleep again.' -LogFile $LogFile
}

# --- Process control (Market Mate scanner only) ------------------------------

# Command-line signatures that uniquely identify our two processes. These match
# the module invocations (`app.main:app` via uvicorn, and `app.worker`) so we
# never touch unrelated python.exe processes.
$script:ApiCommandLineRegex = 'uvicorn.+app\.main:app'
$script:WorkerCommandLineRegex = '-m\s+app\.worker|app\.worker'

function Get-ProcessCommandLine {
    param([Parameter(Mandatory)][int]$ProcessId)
    try {
        $ci = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        if ($ci) { return $ci.CommandLine }
    }
    catch { }
    return $null
}

function Stop-MarketMateProcess {
    <#
      Stops only processes whose command line matches a Market Mate signature.
      Uses the recorded PID file first (verifying the command line so a recycled
      PID is never killed), then sweeps for any stragglers matching the regex.
    #>
    param(
        [Parameter(Mandatory)][string]$PidFile,
        [Parameter(Mandatory)][string]$CommandLineRegex,
        [Parameter(Mandatory)][string]$Label,
        [string]$LogFile
    )
    $stopped = 0

    # 1) PID file, verified against the command line.
    if (Test-Path $PidFile) {
        $pidText = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $procId = 0
        if ([int]::TryParse(($pidText | Out-String).Trim(), [ref]$procId) -and $procId -gt 0) {
            $cmd = Get-ProcessCommandLine -ProcessId $procId
            if ($cmd -and ($cmd -match $CommandLineRegex)) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                    Write-Log -Message "Stopped $Label (PID $procId)." -LogFile $LogFile
                    $stopped++
                }
                catch {
                    Write-Log -Message "Failed to stop $Label PID ${procId}: $($_.Exception.Message)" -Level WARN -LogFile $LogFile
                }
            }
            elseif ($cmd) {
                Write-Log -Message "PID $procId no longer matches $Label (command line changed); leaving it alone." -Level WARN -LogFile $LogFile
            }
        }
        Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
    }

    # 2) Sweep for stragglers that match the signature (scoped to python hosts).
    try {
        $found = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and ($_.CommandLine -match $CommandLineRegex) -and ($_.Name -match '^(python|python3|py|pythonw)(\.exe)?$')
        }
        foreach ($m in $found) {
            try {
                Stop-Process -Id $m.ProcessId -Force -ErrorAction Stop
                Write-Log -Message "Stopped stray $Label (PID $($m.ProcessId))." -LogFile $LogFile
                $stopped++
            }
            catch {
                Write-Log -Message "Failed to stop stray $Label PID $($m.ProcessId): $($_.Exception.Message)" -Level WARN -LogFile $LogFile
            }
        }
    }
    catch {
        Write-Log -Message "Process sweep for $Label failed: $($_.Exception.Message)" -Level WARN -LogFile $LogFile
    }

    if ($stopped -eq 0) {
        Write-Log -Message "No running $Label process found to stop." -LogFile $LogFile
    }
    return $stopped
}

function Get-ApiCommandLineRegex { return $script:ApiCommandLineRegex }
function Get-WorkerCommandLineRegex { return $script:WorkerCommandLineRegex }
