# 案隐盾本机现状与完成清单

盘点日期：**2026-09-14**（文首为现役；其下 09-12 / 09-11 细表只追溯，过期句以文首为准）。对象是本机仓库 `E:\LexAegis`，不是远端 CI，也不是正式发行结论。

版本号：**V1.0**（`1.0.0`）。已推送 `main` 停在 `5de4113`；工作树有未提交 D 路径、交付包与改号。非正式发行。**正式案件外发保持阻断。**

读法：`[x]` 表示本机或仓库里已经有对应产物；`[ ]` 表示尚未完成、未验收或不得主张完成。五类事实分开写：代码、本机资产、运行证据、法学发布、攻击结论。不要把某一栏的勾选合成「已经安全」或「可以对外发」。

法学文件只走 [legal/README.md](legal/README.md)。

---

## 一、现在先看这里

| 项 | 现在 |
| --- | --- |
| 10 案 | 层 A 评估完成。**0 案真实发送**。D 走一遍 = evaluate，不是 HTTP |
| 隔离 | Compose 五项探测可在宿主机为真。探测 ≠ 本请求收据，native 不能自证隔离 |
| 攻击 | 隔离栈已实跑工程基线。阳性对照 `identity=succeeded`。空辅助不是四绿。合成正式案**不是**四类 `resisted` |
| 包 | 仓库 `2.0.0-draft.3` 仍 draft，`dispatch_allowed=false` |
| 法学 | 规则正文已定稿并归入 `docs/legal/`。未签署、未 `reviewed`、未发送 |
| 测试 | 2026-09-14 pytest **283 过 / 3 跳过**。e2e 未重跑 |
| LA-001 交付包 | `.data/outbound_packets/LA001_D_外发交付包_20260914/`。`gate_status` 十门均非 `pass`。不要提交 zip |

下面从「二、本机快照」起仍是 09-11/09-12 细表。其中「Docker 未开 / 攻击未跑 / 指南未冻 / 后 7 案未做 / 包 draft.1 / HEAD 60cdc73」已经过期，以本节为准。

---

## 二、本机快照

| 项 | 本机事实 |
| --- | --- |
| 操作系统 | Windows 10/11 AMD64（`win32 10.0.26200`） |
| Python / venv | 3.13.2，`.venv` 已存在 |
| Node / pnpm | Node v25.9.0，pnpm 12.3.4（README 写的是 Node 22+ / pnpm 11） |
| 前端构建产物 | `frontend/node_modules` 与 `frontend/dist` 都在 |
| GPU | NVIDIA GeForce RTX 4060 Laptop，8188 MiB，驱动 566.24 |
| Docker | 客户端 29.7.2 + Compose v5.5.0；**Docker Desktop 引擎未连接** |
| Git | `main` 跟踪 `origin/main`，HEAD `60cdc73` |
| `.env` | 存在且未入库。网关密钥、本地口令、主/备云端密钥、边侧路径均已填写 |
| 部署模式 | `LEX_DEPLOYMENT_MODE=native`（native **不能**自证隔离） |
| 工作台 / 网关 / 边侧 | `8765` `8766` `8080` 及验收端口全部空闲；当前没有在跑的 `lexaegis start` |
| 边侧权重 | `models/MiniCPM5-2B-Q4_K_M.gguf` 约 1.56 GB 已在本机（gitignore） |
| llama-server | `.artifacts/llama-server/llama-server.exe` 及 CUDA 12 运行库已在本机 |
| 残留下载 | `models/.cache` 里有未完成的 Qwen3-8B GGUF，**不是**现行生产方案 |
| OCR 配置 | `.env` 写了 `LEX_OCR_ENABLED=1`、`LEX_OCR_PROVIDER=paddle`、`LEX_OCR_MODELS_READY=1` |
| OCR 库 | venv **未装** `paddleocr` / `rapidocr` / `onnxruntime`。声明与安装不一致 |
| 转写 | `.env` 无 `LEX_WHISPER_*`；无 `ffmpeg`、无 `whisper-cli`、无 `ggml-large-v3-turbo.bin` |
| 评测实验库 | venv 已有 `numpy`、`sklearn` |
| 合成例子 | `examples/synthetic_labor.docx`、`examples/synthetic_scan.pdf`（目录本身 gitignore） |
| 仓库评测集 | 仅 `data/mock_labor_v1`（8 条全合成），`dispatch_allowed=false` |
| 半合成脚手架 | `.data/semi_labor_v1` 目录在，当前未见完整材料；未进 `data/catalog.json` |
| 本机真案整理 | `.data/real_cases/`：LA-001–005、SMP-001–005，状态均为 `sourced`，`dispatch_allowed=false` |
| 试点跑前准备 | `.data/real_cases/runs/pilot-2026-09/`（gitignore）。准备已完成；CAL-1/2/3 已做 Path A/B 与云端评估。Path A 抽取三案均失败（JSON 截断）。Path B 评估均为 blocked / 批准 409。未发送 |
| 进料副本 | `data/真实案件/` 被 gitignore，不要拷回主库或提交 |
| 旧 wheel | `.artifacts/wheel/lexaegis-0.2.0-py3-none-any.whl`（归档旧号，未重打 `lexaegis-1.0.0`） |

