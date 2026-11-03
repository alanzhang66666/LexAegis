# 阿里云试用部署：PAI-DSW + Qwen3.5-9B

**结论**：试用阶段在 PAI-DSW 的免费 GPU 实例（A10 24G）上原生运行工作台，边侧模型用 **Qwen3.5-9B Q8_0**（约 10GB），只放合成材料。确认可用后，再用 `deploy.sh --gpu` 在阿里云 ECS 上做 Compose 隔离部署。

> 状态：脚本流程已在无 GPU 的沙箱里用假的模型服务验证（见文末“已验证 / 未验证”）。Qwen3.5-9B 在真实 GPU 上的速度和抽取质量尚未实测，模型声明为 `trial_unverified`。正式外发在代码里仍是阻断的，本部署不改变这一点。

## 1. 范围与前提

- **只用合成材料。** DSW 和这里生成的发布清单都不构成隔离收据或正式发布身份。
- **边侧模型**：Qwen3.5-9B Q8_0，服务别名仍是 `edge-small`，声明见 `models/catalog/edge.qwen3.5-9b.q8_0.trial.json`。生产声明（MiniCPM5-2B）不变。
- **运行环境**：DSW 里用 `production`。它可以新建案件、上传自己的合成 Word 材料并自动抽取；`integration` 只接受项目内置场景（新建案件会返回 409），`demo` 的演示案件不能重新抽取。

## 2. 文件

| 文件 | 用途 |
| --- | --- |
| `dsw_edge_test.sh` | 在 DSW 里编译 llama.cpp（CUDA）、下载 Qwen3.5-9B、准备 Python 3.12 环境，再按 worker 的真实调用方式和 120 秒超时测抽取，输出耗时对比表 |
| `dsw_workbench.sh` | 在 DSW 里原生启动工作台（GPU 边侧模型 + 前端），生成登录口令 |
| `deploy.sh` | 阿里云 ECS 一键部署：装 Docker / NVIDIA 运行时、生成 `.env` 和密钥、生成未验证发布清单、准备数据目录、构建、启动、隔离自检 |
| `compose.gpu.yaml` | 叠加在 `compose.yaml` 上：边侧模型改用 llama.cpp CUDA 镜像并占用一块 GPU，默认加载 Qwen3.5-9B |

## 3. 试用：PAI-DSW

### 3.1 资源与费用

