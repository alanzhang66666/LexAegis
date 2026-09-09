# 边侧模型、云端与 OCR

将 `.env.example` 复制为 `.env` 后按需填写。真实密钥只放在被忽略的目录中。未配置边侧模型时，正式案件仍可人工录入事实。

## 边侧小模型

用于**正式案件事实提取**，协议为 OpenAI-compatible `/v1/models` 与 `/v1/chat/completions`，须输出结构化 JSON。可接本机 Ollama 或 llama.cpp。

- `LEX_EDGE_URL`、`LEX_EDGE_MODEL`，或在工作台「运行配置」保存。
- 默认主机白名单：`127.0.0.1`、`localhost`、`edge-model`；内网另设 `LEX_EDGE_ALLOWED_HOSTS`。
- 训练/微调可在外部完成，本地只部署最终权重（`models/` 不入库）。
- 现行权重：**MiniCPM5-2B** Q4_K_M 非思考（[openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)，GGUF 见 [MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)）。约 4GB 显存即可按块抽取；无显卡可用 CPU 或纯人工。
- 演示案例不调用边侧模型。仓库不分发权重。
- 边侧模型仍只做事实抽取。正式案默认的事实摘要是本地按已披露文本拼装，不调用 MiniCPM，也不自动出网；云端润色须显式创建「云端摘要任务」。

本机 GGUF：`lexaegis edge` 探测 `LEX_EDGE_URL`（默认 `127.0.0.1:8080`）。未监听时打印启动命令；`lexaegis edge --start` 使用 `models/MiniCPM5-2B-Q4_K_M.gguf`，或 `LEX_EDGE_GGUF`。思考由 `--reasoning-budget 0 --reasoning off` 关闭。`lexaegis start` 在边侧未监听时给出同一提示，不自动下载权重。

合成抽取工程探测：`lexaegis dataset probe-edge`（无法学分，见 [data/README.md](../data/README.md)）。

Compose：`docker compose --profile edge up -d`（见 [DEPLOY.md](DEPLOY.md)）。

## 云端大模型

批准的双槽由网关封装：**DeepSeek V4 Flash 主**（`deepseek-v4-flash`，`https://api.deepseek.com/v1/chat/completions`）+ **阿里云百炼 / 模型服务 Qwen3.8-Flash 备**（`qwen3.8-flash`）。备槽默认 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`；国际站设 `LEX_CLOUD_STANDBY_HOST=dashscope-intl.aliyuncs.com`；工作空间 MaaS 设 `LEX_CLOUD_STANDBY_HOST=<workspace>.cn-beijing.maas.aliyuncs.com`，且该主机必须出现在 `LEX_CLOUD_ALLOWED_HOSTS`。只走 OpenAI 兼容路径 `/compatible-mode/v1/chat/completions`，不接 DashScope 原生 `/api/v1`。律师一次批准两侧的 target 与 model；运行时实际选用只写入网关账本，不改 `request_hash`。

密钥只在网关进程：`LEX_CLOUD_PRIMARY_KEY`（兼容旧名 `LEX_CLOUD_API_KEY`）与 `LEX_CLOUD_STANDBY_KEY`。写在工作目录 `.env`，不要提交、不要填进工作台。`lexaegis start` 不会把这三项传给业务 API 或 worker。默认白名单含 `api.deepseek.com`、`dashscope.aliyuncs.com`。未配置备用密钥时只走主槽，审批写明无备用。

流式只在网关内把 `delta.content` 拼成完整 `content`，再 `json.loads` 为 claims 对象。工作台仍等完整 result，再跑 `check_claims` 与边侧回写校验（本地计算 `unused_fact_ids`，核验可选 `gaps`）。未使用事实与缺口写入案件待办，可忽略或创建后续披露，不自动再调边侧模型。禁止把模型 token SSE 到工作台，不接 Responses API 或工具调用。

主→备仅当确认请求尚未离开本地（例如连接未建立）且备用槽已审核。主方已收到请求体后的首字节超时、401/服务端错误或进程崩溃记为可能披露，默认不自动切备、不自动重发。一旦开始生成、流中断且已有 token、或 JSON 不合格：记 `unknown`，禁止切备、禁止自动重发。思考必须关闭：DeepSeek 发送 `thinking: {type: disabled}`；百炼不启用 `enable_thinking`，并丢掉 `reasoning_content`。

合成案例中的「新建真实 API 演示任务」仍需审批并产生费用。正式外发门禁保持失败关闭。**交付验证没有调用真实云端模型。** mock 传输仍走本地拼装，不打云端。

## OCR

无 OCR 时保留扫描页与待处理状态，可看原图并人工转录。自动 OCR 须在本机安装 `paddleocr>=3,<4` 与匹配的 **CPU** `paddlepaddle>=3,<4`（不要安装 `paddlepaddle-gpu`），预置离线模型，并设置：

- `LEX_OCR_ENABLED=1`
- `LEX_OCR_PROVIDER=paddle`
- `LEX_OCR_MODELS_READY=1`（部署者声明离线资产已就绪，不触发下载，不代表精度验收）

适配器构造 PaddleOCR 时固定传入 `device="cpu"`，避免与占用 GPU 的 llama-server（MiniCPM5-2B GGUF）争用显存。GPU 留给边侧推理。CPU 路径另传 `enable_mkldnn=False`，规避 Paddle 3.3 oneDNN 崩溃，不表示识别质量。`pyproject.toml` extra `ocr` 使用的是 CPU 包名 `paddlepaddle`，不是 `paddlepaddle-gpu`。`LEX_OCR_MODELS_READY=1` 只表示操作员确认离线资产已预置，不代表识别精度已验收。仓库与 `lexaegis doctor` 都不会下载模型。

`lexaegis doctor` 把 `ocr` 列为可选检查，与 `edge_model` / `edge_json` / `isolation` 一样不失败关闭：未启用或未声明模型资产时为 `unconfigured`（扫描页保留原图并人工转录）。若已设置 `LEX_OCR_ENABLED=1` 且 `LEX_OCR_MODELS_READY=1` 但导入、健康检查或 CPU 构造失败，该检查为 `failed`（doctor 总体仍通过）。`available` 只表示冒烟/资产声明，不代表识别精度。不使用云端 OCR。CI 不安装 `paddleocr`；真实扫描冒烟仅在本机已能 `import paddleocr` 且环境中已有 `LEX_OCR_MODELS_READY=1` 时执行，否则跳过，不要为跑通而 `pip install`。

失败或未配置时保留扫描锚点并转人工，**绝不**回退云端 OCR。结果默认需人工复核。当前已验证 Provider 契约、doctor 可选检查与手工转录；本机已对 `examples/synthetic_scan.pdf` 做过合成扫描冒烟，**不是识别精度验收**。