`.env` 只确认「已设置」，本文不写密钥、口令或具体云端工作空间主机名。

---

## 三、代码层：已完成（已推送 `60cdc73`）

下列已在代码里（工程落地，不是法学或攻击验收）。`origin/main` 在改号前提交的仍可能显示旧号。

### 3.1 产品骨架与工作台

- [x] 模块化单体 + 独立外发网关：API `8765`、网关 `8766`、单进程 worker
- [x] 本地会话、具名角色（`admin` / `case_operator` / `legal_reviewer` / `approver`）、写操作 Origin/Host 校验
- [x] 四步工作台：事实与证据 → 逐项披露 → 风险冻结/审批 → 摘要回链
- [x] 治理四页：法学规则中心、服务商治理、隔离实验、本地用户
- [x] 运行配置页：边侧 URL、主/备回显；云端密钥不进 API/worker
- [x] 三色系（林绿 / 墨青 / 缃褐）× 浅/深，语义色不与品牌色合并
- [x] 三个固定合成演示案；01 可走通模拟发送；02 组合线索风险批准 409
- [x] CLI：`start` `doctor` `backup` `restore` `check-isolation` `edge` `dataset` `bench`
- [x] Compose 拓扑：api / worker / gateway，以及 `edge` `redteam` `benchmark` profile；宿主机默认 `127.0.0.1:38765`

### 3.2 契约、门禁与外发控制

- [x] V2 契约：`DomainPackV2`、`TaskDefinitionV2`、`DocumentIRV2`、稳定 `MappingEntry`、`ClaimArtifactV2`
- [x] 正式外发只走 `[[LEX:P0001]]` 线 token；mapping / 原文 / anchors / `local_text` 不进 V2 wire 或网关账本
- [x] 状态机：`draft → review/blocked → approved → queued → sending → complete/unknown/failed`
- [x] 发送与队列同事务；网关先记 sending 再调用；超时不主动重发；reconcile 只读已有账本
- [x] 主备分档审核：未审核备用不进批准目标；仅确认请求未离开本地才允许切已批准备用
- [x] 主方已收包后的超时 / 401 / 崩溃记可能披露，不自动换模、不自动重发
- [x] 已有 token 的断流或坏 JSON 记 `unknown`
- [x] 发送时重验冻结依赖与有效期（规则退役即使哈希未变也拒发）
- [x] 正式门禁失败关闭：未发布规则、服务商未审完、四类攻击未全部 `resisted`、隔离未验证等
- [x] 能力面板区分未验证 / 可能披露 / 工程基线；`formal_dispatch=blocked`
- [x] 跨轮工程预算（默认 5 万字 / 20 条），超限评估阻断，不写入法学包
- [x] `ProcessingBasis` 与 `ConfidentialityRecord` 已建模；必要性 / 可处理性 / 残余风险不合成安全分
- [x] 律师法条号映射：须用 2026-09-01 文本第 41 条（旧第 38 条）

### 3.3 材料、任务与复原

- [x] DOCX / 文本 PDF / 扫描 PDF / PNG / JPEG 解析契约
- [x] `ocr` / `scan` 未复核不得抽取或批准
- [x] 事实并存矛盾陈述，不自动覆盖；披露决定与规则硬约束分离
- [x] 本地确定性任务：`timeline`、`evidence_inventory`、`issue_extraction`（六字段分桶，非法学结论）
- [x] 正式案默认 `fact_summary` 为本地拼装（`transport=local`）；`mock` 仅演示；`cloud` 仍走网关且门禁关闭
- [x] 加班核对有界披露候选（`disclosure.py`），劳动争议 V2 包内为**待审草稿**
- [x] 云端回写 `unused_fact_ids` / `gaps` → 案件 `followups`，不自动二次调边侧
- [x] 默认导出 `cloud_view`；`local_review_bundle` 需结果确认 + 15 分钟具名二次确认

### 3.4 边侧、云端与评测骨架

