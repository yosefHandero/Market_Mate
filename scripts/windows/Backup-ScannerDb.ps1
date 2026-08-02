<#
    Backup-ScannerDb.ps1
    Creates a consistent, online backup of the Market Mate SQLite database and
    verifies its integrity. Uses the sqlite3 backup API (via the resolved Python
    interpreter) so it is safe to run while the API/worker are live. Old backups
    are rotated so the backup folder does not grow without bound.

    Usage:
      pwsh -File scripts\windows\Backup-ScannerDb.ps1
      pwsh -File scripts\windows\Backup-ScannerDb.ps1 -KeepCount 30 -PythonPath C:\path\python.exe
#>
param(
    [int]$KeepCount = 14,
    [string]$PythonPath,
    [string]$BackupDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

$logDir = Get-LogDir
$logFile = Join-Path $logDir 'backup-scanner-db.log'

function Resolve-DbPath {
    $url = Get-DotEnvValue -Name 'DATABASE_URL'
    if (-not $url) { $url = 'sqlite:///./market_mate.db' }
    if (-not $url.StartsWith('sqlite:///')) {
        Write-Log -Message "DATABASE_URL is not sqlite ($url); this backup script only supports SQLite." -Level ERROR -LogFile $logFile
        throw "Unsupported DATABASE_URL for file backup: $url"
    }
    $raw = $url.Substring('sqlite:///'.Length)
    if ([System.IO.Path]::IsPathRooted($raw)) {
        return (Resolve-Path -LiteralPath $raw -ErrorAction Stop).Path
    }
    $scannerDir = Get-ScannerDir
    return (Resolve-Path -LiteralPath (Join-Path $scannerDir $raw) -ErrorAction Stop).Path
}

try {
    $python = Resolve-PythonPath -PythonPath $PythonPath
    $dbPath = Resolve-DbPath
    if (-not (Test-Path -LiteralPath $dbPath)) {
        Write-Log -Message "Database file not found at $dbPath; nothing to back up yet." -Level WARN -LogFile $logFile
        return
    }

    if (-not $BackupDir) { $BackupDir = Join-Path (Get-VarDir) 'backups' }
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $dest = Join-Path $BackupDir ("market_mate-{0}.db" -f $stamp)

    # Online backup + integrity verification via the sqlite3 backup API.
    $pyScript = @'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(src)
try:
    backup = sqlite3.connect(dst)
    try:
        source.backup(backup)
    finally:
        backup.close()
    check = sqlite3.connect(dst)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check.close()
finally:
    source.close()
if result != "ok":
    print("integrity_check_failed:" + str(result))
    sys.exit(2)
print("ok")
'@
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $pyScript -Encoding utf8
    try {
        $output = & $python $tmp $dbPath $dest 2>&1
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $dest -ErrorAction SilentlyContinue
            Write-Log -Message "Backup integrity check failed: $output" -Level ERROR -LogFile $logFile
            throw "Backup failed integrity verification: $output"
        }
    }
    finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    }

    $sizeKb = [math]::Round((Get-Item -LiteralPath $dest).Length / 1KB, 1)
    Write-Log -Message "Backup verified OK: $dest ($sizeKb KB)." -LogFile $logFile

    # Rotate: keep the most recent $KeepCount backups.
    $backups = Get-ChildItem -Path $BackupDir -Filter 'market_mate-*.db' | Sort-Object LastWriteTime -Descending
    if ($backups.Count -gt $KeepCount) {
        foreach ($old in $backups | Select-Object -Skip $KeepCount) {
            Remove-Item -LiteralPath $old.FullName -ErrorAction SilentlyContinue
            Write-Log -Message "Rotated out old backup: $($old.Name)" -LogFile $logFile
        }
    }
}
catch {
    Write-Log -Message "Backup-ScannerDb failed: $($_.Exception.Message)" -Level ERROR -LogFile $logFile
    exit 1
}
