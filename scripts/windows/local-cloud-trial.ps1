param([ValidateSet('start', 'stop', 'status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$lexTrialProject = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
& (Join-Path $lexTrialProject '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'local-cloud-trial.py') $Action
exit $LASTEXITCODE
