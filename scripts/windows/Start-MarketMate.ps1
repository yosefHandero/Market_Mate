<# Start API, web app, and one worker for this manual session. Ctrl+C stops them. #>
[CmdletBinding()]
param([string]$PythonPath, [switch]$NoAutoScan)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"
$python = Resolve-PythonPath -PythonPath $PythonPath
$arguments = @((Join-Path $PSScriptRoot 'manual_app.py'), 'start')
if ($NoAutoScan) { $arguments += '--no-auto-scan' }
& $python @arguments
exit $LASTEXITCODE