- [x] 边侧只做正式案事实抽取；OpenAI 兼容 `/v1/models` + `/v1/chat/completions` + `json_schema`
- [x] 现行唯一生产声明：MiniCPM5-2B Q4_K_M，别名 `edge-small`，`role=fact_extraction_only`
- [x] 云端双槽适配：DeepSeek V4 Flash 主 + 百炼 Qwen3.8-Flash 备；思考关闭；流式只在网关拼 JSON
- [x] `dataset`：list / validate / show / generate-mock / freeze / run / compare / probe-edge / promote-semi
- [x] 仓库语料 `mock_labor` 8 条全合成，6:2 划分，法律标注 pending
- [x] 隔离实验：DP/RDP、投影、MIA 输入门槛；无输入时 Ianvs 只报 `input_required`
- [x] 四类攻击协议与工程基线执行器（空辅助不得四类 `resisted`；已知泄漏阳性对照必须 identity=`succeeded`）

### 3.5 案由包（仓库内无一 `published`）

| 包 | 版本 / 状态 | 外发 |
| --- | --- | --- |
| `packs/labor_demo.json` | v1 `0.1.0-demo` / `demo` | 仅演示 |
| `packs/labor_v2_draft.json` | v2 `2.0.0-draft.1` / `draft` | `dispatch_allowed=false` |
| `packs/contract_test.json` | v1 `draft` 测试夹具 | 非正式 |

隔离库里曾经 publish 过试点包 `2.0.0-pilot.1`，**仓库草稿并未改成 published**，不能当成正式开通。

---

## 四、代码层：工作树未提交（已写、未入库）

这些在本机文件里，**尚未 commit**。收集测试现为 **242** 项（文档记录的上次通过是 216 过 / 1 跳过）。本轮没有重跑 pytest / e2e。

- [x] 代码已写：`lexaegis/gpu_runtime.py`、`gpu_aux.py` — GPU 阶段锁；OCR/转写前卸载 2B，抽取时再加载；空闲卸载默认 300s
- [x] 代码已写：`lexaegis/transcribe.py` — 本机 FFmpeg + whisper.cpp，禁止远程 URL；空转写须人工
- [x] 代码已写：`parsing.py` — XLSX/CSV 单元格锚点；音视频走转写；默认 OCR extra 改为 RapidOCR，Paddle 仅 CPU 回滚
- [x] 代码已写：`edge_runtime.py` 扩成可探测/可拉起 llama-server（`--jinja`、32K、FlashAttn、`--n-gpu-layers 99`）
- [x] 代码已写：`diagnostics.py` 把 `ocr` / `whisper` 列为可选 doctor 项
- [x] 代码已写：工作台上传接受表格与音视频；`ocr`/`scan`/`transcript` 可「确认本块」
- [x] 代码已写：`tests/test_materials.py` 及若干回归补丁
- [x] 代码已写：法学交接稿生成脚本与两份 DOCX（见第六节）
- [ ] 未提交到 git
- [ ] 未用当前工作树重跑 `python -m pytest -q`
- [ ] 未重跑 Playwright / `pnpm walk:ui`
- [ ] RapidOCR + CUDA 路径在本机未装库，谈不上冒烟
- [ ] whisper.cpp 路径在本机无二进制、无权重

---

## 五、本机运行与验证：已完成 / 未完成

### 5.1 本机已经取得过的证据（2026-09-08/09/10，改号后未整套重跑）

- [x] 2026-09-09：`pytest` 216 过 / 1 跳过（当时基线；现工作树已变成 242 项待跑）
- [x] `dataset validate`：`ok=true`，catalog 仅 `mock_labor` 1.0.0
- [x] 2026-09-08：`tsc --noEmit` 与 `pnpm build`（当时 1588 模块）
- [x] wheel 检查通过，产物仍是 `lexaegis-0.2.0` 文件名
- [x] Ianvs 无输入：`input_required`，`production_dispatch=false`
- [x] `dataset compare` 五组对照写出分子/分母；法律可用性 / 隐私降低率 / AURA **未评分**
- [x] `desktop-1280` Playwright 6 项（不含五视口）
- [x] 三色系六态手工点过
- [x] 隔离栈点过「本地生成争点候选」：6 个字段桶，`provenance=local_deterministic`
- [x] MiniCPM `probe-edge`：工程五项 8/8，**无法学分**
- [x] native 演示 01 mock 发送完成（`provenance=simulation`）
- [x] 正式合成 TXT 解析 + MiniCPM 抽取作业完成（契约冒烟，无法学分）
- [x] 人工事实后真云：批准/发送 **409**
- [x] 本机 PaddleOCR CPU 对 `synthetic_scan.pdf` 冒烟过（3 块 `kind=ocr`）；**无识别率**。当前 venv 已卸/未装该库
- [x] 2026-09-08 与 2026-09-10：Compose `check-isolation` 五项 true，并写入隔离卷
- [x] 2026-09-10：10 案迁入隔离库后 evaluate 仍 409（攻击 `uncertain`）

