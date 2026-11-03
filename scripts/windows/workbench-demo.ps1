param(
    [ValidateSet('init','build','start','stop','status','verify','repair')]
    [string]$Action = 'status',
    [string]$RuntimeRoot = '',
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Options
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create this checkout venv and install the project first.' }
$controller = Join-Path $projectRoot 'deploy\workbench_demo\control.py'
$arguments = @($controller, $Action)
if ($RuntimeRoot) { $arguments += @('--runtime-root', $RuntimeRoot) }
& $python @arguments @Options
exit $LASTEXITCODE
