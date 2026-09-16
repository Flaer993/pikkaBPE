$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PIKKABPE_DATA = Join-Path $projectRoot 'data'
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m pikkabpe.app
