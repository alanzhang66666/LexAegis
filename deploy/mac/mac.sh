#!/usr/bin/env bash
# LexAegis · Apple Silicon Mac（MacBook Air M4，24GB 统一内存）本机部署。只用于合成材料。
#
# 在仓库根目录运行（macOS 自带 bash 3.2 即可）：
#   bash deploy/mac/mac.sh check      环境体检：芯片 / 内存 / 磁盘 / 供电 / FileVault / 工具 / 网络 / 端口，不改任何东西
#   bash deploy/mac/mac.sh setup      brew 装 llama.cpp、Python 3.12、Node 22，建 Python 环境、构建前端、下载模型
#   bash deploy/mac/mac.sh start      启动边侧模型 + 工作台，打印口令并打开浏览器
#   bash deploy/mac/mac.sh bench      实测各档材料块的抽取耗时（需要先 start 过一次的环境，不需要工作台在运行）
#   bash deploy/mac/mac.sh stop       停止
#   bash deploy/mac/mac.sh status     看进程和端口
#
# 可选环境变量：
#   MODEL=q4|q8|minicpm   默认 q4：Qwen3.5-9B Q4_K_M（约 5.7GB）；q8 是 Qwen3.5-9B Q8_0（约 9.5GB，更慢、更占内存）；
#                         minicpm 是生产声明的 MiniCPM5-2B Q4_K_M（约 1.5GB，最快）
#   PROFILE=production|demo   默认 production（可新建案件并上传自己的合成材料）；demo 是内置的四条演示流程
#   WORK=~/lexaegis-work      模型、Python 环境、数据、日志都放这里（必须在本地磁盘，不要放 iCloud 同步目录）
#   LLAMA_SERVER=/path        使用已有的 llama-server，不通过 brew 安装
#   HF_ENDPOINT / PIP_INDEX_URL / NPM_REGISTRY   换下载镜像
#   NO_OPEN=1                 start 后不自动打开浏览器
#   以及 LEX_EDGE_CTX_SIZE / LEX_EDGE_REQUEST_TIMEOUT / LEX_EDGE_EXTRACT_CHUNK_CHARS 等边侧参数（start 里有默认值，已设置的不覆盖）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEXDIR="$(cd "$HERE/../.." && pwd)"
WORK="${WORK:-$HOME/lexaegis-work}"
PROFILE="${PROFILE:-production}"
MODEL="${MODEL:-q4}"
CMD="${1:-help}"

case "$PROFILE" in
  production) PORT=38765 ;;
  demo) PORT=48765 ;;
  *) echo "PROFILE 只能是 production 或 demo（integration 只接受项目内置场景）" >&2; exit 2 ;;
esac
case "$MODEL" in
  q4)      MODEL_REPO=unsloth/Qwen3.5-9B-GGUF;      MODEL_FILE=Qwen3.5-9B-Q4_K_M.gguf;   MODEL_GB=6;  MODEL_NAME="Qwen3.5-9B Q4_K_M" ;;
  q8)      MODEL_REPO=unsloth/Qwen3.5-9B-GGUF;      MODEL_FILE=Qwen3.5-9B-Q8_0.gguf;     MODEL_GB=10; MODEL_NAME="Qwen3.5-9B Q8_0" ;;
  minicpm) MODEL_REPO=openbmb/MiniCPM5-2B-GGUF;     MODEL_FILE=MiniCPM5-2B-Q4_K_M.gguf;  MODEL_GB=2;  MODEL_NAME="MiniCPM5-2B Q4_K_M" ;;
  *) echo "MODEL 只能是 q4、q8 或 minicpm" >&2; exit 2 ;;
esac
# 允许用环境变量覆盖仓库 / 文件名（比如换别的量化）
MODEL_REPO="${MODEL_REPO_OVERRIDE:-$MODEL_REPO}"; MODEL_FILE="${MODEL_FILE_OVERRIDE:-$MODEL_FILE}"

VENV="$WORK/lexenv"
GGUF="$WORK/models/$MODEL_FILE"
LOG="$WORK/workbench.log"
PASSFILE="$WORK/workbench-password.txt"
APP_PID="$WORK/workbench.pid"
AWAKE_PID="$WORK/caffeinate.pid"
EDGE_PID="$WORK/llama-server.pid"
NPM_REGISTRY="${NPM_REGISTRY:-}"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }
[ -f "$LEXDIR/lexaegis/cli.py" ] || die "请在 LexAegis 仓库里运行（找不到 lexaegis/cli.py）"

