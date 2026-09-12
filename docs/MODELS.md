# 边侧模型、云端与 OCR

将 `.env.example` 复制为 `.env` 后按需填写。真实密钥只放在被忽略的目录中。未配置边侧模型时，正式案件仍可人工录入事实。

## 边侧小模型

用于**正式案件事实提取**，协议为 OpenAI-compatible `/v1/models` 与 `/v1/chat/completions`，须输出结构化 JSON。可接本机 Ollama 或 llama.cpp。

- `LEX_EDGE_URL`、`LEX_EDGE_MODEL`，或在工作台「运行配置」保存。
- 默认主机白名单：`127.0.0.1`、`localhost`、`edge-model`；内网另设 `LEX_EDGE_ALLOWED_HOSTS`。
- 训练/微调可在外部完成，本地只部署最终权重（`models/` 不入库）。
- 现行权重：**MiniCPM5-2B** Q4_K_M（[openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)，GGUF 见 [MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)）。启动预算为 32K、KV F16、FlashAttn、`--n-gpu-layers 99`、并发 1；8GB 为方案预算，不是实测。无显卡可用 CPU 或纯人工。不换 MiniCPM-V，不上非官方 Vision-2B。
- 演示案例不调用边侧模型。仓库不分发权重。
- 边侧模型仍只做事实抽取。正式案默认的事实摘要是本地按已披露文本拼装，不调用 MiniCPM，也不自动出网；云端润色须显式创建「云端摘要任务」。

本机 GGUF：`lexaegis edge` 探测 `LEX_EDGE_URL`（默认 `127.0.0.1:8080`）。未监听时打印启动命令；`lexaegis edge --start` 使用 `models/MiniCPM5-2B-Q4_K_M.gguf`，或 `LEX_EDGE_GGUF`。服务进程不再加 `--reasoning off`。抽取请求仍用 `temperature: 0`、`json_schema`，默认 `enable_thinking: false`，并带 `max_tokens`（默认 3072，`LEX_EDGE_EXTRACT_MAX_TOKENS`）、`facts.maxItems`（默认 40，`LEX_EDGE_EXTRACT_MAX_FACTS`）与每批 event 上限（默认 8，`LEX_EDGE_EXTRACT_MAX_EVENTS`）。缺字段同站点二次抽取可设 `LEX_EDGE_SECOND_PASS_THINKING=1` 打开有界 thinking（仍剥离 `<think>`）。截断 JSON 会缩批重试；假 quote 会丢弃或回退到原文 value，无效来源条丢弃而不是整批作废。`lexaegis start` 在边侧未监听时给出同一提示，不自动下载权重。本文是部署方案，不是已安装或已评测结论。

合成抽取工程探测：`lexaegis dataset probe-edge`（无法学分，见 [data/README.md](../data/README.md)）。

Compose：`docker compose --profile edge up -d`（见 [DEPLOY.md](DEPLOY.md)）。

## 云端大模型

