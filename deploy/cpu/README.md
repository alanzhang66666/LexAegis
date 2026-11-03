# 版本 C · CPU 部署（无需 GPU）

> 三个版本的对比和怎么选见 [deploy/README.md](../README.md)。

**结论**：在一台普通 CPU 服务器上用 Docker Compose 部署整套工作台，边侧模型用 **MiniCPM5-2B（Q4_K_M，约 1.5GB）跑在 CPU 上**，可以 24 小时在线、不为 GPU 付费。代价是自动抽取很慢，只适合材料不长、能接受等待的场景；材料多、要快就用版本 A 的 GPU。只放合成材料。

> 状态：配置（Compose、`.env`）、可配置的超时与分块、基准脚本都已在沙箱里验证。**CPU 上模型到底多慢我没法实测**（沙箱下载不了权重，也没有目标服务器），默认值是估计值，部署后请先跑一遍 `bench_edge.py`。

## 1. 为什么 CPU 不能直接用默认配置

worker 每次把一块材料发给模型，原来**写死**：最多等 120 秒，每块最多 1.4 万字。CPU 生成速度比 GPU 低一到两个数量级，一整块大材料几乎一定超过 120 秒，整块抽取失败。本版本做了两件事：

1. **让这两个数可配置**（`lexaegis/providers.py`、`lexaegis/worker.py`，默认值不变，不设置时行为和以前完全一致）：

   | 环境变量 | 默认（代码） | CPU 版取值 | 含义 |
   | --- | --- | --- | --- |
   | `LEX_EDGE_REQUEST_TIMEOUT` | 120 | 900 | 每次调用边侧模型最多等多少秒（10–3600） |
   | `LEX_EDGE_EXTRACT_CHUNK_CHARS` | 14000 | 3000 | 每块材料最多多少字（500–50000） |
   | `LEX_EDGE_EXTRACT_CHUNK_BLOCKS` | 8 | 4 | 每块最多多少段（1–50） |

   单个超过上限的段不会被切开，自成一块。

2. **用已有的调参项压低每次生成量**：`LEX_EDGE_EXTRACT_MAX_TOKENS=2048`（默认 3072）、`LEX_EDGE_EXTRACT_MAX_FACTS=20`（默认 40）；上下文降到 8192，省内存。输出被截断时代码会自己拆分重试。

任务本身没有“运行超时被收回”的机制，所以把等待上限调大是有效的。

## 2. 规格建议

估算（未实测）：整套系统约 4–5GB 内存，其中应用本身实测不到 0.5GB，大头是模型权重（约 1.5GB）和上下文缓存。**4 核 8G 起步，8 核更快**；核数只影响抽取快慢，内存决定能开多大的上下文。

价格参考（2026 年 1 月前后第三方整理，以控制台为准，见 [阿里云开发者社区](https://developer.aliyun.com/article/1705845)）：4 核 8G 的 u2a 活动价约 898 元/年；8 核 32G 的 u2a 原价约 787 元/月。

## 3. 部署

```bash
git clone [-b <分支>] https://github.com/alanzhang66666/LexAegis.git && cd LexAegis
sudo DOCKER_MIRROR=<ACR 加速器地址> bash deploy/cpu/deploy.sh --docker-only    # 先只装 Docker
docker load -i llama.tar      # 内地地域：导入在海外机器上 docker save 的 ghcr.io/ggml-org/llama.cpp:server
sudo LEX_PROFILE=production PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
     HF_ENDPOINT=https://hf-mirror.com bash deploy/cpu/deploy.sh
ssh -N -L 38765:127.0.0.1:38765 root@<服务器公网 IP>      # 在自己电脑上，浏览器打开 http://127.0.0.1:38765
```

`deploy/cpu/deploy.sh` 等价于 `deploy/aliyun/deploy.sh --cpu`：装 Docker、生成 `.env` 和随机密钥、生成未验证发布清单、准备数据目录、下载 MiniCPM5-2B、构建、启动、隔离自检。`.env` 里写好了第 1 节的调参值和 `COMPOSE_FILE=compose.yaml:deploy/cpu/compose.cpu.yaml`，之后直接 `docker compose ps|logs|down`。镜像、安全组、备份、`LEX_PUBLIC_ORIGIN` 公网链接等通用事项与[版本 A](../aliyun/README.md) 相同。

## 4. 先实测再定参数

```bash
docker compose exec -T api python - < deploy/cpu/bench_edge.py                       # 默认测 1000、3000 字
docker compose exec -T -e SIZES=1000,3000,6000 api python - < deploy/cpu/bench_edge.py
```

用合成文本，按 worker 的真实方式（`second_pass=True`，超时取 `LEX_EDGE_REQUEST_TIMEOUT`）测每档块的耗时和抽取质量。读结果：

- 某档“失败”：这个大小的块会抽取失败——调小 `LEX_EDGE_EXTRACT_CHUNK_CHARS`，或调大 `LEX_EDGE_REQUEST_TIMEOUT`
- 全部“通过”：整份材料耗时 ≈ 块数 × 单块耗时，决定能不能接受；引用、数字两列应为 `True`
- 改 `.env` 后 `docker compose up -d worker api` 生效

## 5. 取舍与限制

- 抽取慢：一份几千字的材料可能要等几分钟甚至更久（未实测）；这是后台任务，不阻塞其他操作
- 2B 模型比版本 A 的 9B 弱，漏抽和引用错位会更多；`quote_ok` / `numbers_ok` 校验会把引用不出自原文的事实丢掉
- 扫描件 OCR 和录音转写不可用（镜像里没有 RapidOCR / whisper.cpp），扫描件走“看原图 + 人工转录”
- 正式外发在代码里仍是阻断的，本部署不改变这一点

## 6. 已验证 / 未验证

已验证（沙箱）：

- `deploy.sh --cpu --prepare-only` 生成的 `.env` 被 `docker compose config` 正确解析（无 GPU 设备、CPU 镜像、`--n-gpu-layers 0`、线程数取本机核数、worker 收到超时与分块参数）；`--gpu --cpu` 同时给会报错；GPU 模式配置不受影响
- `tests/test_edge_timeout_and_chunks.py`：默认值不变、环境变量覆盖并限幅、超时确实传到抽取 / 出站审核 / 复核底稿三处 HTTP 调用、显式参数优先、超大单段不被切开
- `bench_edge.py` 对假的模型服务：超时充足时全部通过，超时不够时如实记为失败

未验证：

- MiniCPM5-2B 在 CPU 上的真实速度、各档块耗时，以及 900 秒 / 3000 字 / 2048 token 这组默认值是否合适
- `deploy.sh` 的 Docker 构建、启动和 `check-isolation` 全流程（沙箱拉不到 Docker Hub / ghcr.io 镜像）
