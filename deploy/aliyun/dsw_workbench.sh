#!/usr/bin/env bash
# 在 PAI-DSW 里启动 LexAegis 工作台（原生方式，不用 Docker），边侧模型用 GPU。只用于合成材料。
#
# 前提：先跑过一次 dsw_edge_test.sh（它会准备好 llama.cpp、Qwen3.5-9B 权重和 Python 3.12 环境）。
# 用法：bash dsw_workbench.sh          启动（默认 production 环境：可新建案件、上传自己的合成材料并自动抽取）
#       PROFILE=demo bash dsw_workbench.sh    看项目内置的四条演示流程（演示案件不能重新抽取）
#       PUBLIC_ORIGIN=http://<EIP>[:端口] bash dsw_workbench.sh
#           开公网访问：工作台监听 0.0.0.0 并额外接受这一个地址（配合实例的 NAT 网关 + EIP 端口映射）
#       bash dsw_workbench.sh stop     停止
# 可选环境变量：LLAMA_SERVER（已有的 llama-server 路径）、HINT=none（不打印 DSW 专有提示）、MODEL_FILE（用 dsw_edge_test.sh 下载过的其他模型文件名）、WORK=/mnt/workspace、LEX_API_PORT（默认 production 38765 / demo 48765）
set -euo pipefail

WORK="${WORK:-/mnt/workspace}"; [ -d "$WORK" ] || WORK="$HOME"
PY="$WORK/lexenv/bin/python"; LEX="$WORK/lexenv/bin/lexaegis"
SERVER="${LLAMA_SERVER:-$WORK/llama.cpp/build/bin/llama-server}"; GGUF="$WORK/models/${MODEL_FILE:-Qwen3.5-9B-Q8_0.gguf}"
PROFILE="${PROFILE:-production}"
LOG="$WORK/workbench.log"; PASSFILE="$WORK/workbench-password.txt"
log() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = stop ]; then
  pkill -f "[l]exaegis start" || true; pkill -f "[u]vicorn lexaegis" || true
  pkill -f "[l]exaegis.worker" || true; pkill -f "[l]lama-server" || true
  echo "已停止"; exit 0
fi

# 代码位置：脚本放在仓库里运行时直接用当前检出（推荐）；单独拿到脚本时才克隆（LEXAEGIS_REF 指定分支，仓库未合并时必填）
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$HERE/../../lexaegis/cli.py" ]; then LEXDIR="$(cd "$HERE/../.." && pwd)"; else LEXDIR="$WORK/LexAegis"; fi
[ -d "$LEXDIR" ] && [ -x "$PY" ] || die "没找到 LexAegis 或 Python 环境，请先运行 dsw_edge_test.sh"
case "$PROFILE" in production|demo) ;; *) die "PROFILE 只能是 production 或 demo（integration 只接受项目内置场景）" ;; esac
cd "$LEXDIR"