brew_prefix() { brew --prefix "$1" 2>/dev/null || true; }
py312() {
  if [ -x "$VENV/bin/python" ]; then echo "$VENV/bin/python"; return; fi
  local p; p="$(brew_prefix python@3.12)"
  if [ -n "$p" ] && [ -x "$p/bin/python3.12" ]; then echo "$p/bin/python3.12"; return; fi
  command -v python3.12 || true
}
node22_dir() {
  local p; p="$(brew_prefix node@22)"
  if [ -n "$p" ] && [ -x "$p/bin/node" ]; then echo "$p/bin"; return; fi
  if command -v node >/dev/null 2>&1 && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ]; then dirname "$(command -v node)"; return; fi
}
llama_server() {
  if [ -n "${LLAMA_SERVER:-}" ]; then echo "$LLAMA_SERVER"; return; fi
  command -v llama-server || true
}
kill_pidfile() {
  local f="$1" pid
  [ -s "$f" ] || return 0
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
}

check() {
  local bad=0 warn=0
  ok()   { printf '  [通过] %s\n' "$*"; }
  note() { printf '  [注意] %s\n' "$*"; warn=$((warn + 1)); }
  fail() { printf '  [不行] %s\n' "$*"; bad=$((bad + 1)); }

  echo "== 系统"
  if [ "$(uname -s)" != Darwin ]; then fail "这不是 macOS（$(uname -s)）。Linux 请用 deploy/aliyun 或 deploy/cpu"; echo; echo "体检结果：$bad 项不行。"; return 1; fi
  local arch chip osver mem_gb translated
  arch="$(uname -m)"; chip="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 未知)"; osver="$(sw_vers -productVersion 2>/dev/null || echo 未知)"
  mem_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
  translated="$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)"
  echo "  芯片 $chip  架构 $arch  macOS $osver  内存 ${mem_gb}GB  CPU $(sysctl -n hw.ncpu 2>/dev/null) 核"
  if [ "$arch" != arm64 ] || [ "$translated" = 1 ]; then
    fail "不是原生 Apple Silicon 终端（arch=$arch，Rosetta=$translated）：Metal 加速和内存带宽都会打折。请用原生终端"
  else ok "原生 arm64（Metal 可用）"; fi
  if [ "${osver%%.*}" -lt 13 ] 2>/dev/null; then note "macOS $osver 较旧，brew 的 llama.cpp 需要较新的系统"; fi

  echo "== 内存预算（$MODEL_NAME）"
  # 经验：权重控制在统一内存的 60% 以内，给系统、工作台和上下文缓存留余量
  if [ "$mem_gb" -le 0 ]; then note "读不到内存大小"
  elif [ $((MODEL_GB * 100)) -gt $((mem_gb * 60)) ]; then
    fail "权重约 ${MODEL_GB}GB，超过 ${mem_gb}GB 内存的 60%。换更小的 MODEL=q4 或 minicpm"
  else ok "权重约 ${MODEL_GB}GB / ${mem_gb}GB（${MODEL_GB}×100÷${mem_gb}≈$((MODEL_GB * 100 / mem_gb))%，上限 60%）"; fi
  if [ "$mem_gb" -le 16 ] && [ "$MODEL" = q8 ]; then note "16GB 机器不建议 q8"; fi

  echo "== 磁盘与位置"
  mkdir -p "$WORK" 2>/dev/null || true
  local avail_gb; avail_gb=$(( $(df -k "$WORK" 2>/dev/null | awk 'NR==2{print $4}') / 1048576 ))
  echo "  工作目录 $WORK：可用约 ${avail_gb}GB"
  if [ "$avail_gb" -lt 20 ]; then fail "可用磁盘 ${avail_gb}GB，不够（权重 ${MODEL_GB}GB + Python 依赖 + 前端依赖，至少留 20GB）"; else ok "磁盘空间"; fi
  case "$LEXDIR $WORK" in
    *"/Desktop"*|*"/Documents"*|*"Mobile Documents"*|*"iCloud"*)
      note "仓库或工作目录在 桌面/文档/iCloud 下：若开了「桌面与文稿」同步，数据库和材料会被同步到云端。建议放在 ~/lexaegis-work 之类不同步的位置" ;;
    *) ok "路径不在 iCloud 常见同步目录里" ;;
  esac

  echo "== 供电与加密"
  if pmset -g batt 2>/dev/null | head -1 | grep -q "AC Power"; then ok "接着电源"; else note "正在用电池：跑模型会很耗电，建议接电源（Air 无风扇，持续负载会降频，速度会比估计的慢）"; fi
  local fv; fv="$(fdesetup status 2>/dev/null || true)"
  case "$fv" in
    *"is On"*) ok "FileVault 已开启（磁盘加密）" ;;
    *"is Off"*) note "FileVault 未开启：数据库和材料以明文落在磁盘上。丢机器会泄露，建议在「系统设置 → 隐私与安全性」开启" ;;
    *) note "读不到 FileVault 状态" ;;
  esac

  echo "== 工具"
  if command -v brew >/dev/null 2>&1; then ok "Homebrew"; else fail "没有 Homebrew：先装 https://brew.sh ，或自己准备 llama-server、Python 3.12、Node 22"; fi
  local ls; ls="$(llama_server)"
  if [ -n "$ls" ] && [ -x "$ls" ]; then ok "llama-server：$ls"; else note "还没有 llama-server（setup 会 brew install llama.cpp）"; fi
  if [ -n "$(py312)" ]; then ok "Python 3.12：$(py312)"; else note "还没有 Python 3.12（setup 会 brew install python@3.12）"; fi
  if [ -n "$(node22_dir)" ]; then ok "Node 22+：$(node22_dir)"; else note "还没有 Node 22+（setup 会 brew install node@22）"; fi
  if command -v git >/dev/null 2>&1; then ok "git"; else note "没有 git（只影响更新代码；首次会弹出命令行工具安装）"; fi
  if [ -f "$GGUF" ]; then ok "权重已就位：$GGUF"; else note "权重还没下载（setup 会下载约 ${MODEL_GB}GB）"; fi

  echo "== 端口 $PORT"
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    if [ -s "$APP_PID" ] && kill -0 "$(cat "$APP_PID")" 2>/dev/null; then ok "端口 $PORT 被本脚本启动的工作台占用（start 会先停掉再重启）"; else fail "端口 $PORT 已被别的程序占用"; fi
  else ok "端口空闲"; fi
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1 && [ ! -s "$EDGE_PID" ]; then
    note "8080 已被别的程序占用：边侧模型默认用 8080，请先关掉它，或设 LEX_EDGE_URL"
  fi

  echo "== 网络（8 秒超时）"
  local url
  for url in "${HF_ENDPOINT:-https://huggingface.co}" https://pypi.org/simple/ https://registry.npmjs.org; do
    if curl -sI -m 8 -o /dev/null "$url"; then ok "$url"; else
      case "$url" in
        *hugging*|*hf-mirror*) note "$url 不通：权重下不了。可设 HF_ENDPOINT=https://hf-mirror.com，或手动把 $MODEL_FILE 放到 $WORK/models/" ;;
        *pypi*) note "$url 不通：可设 PIP_INDEX_URL 换镜像" ;;
        *) note "$url 不通：可设 NPM_REGISTRY 换镜像" ;;
      esac
    fi
  done

  echo
  if [ "$bad" -gt 0 ]; then echo "体检结果：$bad 项不行、$warn 项注意。先解决「不行」的项再 setup。"; return 1; fi
  echo "体检结果：没有硬性问题（$warn 项注意）。可以运行 setup。"
}

