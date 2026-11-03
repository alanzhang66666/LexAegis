#!/usr/bin/env bash
# 在阿里云 PAI-DSW（带 GPU 的实例）里测试 LexAegis 边侧模型（默认 Qwen3.5-9B Q8_0）：
# 按 worker 的真实调用方式和 120 秒超时，用 8 份短合成材料 + 3 份拼接长材料计时并检查引用。
# 同时会准备好 llama.cpp、权重和 Python 3.12 环境，供 dsw_workbench.sh 使用。
#
# 用法：在 DSW 的 Terminal 里执行   bash dsw_edge_test.sh
# 可选环境变量：
#   WORK=/mnt/workspace                     工作目录（DSW 默认目录，关机后保留）
#   HF_ENDPOINT=https://hf-mirror.com       权重下载端点
#   PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
#   CTX=32768                               模型上下文（与项目默认一致）
#   RUN_CPU=1                               另外用纯 CPU 再跑一遍做对比（9B 在 CPU 上大多会超时，默认不跑）
#   CPU_THREADS=4                           CPU 测试用几个线程（模拟 4 核服务器；默认 4）
#   MODEL_REPO / MODEL_FILE                 换别的 GGUF 模型做对比，默认 unsloth/Qwen3.5-9B-GGUF / Qwen3.5-9B-Q8_0.gguf
#     例：MODEL_REPO=openbmb/MiniCPM5-2B-GGUF MODEL_FILE=MiniCPM5-2B-Q4_K_M.gguf bash dsw_edge_test.sh
#     每个模型的结果分别保存，汇总表会把所有跑过的模型并排列出来。
set -euo pipefail

WORK="${WORK:-/mnt/workspace}"; [ -d "$WORK" ] || WORK="$HOME"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
CTX="${CTX:-32768}"
CPU_THREADS="${CPU_THREADS:-4}"
MODEL_REPO="${MODEL_REPO:-unsloth/Qwen3.5-9B-GGUF}"
MODEL_FILE="${MODEL_FILE:-Qwen3.5-9B-Q8_0.gguf}"
TAG="${MODEL_FILE%.gguf}"
GGUF="$WORK/models/$MODEL_FILE"
SERVER="$WORK/llama.cpp/build/bin/llama-server"
PORT=8080
log() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }
cd "$WORK"

# ---------- 0. GPU ----------
GPU=1
if nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null; then :; else
  echo "[注意] 没检测到 GPU，只做 CPU 测试"; GPU=0
fi

# ---------- 1. 代码 ----------
log "下载代码"
[ -d LexAegis ] || git clone --depth 1 https://github.com/alanzhang66666/LexAegis.git
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp.git

# ---------- 2. 编译 llama-server ----------
if [ ! -x "$SERVER" ]; then
  log "编译 llama-server（约 5–15 分钟）"
  command -v cmake >/dev/null || python3 -m pip install -q cmake
  [ -d /usr/local/cuda/bin ] && export PATH="/usr/local/cuda/bin:$PATH"
  CUDA_FLAG="-DGGML_CUDA=OFF"
  if [ "$GPU" = 1 ]; then
    if command -v nvcc >/dev/null; then CUDA_FLAG="-DGGML_CUDA=ON"
    else echo "[注意] 镜像里没有 nvcc，只能编译 CPU 版。请换带 CUDA 开发工具的官方 GPU 镜像后重跑"; GPU=0; fi
  fi
  cmake -S llama.cpp -B llama.cpp/build "$CUDA_FLAG" -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release >/dev/null
  cmake --build llama.cpp/build -j"$(nproc)" --target llama-server >/dev/null
fi
[ -x "$SERVER" ] || die "llama-server 编译失败"

# ---------- 3. 权重 ----------
if [ ! -f "$GGUF" ]; then
  log "下载 $MODEL_REPO / $MODEL_FILE（经 $HF_ENDPOINT）"
  python3 -m pip install -q huggingface_hub
  python3 - "$WORK/models" "$MODEL_REPO" "$MODEL_FILE" <<'PY' || die "权重下载失败：可以手动放到 $GGUF 后重跑"
import sys
from huggingface_hub import hf_hub_download
hf_hub_download(sys.argv[2], sys.argv[3], local_dir=sys.argv[1])
PY
fi

# ---------- 4. LexAegis 的 Python 环境（需要 3.12+）----------
if [ ! -x "$WORK/lexenv/bin/python" ]; then
  log "准备 Python 3.12 环境"
  python3 -m pip install -q uv
  python3 -m uv venv -q -p 3.12 --seed "$WORK/lexenv" || die "创建 Python 3.12 环境失败（uv 需要从 GitHub 下载 Python）"
  "$WORK/lexenv/bin/pip" install -q -r LexAegis/requirements.lock
  "$WORK/lexenv/bin/pip" install -q --no-deps -e LexAegis
