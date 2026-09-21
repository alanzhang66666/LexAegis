param(
    [string]$PythonCommand = "python",
    [int]$ApiPort = 48765,
    [int]$GatewayPort = 48766,
    [int]$EdgePort = 8080,
    [int]$GpuLayers = 0,
    [string]$LocalPassword = "",
    [switch]$SkipEdge,
    [switch]$FixedDemoReview
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root ".runtime"
$venv = Join-Path $runtime "venv"
$python = Join-Path $venv "Scripts\python.exe"
$wheelhouse = Join-Path $root "vendor\wheels"
$appWheel = Get-ChildItem -LiteralPath $wheelhouse -Filter "lexaegis-1.0.0-*.whl" | Select-Object -First 1

function Test-CompatiblePython {
    param([string]$Executable, [string[]]$Prefix = @())
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Executable @Prefix -c "import sys, platform; assert sys.version_info[:2] in ((3,12),(3,13)); assert platform.machine().lower() in ('amd64','x86_64')" *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
}

if (-not $appWheel) {
    throw "离线 wheelhouse 缺少 lexaegis-1.0.0 wheel"
}
if (-not (Test-Path -LiteralPath (Join-Path $root "container\edge-runtime\windows\llama-server.exe"))) {
    throw "缺少随包 llama-server.exe"
}
if (-not (Test-Path -LiteralPath (Join-Path $root "models\edge\qwen3-4b-grpo\runtime\Qwen3-4B-GRPO.Q4_K_M.gguf"))) {
    throw "缺少随包边侧 GGUF"
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (-not (Test-Path -LiteralPath $python)) {
    $pythonExe = $null
    $pythonPrefix = @()
    $requested = Get-Command $PythonCommand -ErrorAction SilentlyContinue
    if ($requested -and (Test-CompatiblePython -Executable $requested.Source)) {
        $pythonExe = $requested.Source
    }
    if (-not $pythonExe) {
        $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            foreach ($version in @("-3.13", "-3.12")) {
                if (Test-CompatiblePython -Executable $pyLauncher.Source -Prefix @($version)) {
                    $pythonExe = $pyLauncher.Source
                    $pythonPrefix = @($version)
                    break
                }
            }
        }
    }
    if (-not $pythonExe) {
        throw "需要 Windows x64 Python 3.12 或 3.13；可用 -PythonCommand 指定 python.exe"
    }
    & $pythonExe @pythonPrefix -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "创建本地运行环境失败" }
}

$wheelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $appWheel.FullName).Hash.ToLowerInvariant()
$installMarker = Join-Path $runtime "installed-wheel.sha256"
$installedHash = if (Test-Path -LiteralPath $installMarker) {
    (Get-Content -Raw -LiteralPath $installMarker).Trim()
} else { "" }
if ($installedHash -ne $wheelHash) {
    $env:PIP_NO_INDEX = "1"
    & $python -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse "lexaegis==1.0.0"
    if ($LASTEXITCODE -ne 0) { throw "离线依赖安装失败" }
    Set-Content -LiteralPath $installMarker -Value $wheelHash -Encoding ascii
}

$env:LEX_RUN_PROFILE = "demo"
$env:LEX_API_PORT = "$ApiPort"
$env:LEX_GATEWAY_PORT = "$GatewayPort"
$env:LEX_GATEWAY_URL = "http://127.0.0.1:$GatewayPort"
$env:LEX_BIND_HOST = "127.0.0.1"
$env:LEX_DATA_DIR = Join-Path $runtime "data\app"
$env:LEX_GATEWAY_DIR = Join-Path $runtime "data\gateway"
$env:LEX_EDGE_URL = "http://127.0.0.1:$EdgePort/v1"
$env:LEX_EDGE_MODEL = "lexaegis-qwen3-4b-grpo"
$env:LEX_EDGE_BIN = Join-Path $root "container\edge-runtime\windows\llama-server.exe"
$env:LEX_EDGE_GGUF = Join-Path $root "models\edge\qwen3-4b-grpo\runtime\Qwen3-4B-GRPO.Q4_K_M.gguf"
$env:LEX_EDGE_PID_FILE = Join-Path $runtime "edge\llama-server.pid"
$env:LEX_EDGE_OUTBOUND_REVIEW = "1"
$env:LEX_DEMO_LIVE_EDGE_REVIEW = if ($FixedDemoReview) { "0" } else { "1" }
$env:LEX_EDGE_CTX_SIZE = "4096"
$env:LEX_EDGE_BATCH_SIZE = "512"
$env:LEX_EDGE_UBATCH_SIZE = "256"
$env:LEX_EDGE_N_GPU_LAYERS = "$GpuLayers"
$env:LEX_EDGE_FLASH_ATTN = if ($GpuLayers -gt 0) { "on" } else { "off" }
if ($LocalPassword) {
    $env:LEX_LOCAL_PASSWORD = $LocalPassword
}

try {
    if (-not $SkipEdge) {
        & $python -m lexaegis.cli edge --start
        if ($LASTEXITCODE -ne 0) { throw "边侧模型启动失败" }
    }
    Write-Host "比赛版工作台将启动：http://127.0.0.1:$ApiPort"
    Write-Host "三层演示使用实时边侧模型：$($env:LEX_DEMO_LIVE_EDGE_REVIEW -eq '1')"
    & $python -m lexaegis.cli start --profile demo
    exit $LASTEXITCODE
}
finally {
    if (-not $SkipEdge) {
        & $python -m lexaegis.cli edge --stop 2>$null | Out-Null
    }
}
