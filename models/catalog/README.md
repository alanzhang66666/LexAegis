# 边侧模型目录

本目录只放**声明**，不放权重。`models/` 下的 GGUF 等权重要被 gitignore。

当前本机边侧只有一个生产模型：**MiniCPM5-2B Q4_K_M，非思考**（[openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)，权重取 [MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)）。生产调用点仍只有事实提取，不生成 `fact_summary`，也不用模型改写 `local_text`。仓库不随代码分发权重。

## 声明

- `edge.minicpm5-2b.q4_k_m.nothink.json`：现行且唯一的生产声明。`role=fact_extraction_only`，服务别名 `edge-small`，`context=8192`（模型原生最长 131072，边侧抽取仍按块截断），`json_object=required`，`thinking=disabled`，`second_call_site=forbidden`。

Compose / `lexaegis edge --start` 服务别名仍为 `edge-small`。Ollama 需自行导入同一 GGUF 并把 `LEX_EDGE_MODEL` 指到该名称。

## 运行

- **llama.cpp**：将 `MiniCPM5-2B-Q4_K_M.gguf` 放到被忽略的 `models/`。`lexaegis edge --start` 使用该文件，或由 `LEX_EDGE_GGUF` 指定。启动参数含 `--reasoning-budget 0 --reasoning off --jinja --ctx-size 8192`。
- **Compose**：`docker compose --profile edge up -d`。`edge-model` 使用同一别名与关思考参数。
- 约 4GB 显存即可按块抽取（约 4–8k 字符/批）。8GB 卡仍足够，不必再占满整卡。

## 红队

红队可共用同一边侧实例。推理侧应写 JSON rationale；本次不实现红队调模型。