fi

# ---------- 5. 测试 ----------
cat > "$WORK/edge_bench.py" <<'PY'
"""按 worker 的真实调用方式（second_pass=True，超时 120 秒）逐项计时。"""
import json, os, sys, time
from lexaegis.providers import EdgeClient
from lexaegis.edge_eval import score_extract

mode, out = sys.argv[1], sys.argv[2]
client = EdgeClient(os.environ["LEX_EDGE_URL"], "edge-small")
records = [json.loads(line) for line in open("data/mock_labor_v1/records.jsonl", encoding="utf-8")]
rows = []

def run(name, blocks):
    started, error, facts = time.time(), None, []
    try:
        facts = client.extract(blocks, timeout=120, second_pass=True)
    except Exception as exc:  # 超时、JSON 不合格等都记下来
        error = f"{type(exc).__name__}: {str(exc)[:160]}"
    row = {"case": name, "chars": sum(len(b["text"]) for b in blocks),
           "seconds": round(time.time() - started, 1), "facts": len(facts), "error": error}
    if error is None:
        score = score_extract(blocks, facts)
        row.update(quote_ok=score["quote_is_substring"], numbers_ok=score["numbers_from_source"],
                   sources_ok=score["source_ids_in_blocks"])
    rows.append(row)
    print(f"[{mode}] {name:<14} {row['chars']:>6} 字  {row['seconds']:>6} 秒  事实 {row['facts']:>2}  "
          + (f"失败 {error}" if error else f"引用 {row['quote_ok']} 数字 {row['numbers_ok']}"), flush=True)

for record in records:                       # 8 份短材料（每份约 130 字）
    run(record["id"], record["document"]["blocks"])
base = [r["document"]["blocks"][0]["text"] for r in records]
for target in (2000, 6000, 12000):           # 拼成长材料，模拟 worker 一块最多 1.4 万字、8 段
    per = target // 8
    blocks = [{"id": f"long{target}_{k}", "text": (base[k] * (per // len(base[k]) + 1))[:per]} for k in range(8)]
    run(f"long_{target}", blocks)
json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY

run_mode() {  # $1 = gpu|cpu
  local mode=$1 args=()
  if [ "$mode" = gpu ]; then args=(--n-gpu-layers 99); else args=(--n-gpu-layers 0 --threads "$CPU_THREADS"); fi
  log "启动 llama-server（$TAG，$mode）"
  "$SERVER" --model "$GGUF" --host 127.0.0.1 --port "$PORT" --alias edge-small --jinja \
    --ctx-size "$CTX" --parallel 1 "${args[@]}" > "$WORK/llama-$mode.log" 2>&1 &
  local pid=$!
  for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -q edge-small && break
    kill -0 "$pid" 2>/dev/null || { tail -20 "$WORK/llama-$mode.log"; die "llama-server 启动失败（$mode）"; }
    sleep 2
  done
  log "测试（$mode）：8 份短材料 + 3 份长材料"
  (cd "$WORK/LexAegis" && LEX_EDGE_URL="http://127.0.0.1:$PORT/v1" "$WORK/lexenv/bin/python" "$WORK/edge_bench.py" "$mode" "$WORK/bench-$TAG-$mode.json")
  kill "$pid"; wait "$pid" 2>/dev/null || true
}

if [ "$GPU" = 1 ]; then run_mode gpu; fi
if [ "${RUN_CPU:-0}" = 1 ] || [ "$GPU" = 0 ]; then run_mode cpu; fi

# ---------- 6. 汇总 ----------
log "汇总"
"$WORK/lexenv/bin/python" - "$WORK" <<'PY'
import json, sys
from pathlib import Path
work = Path(sys.argv[1]); data = {}
for path in sorted(work.glob("bench-*.json")):
    label = path.stem[len("bench-"):]
    data[label] = {row["case"]: row for row in json.loads(path.read_text(encoding="utf-8"))}
first = next(iter(data.values()))
print("各列 = 模型-运行方式；“超时/失败”= 在正式系统里这份材料会抽取失败")
print(f"{'材料':<14}{'字数':>6}  " + "  ".join(f"{m[-26:]:>26}" for m in data))
for case in first:
    cells = []
    for label in data:
        row = data[label].get(case)
        text = "-" if row is None else ("超时/失败" if row["error"] else f"{row['seconds']} 秒 / {row['facts']} 条")
        cells.append(f"{text:>26}")
    print(f"{case:<14}{first[case]['chars']:>6}  " + "  ".join(cells))
print("\n“N 条”是抽出的事实数。质量还要看 bench-*.json 里的 quote_ok（引用是原文）和 numbers_ok（数字出自原文）。")
PY
