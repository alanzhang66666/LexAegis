# 边侧模型目录

本目录只放**声明**，不放权重。`models/` 下的 GGUF 等权重要被 gitignore。

当前本机边侧只有一个生产模型：**MiniCPM5-2B Q4_K_M**（[openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B)，权重取 [MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)）。生产调用点仍只有事实提取，不生成 `fact_summary`，也不用模型改写 `local_text`。Git 源码不包含权重；同一份权重另作为本仓库 Releases 附件分发。下文是部署方案，**不是本机已安装或已跑通的结论**。

## 下载固定版本权重

[模型附件与校验文件](https://github.com/alanzhang66666/LexAegis/releases/tag/model-minicpm5-2b-q4km-20261103)提供 `MiniCPM5-2B-Q4_K_M.gguf`，大小为 **1,561,318,368 字节**。它与 OpenBMB 官方 GGUF 仓库版本 `2079a22f3beaa4e306449978533478fe0522f4b3` 的文件逐字节一致，没有本项目的微调或权重修改。该附件是模型镜像，使用上游 Apache-2.0 许可证；不是 LexAegis 产品正式发行或模型质量验收。

从源码根目录使用 GitHub CLI 下载，已有同名文件时 CLI 会拒绝覆盖：

```powershell
New-Item -ItemType Directory -Path models -Force | Out-Null
gh release download model-minicpm5-2b-q4km-20261103 --repo alanzhang66666/LexAegis --pattern MiniCPM5-2B-Q4_K_M.gguf --dir models
if ($LASTEXITCODE -ne 0) { throw '模型下载失败；请检查已有文件或重试下载。' }
$expected = 'ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd'
if ((Get-FileHash -LiteralPath models/MiniCPM5-2B-Q4_K_M.gguf -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw '模型校验失败，禁止使用该文件。'
}
```

也可直接在附件页面下载。默认 `git clone` 和 GitHub 的源码 ZIP 均不包含该 1.56 GB 文件。完整来源、固定下载地址和哈希见 [分发清单](MiniCPM5-2B-Q4_K_M.provenance.json)，许可证见 [LICENSE-MiniCPM5-2B.txt](LICENSE-MiniCPM5-2B.txt)。

## 声明

- `edge.minicpm5-2b.q4_k_m.nothink.json`：现行且唯一的生产声明。`role=fact_extraction_only`，服务别名 `edge-small`，`context=32768`（模型原生最长 131072，边侧抽取仍按块截断），`json_object=required`，`thinking=request_controlled`，`vision=false`。不宣称 32K 已在本机跑通。请求默认 `enable_thinking=false`；缺字段同站点二次抽取可按环境打开有界 thinking。

Compose / `lexaegis edge --start` 服务别名仍为 `edge-small`。Ollama 需自行导入同一 GGUF 并把 `LEX_EDGE_MODEL` 指到该名称。

## 运行

- **llama.cpp**：将 `MiniCPM5-2B-Q4_K_M.gguf` 放到被忽略的 `models/`。`lexaegis edge --start` 使用该文件，或由 `LEX_EDGE_GGUF` 指定。启动参数含 `--jinja --ctx-size 32768`、KV F16、`--flash-attn on`、`--n-gpu-layers 99`、`--parallel 1`。服务进程不再加 `--reasoning off`。抽取请求仍是 `temperature: 0` + `json_schema`。
- **Compose**：`docker compose --profile edge up -d`。`edge-model` 使用同一别名与 32K 启动参数；容器内监听 `0.0.0.0:8080` 供内部网络，本机原生默认 `127.0.0.1:8080`。
- 8GB 为方案预算，不是实测。显存不足时先降物理 batch，再降 ctx。RapidOCR / whisper.cpp 与 2B 不同时驻留。

## 红队

红队可共用同一边侧实例。推理侧应写 JSON rationale；本次不实现红队调模型。
