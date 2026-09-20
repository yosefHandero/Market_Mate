# Common.ps1
# Shared helpers for the Market Mate Scanner manual Windows scripts and independent backups.
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

    throw "Could not find a Python interpreter. Pass -PythonPath '<full path to python.exe>' or set MARKETMATE_PYTHON."
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
