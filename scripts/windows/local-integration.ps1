param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status',
    [switch]$NoBrowser,
    [switch]$NoPassword
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logDir = Join-Path $projectRoot '.data/logs'
$lockHandle = $null
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Missing .venv. Create the Python environment and install dependencies first.'
    }
    $configText = & $python -c "import json; from dotenv import load_dotenv; load_dotenv('.env'); from lexaegis.runtime_profile import profile_config; c=profile_config('integration'); print(json.dumps({'api_port':c['api_port'],'gateway_port':c['gateway_port'],'password_file':str(c['app_dir'] / 'local-password')}))"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot load integration configuration. Check LEX_RUN_PROFILE in .env.' }
    $config = $configText | ConvertFrom-Json
    $url = "http://127.0.0.1:$($config.api_port)"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    try {
        $lockHandle = [System.IO.File]::Open((Join-Path $logDir 'integration-control.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch { throw 'Another start/stop operation is running. Try again shortly.' }

    function Get-ProjectLaunchers {
        # Match this checkout's explicit Python path, never every Python process.
        $pattern = '^\s*"?' + [regex]::Escape($python) + '"?\s+(?:-u\s+)?-m\s+lexaegis\.cli\s+start\s+--profile\s+integration\s*$'
        @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object { $_.CommandLine -match $pattern })
    }

    function Test-Workbench {
        $client = New-Object System.Net.WebClient
        $client.Proxy = $null
        try {
            $health = $client.DownloadString("$url/api/v1/health") | ConvertFrom-Json
            return ($health.status -eq 'ok' -and $health.runtime_profile -eq 'integration')
        } catch { return $false }
        finally { $client.Dispose() }
    }

    function Get-OccupiedPorts {
        @(Get-NetTCPConnection -LocalPort $config.api_port,$config.gateway_port -State Listen -ErrorAction SilentlyContinue)
    }

    function Show-Workbench {
        Write-Host "Workbench: $url"
        if (-not $NoBrowser) {
            # Use the installed browser automation dependency only to fill the
            # original form. The user submits it; no login API is added.
            $prefill = @'
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = process.cwd();
const {chromium} = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const checkOnly = process.env.LEX_PREFILL_CHECK_ONLY === '1';
let browser;
(async () => {
  const code = "import json,os; from dotenv import load_dotenv; load_dotenv('.env'); from lexaegis.runtime_profile import profile_config; c=profile_config('integration'); print(json.dumps({'password':os.getenv('LEX_LOCAL_PASSWORD') or (c['app_dir']/'local-password').read_text(encoding='utf-8').strip(),'url':'http://127.0.0.1:'+str(c['api_port'])}))";
  const config = JSON.parse(execFileSync(path.join(root, '.venv/Scripts/python.exe'), ['-c', code], {cwd: root, encoding: 'utf8', windowsHide: true}));
  browser = await chromium.launch({channel: 'msedge', headless: checkOnly});
  const page = await browser.newPage();
  await page.goto(config.url);
  await page.locator('input[autocomplete="username"]').fill('admin');
  const password = page.locator('input[autocomplete="current-password"]');
  await password.fill(config.password);
  await page.getByRole('button', {name: '进入工作台'}).focus();
  if (checkOnly) {
    if (await password.inputValue() !== config.password) throw new Error();
    const status = await page.evaluate(async () => (await fetch('/api/v1/me')).status);
    if (status !== 401 || !await page.locator('.login-card').isVisible()) throw new Error();
    await browser.close();
    return;
  }
  browser.on('disconnected', () => process.exit(0));
})().catch(async () => {
  if (browser) await browser.close();
  console.error('Could not fill the local login form.');
  process.exit(1);
});
'@
            $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($prefill))
            $node = (Get-Command node.exe -ErrorAction Stop).Source
            $browserProcess = Start-Process -FilePath $node -ArgumentList '-e',("`"eval(Buffer.from('$encoded','base64').toString())`"") -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
            if ($env:LEX_PREFILL_CHECK_ONLY -eq '1') {
                $null = $browserProcess.Handle
                $browserProcess.WaitForExit()
                if ($browserProcess.ExitCode -ne 0) { throw 'Login form prefill verification failed.' }
                Write-Host 'Verified: password filled; login still waits for the user.'
            } else {
                Write-Host 'Opening the original login page with the local password filled. Click the login button to continue.'
            }
        }
    }

    if ($Action -eq 'stop') {
        $launchers = @(Get-ProjectLaunchers)
        foreach ($launcher in $launchers) {
            # Re-read identity before terminating its own API/gateway/worker tree.
            $current = @(Get-ProjectLaunchers | Where-Object {
                $_.ProcessId -eq $launcher.ProcessId -and $_.CreationDate -eq $launcher.CreationDate
            })
            if ($current.Count -gt 0) {
                & taskkill.exe /PID $launcher.ProcessId /T /F | Out-Null
                if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $launcher.ProcessId -ErrorAction SilentlyContinue)) {
                    throw "Could not stop launcher $($launcher.ProcessId)."
                }
            }
        }
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (@(Get-OccupiedPorts).Count -eq 0) { break }
            Start-Sleep -Milliseconds 250
        }
        if (@(Get-OccupiedPorts).Count -gt 0) {
            throw 'Ports remain occupied by processes outside the managed launcher. They were left running.'
        }
        Write-Host 'Integration stopped. Case data and .env are retained.'
    } elseif ($Action -eq 'status') {
        if (Test-Workbench) { Write-Host "Integration running: $url" }
        else { Write-Host 'Integration is not ready.' }
    } else {
        $launchers = @(Get-ProjectLaunchers)
        if ((Test-Workbench) -and $launchers.Count -gt 0) {
            Write-Host 'Integration is already running; reusing it.'
            Show-Workbench
        } else {
            if ($launchers.Count -gt 0 -or @(Get-OccupiedPorts).Count -gt 0) {
                throw 'An existing or incomplete instance occupies these ports. Run the stop script first.'
            }
            $env:PYTHONUTF8 = '1'
            $process = Start-Process -FilePath $python -ArgumentList '-u','-m','lexaegis.cli','start','--profile','integration' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'integration.stdout.log') -RedirectStandardError (Join-Path $logDir 'integration.stderr.log') -PassThru
            Set-Content -LiteralPath (Join-Path $logDir 'integration.pid') -Value $process.Id
            $ready = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                Start-Sleep -Milliseconds 500
                $process.Refresh()
                if ($process.HasExited) { break }
                if ((Test-Workbench) -and @(Get-OccupiedPorts).Count -ge 2) { $ready = $true; break }
            }
            if (-not $ready) { throw "Startup did not complete. Check $logDir/integration.stderr.log" }
            Write-Host 'Integration started in the background.'
            Show-Workbench
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($lockHandle) { $lockHandle.Dispose() }
    Pop-Location
}