### 5.2 本机此刻未就绪或未复验

- [ ] `lexaegis start` 三个服务未在运行
- [ ] 边侧 `127.0.0.1:8080` 未监听（权重和二进制在磁盘上，进程没起）
- [ ] Docker 引擎未开，不能主张当前隔离拓扑仍在跑
- [ ] 工作树 242 项测试未跑
- [ ] 五视口 Playwright 本轮未跑
- [ ] `pnpm walk:ui` 未进 CI，本轮也未重跑
- [ ] 远端 GitHub Actions：历史记录为 `startup_failure` / 本轮不跑，**不能写成已通过**
- [ ] V1.0（`1.0.0`）wheel 未重打
- [ ] OCR：`.env` 声称 paddle 就绪，venv 无库 → doctor 构造探测预期失败或不可用
- [ ] RapidOCR + ONNX Runtime CUDA：未安装
- [ ] whisper.cpp + FFmpeg + `large-v3-turbo`：未安装
- [ ] 宿主机 Compose 发布：历史上出现过 `invalid IP:0`；2026-09-10 曾落到 `127.0.0.1:38765`，**此刻引擎未开，不能复述为当前可达**
- [ ] 真实云端 API 成功外发：**从未有过**
- [ ] 边侧 32K / FlashAttn / 8GB 预算：是部署方案，不是本轮实测报告

---

## 六、法学与试点材料：已准备 / 待法学填写

计算机侧已交出交接稿，**不等于法学已审完**。吃不准应填「未知」或「暂不开放」，不能留空充作已审。

### 6.1 已产出的交接物

- [x] 研究备忘：`docs/legal/案隐盾_法学与计算机优化研究_2026-09-09.md`（对照当时提交 `9de4eff`；其后发送控制已部分落地）
- [x] 计算机证据包：`docs/legal/LEX-CS-EVID-2026-09-10-01.docx`（脚本 `scripts/make_legal_evidence_docx.py`）
- [x] 法学须填清单：`docs/legal/LEX-LG-REQ-2026-09-10-01.docx`（脚本 `scripts/make_legal_side_brief_docx.py`）
- [x] 本机真案整理树与 `catalog.json`（gitignore，`contains_real_case_content=true`）
- [x] 每案 `case.json` + `raw/originals.json`；LA 系列带标注 DOCX 与敏感性清单；SMP 系列有 `.doc` 及部分 `working/*.docx`
- [x] 试点 `pilot-2026-09` 跑前准备（见该目录 `PREP_STATUS.md` / `manifest.json`）。法学授权表仍为空；仓库草稿包未发布

### 6.2 法学仍须给出（未完成）

- [ ] 合成材料在本项目中的用途口径（研发 / 教学 / 截图 / 对外交付）
- [ ] 四条处理路径逐条判断：本地整理、本地确定性任务、边侧抽取、可选云端摘要
- [ ] 处理依据落到人和行为：`ProcessingBasis` 不能只写原则句
- [ ] 主备服务商分表：角色、合同/条款快照、留存、训练、地区、有效期；查不到写未知
- [ ] 保存、访问、删除要求（影响评估与处理记录至少三年 ≠ 原始案件全量保存三年）
- [ ] **先冻结一个子场景**（建议：核对加班）；不要同时审四类任务
- [ ] 对着 `labor_v2_draft` 裁定条件规则、精度、禁止词与组合线索；附法源条号与文本日期
- [ ] 输出对错标准：主张写成认定、主体对调、证据挂错人、期限边界等，区分阻断 / 必须改 / 建议改
- [ ] 演示 01/02/03 验收表（01 是模拟拼接，不是模型生成）
- [ ] 标注规范与 10 案双人校准；第三人仲裁
- [ ] 正式发布签署：`legal_status=reviewed`、`dispatch_allowed`、服务商 `reviewed`、攻击者模型与阈值
- [ ] 真实材料组织授权与试点范围（本机已有材料 ≠ 已授权外发或入库）

当前不要预填「允许外发」。工程基线红队 `resisted` 不是法学攻击结论。

---

## 七、待完成总表（按阻塞关系）

### P0 · 把本机工作树收成可复验状态