setup() {
  command -v brew >/dev/null 2>&1 || die "没有 Homebrew"
  mkdir -p "$WORK/models"

  log "安装依赖（brew：llama.cpp、python@3.12、node@22；已有的会跳过）"
  if [ -z "$(llama_server)" ]; then brew install llama.cpp; fi
  if [ -z "$(py312)" ]; then brew install python@3.12; fi
  if [ -z "$(node22_dir)" ]; then brew install node@22; fi
  local ls; ls="$(llama_server)"
  [ -n "$ls" ] && [ -x "$ls" ] || die "仍然找不到 llama-server（brew 的 llama.cpp 应提供 llama-server）"

  log "Python 环境（$VENV）"
  if [ ! -x "$VENV/bin/python" ]; then
    local py; py="$(py312)"; [ -n "$py" ] || die "找不到 Python 3.12"
    "$py" -m venv "$VENV"
  fi
  local pipidx=(); [ -n "${PIP_INDEX_URL:-}" ] && pipidx=(-i "$PIP_INDEX_URL")
  "$VENV/bin/pip" install -q --upgrade pip ${pipidx[@]+"${pipidx[@]}"}
  # 依赖锁 + macOS 约束；项目本体只做可编辑安装，不再解析依赖
  "$VENV/bin/pip" install -q -r "$LEXDIR/requirements.lock" -c "$LEXDIR/constraints/macos.txt" ${pipidx[@]+"${pipidx[@]}"}
  (cd "$LEXDIR" && "$VENV/bin/pip" install -q --no-deps -e .)
  "$VENV/bin/pip" install -q huggingface_hub ${pipidx[@]+"${pipidx[@]}"}

  log "构建前端"
  if [ ! -f "$LEXDIR/frontend/dist/index.html" ]; then
    local nd; nd="$(node22_dir)"; [ -n "$nd" ] || die "找不到 Node 22+"
    local reg=(); [ -n "$NPM_REGISTRY" ] && reg=(--registry="$NPM_REGISTRY")
    (cd "$LEXDIR/frontend" && PATH="$nd:$PATH" npx -y ${reg[@]+"${reg[@]}"} pnpm@11.19.0 install --frozen-lockfile ${reg[@]+"${reg[@]}"} \
       && PATH="$nd:$PATH" npx -y ${reg[@]+"${reg[@]}"} pnpm@11.19.0 build) >/dev/null
  fi
  [ -f "$LEXDIR/frontend/dist/index.html" ] || die "前端构建失败"

  log "下载模型 $MODEL_NAME（约 ${MODEL_GB}GB）"
  if [ -f "$GGUF" ]; then
    echo "已存在：$GGUF"
  else
    MODEL_REPO="$MODEL_REPO" MODEL_FILE="$MODEL_FILE" DEST="$WORK/models" "$VENV/bin/python" - <<'PY'
import os, sys
from huggingface_hub import hf_hub_download, list_repo_files
repo, name, dest = os.environ["MODEL_REPO"], os.environ["MODEL_FILE"], os.environ["DEST"]
files = list_repo_files(repo)
if name not in files:
    near = [f for f in files if f.endswith(".gguf")]
    sys.exit(f"仓库 {repo} 里没有 {name}。现有 gguf：{near[:12]}")
print("下载", repo, name)
print(hf_hub_download(repo, name, local_dir=dest))
PY
  fi
  [ -f "$GGUF" ] || die "没拿到权重 $GGUF"

  echo
  echo "安装完成。下一步：bash $0 start（先想测速度的话：bash $0 bench）"
}

