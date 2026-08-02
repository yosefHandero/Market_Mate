$ErrorActionPreference = 'Stop'
$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $RootDir 'services\scanner')
python -m app.worker
