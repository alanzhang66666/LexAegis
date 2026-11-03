#!/usr/bin/env bash
# LexAegis · 阿里云 ECS 一键部署（Ubuntu 22.04 / 24.04，x86_64）
#
# 做的事情与仓库 CI 的 compose-isolation 任务一致：
#   装 Docker（可选 NVIDIA 容器运行时）→ 生成 .env 与随机密钥 → 生成"未验证"发布清单
#   → 准备数据目录（uid 10001, 0700）→ 拉辅助镜像 → build → up --wait → check-isolation
#
# 用法（在仓库根目录，以 root 或 sudo 运行）：
#   sudo bash deploy/aliyun/deploy.sh                # 无边侧模型（CPU 即可）
#   sudo bash deploy/aliyun/deploy.sh --gpu          # 边侧 Qwen3.5-9B（Q8_0）上 GPU，需 ≥16G 显存
#   sudo bash deploy/aliyun/deploy.sh --cpu          # 边侧 MiniCPM5-2B（Q4_K_M）用 CPU 跑，无需 GPU（见 deploy/cpu/README.md）
#   sudo bash deploy/aliyun/deploy.sh --prepare-only # 只生成 .env/清单/目录，不动 Docker
#   sudo bash deploy/aliyun/deploy.sh --docker-only  # 只装 Docker（+ --gpu 时装 NVIDIA 运行时），便于先 docker load 镜像
#
# 可选环境变量：
#   LEX_PROFILE=production|integration   运行环境，默认 production
#   LEX_CLOUD_PRIMARY_KEY=sk-...          云端模型 Key（只注入网关）；不填则不能外发
#   LEX_CLOUD_ALLOWED_HOSTS=...           外发白名单，默认 dashscope.aliyuncs.com
#   DOCKER_MIRROR=https://xxxx.mirror.aliyuncs.com   阿里云 ACR 镜像加速器地址（内地地域建议设置）
#   PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/   宿主机 pip 镜像（内地地域建议设置）
#   HF_ENDPOINT=https://hf-mirror.com     --gpu 时下载权重用的 HuggingFace 端点
#   LEX_EDGE_GGUF_REPO / LEX_EDGE_GGUF_FILE   边侧权重；--gpu 默认 unsloth/Qwen3.5-9B-GGUF / Qwen3.5-9B-Q8_0.gguf，
#                                             --cpu 默认 openbmb/MiniCPM5-2B-GGUF / MiniCPM5-2B-Q4_K_M.gguf
#   LEX_EDGE_IMAGE=...                    --gpu 时 llama.cpp CUDA 镜像，默认 ghcr.io/ggml-org/llama.cpp:server-cuda
set -euo pipefail

GPU=0; CPU=0; EDGE=0; PREPARE_ONLY=0; DOCKER_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --gpu) GPU=1 ;;
    --cpu) CPU=1 ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    --docker-only) DOCKER_ONLY=1 ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

[ "$GPU" = 1 ] && [ "$CPU" = 1 ] && { echo "--gpu 和 --cpu 只能二选一" >&2; exit 2; }
if [ "$GPU" = 1 ] || [ "$CPU" = 1 ]; then EDGE=1; fi

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
PROFILE="${LEX_PROFILE:-production}"
case "$PROFILE" in production|integration) ;; *) echo "LEX_PROFILE 只能是 production 或 integration（demo 请用 compose.demo.yaml）" >&2; exit 2 ;; esac
DATA_ROOT="$REPO/.data/$PROFILE"
if [ "$CPU" = 1 ]; then
  GGUF_REPO="${LEX_EDGE_GGUF_REPO:-openbmb/MiniCPM5-2B-GGUF}"
  GGUF_FILE="${LEX_EDGE_GGUF_FILE:-MiniCPM5-2B-Q4_K_M.gguf}"
else
  GGUF_REPO="${LEX_EDGE_GGUF_REPO:-unsloth/Qwen3.5-9B-GGUF}"
  GGUF_FILE="${LEX_EDGE_GGUF_FILE:-Qwen3.5-9B-Q8_0.gguf}"
fi
GGUF="$REPO/models/$GGUF_FILE"
EDGE_IMAGE="${LEX_EDGE_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-cuda}"
if [ "$GPU" = 1 ]; then
  COMPOSE_FILE_VALUE="compose.yaml:deploy/aliyun/compose.gpu.yaml"; COMPOSE_PROFILES_VALUE="redteam,edge"
elif [ "$CPU" = 1 ]; then
  COMPOSE_FILE_VALUE="compose.yaml:deploy/cpu/compose.cpu.yaml"; COMPOSE_PROFILES_VALUE="redteam,edge"
else
  COMPOSE_FILE_VALUE="compose.yaml"; COMPOSE_PROFILES_VALUE="redteam"
