# 本地试跑：D 盘模拟云网关与边侧模型

2026-11-01 已在本机跑通 MiniCPM5-2B Q4_K_M 的 GPU 推理、事实抽取，以及独立网关参与的合成流程。工作台、边侧业务库和模拟云端账本均部署在 D 盘，现有 `.env` 与其他运行库保持原样。

本轮采用 `demo` / `native`：边侧运行真实模型，网关返回 `mock` 结果，产物标记为 `provenance=simulation`。没有调用外部模型服务商；正式外发状态保持 `blocked`。

完整扩展测评见 [2026-11-01 本地部署测评报告](LOCAL_DEPLOYMENT_EVALUATION_2026-11-01.md)：本地工程链路通过，新增复杂短样例存在抽取失败，生产隔离与正式构建仍待完成。试用时保留人工核校。

## 1. 直接打开

工作台：[http://127.0.0.1:48765](http://127.0.0.1:48765)

- 用户名：`admin`。
- 登录口令：查看本机文件 [local-password](../.data/local-cloud-trial/credentials/local-password)，复制文件中的单行口令。
- 使用工作台内置合成案例。已有一条完整自检结果和一条风险阻断记录，可直接查看事实、来源与任务状态。

自检中的复核、批准及确认动作由明确标注的自动化合成账号执行，用于验证产品状态流转，不是实际人员签署的法学结论。

## 2. 本机配置

| 项目 | 实际配置 |
| --- | --- |
| 显卡 | NVIDIA GeForce RTX 4060 Laptop GPU，8188MiB 显存 |
| 内存 | 约 16GB |
| 模型 | 官方 MiniCPM5-2B Q4_K_M |
| 模型服务别名 | `edge-small` |
| 运行器 | llama.cpp `b12032`，Windows CUDA 12.4 x64 |
| 上下文与并发 | 8192 tokens，并发 1 |
| 计算参数 | batch 512，ubatch 128，GPU layers 99，Flash Attention on |
| 模型接口 | `http://127.0.0.1:18080/v1` |
| 模拟云网关 | `http://127.0.0.1:48766`，独立进程与账本 |
| 工作台 | `http://127.0.0.1:48765` |

原有 8080 端口的服务保持运行，本次模型使用 18080。模型驻留后观察到整卡占用约 3GB；该数值包含桌面与其他进程，不作为模型独占峰值。

## 3. 文件和数据位置

以下路径均相对于 `<checkout>`：

| 内容 | 路径 |
| --- | --- |
| 模型权重 | `models/MiniCPM5-2B-Q4_K_M.gguf` |
| CUDA 运行器 | `.artifacts/llama-server/b12032-cuda12/` |
| 边侧业务库和材料 | `.data/local-cloud-trial/edge/demo/app/` |
| 模拟云端网关账本 | `.data/local-cloud-trial/cloud/demo/gateway/` |
| 登录口令、签名密钥 | `.data/local-cloud-trial/credentials/` |
| 进程标识与启动时间 | `.data/local-cloud-trial/state.json` |
| 各服务日志 | `.data/local-cloud-trial/logs/` |
| 固定资产来源与哈希 | `.data/local-cloud-trial/setup/ASSETS.json` |
| 自检报告 | `.data/local-cloud-trial/verification.json` |
| 抽取工程报告 | `.data/local-cloud-trial/edge-probe.json` |
| 停止、重启与数据保留报告 | `.data/local-cloud-trial/lifecycle.json` |

三份下载文件均已核验官方 SHA-256。模型固定 revision 为 `2079a22f3beaa4e306449978533478fe0522f4b3`，权重 SHA-256 为 `ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd`。

资产来源：[MiniCPM5 官方 GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/tree/2079a22f3beaa4e306449978533478fe0522f4b3)、[llama.cpp b12032 官方发布](https://github.com/ggml-org/llama.cpp/releases/tag/b12032)。

## 4. 启动、查看状态和停止

在 PowerShell 中运行：

```powershell
Set-Location <checkout>
powershell.exe -NoProfile -File .\scripts\windows\local-cloud-trial.ps1 status
powershell.exe -NoProfile -File .\scripts\windows\local-cloud-trial.ps1 start
```

使用完毕后停止：

```powershell
Set-Location <checkout>
powershell.exe -NoProfile -File .\scripts\windows\local-cloud-trial.ps1 stop
```

控制脚本核对 PID 与进程创建时间，再管理本次部署的进程树。端口已被其他程序占用时停止启动流程，保留原程序。停止后保留模型、口令和合成数据，再次启动可继续查看已有记录。

该脚本启动模型、gateway、API 和 worker 四组进程，均使用本机回环地址。环境变量显式选择独立 demo 数据根；API、worker 与 gateway 不加载仓库 `.env`，运行环境不注入服务商密钥。口令目录已限制为当前 Windows 用户访问。

## 5. 实际测试结果

| 测试 | 结果 |
| --- | --- |
| 工作台与模型接口 | HTTP 正常，`edge-small` 可用 |
| 网关鉴权 | 有效签名可查询，未签名请求返回 403 |
| 网关云凭据 | 主槽 `unconfigured` |
| 真实模型事实抽取 | 8 条内置合成材料，共提取 64 条候选事实，约 20.84 秒 |
| 7 项抽取工程检查 | JSON、来源 ID、引文子串、数字来源、别名、字段枚举和角色枚举均为 8/8 |
| 合成完整流程 | 真实模型初筛 → 合成复核与批准 → 网关 mock 调用 → 来源回链 → 合成确认，完成 |
| 风险阻断 | 高风险合成请求审批返回 409 |
| 停止与重启 | 三个测试端口释放；重启后服务正常，已有合成结果保留 |
| 正式外发状态 | `blocked` |

抽取检查衡量工程契约，报告中的 `legal_availability=not_scored`。真实材料质量评测及生产隔离按 [完整部署方案](CLOUD_EDGE_DEPLOYMENT_PLAN.md)继续实施。

## 6. 后续试用顺序

1. 打开工作台，查看已完成的合成任务，核对来源锚点与本地回链。
2. 新建内置合成案例，观察最小披露、模型初筛和阻断行为。
3. 对比 Q4 与 Q8，使用相同任务记录人工修订量、耗时和资源。
4. 如需接入真实云 API，另建 integration 运行库，在独立网关配置服务商密钥，继续使用已登记合成材料完成付费调用联调。

正式案件继续沿用现行 G 门和逐请求授权；本轮记录用于本机功能试用。
