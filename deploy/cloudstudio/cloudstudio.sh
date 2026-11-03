#!/usr/bin/env bash
# LexAegis · 腾讯云 Cloud Studio「免费高性能空间」（T4 16G）试用部署。只用于合成材料。
#
# 在 Cloud Studio 的终端里（先 git clone 仓库并进入）：
#   bash deploy/cloudstudio/cloudstudio.sh check    环境体检：GPU / 驱动 / CUDA 工具链 / 磁盘 / 网络 / 预览地址，不改任何东西
#   bash deploy/cloudstudio/cloudstudio.sh setup    编译 llama.cpp（CUDA）、下载 Qwen3.5-9B、准备 Python 环境，并跑一遍抽取耗时测试
#   bash deploy/cloudstudio/cloudstudio.sh start    启动工作台，打印预览地址和登录口令
#   bash deploy/cloudstudio/cloudstudio.sh stop     停止
#   bash deploy/cloudstudio/cloudstudio.sh url      只打印预览地址
#
# 可选环境变量：
#   WORK=/workspace          工作目录（模型、编译产物、Python 环境都放这里；Cloud Studio 的 /workspace 在空间关机后保留）
#   PROFILE=production|demo  默认 production（可新建案件并上传自己的合成材料）；demo 是内置的四条演示流程
#   PREVIEW_URL=https://...  手动指定预览地址（默认用 Cloud Studio 预置的 X_IDE_SPACE_* 环境变量拼出）
#   LLAMA_SERVER=/path       使用已有的 llama-server，跳过编译
#   HF_ENDPOINT / PIP_INDEX_URL / MODEL_REPO / MODEL_FILE   同 deploy/aliyun/dsw_edge_test.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALIYUN="$HERE/../aliyun"
WORK="${WORK:-/workspace}"; [ -d "$WORK" ] || WORK="$HOME"
PROFILE="${PROFILE:-production}"
case "$PROFILE" in production) PORT=38765 ;; demo) PORT=48765 ;; *) echo "PROFILE 只能是 production 或 demo" >&2; exit 2 ;; esac
export WORK PROFILE

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }
[ -f "$HERE/../../lexaegis/cli.py" ] && [ -f "$ALIYUN/dsw_edge_test.sh" ] \
  || die "请先把仓库克隆下来再运行：git clone <仓库地址> && cd LexAegis（仓库未合并时加 -b <分支>）"

preview_url() {
  if [ -n "${PREVIEW_URL:-}" ]; then echo "${PREVIEW_URL%/}"; return; fi
  local v
  for v in X_IDE_SPACE_KEY X_IDE_SPACE_REGION X_IDE_SPACE_HOST; do
    [ -n "${!v:-}" ] || die "没有环境变量 $v（应由 Cloud Studio 预置）。可手动指定：PREVIEW_URL=https://<空间标识>--$PORT.<区域>.<平台域名> bash $0 $CMD"
  done
  echo "https://${X_IDE_SPACE_KEY}--${PORT}.${X_IDE_SPACE_REGION}.${X_IDE_SPACE_HOST}"
}

