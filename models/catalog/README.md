# 边侧模型目录

本目录只放**声明**，不放权重。`models/` 下的 GGUF 等权重要被 gitignore。

当前本机边侧只有一个生产模型：**MiniCPM5-2B Q4_K_M**（[openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)，权重取 [MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)）。生产调用点仍只有事实提取，不生成 `fact_summary`，也不用模型改写 `local_text`。仓库不随代码分发权重。下文是部署方案，**不是本机已安装或已跑通的结论**。

## 声明

- `edge.minicpm5-2b.q4_k_m.nothink.json`：现行且唯一的生产声明。`role=fact_extraction_only`，服务别名 `edge-small`，`context=32768`（模型原生最长 131072，边侧抽取仍按块截断），`json_object=required`，`thinking=request_controlled`，`vision=false`。不宣称 32K 已在本机跑通。请求默认 `enable_thinking=false`；缺字段同站点二次抽取可按环境打开有界 thinking。

Compose / `lexaegis edge --start` 服务别名仍为 `edge-small`。Ollama 需自行导入同一 GGUF 并把 `LEX_EDGE_MODEL` 指到该名称。

## 运行

- **llama.cpp**：将 `MiniCPM5-2B-Q4_K_M.gguf` 放到被忽略的 `models/`。`lexaegis edge --start` 使用该文件，或由 `LEX_EDGE_GGUF` 指定。启动参数含 `--jinja --ctx-size 32768`、KV F16、`--flash-attn on`、`--n-gpu-layers 99`、`--parallel 1`。服务进程不再加 `--reasoning off`。抽取请求仍是 `temperature: 0` + `json_schema`。
- **Compose**：`docker compose --profile edge up -d`。`edge-model` 使用同一别名与 32K 启动参数；容器内监听 `0.0.0.0:8080` 供内部网络，本机原生默认 `127.0.0.1:8080`。
- 8GB 为方案预算，不是实测。显存不足时先降物理 batch，再降 ctx。RapidOCR / whisper.cpp 与 2B 不同时驻留。

## 红队

红队可共用同一边侧实例。推理侧应写 JSON rationale；本次不实现红队调模型。