批准的双槽由网关封装：**DeepSeek V4 Flash 主**（`deepseek-v4-flash`，`https://api.deepseek.com/v1/chat/completions`）+ **阿里云百炼 / 模型服务 Qwen3.8-Flash 备**（`qwen3.8-flash`）。备槽默认 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`；国际站设 `LEX_CLOUD_STANDBY_HOST=dashscope-intl.aliyuncs.com`；工作空间 MaaS 设 `LEX_CLOUD_STANDBY_HOST=<workspace>.cn-beijing.maas.aliyuncs.com`，且该主机必须出现在 `LEX_CLOUD_ALLOWED_HOSTS`。只走 OpenAI 兼容路径 `/compatible-mode/v1/chat/completions`，不接 DashScope 原生 `/api/v1`。律师一次批准两侧的 target 与 model；运行时实际选用只写入网关账本，不改 `request_hash`。

密钥只在网关进程：`LEX_CLOUD_PRIMARY_KEY`（兼容旧名 `LEX_CLOUD_API_KEY`）与 `LEX_CLOUD_STANDBY_KEY`。写在工作目录 `.env`，不要提交、不要填进工作台。`lexaegis start` 不会把这三项传给业务 API 或 worker。默认白名单含 `api.deepseek.com`、`dashscope.aliyuncs.com`。未配置备用密钥时只走主槽，审批写明无备用。

流式只在网关内把 `delta.content` 拼成完整 `content`，再 `json.loads` 为 claims 对象。工作台仍等完整 result，再跑 `check_claims` 与边侧回写校验（本地计算 `unused_fact_ids`，核验可选 `gaps`）。未使用事实与缺口写入案件待办，可忽略或创建后续披露，不自动再调边侧模型。禁止把模型 token SSE 到工作台，不接 Responses API 或工具调用。

主→备仅当确认请求尚未离开本地（例如连接未建立）且备用槽已审核。主方已收到请求体后的首字节超时、401/服务端错误或进程崩溃记为可能披露，默认不自动切备、不自动重发。一旦开始生成、流中断且已有 token、或 JSON 不合格：记 `unknown`，禁止切备、禁止自动重发。思考必须关闭：DeepSeek 发送 `thinking: {type: disabled}`；百炼不启用 `enable_thinking`，并丢掉 `reasoning_content`。

合成案例中的「新建真实 API 演示任务」仍需审批并产生费用。正式外发门禁保持失败关闭。**交付验证没有调用真实云端模型。** mock 传输仍走本地拼装，不打云端。

## OCR 与本机转写

无 OCR 时保留扫描页与待处理状态，可看原图并人工转录。默认 Provider 是 **RapidOCR + ONNX Runtime CUDA**（`LEX_OCR_PROVIDER=rapidocr`）。Paddle 仅作 CPU 回滚：`LEX_OCR_PROVIDER=paddle`。不要安装 `paddlepaddle-gpu`。预置离线模型，并设置：

- `LEX_OCR_ENABLED=1`
- `LEX_OCR_PROVIDER=rapidocr`（回滚时改为 `paddle`）
- `LEX_OCR_MODELS_READY=1`（部署者声明离线资产已就绪，不触发下载，不代表精度验收）

RapidOCR 与 MiniCPM5-2B **不同时**占用 GPU：worker 在 OCR/转写前卸载 llama-server，抽取前再加载。Paddle 回滚路径仍固定 `device="cpu"` 与 `enable_mkldnn=False`。`pyproject.toml` extra `ocr` 指向 RapidOCR；`ocr-paddle` 仍是 CPU `paddlepaddle`。`LEX_OCR_MODELS_READY=1` 只表示操作员确认离线资产已预置，不代表识别精度已验收。仓库与 `lexaegis doctor` 都不会下载模型。

音视频文件（`.mp3` `.m4a` `.wav` `.mp4`）经本机 FFmpeg 抽音轨后，由 whisper.cpp CUDA + `large-v3-turbo` 转写为 `kind=transcript` 锚点（时间戳 locator，无 bbox）。须设置 `LEX_WHISPER_ENABLED=1` 与 `LEX_WHISPER_MODELS_READY=1`。无实时录音、无声纹、无说话人分离。空转写不能确认，须人工校正。

`lexaegis doctor` 把 `ocr` / `whisper` 列为可选检查，与 `edge_model` / `edge_json` / `isolation` 一样不失败关闭。`available` 只表示冒烟/资产声明，不代表识别或转写精度。不使用云端 OCR 或云端 whisper，不加载远程图片 URL。CI 不安装 RapidOCR / whisper.cpp；真实扫描或短音频冒烟仅在本机已能导入对应库且环境已声明模型就绪时执行，否则跳过，不要为跑通而 `pip install`。

`ocr` / `scan` / `transcript` 均 `needs_review`，未复核不能 extract/批准。失败或未配置时分别留扫描锚点或待转写块并转人工。当前已验证 Provider 契约、doctor 可选检查与手工转录；历史 Paddle CPU 合成扫描冒烟见 [VALIDATION.md](VALIDATION.md)，**不是识别精度验收**，也不表示 RapidOCR 或 whisper 已在本机装好。