export_edge_env() {
  local ls; ls="$(llama_server)"
  [ -n "$ls" ] && [ -x "$ls" ] || die "找不到 llama-server，请先 setup"
  [ -f "$GGUF" ] || die "找不到权重 $GGUF，请先 setup（或换 MODEL=）"
  export LEX_EDGE_BIN="$ls" LEX_EDGE_GGUF="$GGUF" LEX_EDGE_MODEL=edge-small LEX_EDGE_URL="${LEX_EDGE_URL:-http://127.0.0.1:8080/v1}"
  export LEX_EDGE_PID_FILE="$EDGE_PID"
  # 以下是 24GB 统一内存上的保守默认；已设置的不覆盖
  export LEX_EDGE_CTX_SIZE="${LEX_EDGE_CTX_SIZE:-16384}"
  export LEX_EDGE_N_GPU_LAYERS="${LEX_EDGE_N_GPU_LAYERS:-99}"
  export LEX_EDGE_START_WAIT="${LEX_EDGE_START_WAIT:-120}"
  export LEX_EDGE_REQUEST_TIMEOUT="${LEX_EDGE_REQUEST_TIMEOUT:-600}"
  export LEX_EDGE_EXTRACT_CHUNK_CHARS="${LEX_EDGE_EXTRACT_CHUNK_CHARS:-6000}"
  export LEX_EDGE_EXTRACT_CHUNK_BLOCKS="${LEX_EDGE_EXTRACT_CHUNK_BLOCKS:-6}"
  export LEX_EDGE_EXTRACT_MAX_TOKENS="${LEX_EDGE_EXTRACT_MAX_TOKENS:-2048}"
  export LEX_EDGE_EXTRACT_MAX_FACTS="${LEX_EDGE_EXTRACT_MAX_FACTS:-30}"
  export PATH="$VENV/bin:$PATH"
}