fi

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "请用 root 或 sudo 运行（需要安装软件并把数据目录交给 uid 10001）"
[ -f compose.yaml ] && [ -f lexaegis/cli.py ] || die "请在 LexAegis 仓库里运行此脚本"

# ---------- Docker（及 NVIDIA 容器运行时）----------
install_docker() {
  log "Docker"
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    . /etc/os-release
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $VERSION_CODENAME stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  if [ -n "${DOCKER_MIRROR:-}" ] && ! grep -qs "$DOCKER_MIRROR" /etc/docker/daemon.json; then
    [ -s /etc/docker/daemon.json ] && die "/etc/docker/daemon.json 已有内容，请手动把 $DOCKER_MIRROR 加进 registry-mirrors"
    mkdir -p /etc/docker && printf '{ "registry-mirrors": ["%s"] }\n' "$DOCKER_MIRROR" > /etc/docker/daemon.json
  fi

  if [ "$GPU" = 1 ]; then
    log "NVIDIA 容器运行时"
    command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null \
      || die "nvidia-smi 不可用：请先装 GPU 驱动（创建 ECS 时勾选'安装 GPU 驱动'最省事）"
    if ! command -v nvidia-ctk >/dev/null; then
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
      apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
    fi
    nvidia-ctk runtime configure --runtime=docker >/dev/null
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
  systemctl restart docker

}

if [ "$DOCKER_ONLY" = 1 ]; then install_docker; log "--docker-only：Docker 已就绪。现在可以 docker load / 从 ACR 拉取镜像，然后不带 --docker-only 再运行一次"; exit 0; fi

# ---------- 1. 宿主机 Python（lexaegis CLI：生成清单、check-isolation）----------
log "宿主机 Python 环境"
if ! command -v python3 >/dev/null; then apt-get update -qq && apt-get install -y -qq python3; fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
  || die "需要 Python 3.12+（Ubuntu 24.04 自带 3.12；22.04 请先装 python3.12 或换 24.04 镜像）"
python3 -m venv --help >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq python3-venv; }
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.lock -c constraints/linux.txt
.venv/bin/python -m pip install -q --no-deps -e .
LEX=.venv/bin/lexaegis

# ---------- 2. .env（随机密钥，已存在则不覆盖）----------
log ".env"
if [ -f .env ]; then
  echo ".env 已存在，保留原值（要重新生成请先备份并删除它）"
else
  rand() { .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'; }
  (umask 077; : > .env)
  cat >> .env <<EOF
LEX_RUN_PROFILE=$PROFILE
LEX_COMPOSE_PROJECT=lexaegis-$PROFILE
LEX_COMPOSE_API_PORT=38765
LEX_LOCAL_PASSWORD=$(rand | cut -c1-24)
LEX_GATEWAY_SECRET=$(rand)
LEX_REDTEAM_SECRET=$(rand)
LEX_APP_DATA_PATH=$DATA_ROOT/app
LEX_GATEWAY_DATA_PATH=$DATA_ROOT/gateway
LEX_RELEASE_BUILD_MANIFEST_HOST_PATH=$REPO/release-build-manifest.json
LEX_ROUTE_IMAGE=alpine:3.20
LEX_CLOUD_PRIMARY_KEY=${LEX_CLOUD_PRIMARY_KEY:-}
LEX_CLOUD_ALLOWED_HOSTS=${LEX_CLOUD_ALLOWED_HOSTS:-dashscope.aliyuncs.com}
EOF
  if [ "$GPU" = 1 ]; then
    printf 'LEX_EDGE_MODEL=edge-small\nLEX_EDGE_IMAGE=%s\nLEX_EDGE_CTX_SIZE=32768\nLEX_EDGE_FLASH_ATTN=on\n' "$EDGE_IMAGE" >> .env
  elif [ "$CPU" = 1 ]; then
    # CPU 档：小模型 + 小分块 + 放宽等待上限（原代码写死 120 秒、每块 1.4 万字，CPU 上会超时）。数值是估计值，先用 bench_edge.py 实测再调。
    {
      echo "LEX_EDGE_MODEL=edge-small"
      echo "LEX_EDGE_IMAGE=${LEX_EDGE_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}"
      echo "LEX_EDGE_CTX_SIZE=8192"
      echo "LEX_EDGE_THREADS=$(nproc)"
      echo "LEX_EDGE_REQUEST_TIMEOUT=900"
      echo "LEX_EDGE_EXTRACT_CHUNK_CHARS=3000"
      echo "LEX_EDGE_EXTRACT_CHUNK_BLOCKS=4"
      echo "LEX_EDGE_EXTRACT_MAX_TOKENS=2048"
      echo "LEX_EDGE_EXTRACT_MAX_FACTS=20"
    } >> .env
  fi
  echo "已生成 .env（权限 600）。登录口令见其中 LEX_LOCAL_PASSWORD。"
fi

# compose 文件与 profile 也写进 .env：之后任何 `docker compose ...`（包括 check-isolation 内部调用）都一致
setenv() { if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi; }
setenv COMPOSE_FILE "$COMPOSE_FILE_VALUE"
setenv COMPOSE_PROFILES "$COMPOSE_PROFILES_VALUE"
[ "$EDGE" = 1 ] && setenv LEX_EDGE_GGUF_FILE "$GGUF_FILE"

# ---------- 3. 发布清单 + 数据目录 ----------
log "发布清单与数据目录"
if [ -d release-build-manifest.json ]; then
  rmdir release-build-manifest.json 2>/dev/null || die "release-build-manifest.json 是非空目录（多半是 Docker 曾自动创建），请检查后删除"
fi
if [ ! -f release-build-manifest.json ]; then
  .venv/bin/python scripts/prepare_ci_runtime.py
  echo "已生成 status=pending 的清单：可以运行，但不构成正式发布身份（正式外发本来也处于阻断状态）。"
fi
mkdir -p "$DATA_ROOT/app" "$DATA_ROOT/gateway"
chown -R 10001:10001 "$DATA_ROOT"
chmod 700 "$DATA_ROOT/app" "$DATA_ROOT/gateway"
fstype="$(stat -f -c %T "$DATA_ROOT")"
case "$fstype" in nfs*|cifs|smb*|fuse*) die "数据目录在 $fstype 上；SQLite 必须放本地云盘（ESSD），不能放 NAS/OSS 挂载" ;; esac

