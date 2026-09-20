<# One-time retirement only. Run in an elevated PowerShell; never registers tasks. #>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"
$repo = Get-RepoRoot
$archive = Join-Path (Get-VarDir) ('retired-scheduled-tasks\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $archive -Force | Out-Null
$names = @(
    'MarketMate-Daily-Overnight', 'MarketMate-Weekday-Market', 'MarketMate-Weekend-Crypto',
    'MarketMate-WakeOnly15', 'MarketMate-WakeOnlyBattery', 'MarketMate-WakeOnlyTest', 'MarketMate-WakeTest'
)
$before = @(Get-ScheduledTask | Select-Object TaskName, TaskPath)
$before | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archive 'task-inventory-before.json') -Encoding utf8
$exports = @()
try {
    foreach ($name in $names) {
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        if (-not $task) { continue }
        $arguments = $task.Actions.Arguments -join ' '
        if ($arguments -notmatch [regex]::Escape($repo)) {
            throw "Refusing to retire $name because its action does not reference this repository."
        }
        if ($arguments -notmatch 'Invoke-WakeWindow\.ps1|wake-only(-battery)?-test\.txt') {
            throw "Refusing to retire $name because its action is not a recognized wake/scan action."
        }
        $xml = Export-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
        if (-not ([xml]$xml).Task) { throw "Invalid exported XML for $name" }
        $path = Join-Path $archive "$name.xml"
        $xml | Set-Content -LiteralPath $path -Encoding Unicode
        $exports += [pscustomobject]@{
            TaskName = $name; TaskPath = '\'; ExportPath = $path
            Sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        }
    }
    $exports | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archive 'manifest.json') -Encoding utf8
    foreach ($item in $exports) {
        if ((Get-FileHash -LiteralPath $item.ExportPath -Algorithm SHA256).Hash -ne $item.Sha256) {
            throw "Task export changed: $($item.TaskName)"
        }
        Unregister-ScheduledTask -TaskName $item.TaskName -TaskPath $item.TaskPath -Confirm:$false -ErrorAction Stop
        Write-Host "Retired $($item.TaskName)"
    }
}
finally {
    $after = @(Get-ScheduledTask | Select-Object TaskName, TaskPath)
    $after | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archive 'task-inventory-after.json') -Encoding utf8
    Compare-Object ($before | ForEach-Object { $_.TaskPath + $_.TaskName }) ($after | ForEach-Object { $_.TaskPath + $_.TaskName }) |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archive 'task-inventory-diff.json') -Encoding utf8
    Write-Host "Task exports and inventories: $archive"
}