- [ ] 决定 OCR：要么按文档改回 RapidOCR 并安装 CUDA 栈，要么安装 CPU Paddle 并与 `.env` 对齐；不要「声明就绪但库不在」
- [ ] 提交或搁置 GPU/表格/转写这一批；提交前跑 `python -m pytest -q`
- [ ] 需要演示时再 `lexaegis start`，用 **http://127.0.0.1:8765**，不要用 `localhost`
- [ ] 需要抽取时再 `lexaegis edge --start`；不要把磁盘上有 GGUF 写成服务已通
- [ ] 需要隔离主张时先开 Docker Desktop，再 `check-isolation`；native 启动不写 `isolation_verified`

### P1 · 工程后续（文档已点名、本批未修）

- [ ] e2e 覆盖演示 03 与治理四页，并进入 CI
- [ ] bootstrap 仍发 v1 `TASKS`；工作台 `task_definitions || tasks` 回退要保留到契约切干净
- [ ] `lexaegis.tasks` entry point **未**在 `pyproject.toml` 声明，仓库无任务插件
- [ ] `App.tsx` 仍未拆文件
- [ ] `semi_labor_v1` 标注完成后才 `promote-semi`；未标注完整材料不进主库
- [ ] 重打并核验 `lexaegis-1.0.0` wheel
- [ ] 取得 GitHub Actions 三平台 / 五视口 / 双架构的真实远端结果（现在不能填绿）
- [ ] 清理或明确放弃 `models/.cache` 里未完成的 Qwen3-8B，避免当成第二套生产边侧

### P2 · 方法与产品深化（研究备忘，非正式发行条件）

- [ ] 法律关系保真的有界披露搜索（少量合法候选 + 硬约束淘汰）
- [ ] 跨轮由字符预算升级为按接收方的历史信息组合检测
- [ ] 校核从「引用存在 / 数字出现」升级到主体、否定、主张/认定、证据归属
- [ ] 标注数据按模板族切分后的五组方法对照（查找替换 / 一致假名 / 任务矩阵 / 通用薄基线 / 法律约束）

### 打开正式外发之前（缺一不可，现在全是空）

- [ ] 法学发布劳动争议 V2：必要性矩阵、条件规则、法源版本、具名签署；`dispatch_allowed` 才能谈
- [ ] 主、备服务商均 `reviewed` 且未过期；合同/评估/留存/训练/地区写清
- [ ] 四类攻击达到**法学承认**的 `resisted`（不是空辅助工程基线）
- [ ] 目标环境隔离验收：防火墙与镜像供应链，不只是容器内探测
- [ ] 真实材料授权、试点范围、双人标注/仲裁
- [ ] 至少一条经门禁允许的真实云端外发成功记录（现在没有）
- [ ] 五类风险信号权重冻结

在上述补齐之前，系统继续失败关闭。Compose 隔离探测通过 **不能** 替代法学条件。

---

## 八、不要写成已完成的句子

- 「V1.0 已正式发行」——现为非正式发行；正式外发保持阻断
- 「正式外发已开通」——`formal_dispatch=blocked`
- 「四类攻击已通过」——隔离栈已实跑工程基线，不是法学 `resisted`
- 「已经匿名化」——边侧保留身份映射，不是匿名化
- 「律师批准即处理合法」——批准是发送控制，不是个法第 13 条依据
- 「争点提取能识别法律关系」——只是六类字段分桶
- 「probe-edge 8/8 证明抽取可用」——工程契约冒烟，无法学分
- 「Paddle/RapidOCR/whisper 已验收」——最多有过合成扫描冒烟；精度、转写准确率均未验收
- 「本机已隔离」——native 不能自证；Compose 五项探测通过 ≠ 防火墙/供应链审计
- 「CI 绿了」——远端未取得成功运行
- 「10 份真案已可外发/已入库」——本机整理为 `sourced`，评测主库禁止真实案件，外发未授权

---

## 九、建议的下一步（约 15–40 分钟可核对）

1. 打开 [legal/README.md](legal/README.md)，只读「现在读」那 5 个文件。
2. 缺合同引用 / 签约主体全称 / 服务商删除渠道则不要标 `reviewed`，也不要发送。
3. 需要对代码时再跑 `python -m pytest -q`（上次记录 216 过 / 1 跳过，约 3 分钟）。
4. 看界面：`lexaegis start` → http://127.0.0.1:8765 → 演示 01；正式案仍应 409。
5. OCR / whisper 声明与库不一致时，先改配置或补装，不要假装 available。

现行规格入口仍是 [PROJECT_MAP.md](PROJECT_MAP.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[VALIDATION.md](VALIDATION.md)、[PROVENANCE.md](PROVENANCE.md)。本文不替代 VALIDATION 的逐条运行证据，也不构成发布或外发许可。
