# 部署方案总览：三个版本

三个版本都只用于**合成材料**，都不改变“正式外发失败关闭”和各道门禁。区别在边侧模型跑在哪、能不能长期在线、花不花钱。

| | **A · 阿里云 GPU**（[说明](aliyun/README.md)） | **B · 腾讯 Cloud Studio**（[说明](cloudstudio/README.md)） | **C · CPU**（[说明](cpu/README.md)） |
| --- | --- | --- | --- |
| 边侧模型 | Qwen3.5-9B Q8_0（约 10GB） | Qwen3.5-9B Q8_0（约 10GB） | MiniCPM5-2B Q4_K_M（约 1.5GB） |
| 硬件 | DSW：A10 24G；ECS：T4 16G 或 A10 | 免费基础型：T4 16G、8 核 32G | 普通 CPU 服务器，4 核 8G 起 |
| 费用（参考，以控制台为准） | DSW 新用户免费额度（共 750 计算时、3 个月）；ECS T4 包月约 1681 元 | 免费，每月时长额度 3600 或 1 万分钟（官方两处说法不一致） | 4 核 8G 活动价约 898 元/年起 |
| 长期在线 | DSW 否；ECS 是 | 否（10 分钟不操作自动关机） | 是 |
| 怎么访问 | SSH 隧道（默认）；DSW 可选 `LEX_PUBLIC_ORIGIN` 公网链接 | Cloud Studio 预览地址（https） | SSH 隧道；可选 `LEX_PUBLIC_ORIGIN` |
| 抽取速度 | 快（待实测） | 快（待实测） | 慢，大块材料需调大超时（待实测） |
| 部署形态 | DSW：原生；ECS：Docker Compose 隔离拓扑 | 原生（无 Docker） | Docker Compose 隔离拓扑 |
| 入口脚本 | `aliyun/dsw_edge_test.sh`、`dsw_workbench.sh`、`deploy.sh --gpu` | `cloudstudio/cloudstudio.sh` | `cpu/deploy.sh` |

## 怎么选

- **想免费试用、看抽取效果**：先用 B（Cloud Studio）或 A 的 DSW。两个都是临时环境，用完要停。
- **想长期在线、要速度**：A 的 ECS（T4 包月）。
- **想长期在线、尽量省钱，能接受抽取很慢**：C（CPU）。先跑 `cpu/bench_edge.py` 看各档材料耗时再定。
- **只用工作台、事实人工录入**：不需要边侧模型，`deploy.sh` 不加 `--gpu` / `--cpu`，一台 2 核 4G 的小服务器即可。

## 三个版本共用的两处代码改动（都是默认关闭的可选项）

| 环境变量 | 作用 | 谁用 | 不设置时 |
| --- | --- | --- | --- |
| `LEX_PUBLIC_ORIGIN` | 工作台额外接受这一个公网地址（Host 白名单和 Origin 校验各加一项） | B 必须；A、C 可选 | 完全不变：只接受 `127.0.0.1` / `localhost` |
| `LEX_EDGE_REQUEST_TIMEOUT`、`LEX_EDGE_EXTRACT_CHUNK_CHARS`、`LEX_EDGE_EXTRACT_CHUNK_BLOCKS` | 每次调用边侧模型的等待上限，每块材料的字数 / 段数上限 | C 必须；其他可选 | 完全不变：120 秒、1.4 万字、8 段 |

对应测试：`tests/test_public_origin.py`、`tests/test_edge_timeout_and_chunks.py`。

## 共同的限制

- 只放合成材料。公网地址 / 预览地址是明文 HTTP 或公开可达的链接，不构成隔离收据，也不是正式发布。
- 边侧模型换成 Qwen3.5-9B 对应 `models/catalog/edge.qwen3.5-9b.q8_0.trial.json`（`trial_unverified`），生产声明（MiniCPM5-2B）不变。
- 所有真实 GPU / CPU 上的速度、质量、`enable_thinking=false` 是否生效、Docker 构建与 `check-isolation` 全流程，都还没有在真实环境里跑过（沙箱没有 GPU，也拉不到 Docker Hub / ghcr.io 镜像）。各版本 README 末尾分别列了已验证 / 未验证。
