# 比赛版与生产版交付边界

LexAegis 从同一份业务核心生成两种交付形态。两者都不得包含 `.env`、真实密钥、运行数据库、
真实案件或把待验收事项写成通过。

## 比赛版

目录名为 `1-智能体作品及其完整材料`，参照比赛材料的分组方式提供源码、测试、容器材料、
合成示例、提示词、知识资源和依赖说明。比赛端侧模型改为用户指定的 Unsloth Qwen3-4B
GRPO 路线，并保留完整公开基座权重与适配材料：

- Hugging Face 基座：`unsloth/Qwen3-4B-Base`；固定提交
  `0573b584bc6b32adc84bb9c91bf9b71bea71fc40`；
- GRPO Notebook：`unslothai/notebooks/nb/Qwen3_(4B)-GRPO.ipynb`；固定提交
  `8081c7e480275013fa38cf2bfbaf902af5ccf589`；
- `training/`：LexAegis `fact_summary v2` 的完全合成训练投影、奖励器、状态和使用说明；
- `models/model-manifest.json`：完整随包文件大小和逐文件 SHA-256；
- `models/reproducibility.json`：固定 Notebook、基座提交、运行时和导出约定；
- 模型缓存、浮动 `main/latest` 和其他未声明权重一律排除。

公开仓库默认可匿名下载，不需要 Token；可选 `HF_TOKEN` 仅用于账户镜像或限流场景。
Notebook 的适配代码和数据契约可作为微调工程成果，但当前未执行 GPU 训练，随包权重仍是基座，
不能写成已经生成的 LexAegis checkpoint。训练后须导出 merged 权重、记录环境并补充逐文件哈希。
比赛单容器演示仍是 native，不能自证隔离；正式外发保持阻断。

生成命令：

```powershell
.\.venv\Scripts\python.exe -m pip install huggingface-hub
.\.venv\Scripts\python.exe scripts/export_grpo_assets.py
.\.venv\Scripts\python.exe scripts/fetch_competition_model.py
.\.venv\Scripts\python.exe scripts/build_submission.py --edition competition `
  --competition-model-dir .data/models/qwen3-4b-base `
  --competition-repro-dir .data/model-reproduction/qwen3-4b-grpo
```

## 生产版

目录名为 `2-生产部署交付结构（待签封）`。它只提供生产配置、Windows 维护脚本、许可、模型登记
要求、验收说明和封装工具，不制造以下正式产物：

- 固定应用镜像和 route-isolation 镜像的 `images.tar`；
- 状态为 `verified` 的 `release-build-manifest.json`；
- 与清单匹配的 wheel；
- 绑定相同镜像的依赖及许可证清单；
- 目标环境隔离、备份恢复、十门收据和逐请求批准。

上述输入实际完成后，使用 `scripts/package_delivery.py` 生成最终离线 ZIP。生产端侧模型按受控资产
单独登记、校验和安装，不从比赛目录静默继承。打包成功也只代表产物一致，不代表案件授权或
正式发送验收。

生成待签封结构：

```powershell
.\.venv\Scripts\python.exe scripts/build_submission.py --edition production
```

一次生成两种形态：

```powershell
.\.venv\Scripts\python.exe scripts/build_submission.py --edition both `
  --competition-model-dir .data/models/qwen3-4b-base `
  --competition-repro-dir .data/model-reproduction/qwen3-4b-grpo
```
