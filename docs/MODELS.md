# 边侧模型、云端与 OCR

将 `.env.example` 复制为 `.env` 后按需填写。真实密钥只放在被忽略的目录中。未配置边侧模型时，正式案件仍可人工录入事实。

## 边侧小模型

用于**正式案件事实提取**，协议为 OpenAI-compatible `/v1/models` 与 `/v1/chat/completions`，须输出结构化 JSON。可接本机 Ollama 或 llama.cpp。

- `LEX_EDGE_URL`、`LEX_EDGE_MODEL`，或在工作台「运行配置」保存。
- 默认主机白名单：`127.0.0.1`、`localhost`、`edge-model`；内网另设 `LEX_EDGE_ALLOWED_HOSTS`。
- 训练/微调可在外部完成，本地只部署最终权重（`models/` 不入库）。
- 约 8GB 独显：本机 Qwen3-8B Q4 非思考即可支撑事实提取；无显卡可用更小 CPU 模型或纯人工。
- 演示案例不调用边侧模型。

本机 GGUF：`lexaegis edge` 探测 `LEX_EDGE_URL`（默认 `127.0.0.1:8080`）。未监听时打印启动命令；`lexaegis edge --start` 可选拉起 `.artifacts/llama-server` + `models/edge.gguf`。`lexaegis start` 在边侧未监听时给出同一提示，不自动下载权重。

合成抽取工程探测：`lexaegis dataset probe-edge`（无法学分，见 [data/README.md](../data/README.md)）。

Compose：`docker compose --profile edge up -d`（见 [DEPLOY.md](DEPLOY.md)）。

## 云端大模型

批准的双槽由网关封装：**DeepSeek V4 Flash 主**（`deepseek-v4-flash`，`https://api.deepseek.com/v1/chat/completions`）+ **阿里云百炼 / 模型服务 Qwen3.8-Flash 备**（`qwen3.8-flash`）。备槽默认 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`；国际站设 `LEX_CLOUD_STANDBY_HOST=dashscope-intl.aliyuncs.com`；工作空间 MaaS 设 `LEX_CLOUD_STANDBY_HOST=<workspace>.cn-beijing.maas.aliyuncs.com`，且该主机必须出现在 `LEX_CLOUD_ALLOWED_HOSTS`。只走 OpenAI 兼容路径 `/compatible-mode/v1/chat/completions`，不接 DashScope 原生 `/api/v1`。律师一次批准两侧的 target 与 model；运行时实际选用只写入网关账本，不改 `request_hash`。

密钥只在网关进程：`LEX_CLOUD_PRIMARY_KEY`（兼容旧名 `LEX_CLOUD_API_KEY`）与 `LEX_CLOUD_STANDBY_KEY`。写在工作目录 `.env`，不要提交、不要填进工作台。`lexaegis start` 不会把这三项传给业务 API 或 worker。默认白名单含 `api.deepseek.com`、`dashscope.aliyuncs.com`。未配置备用密钥时只走主槽，审批写明无备用。

流式只在网关内把 `delta.content` 拼成完整 `content`，再 `json.loads` 为 claims 对象。工作台仍等完整 result，再跑 `check_claims` 与边侧回写校验（本地计算 `unused_fact_ids`，核验可选 `gaps`）。未使用事实与缺口写入案件待办，可忽略或创建后续披露，不自动再调边侧模型。禁止把模型 token SSE 到工作台，不接 Responses API 或工具调用。

主→备仅当尚未 `generation_started`（未收到任何 content/reasoning token）。连接失败或 401 可切备；一旦开始生成、流中断且已有 token、或 JSON 不合格：记 `unknown`，禁止切备、禁止自动重发。思考必须关闭：DeepSeek 发送 `thinking: {type: disabled}`；百炼不启用 `enable_thinking`，并丢掉 `reasoning_content`。

合成案例中的「新建真实 API 演示任务」仍需审批并产生费用。正式外发门禁保持失败关闭。**交付验证没有调用真实云端模型。** mock 传输仍走本地拼装，不打云端。

## OCR

无 OCR 时保留扫描页与待处理状态，可看原图并人工转录。自动 OCR 须在本机安装 `paddleocr>=3,<4` 与匹配的 `paddlepaddle>=3,<4`，预置离线模型，并设置：

- `LEX_OCR_ENABLED=1`
- `LEX_OCR_PROVIDER=paddle`
- `LEX_OCR_MODELS_READY=1`（部署者声明离线资产已就绪，不触发下载，不代表精度验收）

失败或未配置时保留扫描锚点并转人工，**绝不**回退云端 OCR。结果默认需人工复核。当前已验证 Provider 契约与手工转录，**未验证 PaddleOCR 权重推理或识别精度**。