start() {
  [ -x "$VENV/bin/lexaegis" ] || die "没找到 Python 环境，请先运行：bash $0 setup"
  [ -f "$LEXDIR/frontend/dist/index.html" ] || die "前端还没构建，请先运行：bash $0 setup"
  export_edge_env
  stop >/dev/null 2>&1 || true
  mkdir -p "$WORK/data"
  export LEX_PROFILE_ROOT="$WORK/data" LEX_RUN_PROFILE="$PROFILE"

  if [ ! -s "$PASSFILE" ]; then (umask 077; "$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(18))' > "$PASSFILE"); fi
  export LEX_LOCAL_PASSWORD; LEX_LOCAL_PASSWORD="$(cat "$PASSFILE")"

  cd "$LEXDIR"
  log "启动边侧模型 $MODEL_NAME（首次加载约几十秒，Metal 会预热）"
  "$VENV/bin/lexaegis" edge --start || echo "[注意] 边侧模型没能预先启动；抽取时 worker 会再尝试拉起，也可以看 $WORK 下的日志"

  log "启动工作台（$PROFILE）"
  nohup "$VENV/bin/lexaegis" start --profile "$PROFILE" > "$LOG" 2>&1 &
  echo $! > "$APP_PID"
  local port=""
  for _ in $(seq 1 60); do
    port="$(grep -o '127\.0\.0\.1:[0-9]*' "$LOG" 2>/dev/null | head -1 | cut -d: -f2 || true)"
    if [ -n "$port" ] && curl -sf "http://127.0.0.1:$port/api/v1/health" >/dev/null 2>&1; then break; fi
    port=""; sleep 2
  done
  [ -n "$port" ] || { tail -30 "$LOG"; die "工作台没有起来，日志见 $LOG"; }

  # 工作台运行期间不让系统因空闲睡眠（合盖仍会睡眠，见 README）
  if command -v caffeinate >/dev/null 2>&1; then
    nohup caffeinate -i -w "$(cat "$APP_PID")" >/dev/null 2>&1 &
    echo $! > "$AWAKE_PID"
  fi

  local url="http://127.0.0.1:$port"
  if [ -z "${NO_OPEN:-}" ] && command -v open >/dev/null 2>&1; then open "$url" || true; fi
  cat <<EOF

==================== 工作台已启动 ====================
环境：$PROFILE    边侧模型：$MODEL_NAME（Metal，上下文 ${LEX_EDGE_CTX_SIZE}）
地址：$url（只在本机访问，不需要隧道）
用户名：admin    口令：cat $PASSFILE
日志：$LOG      停止：bash $0 stop
只放合成材料。合盖会睡眠并中断抽取；长任务请接电源、开着盖子。
EOF
}

stop() {
  kill_pidfile "$APP_PID"
  kill_pidfile "$AWAKE_PID"
  if [ -x "$VENV/bin/lexaegis" ]; then
    LEX_EDGE_PID_FILE="$EDGE_PID" "$VENV/bin/python" -c 'from lexaegis.edge_runtime import stop_edge; stop_edge()' >/dev/null 2>&1 || true
  fi
  kill_pidfile "$EDGE_PID"
  echo "已停止"
}

status() {
  local p f
  for p in "$APP_PID:工作台" "$EDGE_PID:边侧模型" "$AWAKE_PID:防睡眠"; do
    f="${p%%:*}"
    if [ -s "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then echo "  ${p##*:}：运行中（PID $(cat "$f")）"; else echo "  ${p##*:}：未运行"; fi
  done
  if command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$PORT" -iTCP:8080 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print "  监听 "$9" ("$1")"}'; fi
}

bench() {
  [ -x "$VENV/bin/python" ] || die "没找到 Python 环境，请先 setup"
  export_edge_env
  cd "$LEXDIR"
  local started=0
  if ! curl -sf "${LEX_EDGE_URL%/v1}/health" >/dev/null 2>&1; then
    log "启动边侧模型"
    "$VENV/bin/lexaegis" edge --start || die "边侧模型启动失败"; started=1
  fi
  log "实测抽取耗时（SIZES=${SIZES:-1000,3000,6000}，超时 ${LEX_EDGE_REQUEST_TIMEOUT} 秒；全部是合成文本）"
  SIZES="${SIZES:-1000,3000,6000}" "$VENV/bin/python" - < "$LEXDIR/deploy/cpu/bench_edge.py"
  if [ "$started" = 1 ] && [ ! -s "$APP_PID" ]; then
    LEX_EDGE_PID_FILE="$EDGE_PID" "$VENV/bin/python" -c 'from lexaegis.edge_runtime import stop_edge; stop_edge()' >/dev/null 2>&1 || true
  fi
}

case "$CMD" in
  check) check ;;
  setup) log "先体检"; check || die "体检未通过"; setup ;;
  start) start ;;
  stop) stop ;;
  status) status ;;
  bench) bench ;;
  *) sed -n 2,19p "$0"; [ "$CMD" = help ] || exit 2 ;;
esac
