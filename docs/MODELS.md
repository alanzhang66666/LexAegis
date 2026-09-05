# 边侧模型、云端与 OCR

将 `.env.example` 复制为 `.env` 后按需填写。真实密钥只放在被忽略的目录中。未配置边侧模型时，正式案件仍可人工录入事实。

## 边侧小模型

用于**正式案件事实提取**，协议为 OpenAI-compatible `/v1/models` 与 `/v1/chat/completions`，须输出结构化 JSON。可接本机 Ollama 或 llama.cpp。

- `LEX_EDGE_URL`、`LEX_EDGE_MODEL`，或在工作台「运行配置」保存。
- 默认主机白名单：`127.0.0.1`、`localhost`、`edge-model`；内网另设 `LEX_EDGE_ALLOWED_HOSTS`。
- 训练/微调可在外部完成，本地只部署最终权重（`models/` 不入库）。
- 约 12G 独显：一个 7B 级量化主模型即可支撑多角色提示词；无显卡可用更小 CPU 模型或纯人工。
- 演示案例不调用边侧模型。

Compose：`docker compose --profile edge up -d`（见 [DEPLOY.md](DEPLOY.md)）。

## 云端大模型

工作台填写 API 根地址与模型；**仅网关**读取 `LEX_CLOUD_API_KEY` 与 `LEX_CLOUD_ALLOWED_HOSTS`。`lexaegis start` 不会把云端密钥传给业务 API 或 worker。

要求 HTTPS、已登记主机、Chat Completions JSON。不支持 Responses API、自动工具调用或服务商回退。合成案例中的「新建真实 API 演示任务」仍需审批并产生费用。**交付验证没有调用真实云端模型。**

## OCR

无 OCR 时保留扫描页与待处理状态，可看原图并人工转录。自动 OCR 须在本机安装 `paddleocr>=3,<4` 与匹配的 `paddlepaddle>=3,<4`，预置离线模型，并设置：

- `LEX_OCR_ENABLED=1`
- `LEX_OCR_PROVIDER=paddle`
- `LEX_OCR_MODELS_READY=1`（部署者声明离线资产已就绪，不触发下载，不代表精度验收）

失败或未配置时保留扫描锚点并转人工，**绝不**回退云端 OCR。结果默认需人工复核。当前已验证 Provider 契约与手工转录，**未验证 PaddleOCR 权重推理或识别精度**。