check() {
  local bad=0 warn=0
  ok()   { printf '  [通过] %s\n' "$*"; }
  note() { printf '  [注意] %s\n' "$*"; warn=$((warn + 1)); }
  fail() { printf '  [不行] %s\n' "$*"; bad=$((bad + 1)); }

  echo "== 基本环境"
  echo "  用户 $(id -un)（uid $(id -u)）  系统 $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-未知}")"
  echo "  CPU $(nproc) 核  内存 $(free -g 2>/dev/null | awk '/^Mem:/{print $2}') GB"
  df -h "$WORK" 2>/dev/null | awk 'NR==2{printf "  工作目录 %s：总 %s，可用 %s\n", "'"$WORK"'", $2, $4}'
  local avail_gb; avail_gb=$(df -BG --output=avail "$WORK" 2>/dev/null | tail -1 | tr -dc '0-9')
  if [ -n "$avail_gb" ] && [ "$avail_gb" -lt 25 ]; then fail "可用磁盘 ${avail_gb}GB，不够（权重约 10GB + 编译产物 + 依赖，至少留 25GB）"; else ok "磁盘空间"; fi

  echo "== GPU"
  if nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | sed 's/^/  /'
    local vram; vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -dc '0-9')
    if [ -n "$vram" ] && [ "$vram" -lt 14000 ]; then fail "显存 ${vram}MiB，放不下 Qwen3.5-9B Q8_0（约 10GB + 缓存）"; else ok "GPU 与显存"; fi
    local dcuda; dcuda=$(nvidia-smi | grep -o 'CUDA Version: [0-9]*\.[0-9]*' | awk '{print $3}')
    echo "  驱动支持的 CUDA 版本：${dcuda:-未知}"
    if command -v nvcc >/dev/null 2>&1; then
      local tk; tk=$(nvcc --version | grep -o 'release [0-9]*\.[0-9]*' | awk '{print $2}')
      echo "  nvcc（CUDA 工具包）：${tk:-未知}"
      if [ -n "$tk" ] && [ -n "$dcuda" ] && [ "$(printf '%s\n%s\n' "$tk" "$dcuda" | sort -V | tail -1)" != "$dcuda" ]; then
        note "工具包 $tk 比驱动支持的 $dcuda 新，编出的程序可能无法使用 GPU"
      else ok "CUDA 工具包与驱动匹配"; fi
    elif [ -n "${LLAMA_SERVER:-}" ] && [ -x "$LLAMA_SERVER" ]; then
      ok "没有 nvcc，但已指定 LLAMA_SERVER=$LLAMA_SERVER"
    else
      fail "没有 nvcc，编不出 CUDA 版 llama-server。换带 CUDA 开发工具的模板，或自己准备好 llama-server 后用 LLAMA_SERVER=/路径"
    fi
  else
    fail "nvidia-smi 不可用：这不是 GPU 空间。创建空间时要选标有「免费」的高性能工作空间（基础型）"
  fi

  echo "== 工具"
  command -v git >/dev/null 2>&1 && ok "git" || fail "没有 git"
  command -v python3 >/dev/null 2>&1 && ok "python3 $(python3 --version 2>&1 | awk '{print $2}')（项目需要 3.12+，setup 会用 uv 另装）" || fail "没有 python3"
  command -v cmake >/dev/null 2>&1 && ok "cmake" || note "没有 cmake（setup 会用 pip 安装）"

  echo "== 网络（8 秒超时）"
  local url
  for url in https://hf-mirror.com https://github.com https://mirrors.aliyun.com/pypi/simple/ https://registry.npmmirror.com; do
    if curl -sI -m 8 -o /dev/null "$url"; then ok "$url"; else
      case "$url" in
        *hf-mirror*) note "$url 不通：权重下不了，可设 HF_ENDPOINT 换端点，或手动放到 $WORK/models/" ;;
        *github*) fail "$url 不通：克隆 llama.cpp 和 uv 装 Python 需要它" ;;
        *) note "$url 不通：相应的依赖下载会失败，可换镜像" ;;
      esac
    fi
  done

  echo "== 预览地址"
  local v missing=0
  for v in X_IDE_SPACE_KEY X_IDE_SPACE_REGION X_IDE_SPACE_HOST; do
    if [ -n "${!v:-}" ]; then ok "$v 已设置"; else missing=1; note "$v 未设置"; fi
  done
  if [ "$missing" = 0 ] || [ -n "${PREVIEW_URL:-}" ]; then echo "  预览地址：$(CMD=check preview_url)"; fi

  echo
  if [ "$bad" -gt 0 ]; then echo "体检结果：$bad 项不行、$warn 项注意。先解决「不行」的项再 setup。"; return 1; fi
  echo "体检结果：没有硬性问题（$warn 项注意）。可以运行 setup。"
}

CMD="${1:-help}"
case "$CMD" in
  check) check ;;
  setup)
    log "先体检"; check || die "体检未通过"
    log "安装 + 抽取耗时测试（REQUIRE_GPU=1：没有 GPU 或编不出 CUDA 版就报错，不退回 CPU）"
    REQUIRE_GPU=1 bash "$ALIYUN/dsw_edge_test.sh"
    echo; echo "接下来：bash $0 start"
    ;;
  start)
    URL="$(CMD=start preview_url)"
    log "启动工作台（预览地址 $URL）"
    HINT=none PUBLIC_ORIGIN="$URL" bash "$ALIYUN/dsw_workbench.sh"
    cat <<EOF

---------- Cloud Studio 提示 ----------
在浏览器里打开：$URL
  · 预览地址是 https；登录用户 admin，口令见上面的 workbench-password.txt
  · 预览地址对外公开可达（知道地址的人都能看到登录页），所以只放合成材料
  · 不操作 10 分钟空间会自动关机，关机后进程都会停：回来后重新运行  bash $0 start
    （模型、编译产物、Python 环境在 $WORK 里，不用重装）
  · 免费时长用完前记得在控制台点「停止」，不要只关浏览器标签
EOF
    ;;
  stop) bash "$ALIYUN/dsw_workbench.sh" stop ;;
  url) preview_url ;;
  *) sed -n 2,19p "$0"; [ "$CMD" = help ] || exit 2 ;;
esac
