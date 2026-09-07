# 边侧模型目录

本目录只放**声明**，不放权重。`models/` 下的 GGUF 等权重要被 gitignore。

当前本机边侧只有一个生产模型：**Qwen3-8B Q4_K_M，非思考**。生产调用点仍只有事实提取，不生成 `fact_summary`，也不用模型改写 `local_text`。

## 声明

- `edge.qwen3-8b.q4_k_m.nothink.json`：`role=fact_extraction_only`，`context=8192`，`json_object=required`，`thinking=disabled`，`second_call_site=forbidden`。

Compose（llama.cpp）服务别名为 `edge-small`。Ollama 请先 `/set nothink`，再 `save qwen3-8b-nothink`，本地把 `LEX_EDGE_MODEL` 指到该名称。

## 运行

- **llama.cpp**：`docker compose --profile edge up -d`。`edge-model` 使用 `--reasoning-budget 0 --jinja --ctx-size 8192` 硬关思考，并同时挂到 `internal` 与 `redteam` 网络。
- **Ollama**：本机 OpenAI 兼容口即可；思考必须在模型层关闭，不要依赖提示词。
- 8GB 显存按块抽取（约 4–8k 字符/批）。权重放到被忽略的 `models/`（Compose 默认挂载 `models/edge.gguf`）。

## 红队

红队可共用同一边侧实例。推理侧应写 JSON rationale；本次不实现红队调模型。
