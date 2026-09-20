<# Ask this repository's manual session to stop its owned services. #>
[CmdletBinding()]
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"
$python = Resolve-PythonPath -PythonPath $PythonPath
& $python (Join-Path $PSScriptRoot 'manual_app.py') stop
exit $LASTEXITCODE
