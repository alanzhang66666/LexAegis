# LexAegis 本地部署完整测评报告

测评日期：2026-11-01（Asia/Shanghai）
对象：D 盘边侧模型、独立模拟云网关及工作台；产品 V1.0（`1.0.0`）
运行形态：Windows / `demo` / `native`，真实本地模型与本机 mock 网关

配套文件：[五列 Excel 测评表](../deliverables/outputs/01a19508-ba86-70d2-a9b3-4f623ce1fb75/LOCAL_DEPLOYMENT_EVALUATION_2026-11-01.xlsx)。表内保留 121 项部署检查与 805 条后端执行记录，非通过行标黄；定向回归与完整回归有重叠。问题、文件改动与原方案修订见[部署方案第 15 章](CLOUD_EDGE_DEPLOYMENT_PLAN.md#15-本地模拟部署的问题解决方案与文件改动)。

## 1. 测评结论

**当前部署可用于本地合成材料的流程验证，完整生产验收条件尚未满足。** 本轮验证了真实 GPU 模型、权限分工、请求冻结、网关核验、结果回链、备份恢复及浏览器操作，并修复了三处工程问题。扩大模型样例后发现的抽取失败，以及隔离、构建和真实外发的缺项，均保留在本报告中。

| 层次 | 结论 | 主要证据 |
| --- | --- | --- |
| 代码与前端工程 | 通过本轮回归 | 全量 Python **749 通过、5 跳过**；修复后定向 **51 通过**；类型检查和前端构建通过 |
| 浏览器业务流程 | 通过 | 桌面 12 项、production 合成接收 4 项、补充视口 4 项，共 **20 项通过** |
| 当前实际部署 | 通过本地功能与安全检查 | 9 组实际 HTTP、模型、网关及备份恢复检查通过；当前工作台仍可访问 |
| 案由包验收 | 10 项直接断言通过 | 另有 8 项测试映射、1 项真实发送人工门禁；分别保留状态 |
| 模型工程接口 | 内置基线通过 | 前次 8 条合成材料的 7 项工程检查均为 8/8；本轮复核资产与完整流程 |
| 模型扩展适用性 | **需要改进** | 本轮新增 8 个短样例中，3 个返回合法事实，5 个抽取失败；长文分块任务完成 |
| 生产隔离 | **未验收** | 当前为 native；Docker 引擎未就绪；同等原生环境可连接公开外网目标 |
| 正式构建身份 | **未就绪** | API / worker / demogateway 均为 `unconfigured`；发布候选为 `pending` |
| 真实云端与真实案件 | **未执行** | 本轮未调用付费云服务，未消费正式许可，`formal_dispatch=blocked` |

建议继续使用内置合成材料评估产品流程。进入真实使用前，优先完成模型复杂样例改进、目标隔离部署、固定构建和 integration 真实云联调，再按现行 G 门办理具体请求的正式授权。

## 2. 验收依据与源码基线

### 2.1 依据

测评以仓库现行代码、[AGENTS.md](../AGENTS.md)、[架构](ARCHITECTURE.md)、[三环境部署](DUAL_TRACK_DEPLOY.md)、[双线验收](DUAL_TRACK_ACCEPTANCE.md)、[验证记录](VALIDATION.md)和[边侧模型接口](EDGE_MODEL_INTERFACE.md)为依据。

核对的[远端仓库](https://github.com/alanzhang66666/LexAegis) HEAD 为 `2aa5f967972ba7df13dd85be3a6b9ffc676d34f1`，本地源码基线为 `263b2275091ef9ae1c8228eda553da6bf7ee69bc`。两者的相关应用与部署代码一致，远端新增文档按其 Proposed 状态处理。本轮修复保留在工作树，尚未提交或生成正式发布构建。

### 2.2 结果分级

| 状态 | 含义 |
| --- | --- |
| 通过 | 有本轮实际执行记录，满足对应工程断言 |
| 需要改进 | 已执行，出现影响适用范围的失败 |
| 跳过 | 测试已收集，但当前平台或可选资产条件不满足 |
| 未验收 | 当前部署形态或证据条件尚未满足要求 |
| 未执行 | 本轮未进行该项实机操作 |

全量、定向、浏览器与实机检查分别计数；定向回归包含与全量重叠的用例。自动化复核、批准及确认动作使用明确标注的合成测试账号，验证状态流转，不替代真实案件的具名决定。

## 3. 设备、资产与运行参数

| 项目 | 本机情况 |
| --- | --- |
| 操作系统 | Windows，x64 |
| GPU | NVIDIA GeForce RTX 4060 Laptop，8188MiB 显存 |
| 驱动 | 592.00 |
| 系统内存 | 约 16GB |
| D 盘剩余空间 | 收尾采样约 201.3GiB |
| Python | 3.12.3 |
| Node.js | 24.14.1 |
| 浏览器 | Microsoft Edge 156.0.4314.58，headless 自动化 |
| 模型 | `openbmb/MiniCPM5-2B-GGUF`，Q4_K_M |
| 模型 revision | `2079a22f3beaa4e306449978533478fe0522f4b3` |
| 权重大小 | 1,561,318,368 bytes |
| 运行器 | llama.cpp `b12032`，Windows CUDA 12.4 x64 |
| 推理参数 | ctx 8192、batch 512、ubatch 128、parallel 1、GPU layers 99、Flash Attention on、threads 4 |
| GPU 使用观察 | 早期整卡采样约 3–3.4GiB；收尾采样为 6,851MiB。包含同时运行的其他图形负载，未作模型独占或连续峰值测量 |

权重 SHA-256：`ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd`。模型、CUDA 运行包和 CUDA 依赖包三份下载资产均重新核验了清单中的官方 SHA-256。

资产来源与固定版本见 [ASSETS.json](../.data/local-cloud-trial/setup/ASSETS.json)。性能结果对应本机、本轮输入与负载，未据此推算其他显卡或真实案件的处理速度。

## 4. 部署边界检查

### 4.1 进程、端口与数据

| 组件 | 地址或位置 | 实测情况 |
| --- | --- | --- |
| 模型 | `127.0.0.1:18080/v1` | `edge-small` 可用，GPU 推理正常 |
| API / 工作台 | `127.0.0.1:48765` | 健康检查与浏览器登录正常 |
| 模拟云网关 | `127.0.0.1:48766` | 签名健康查询正常，主槽 `unconfigured` |
| worker | 独立后台进程 | 队列执行与重启恢复正常 |
| 边侧业务根 | `.data/local-cloud-trial/edge/demo/app/` | 独立业务库与合成材料 |
| 网关数据根 | `.data/local-cloud-trial/cloud/demo/gateway/` | 独立账本，mock 请求可追溯 |
| 凭据目录 | `.data/local-cloud-trial/credentials/` | Windows ACL 禁用继承，1 条当前用户访问规则 |

三个测试端口均绑定 `127.0.0.1`，原有 8080 服务保持运行。停止脚本使用 PID 和进程创建时间核对归属，再停止本次部署的进程树。

收尾再次确认 API、gateway、worker、模型均存活，API 健康与模型列表接口均返回 200。资源和进程快照见 [final-state.json](../.data/deployment-evaluation/20261101-211139/final-state.json)。

### 4.2 凭据最小化

发现启动脚本最初将通用应用环境传给所有角色，使模型进程继承了网关 HMAC 密钥。已按角色收紧：

- 模型进程：无 `LEX_*` 应用变量，无登录口令或网关签名密钥。
- API：本地登录配置、业务路径和网关签名配置。
- worker：业务路径、模型与网关签名配置，不传登录口令。
- gateway：自身数据根与签名配置，不传边侧业务根或模型地址。
- 本轮所有角色：均不注入 `LEX_CLOUD_*` 服务商凭据。

对应回归检查通过，随后完成了实际停服与重启。证据为环境生成契约、运行状态及网关健康结果；原生同用户进程之间的文件访问边界仍由目标隔离部署补齐。

## 5. 全量代码回归

### 5.1 最终完整回归

执行 `pytest -q -ra`，使用独立临时目录与 JUnit 输出：

| 项目 | 结果 |
| --- | --- |
| 收集测试 | 754 |
| 通过 | **749** |
| 失败 / 错误 | **0 / 0** |
| 跳过 | **5** |
| 耗时 | 194.68 秒，约 3 分 15 秒 |
| 测试模块 | 77 个 |
| 警告 | 1 条 Starlette TestClient / httpx 弃用提示 |

报告：[pytest-corrected.xml](../.data/deployment-evaluation/20261101-211139/pytest-corrected.xml)；日志：[backend-corrected.log](../.data/deployment-evaluation/20261101-211139/backend-corrected.log)。模块计数见附录 A。

### 5.2 重点覆盖

| 能力 | 对应测试范围 |
| --- | --- |
| 角色权限与人工复核 | auth、legal_review、human_veto_flow、review_races |
| 冻结与逐请求授权 | outbound_gate、gate_matrix、formal_release、dispatch_control |
| 网关签名、重放及不确定结果 | gateway_release、cloud_dual、formal_release_standby |
| 合成材料与 profile 边界 | runtime_profiles、synthetic_scope、three_layer_execution |
| 回包校验与来源回链 | return_pipeline、result_envelope、output_checks、workflow |
| 备份恢复与授权失效 | restore_reauthorization、upgrade_approval、windows_maintenance_contract |
| 规则和领域扩展 | pack_integrity、runtime_pack、domain_packages、support_registry、package_controller |
| 编排器与上下文 | orchestrator、domain_runtime、domain_mapper |
| 解析与可选能力回退 | materials、assets、platform |

这些测试中的模拟供应商、HTTP 异常及合成证据用于验证代码行为。真实服务商调用、目标网络隔离和法学签署分别按其验收条件执行。

### 5.3 修复后定向回归

案由验收 CLI 修复后，再执行 acceptance_suite、diagnostics、local_cloud_trial、orchestrator 与 return_pipeline：**51 项通过**，无失败或跳过。

报告：[focused.xml](../.data/deployment-evaluation/20261101-211139/focused.xml)。新增 CLI 路径测试在这轮执行，确保命令入口也能实际运行。

### 5.4 五个跳过项

| 项目 | 跳过原因 | 影响 |
| --- | --- | --- |
| PaddleOCR 实际资产 | 当前环境未安装 | CPU Paddle 回退的真实资产未测 |
| POSIX SIGTERM 清理 | 本机为 Windows | 该平台专属测试不适用；本机进程树停止另有实测 |
| RapidOCR 扫描识别 | 未安装且未预置模型 | 本机真实 OCR 识别能力未验收 |
| whisper.cpp 实际转写 | 运行器 / large-v3-turbo 未预置 | 音视频真实转写未验收 |
| 符号链接数据根 | Windows 创建符号链接权限不足 | 此实机用例跳过；其他路径与 profile 拒绝检查已运行 |

当前部署关闭 OCR 和转写，试用范围以文本材料、内置合成材料及人工核校为主。

## 6. 前端与浏览器测评

### 6.1 构建

TypeScript `--noEmit` 检查和 Vite 真实构建均通过，总计约 6.03 秒。证据：[frontend.log](../.data/deployment-evaluation/20261101-211139/frontend.log)。

### 6.2 仓库浏览器用例

| 测试组 | 视口 | 结果 | 覆盖内容 |
| --- | --- | --- | --- |
| demo 桌面全流程 | 1280×900 | 12/12 | Word 导入、本地工具、技术暂停与法学否决、主动停止、完整合成流程、回链、配置、可访问性 |
| production 合成接收 | 1440×1000 | 4/4 | 规则草稿权限、正式材料接收、构建缺失阻断、精确角色与待核默认值 |
| 补充响应式布局 | 1440、900、650、390 宽 | 4/4 | 横向溢出、材料 / 工作区 / 依据面板切换 |

五个目标视口均有检查。production 接收测试中的表单绑定用例包含显式测试 stub，验证表单和契约；该记录不作为正式 G 收据。

浏览器基线使用独立测试库与仓库合成夹具，默认固定审核。真实模型行为另在第 7、9 节测量，避免混用证据来源。

日志：[桌面](../.data/deployment-evaluation/20261101-211139/browser-desktop.log)、[production](../.data/deployment-evaluation/20261101-211139/browser-production.log)、[响应式](../.data/deployment-evaluation/20261101-211139/browser-responsive.log)。20 项名称见附录 B。

### 6.3 当前部署的实际浏览器检查

登录 `http://127.0.0.1:48765`，检查了真实部署的桌面、390px 手机布局和已完成任务结果页：

- 登录成功，浏览器脚本错误为 0。
- 手机页面无横向溢出。
- 结果页显示“本地预置结果”，与 `provenance=simulation` 一致。
- 查看截图确认结果、身份回填、来源锚点和已确认状态可见。

截图：[桌面结果](../.data/deployment-evaluation/20261101-211139/screenshots/native-result-1280.png)、[手机工作台](../.data/deployment-evaluation/20261101-211139/screenshots/native-dashboard-390.png)、[人工否决](../.data/deployment-evaluation/20261101-211139/screenshots/human-veto-rejected.png)。

## 7. 当前部署的实际 HTTP 与网关检查

本轮对正在运行的 API、独立 gateway 和真实 GPU 模型执行了 9 组检查，全部通过。复核、批准和确认节点由合成账号驱动，整个链路使用 mock 回包。

| 检查 | 实际结果 |
| --- | --- |
| 未登录访问业务接口 | 401 |
| 错误登录口令 | 401 |
| 外来 Origin 写请求 | 403 |
| 非受信 Host | 400 |
| 管理员直接代行审批 | 403 |
| demo 任意上传材料 | 409 |
| 公开 bootstrap 泄漏口令 / 签名密钥 | 未发现这两项凭据值 |
| 网关错误签名 | 403 |
| 已批准请求正文被篡改 | 403 |
| 过期批准 | 403 |
| 本地 mapping 混入 wire | 403；即使重算请求哈希并签名也拒绝 |
| demo 改成 cloud 传输 | 403；未调用服务商 |
| 重放已完成请求 | 返回原记录；账本记录数重放前后均为 2 |
| 真实模型初筛与完整流程 | `live_edge_model` → 合成复核 / 批准 → mock 网关 → 回链 → 合成确认，完成 |
| 高风险合成请求 | 模型阻断，审批 409 |

本轮成功任务为 `task_a6e8938a0f244325`，包含 7 条结果陈述与有效来源锚点。风险阻断任务为 `task_5f77ec6b56e54b60`。它们属于独立本地合成运行库，不属于既有十案的真实发送验收。

完整证据：[live-and-backup.json](../.data/deployment-evaluation/20261101-211139/live-and-backup.json)。

## 8. 真实备份、恢复与启停演练

在本机执行了“准备未发送批准 → 停服 → CLI 备份 → 恢复到新目录 → 校验授权及历史 → 重启原环境”。

| 检查 | 实测结果 |
| --- | --- |
| 停止进程树 | 本次部署所属进程停止，保留其他服务 |
| 备份归档 | `native-demo-backup.zip`，335,177 bytes |
| 恢复目标 | 本次证据目录内新建的 `restored/app` 和 `restored/gateway` |
| 尚未发送的批准 | 恢复后失效 |
| 已确认合成结果 | 保留 |
| 网关历史记录 | 保留 2 条 |
| 原运行库 | 保持原样，重新启动后继续使用 |
| 临时批准夹具 | 原库中本轮创建的未发送合成任务已主动停止 |
| 凭据修复生效 | 重启后模型环境无 `LEX_*`，网关不接收业务数据根 |

恢复日志明确进入 review-required 状态。本次是同机、两个数据根的 demo 演练；跨主机一致备份、生产发送不明状态对账及生产升级回滚继续按目标环境验收。

证据：[备份日志](../.data/deployment-evaluation/20261101-211139/backup.log)、[恢复日志](../.data/deployment-evaluation/20261101-211139/restore.log)、[重启日志](../.data/deployment-evaluation/20261101-211139/maintenance-restart.log)、[夹具清理](../.data/deployment-evaluation/20261101-211139/cleanup.json)。

## 9. 模型质量与长文测评

### 9.1 内置工程基线

前次部署已经实测 8 条 `mock_labor` 合成材料，64 条候选事实，约 20.84 秒。JSON、来源 ID、引文子串、数字来源、别名冲突、字段枚举和角色枚举七项均为 8/8，`legal_availability=not_scored`。

本轮核对相同权重与运行器哈希，并用该模型再次完成实际工作台的初筛和合成流程。前次基线结果与本轮新增样例分开列示，保留各自的测试范围。

前次证据：[edge-probe.json](../.data/local-cloud-trial/edge-probe.json)。

### 9.2 本轮扩展短样例

新增 8 个受控短样例，使用现有抽取提示词、`temperature=0`、默认关闭 thinking 和 JSON Schema。关键值匹配用于观察样例覆盖，不作为人工标注的法律事实准确率。

| 样例 | 合法候选数 | 耗时 | 结果 |
| --- | ---: | ---: | --- |
| 基本工资与入职日期 | 5 | 2.266 秒 | 预设金额、日期匹配；7 项工程检查通过 |
| 双方主张不同欠薪金额 | 0 | 0.812 秒 | 抽取失败：无合法 field 事实 |
| 加班主张与否认 | 0 | 0.813 秒 | 抽取失败 |
| 应发、实发与差额 | 0 | 0.812 秒 | 抽取失败 |
| 主体别名 | 0 | 0.797 秒 | 抽取失败 |
| 两名劳动者与不同工资 | 5 | 1.719 秒 | 两项金额匹配；7 项工程检查通过 |
| 扫描噪声与可辨金额 | 4 | 1.765 秒 | 可辨金额匹配；7 项工程检查通过 |
| 文内恶意指令 | 0 | 0.782 秒 | 未产生可用抽取，按失败处理 |

**这一组中 3/8 返回合法事实，5/8 抽取失败。** 失败得到阻断，没有转为自动可用事实；它同时说明当前 Q4 配置对扩展样例的可用性还需要改进。三个成功样例的关键值匹配，也没有覆盖所有主体关系和争议语义。

对金额冲突与工资表追加了原始响应诊断。观察到无 thinking 工资表返回空数组，以及部分响应复述来源 ID 占位文字；开启 thinking 的诊断响应可增加字段，但尚未形成经过整组回归的配置。本轮保留默认配置，未以放宽来源检查或临时改参数替换失败结果。

文内指令样例的失败关闭不直接记为四类攻击的法学 `resisted`。

证据：[model-bench.json](../.data/deployment-evaluation/20261101-211139/model-bench.json)。

### 9.3 长 DOCX 分块

另建独立 production 合成测试库，上传人工生成的长 DOCX，经实际解析、排队和 worker 调用真实本地模型抽取：

| 指标 | 结果 |
| --- | --- |
| 文本字符数 | 5,212 |
| 来源块 | 62 |
| 抽取批次 | 8 |
| parse / extract 作业 | 均 complete |
| 抽取用时 | 100.81 秒 |
| 最终候选事实 | 15 条，含重复内容合并 |
| 材料末尾独立事实 | 检出“2345 元” |

该测试确认了跨块处理和末尾事实可达。材料中有重复段落，15 条不是按全文人工标签计算的召回率；整篇复杂材料的质量仍须建立独立标注集评估。

### 9.4 模型交付建议

当前 Q4 配置继续用于受控合成试用和人工辅助抽取。下一轮以本次失败样例为开发集，新增独立保留集，比较 Q8_0、Qwen3.5-4B 4bit 及受控提示词 / 参数调整。比较重点为有效事实覆盖、否认与冲突保留、来源正确性、人工修订量和整份材料耗时。

Q8 与 Qwen3.5 的实测尚未执行，本报告不预设其中某个一定更好。

## 10. 案由验收与正式构建

### 10.1 DomainAcceptanceSuite

修复 CLI 路径类型后，对当前运行库执行：

```powershell
.\.venv\Scripts\python.exe -m lexaegis.acceptance_suite --data <checkout>\.data\local-cloud-trial\edge\demo\app --cause labor
```

结果为：**10 项直接断言通过、8 项 test_mapped、1 项 manual_gate**。直接断言包括包结构、法源字段、绑定兼容、最小化画像、门禁画像、包哈希、manifest、平台版本、来源链与夹具。八项映射保留测试引用；真实发送人工门禁 `g10_real_send` 保留待验收。

证据：[acceptance-suite.json](../.data/deployment-evaluation/20261101-211139/acceptance-suite.json)。

### 10.2 wheel 构建

独立构建虚拟环境安装仓库锁定的 setuptools / wheel，实际生成 `lexaegis-1.0.0-py3-none-any.whl`，并通过 `scripts/verify_wheel.py` 的自包含资源检查。

wheel 大小为 616,149 bytes，SHA-256：`5c22d36ca65c0953e8d0a4c233281990710264ca737a8d22eacdbeaf3e3ac95a`。前端、规则包和许可资源均与本次构建输入匹配。

证据：[wheel.log](../.data/deployment-evaluation/20261101-211139/wheel.log)、[wheel-result.json](../.data/deployment-evaluation/20261101-211139/wheel-result.json)。

随后创建全新虚拟环境，在源码目录之外安装该 wheel 和受仓库锁文件约束的运行依赖：

| 安装检查 | 结果 |
| --- | --- |
| wheel 与运行依赖安装 | 通过，约 79.62 秒 |
| `pip check` | 通过，无损坏依赖 |
| 实际导入位置 | 新虚拟环境的 `site-packages/lexaegis`，未导入工作树源码 |
| 打包后 API | 健康、未登录拒绝、登录与 bootstrap 均通过 |
| 打包后前端 | 首页及引用的 2 个静态资源均返回 200 |
| 包内初始化 | 创建合成案例成功，案由验收 CLI 成功 |

安装后冒烟约 18.16 秒。这补齐了本机干净虚拟环境的交付包检查；干净客户机器、固定 Docker 交付镜像及跨平台安装仍需按交付目标验收。

证据：[wheel-install.log](../.data/deployment-evaluation/20261101-211139/wheel-install.log)、[wheel-install-result.json](../.data/deployment-evaluation/20261101-211139/wheel-install-result.json)、[安装后冒烟结果](../.data/deployment-evaluation/20261101-211139/install-work/smoke-result.json)。

### 10.3 发布候选与运行身份

`release verify-candidate` 返回 `pending`，退出码 1：

- 工作树包含本轮修复及文档变更，`worktree_clean=false`。
- 缺少 `runtime_pack_hash`、`validation_results_hash`、`container_image_digests`。
- 正式验证报告和参考构建清单尚未接入候选核验流程。
- `policy_installed=false`、`dispatch_attempted=false`，产品外发状态为 `blocked`。

本轮 JUnit 和日志虽已生成，仍须按发布工具契约归并、审核并作为正式 validation 输入；不会因存在测试文件自动形成 verified 身份。当前三进程实际身份均为 `unconfigured`，规则库没有 published 包。

证据：[release-candidate.json](../.data/deployment-evaluation/20261101-211139/release-candidate.json)、[runtime-inventory.json](../.data/deployment-evaluation/20261101-211139/runtime-inventory.json)。

## 11. 隔离、真实云与正式授权缺项

### 11.1 当前原生部署的网络边界

native 为独立进程部署，尚未构成操作系统级隔离。本轮同等原生执行环境的无载荷 TCP 探测结果为：

| 目标 | 结果 |
| --- | --- |
| `1.1.1.1:443` | 超时 |
| `api.github.com:443` | 连接成功 |
| `huggingface.co:443` | 超时 |

公开外网目标仍可连接，且单个 IP 超时不能证明出口关闭。这是原生环境探测，不是 API / worker 容器命名空间的隔离收据。正式 G9 条件继续待验收。

### 11.2 Docker 状态

已尝试后台启动 Docker Desktop，并通过 `docker desktop start --timeout 30` 再次启动。该次调用在约 34.52 秒后返回：`Docker Desktop is still starting: context deadline exceeded`；此前 `docker version` 无法连接 `dockerDesktopLinuxEngine` 管道。

因此本轮没有生成固定容器镜像、启动目标 Compose 栈或取得五项运行探测结果。下一步应先确认 Docker Desktop / WSL2 引擎健康，再实际构建、启动、取证；当前 native 结果保持其本地功能验证范围。

证据：[isolation-status.json](../.data/deployment-evaluation/20261101-211139/isolation-status.json)、[native-network-probes.json](../.data/deployment-evaluation/20261101-211139/native-network-probes.json)、[docker-start-attempt.json](../.data/deployment-evaluation/20261101-211139/docker-start-attempt.json)。

### 11.3 真实云与真实案件

本轮没有进行 integration 的真实服务商调用，所有网关成功记录均来自 mock。真实网络错误、服务商计费、模型响应格式、云端读取超时与账本对账，仍需用已登记合成材料在 integration 中实测。

真实案件还须取得材料授权、规则发布、经审核服务商、有效攻击与隔离证据、请求冻结、具名复核批准及一次性许可。首案策略仍限 LA-001 的一次哈希绑定 D 发送；后续请求分别核验授权。既有十案保持层 A 评估完成、0 案真实发送的现行口径。

## 12. 本轮发现与修复

| 问题 | 影响 | 修复及验证 |
| --- | --- | --- |
| 模型进程继承网关签名密钥 | 超出模型所需权限 | 启动器按角色生成环境；新增 4 类角色断言和端口冲突测试；实际重启 |
| doctor 测试依赖默认数据目录 | 初轮 7 项诊断聚合断言失败，受测试环境和执行顺序影响 | 测试文件使用独立临时数据根；新增“缺失必需数据根仍应失败”测试；完整回归通过 |
| 案由验收 CLI 传入字符串路径 | CLI 触发 `AttributeError: 'str' object has no attribute 'parent'` | argparse 使用 Path，Store 接收路径对象；新增 CLI 测试并在实际运行库执行成功 |
| 扩展短样例 5 项无合法事实 | 当前模型配置适用性不足 | 保留失败与原始诊断；作为下一轮模型 / 提示词回归基线 |
| Docker 引擎未就绪 | 无法取得本机 Compose 隔离证据 | 有界启动尝试与错误记录；列为后续环境工作 |
| 通用模型自动拉起路径继承父进程环境 | demo 专用控制器的凭据修复尚未覆盖该路径 | 本次文档复核确认 `edge_runtime._spawn_once` 的 Popen 未显式设置 env；纳入部署 T6 待修复和故障回归，当前不记为通过 |

修复没有修改 `validate_formal_gate`、`authorize_dispatch`、规则发布条件或正式放行语义。51 项定向回归对修改处再次检查。

初轮、中间测试环境调整和最终回归日志分别保留。结论使用最终 `pytest-corrected.xml` 与定向 `focused.xml`，不将历史失败隐藏或混算为最终通过数。

## 13. 达到完整项目预期的后续顺序

| 优先级 | 工作 | 完成判据 |
| --- | --- | --- |
| 高 | 改进模型复杂样例 | 修复本轮失败样例，并在独立保留集验证事实、来源、否认与冲突保留 |
| 高 | 完成目标隔离部署 | Docker / WSL2 健康；固定 Compose 栈启动；两端出口、挂载、凭据、重启均有证据 |
| 高 | 冻结正式构建 | 审核并提交版本，固定镜像和运行包，接入验证报告，三进程 verified 身份一致 |
| 高 | integration 真实云联调 | 已登记合成输入，经真实网关调用后取得 `provenance=cloud`；验证错误、断连与 unknown 不重发 |
| 正式启用前 | 完成现行 G 表与具名授权 | 真实证据、规则、接收方、当前请求和许可精确匹配 |
| 功能启用前 | OCR / 转写与 GPU 生命周期 | 预置固定资产，验证目标硬件和模型卸载 / 重载，再启用对应输入 |
| 交付前 | 客户端与跨主机恢复演练 | 干净机器安装、固定镜像、两端一致备份、升级与回滚可复现 |

## 14. 复现入口与证据目录

当前服务仍运行在 [http://127.0.0.1:48765](http://127.0.0.1:48765)。登录及启停方法见 [LOCAL_CLOUD_TRIAL.md](LOCAL_CLOUD_TRIAL.md)，口令保留在本机受控目录。

标准回归入口：

在未加载部署用 `LEX_*` 变量的新终端执行；本轮回归执行器会显式清理继承的 `LEX_*` 变量，避免运行中的 demo 配置影响独立测试。

```powershell
Set-Location <checkout>
.\.venv\Scripts\python.exe -m pytest -q -ra
Set-Location <checkout>\frontend
node .\node_modules\typescript\bin\tsc --noEmit
node .\node_modules\vite\bin\vite.js build
```

本轮浏览器覆写配置位于证据目录，指定本机 Edge、独立数据根和空云凭据，保留仓库默认夹具行为。具体命令、退出码和耗时见各 `*-result.json`。

证据根目录：`<checkout>\.data\deployment-evaluation\20261101-211139\`。

| 文件 | 用途 |
| --- | --- |
| `remote-head.txt` | 远端提交核对 |
| `pytest.xml`、`pytest-final.xml` | 初轮及中间测试环境记录 |
| `pytest-corrected.xml`、`focused.xml` | 最终完整与定向回归 |
| `frontend.log` | 类型检查与构建 |
| `browser-*.log`、`browser-tests.json` | 20 项浏览器结果 |
| `native-browser.json`、`screenshots/` | 当前实际部署的浏览器检查与截图 |
| `live-and-backup.json` | 实际 HTTP、网关及备份恢复 |
| `model-bench.json` | 本轮短样例与长文结果 |
| `acceptance-suite.json` | 10 断言、8 映射、1 人工门禁 |
| `wheel.log`、`wheel-result.json`、`wheel/` | 自包含 wheel 构建 |
| `wheel-install.log`、`wheel-install-result.json`、`install-work/smoke-result.json` | 新虚拟环境中的安装、依赖和包内运行检查 |
| `release-candidate.json` | 正式发布候选缺项 |
| `runtime-inventory.json` | 运行身份、包状态及最小权限元数据 |
| `final-state.json` | 收尾健康、进程与资源快照 |
| `evaluation-summary.json`、`evidence-sha256.json` | 机器可读结果汇总与证据文件校验和 |
| `isolation-status.json`、`native-network-probes.json` | 当前网络和隔离条件 |
| `docker-start-attempt.json` | 有界 Docker 启动结果 |
| `backup.log`、`restore.log`、`cleanup.json` | 维护演练与测试夹具处置 |

下列附录由本轮 JUnit 与浏览器日志生成，便于逐项追溯。

## 附录 A：全量 Python 测试逐模块结果

以下来自最终完整回归 JUnit。合计 77 个模块，749 通过、5 跳过、0 失败 / 错误。后续新增的验收 CLI 回归另计入 51 项定向结果。

| 测试文件 | 通过 | 跳过 | 失败 / 错误 |
| --- | ---: | ---: | ---: |
| [tests/test_acceptance_suite.py](../tests/test_acceptance_suite.py) | 3 | 0 | 0 |
| [tests/test_adapted_recording.py](../tests/test_adapted_recording.py) | 8 | 0 | 0 |
| [tests/test_assets.py](../tests/test_assets.py) | 21 | 1 | 0 |
| [tests/test_audit_chain.py](../tests/test_audit_chain.py) | 5 | 0 | 0 |
| [tests/test_auth_governance.py](../tests/test_auth_governance.py) | 5 | 0 | 0 |
| [tests/test_capability_registry.py](../tests/test_capability_registry.py) | 6 | 0 | 0 |
| [tests/test_ci_runtime.py](../tests/test_ci_runtime.py) | 1 | 0 | 0 |
| [tests/test_cloud_dual.py](../tests/test_cloud_dual.py) | 26 | 0 | 0 |
| [tests/test_comparable.py](../tests/test_comparable.py) | 4 | 0 | 0 |
| [tests/test_d_path.py](../tests/test_d_path.py) | 23 | 0 | 0 |
| [tests/test_dataset.py](../tests/test_dataset.py) | 18 | 0 | 0 |
| [tests/test_delivery_package.py](../tests/test_delivery_package.py) | 6 | 0 | 0 |
| [tests/test_demo_document_import.py](../tests/test_demo_document_import.py) | 6 | 0 | 0 |
| [tests/test_diagnostics.py](../tests/test_diagnostics.py) | 25 | 0 | 0 |
| [tests/test_dispatch_control.py](../tests/test_dispatch_control.py) | 3 | 0 | 0 |
| [tests/test_disposition.py](../tests/test_disposition.py) | 8 | 0 | 0 |
| [tests/test_dockerfile_single_container.py](../tests/test_dockerfile_single_container.py) | 2 | 0 | 0 |
| [tests/test_domain_mapper.py](../tests/test_domain_mapper.py) | 11 | 0 | 0 |
| [tests/test_domain_packages.py](../tests/test_domain_packages.py) | 8 | 0 | 0 |
| [tests/test_domain_runtime.py](../tests/test_domain_runtime.py) | 10 | 0 | 0 |
| [tests/test_edge_eval.py](../tests/test_edge_eval.py) | 14 | 0 | 0 |
| [tests/test_edge_provider.py](../tests/test_edge_provider.py) | 35 | 0 | 0 |
| [tests/test_edge_review.py](../tests/test_edge_review.py) | 13 | 0 | 0 |
| [tests/test_evidence_receipts.py](../tests/test_evidence_receipts.py) | 24 | 0 | 0 |
| [tests/test_evidence_store.py](../tests/test_evidence_store.py) | 4 | 0 | 0 |
| [tests/test_experiments.py](../tests/test_experiments.py) | 5 | 0 | 0 |
| [tests/test_formal_attack_suite.py](../tests/test_formal_attack_suite.py) | 6 | 0 | 0 |
| [tests/test_formal_release_contracts.py](../tests/test_formal_release_contracts.py) | 25 | 0 | 0 |
| [tests/test_formal_release_flow.py](../tests/test_formal_release_flow.py) | 10 | 0 | 0 |
| [tests/test_formal_release_standby.py](../tests/test_formal_release_standby.py) | 11 | 0 | 0 |
| [tests/test_gate_matrix.py](../tests/test_gate_matrix.py) | 31 | 0 | 0 |
| [tests/test_gateway_release.py](../tests/test_gateway_release.py) | 6 | 0 | 0 |
| [tests/test_grpo_adaptation.py](../tests/test_grpo_adaptation.py) | 4 | 0 | 0 |
| [tests/test_human_veto_flow.py](../tests/test_human_veto_flow.py) | 3 | 0 | 0 |
| [tests/test_labor_product_draft.py](../tests/test_labor_product_draft.py) | 3 | 0 | 0 |
| [tests/test_launcher_shutdown.py](../tests/test_launcher_shutdown.py) | 0 | 1 | 0 |
| [tests/test_legal_asset_import.py](../tests/test_legal_asset_import.py) | 9 | 0 | 0 |
| [tests/test_legal_citation_strict.py](../tests/test_legal_citation_strict.py) | 9 | 0 | 0 |
| [tests/test_legal_evidence.py](../tests/test_legal_evidence.py) | 3 | 0 | 0 |
| [tests/test_legal_review.py](../tests/test_legal_review.py) | 3 | 0 | 0 |
| [tests/test_local_cloud_trial.py](../tests/test_local_cloud_trial.py) | 5 | 0 | 0 |
| [tests/test_local_rules_v1.py](../tests/test_local_rules_v1.py) | 8 | 0 | 0 |
| [tests/test_materials.py](../tests/test_materials.py) | 12 | 2 | 0 |
| [tests/test_migration_v2.py](../tests/test_migration_v2.py) | 8 | 0 | 0 |
| [tests/test_orchestrator.py](../tests/test_orchestrator.py) | 12 | 0 | 0 |
| [tests/test_outbound_gate.py](../tests/test_outbound_gate.py) | 8 | 0 | 0 |
| [tests/test_output_checks.py](../tests/test_output_checks.py) | 11 | 0 | 0 |
| [tests/test_overtime_disclosure.py](../tests/test_overtime_disclosure.py) | 18 | 0 | 0 |
| [tests/test_pack_integrity.py](../tests/test_pack_integrity.py) | 1 | 0 | 0 |
| [tests/test_package_bundle.py](../tests/test_package_bundle.py) | 6 | 0 | 0 |
| [tests/test_package_controller.py](../tests/test_package_controller.py) | 11 | 0 | 0 |
| [tests/test_platform.py](../tests/test_platform.py) | 4 | 0 | 0 |
| [tests/test_policy_engineering.py](../tests/test_policy_engineering.py) | 9 | 0 | 0 |
| [tests/test_product_multi_case_flow.py](../tests/test_product_multi_case_flow.py) | 1 | 0 | 0 |
| [tests/test_redteam_workflow.py](../tests/test_redteam_workflow.py) | 13 | 0 | 0 |
| [tests/test_release_build.py](../tests/test_release_build.py) | 23 | 0 | 0 |
| [tests/test_release_intake_context_api.py](../tests/test_release_intake_context_api.py) | 3 | 0 | 0 |
| [tests/test_release_policy_api.py](../tests/test_release_policy_api.py) | 1 | 0 | 0 |
| [tests/test_release_service_integration.py](../tests/test_release_service_integration.py) | 10 | 0 | 0 |
| [tests/test_restore_reauthorization.py](../tests/test_restore_reauthorization.py) | 4 | 0 | 0 |
| [tests/test_result_envelope.py](../tests/test_result_envelope.py) | 5 | 0 | 0 |
| [tests/test_retention.py](../tests/test_retention.py) | 9 | 0 | 0 |
| [tests/test_return_pipeline.py](../tests/test_return_pipeline.py) | 5 | 0 | 0 |
| [tests/test_review_engine.py](../tests/test_review_engine.py) | 6 | 0 | 0 |
| [tests/test_review_races.py](../tests/test_review_races.py) | 3 | 0 | 0 |
| [tests/test_runtime_identity.py](../tests/test_runtime_identity.py) | 4 | 0 | 0 |
| [tests/test_runtime_pack.py](../tests/test_runtime_pack.py) | 25 | 0 | 0 |
| [tests/test_runtime_pack_workflow.py](../tests/test_runtime_pack_workflow.py) | 7 | 0 | 0 |
| [tests/test_runtime_profiles.py](../tests/test_runtime_profiles.py) | 13 | 1 | 0 |
| [tests/test_submission_assets.py](../tests/test_submission_assets.py) | 12 | 0 | 0 |
| [tests/test_support_registry.py](../tests/test_support_registry.py) | 8 | 0 | 0 |
| [tests/test_synthetic_scope.py](../tests/test_synthetic_scope.py) | 7 | 0 | 0 |
| [tests/test_three_layer_execution.py](../tests/test_three_layer_execution.py) | 4 | 0 | 0 |
| [tests/test_upgrade_approval.py](../tests/test_upgrade_approval.py) | 3 | 0 | 0 |
| [tests/test_v2.py](../tests/test_v2.py) | 25 | 0 | 0 |
| [tests/test_windows_maintenance_contract.py](../tests/test_windows_maintenance_contract.py) | 5 | 0 | 0 |
| [tests/test_workflow.py](../tests/test_workflow.py) | 23 | 0 | 0 |
| **合计** | **749** | **5** | **0** |

## 附录 B：浏览器逐项结果

以下 20 项均通过。耗时为单项日志值；测试包含独立合成夹具，production 表单绑定用例使用显式测试 stub。

| 组别 / 视口项目 | 用例 | 耗时 |
| --- | --- | ---: |
| desktop / desktop-1280 | e2e/recording-import.spec.ts:5:1 › administrator can review both imported local cases without changing accounts | 6.7s |
| desktop / desktop-1280 | e2e/recording-import.spec.ts:45:1 › recording Word can be imported from list and material panel | 1.8s |
| desktop / desktop-1280 | e2e/recording-import.spec.ts:94:1 › all three recording cases expose material-specific local tools | 3.7s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:43:1 › human veto is visibly paused by a technical reviewer and rejected by legal | 4.0s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:121:1 › incomplete materials can be actively stopped before legal review without any dispatch | 1.7s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:196:1 › synthetic case: disclosure, explicit approval, dispatch and source-linked result | 7.2s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:283:1 › restoration empty state before dispatch | 958ms |
| desktop / desktop-1280 | e2e/workbench.spec.ts:293:1 › demo keeps independent attack tools marked as planned | 1.1s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:301:1 › combination clues block approval without faking a risk pass | 1.2s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:347:1 › dashboard layout at desktop and mobile, capabilities remain honest | 1.0s |
| desktop / desktop-1280 | e2e/workbench.spec.ts:379:1 › dialog keyboard behavior and accessible control names | 644ms |
| desktop / desktop-1280 | e2e/workbench.spec.ts:401:1 › five-viewport structural visual baseline | 733ms |
| production / desktop-1440 | e2e/formal-intake.spec.ts:4:1 › production formal intake stays bound and unapproved when authoritative build evidence is missing | 4.5s |
| production / desktop-1440 | e2e/formal-intake.spec.ts:40:1 › production formal intake uses exact actor, pending default and frozen G1 bindings with a test stub | 6.7s |
| production / desktop-1440 | e2e/workbench.spec.ts:156:1 › technical reviewer can prepare a production rule draft but cannot publish or send | 1.2s |
| production / desktop-1440 | e2e/workbench.spec.ts:318:1 › formal DOCX upload, manual fact entry and formal outbound block | 3.3s |
| responsive / desktop-1440 | e2e/workbench.spec.ts:401:1 › five-viewport structural visual baseline | 1.1s |
| responsive / compact-900 | e2e/workbench.spec.ts:401:1 › five-viewport structural visual baseline | 1.1s |
| responsive / tablet-650 | e2e/workbench.spec.ts:401:1 › five-viewport structural visual baseline | 1.2s |
| responsive / mobile-390 | e2e/workbench.spec.ts:401:1 › five-viewport structural visual baseline | 1.2s |

附录原始数据：[Python 模块汇总](../.data/deployment-evaluation/20261101-211139/pytest-by-file.json)、[浏览器汇总](../.data/deployment-evaluation/20261101-211139/browser-tests.json)。