- DSW 新用户免费额度：每月 250 计算时，共 3 个月 750 计算时，只能抵扣 DSW 免费资源类型（[PAI 计费说明](https://help.aliyun.com/zh/pai/product-overview/billing-overview)）。A10 每小时消耗多少计算时以控制台为准。
- 实例规格选可用免费额度抵扣的 GPU 规格，例如 `ecs.gn7i-c8g1.2xlarge`（1×A10 24G、8 vCPU、30G 内存）。
- 免费云盘 100GiB；实例停止超过 15 天，云盘内容会被清空。
- **用完立即停止实例**，开着就一直扣额度（下载、编译期间也在计时）。

### 3.2 步骤

1. **领额度、开 PAI**：在免费试用页领取“交互式建模 PAI-DSW”；进入 PAI 控制台，选地域（如华东1 杭州），开通并创建默认工作空间。
2. **建实例**：交互式建模（DSW）→ 新建实例。资源类型“公共资源”，规格选标明可用免费额度的 A10，镜像选官方带 CUDA 开发工具的 GPU 镜像（PyTorch 或 ModelScope）。
3. **打开终端**：实例运行后点“打开”，在 JupyterLab 的 Launcher 里打开 Terminal，`nvidia-smi` 确认能看到显卡，`nvcc --version` 确认有 CUDA 编译器。
4. **测模型**：把 `dsw_edge_test.sh` 和 `dsw_workbench.sh` 上传到 `/mnt/workspace`，执行：

   ```bash
   bash dsw_edge_test.sh
   ```

   首次约半小时以上（编译 llama.cpp、下载约 10GB 权重、准备 Python 环境）。可用 `HF_ENDPOINT`、`PIP_INDEX_URL` 换下载源（默认 hf-mirror.com 和阿里云 PyPI 镜像）。

5. **看结果**：汇总表列出 8 份短材料（约 130 字）和 2000 / 6000 / 12000 字三份长材料的耗时与事实条数。通过标准见 3.4。
6. **启动工作台**：

   ```bash
   bash dsw_workbench.sh          # 停止：bash dsw_workbench.sh stop
   ```

   首次会用 nodeenv 安装 Node 22（npmmirror 镜像）并构建前端。登录用户名 `admin`，口令在 `/mnt/workspace/workbench-password.txt`。看内置四条演示流程用 `PROFILE=demo bash dsw_workbench.sh`。

### 3.3 访问方式：只能用 SSH 隧道

工作台在代码里只接受本机地址：`TrustedHostMiddleware` 只放行 `127.0.0.1` / `localhost`，写操作（含登录）还会校验 `Origin`。实测结果：

| 访问方式 | 结果 |
| --- | --- |
| 公网 IP（NAT 网关 + EIP） | `Invalid host header` |
| DSW 网关链接 | 登录被拒：“不允许跨站请求” |
| SSH 隧道到本机地址 | 正常 |

做法：在 DSW 控制台按“远程连接 → ProxyClient 方式”配好 SSH（不需要 NAT 网关，无额外费用），然后在自己电脑上：

```bash
ssh -N -L 38765:127.0.0.1:38765 <DSW 的 SSH 主机名>
```

浏览器打开 `http://127.0.0.1:38765`。本方案不修改这两道检查。

### 3.4 验收

- [ ] 汇总表里 Qwen3.5-9B 没有“超时/失败”，12000 字那一行也在 120 秒内完成
- [ ] `bench-*.json` 中 `quote_ok`、`numbers_ok` 为 `true`（引用和数字都出自原文）
- [ ] 工作台能登录，新建案件、上传合成 Word 材料后出现自动抽取的候选事实
- [ ] 试用结束后实例已停止

大量超时时，先怀疑模型没有关掉思考模式（请求带 `chat_template_kwargs.enable_thinking=false`），把 `llama-gpu.log` 和 `bench-*.json` 留下再排查。对比旧模型可加 `MODEL_REPO=openbmb/MiniCPM5-2B-GGUF MODEL_FILE=MiniCPM5-2B-Q4_K_M.gguf`，汇总表会并排显示。

## 4. 之后：阿里云 ECS（Compose 隔离部署）

试用通过后，用 `deploy.sh` 部署和 CI `compose-isolation` 任务相同的拓扑：api、worker、edge-model 在内网，只有 gateway 能出网。

| 项 | 建议 |
| --- | --- |
| 规格 | `ecs.gn6i-c4g1.xlarge`（4 核 15G，T4 16G），包月参考 1681 元；或 A10 规格 |
| 系统 | Ubuntu 24.04，创建时勾选“安装 GPU 驱动” |
| 磁盘 | 系统盘 40–80GB；长期使用加一块 ESSD 数据盘（数据目录不能放 NAS/OSS） |
| 安全组 | 只放行 22，限定来源 IP |
| 地域 | 真实材料只放内地地域；内地拉 ghcr.io 镜像需离线导入或推到自己的 ACR |

```bash
git clone https://github.com/alanzhang66666/LexAegis.git && cd LexAegis
sudo DOCKER_MIRROR=<ACR 加速器地址> bash deploy/aliyun/deploy.sh --gpu --docker-only   # 先只装 Docker
docker load -i llama.tar     # 内地地域：导入在海外机器上 docker save 的 llama.cpp:server 和 :server-cuda
sudo LEX_PROFILE=production PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
     HF_ENDPOINT=https://hf-mirror.com bash deploy/aliyun/deploy.sh --gpu
ssh -N -L 38765:127.0.0.1:38765 root@<ECS 公网 IP>    # 在自己电脑上
```

`deploy.sh` 会自动下载 Qwen3.5-9B 到 `models/`，把 `COMPOSE_FILE` / `COMPOSE_PROFILES` / `LEX_EDGE_GGUF_FILE` 写进 `.env`，之后直接用 `docker compose ps|logs|down`。T4 上 flash-attn 报错时在 `.env` 加 `LEX_EDGE_FLASH_ATTN=off`。备份前先 `docker compose stop`，再用 `lexaegis backup ... --offline-confirm`（数据目录取 `.env` 里的 `LEX_APP_DATA_PATH` / `LEX_GATEWAY_DATA_PATH`）。

## 5. 已验证 / 未验证

已验证（无 GPU 沙箱）：

- 原生方式启动 `production`，用假的模型服务跑通“新建案件 → 上传 Word → 解析 → 自动抽取 → 事实写回”；`integration` 新建案件返回 409
- `dsw_edge_test.sh` 的计时、120 秒超时判定和多模型汇总表（假模型服务）
- `dsw_workbench.sh` 启停；Host / Origin 三种访问方式的结果
- `deploy.sh --prepare-only` 生成的 `.env` 被 Compose 正确解析（GPU 设备、CUDA 镜像、模型路径）；所有脚本通过 `bash -n` 和 shellcheck

未验证：

- Qwen3.5-9B 在 A10 / T4 上的速度、抽取质量，以及 `enable_thinking=false` 是否生效
- DSW 镜像里编译 llama.cpp（CUDA）、nodeenv 安装 Node 22、uv 安装 Python 3.12
- `deploy.sh` 的 Docker 构建、启动和 `check-isolation` 全流程（沙箱无法拉取 Docker Hub / ghcr.io 镜像）
- ProxyClient SSH 的具体配置步骤