if [ "$PREPARE_ONLY" = 1 ]; then log "--prepare-only：到此为止"; exit 0; fi

install_docker

# ---------- 5. 权重（--gpu / --cpu）----------
if [ "$EDGE" = 1 ] && [ ! -f "$GGUF" ]; then
  log "下载 $GGUF_REPO / $GGUF_FILE（GPU 档 Q8_0 约 10GB，CPU 档约 1.5GB）"
  .venv/bin/python -m pip install -q huggingface_hub
  .venv/bin/python - "$REPO/models" "$GGUF_REPO" "$GGUF_FILE" <<'PY' || die "权重下载失败：可手动放到 models/$GGUF_FILE 后重跑"
import sys
from huggingface_hub import hf_hub_download
hf_hub_download(sys.argv[2], sys.argv[3], local_dir=sys.argv[1])
PY
fi

# ---------- 6. 镜像、构建、启动 ----------
log "准备镜像（本地已有就不再拉取；compose 设置了 pull_policy: never）"
ensure_image() {
  docker image inspect "$1" >/dev/null 2>&1 && { echo "本地已有：$1"; return; }
  docker pull "$1" || die "拉取 $1 失败。内地地域请在海外机器上 docker pull + docker save，传上来 docker load（或推到自己的 ACR 后 docker tag 成原名）再重跑"
}
ensure_image alpine:3.20
ensure_image ghcr.io/ggml-org/llama.cpp:server   # Dockerfile 的构建阶段要用
if [ "$GPU" = 1 ]; then ensure_image "$EDGE_IMAGE"; fi

log "构建应用镜像（首次约 5–15 分钟）"
docker compose build

log "启动"
docker compose up -d --pull never --wait \
  || { docker compose ps -a; docker compose logs --no-color --tail 80; die "启动失败，日志见上"; }

if [ "$EDGE" = 1 ]; then
  log "等待边侧模型就绪"
  for _ in $(seq 1 60); do
    if docker compose logs edge-model 2>/dev/null | grep -qiE "server is listening|HTTP server listening"; then ok=1; break; fi
    sleep 5
  done
  [ "${ok:-0}" = 1 ] && echo "边侧模型已加载" \
    || echo "[注意] 5 分钟内未见到就绪日志，检查：docker compose logs edge-model（显存/内存不足就调小 .env 里的 LEX_EDGE_CTX_SIZE）"
fi

# ---------- 7. 隔离自检 ----------
log "隔离自检（五项探测）"
set -a; . ./.env; set +a
$LEX check-isolation || echo "[注意] 隔离探测未全部通过，见上方输出；不影响试用，但不能主张隔离已验证"

cat <<EOF

==================== 部署完成 ====================
工作台只监听服务器本机 127.0.0.1:38765，不对公网开放。在你自己的电脑上执行：
    ssh -N -L 38765:127.0.0.1:38765 <用户名>@<ECS公网IP>
然后浏览器打开 http://127.0.0.1:38765
登录口令：服务器上 grep LEX_LOCAL_PASSWORD $REPO/.env

常用命令（在 $REPO 下）：
    状态   docker compose ps
    日志   docker compose logs -f worker
    停止   docker compose down          （不要加 -v，数据在 $DATA_ROOT）
    备份   先停止，再 .venv/bin/lexaegis backup /root/lexaegis-backup.zip --offline-confirm
EOF