# ---------- 1. 前端（需要 Node 22+ 和 pnpm 11）----------
if [ ! -f frontend/dist/index.html ]; then
  log "构建前端"
  NODE_OK=0
  if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ]; then NODE_OK=1; fi
  if [ "$NODE_OK" = 0 ]; then
    [ -x "$WORK/node/bin/node" ] || {
      "$PY" -m pip install -q nodeenv
      "$PY" -m nodeenv --node=22.12.0 --mirror=https://npmmirror.com/mirrors/node --prebuilt "$WORK/node"
    }
    export PATH="$WORK/node/bin:$PATH"
  fi
  (cd frontend && npx -y --registry=https://registry.npmmirror.com pnpm@11.19.0 install --frozen-lockfile \
     --registry=https://registry.npmmirror.com && npx -y pnpm@11.19.0 build) >/dev/null
fi
[ -f frontend/dist/index.html ] || die "前端构建失败"

# ---------- 2. 边侧模型（有就用，没有就人工录入事实）----------
if [ -x "$SERVER" ] && [ -f "$GGUF" ]; then
  export LEX_EDGE_BIN="$SERVER" LEX_EDGE_GGUF="$GGUF" LEX_EDGE_MODEL=edge-small \
         LEX_EDGE_URL=http://127.0.0.1:8080/v1 LEX_EDGE_CTX_SIZE=32768 \
         LEX_EDGE_N_GPU_LAYERS="${LEX_EDGE_N_GPU_LAYERS:-99}" LEX_EDGE_FLASH_ATTN="${LEX_EDGE_FLASH_ATTN:-on}"
  EDGE=1
else
  echo "[注意] 没找到 llama-server 或权重，边侧模型不启用，事实需要人工录入"; EDGE=0
fi

# ---------- 3. 口令与监听地址 ----------
if [ ! -s "$PASSFILE" ]; then (umask 077; "$PY" -c 'import secrets; print(secrets.token_urlsafe(18))' > "$PASSFILE"); fi
export LEX_LOCAL_PASSWORD; LEX_LOCAL_PASSWORD="$(cat "$PASSFILE")"

if [ -n "${PUBLIC_ORIGIN:-}" ]; then
  LEX_PUBLIC_ORIGIN="$PUBLIC_ORIGIN" "$PY" -c 'from lexaegis.api import public_origin; public_origin()' \
    || die "PUBLIC_ORIGIN 格式不对，应为 http://IP 或 http://IP:端口（和浏览器地址栏完全一致）"
  export LEX_PUBLIC_ORIGIN="$PUBLIC_ORIGIN" LEX_BIND_HOST=0.0.0.0
fi

# ---------- 4. 启动 ----------
"$0" stop >/dev/null 2>&1 || true
if [ "$EDGE" = 1 ]; then
  log "启动边侧模型（首次加载约几十秒）"
  "$LEX" edge --start || echo "[注意] 边侧模型没能预先启动；抽取时 worker 会再尝试拉起"
fi
log "启动工作台（$PROFILE）"
nohup "$LEX" start --profile "$PROFILE" > "$LOG" 2>&1 &
for _ in $(seq 1 60); do
  PORT=$(grep -o '127\.0\.0\.1:[0-9]*' "$LOG" 2>/dev/null | head -1 | cut -d: -f2 || true)
  [ -n "$PORT" ] && curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1 && break
  sleep 2
done
[ -n "${PORT:-}" ] || { tail -30 "$LOG"; die "工作台没有起来，日志见 $LOG"; }

if [ "${HINT:-dsw}" = none ]; then
  ACCESS_TEXT="地址：${PUBLIC_ORIGIN:-http://127.0.0.1:$PORT}"
elif [ -n "${PUBLIC_ORIGIN:-}" ]; then
  ACCESS_TEXT="公网地址：$PUBLIC_ORIGIN
  需要在实例的「服务访问与端口配置」里把容器端口 $PORT 映射到公网（NAT 网关 + EIP，单独计费），
  且 PUBLIC_ORIGIN 必须和浏览器地址栏完全一致（端口不是 80 时要带端口）。明文 HTTP，只放合成材料。"
else
  ACCESS_TEXT="地址：http://127.0.0.1:$PORT（只接受本机地址；DSW 网关链接登录不了）
用 SSH 隧道：在 DSW 控制台按「远程连接（ProxyClient 方式）」配好 SSH 后，在你电脑上执行
  ssh -N -L $PORT:127.0.0.1:$PORT <DSW 的 SSH 主机名>   然后浏览器打开 http://127.0.0.1:$PORT
要开公网链接：PUBLIC_ORIGIN=http://<EIP> bash $0"
fi
if [ "${HINT:-dsw}" = none ]; then TAIL_TEXT="只放合成材料。"; else TAIL_TEXT="只放合成材料。用完记得在控制台停止实例；配了 NAT 网关和 EIP 的话要单独删除，否则一直计费。"; fi

cat <<EOF

==================== 工作台已启动 ====================
环境：$PROFILE    边侧模型：$([ "$EDGE" = 1 ] && echo "已启用（GPU）" || echo "未启用")
$ACCESS_TEXT
用户名：admin    口令：cat $PASSFILE
日志：$LOG      停止：bash $0 stop
$TAIL_TEXT
EOF
