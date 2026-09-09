# 架构与接口约定

LexAegis 0.9.0 待发布（`0.9.0rc0`）使用模块化单体和独立外发网关。所有敏感原文留在边侧；云端仅负责经过批准的假名化事实摘要生成。劳动争议 V2 包仍为 `draft`：没有经审核服务商、四类真实攻击 `resisted`、隔离验收与具名审批时，正式外发保持失败关闭。这不是缺省“安全”。当前四类攻击执行器是工程基线，不是正式攻击结论，也不能作为法学背书。本号不是正式发行版。

## 0.9 待发布范围

- V2 契约：`DomainPackV2`、`TaskDefinitionV2`、`DocumentIRV2`、稳定 `MappingEntry`、`ClaimArtifactV2`、服务商、审批、攻击协议。
- v1 包只作为 draft/demo 读取；V2 包按生命周期冻结哈希，同版本不能覆盖。
- 正式案件外发只使用 `[[LEX:P0001]]` 线 token；mapping、原文、anchors 与 `local_text` 不进入 V2 wire payload 或网关账本。
- 确定性 PII 坐标、重叠合并、敏感性与冻结权重风险信号；不自动作法律结论。
- `fact_summary` 走通用任务定义：正式案默认 `transport=local`，在已批准披露文本上确定性拼 claims，不调用边侧或云端模型；`mock` 仅演示；`cloud` 仍走网关双槽且正式门禁失败关闭。`timeline`、`evidence_inventory` 与 `issue_extraction` 可本地确定性执行；争点提取只按字段分组候选，非法学结论，不调用模型。云端回写的未使用事实与缺口写入案件 `followups`，可忽略或据此创建后续披露，不自动二次调用边侧模型。
- 默认导出 `cloud_view`；含身份与锚点的 `local_review_bundle` 要求结果确认及具名二次确认。
- 跨平台 CLI：`lexaegis start|doctor|backup|restore|check-isolation`；Compose 提供 native/isolated/edge/benchmark/redteam 拓扑。

历史计划与共识见 [docs/archive](archive/README.md)。验证证据见 [VALIDATION.md](VALIDATION.md)。

## 代码组织

| 位置 | 职责 |
| --- | --- |
| `frontend/` | React 工作台、事实和披露编辑、审批、结果回链、运行配置 |
| `lexaegis/api.py` | 会话、HTTP API、材料上传和页面渲染、SSE |
| `lexaegis/service.py` | 案件版本、事实与任务、审批及发送状态转换 |
| `lexaegis/storage.py` | SQLAlchemy 聚合存储、SQLite WAL、Alembic 迁移 |
| `lexaegis/parsing.py` | DOCX、PDF、扫描识别和可选本地 OCR |
| `lexaegis/policy.py` | 标识检测、映射、披露变换、门禁及结果检查 |
| `lexaegis/disclosure.py` | 加班核对的条件规则、有界披露候选与分别判定（待审草稿） |
| `lexaegis/providers.py` | 边侧 `EdgeClient`；云端调用由网关 `DualSlotProvider` 流式装配 |
| `lexaegis/cloud.py` | DeepSeek 主 / 百炼备双槽、网关内流式拼 JSON |
| `lexaegis/gateway.py` | 签名核验、目标白名单、独立请求账本与实际调用 |
| `lexaegis/worker.py` | 单进程队列、解析、提取、发送与恢复 |
| `lexaegis/detection.py` | 坐标化 PII、敏感性与冻结权重风险信号 |
| `lexaegis/governance.py` | 服务商、协议、逐项合规检查和正式门禁 |
| `lexaegis/task_engine.py` | V2 任务定义与本地确定性任务（目前只内置；`lexaegis.tasks` entry point 未在 pyproject 声明） |
| `lexaegis/experiments.py` | 隔离实验的 DP/RDP、掩码、投影和 MIA 输入门槛 |
| `lexaegis/redteam.py` | 无原件/映射/真值访问的四类攻击接口（工程基线执行器） |
| `packs/` | 版本化声明式案由知识包 |

业务聚合保存在 `records(id, kind, scope, body)` 中。本地会话绑定具名角色；SQLite 只支持单实例，不可置于网络共享盘。当前迁移是 `0002_v2_contracts`，从 0001 升级前生成并校验备份，失败保持旧版本。

## 数据和安全契约

- `SourceAnchor` 保存材料版本、段落/单元格或 PDF 页、归一化左上坐标，以及 OCR Provider 的稳定 id/版本。
- `DocumentIR` 保存版本、来源块、置信度、警告与复核状态。OCR 低质量、缺失、失败都不会计为完成复核。
- `Fact` 保存字段、陈述、来源列表、提取来源和确认状态。加班核对可另存主张/否认、日性质、小时数、工资基数与证据归属。不同或矛盾陈述并存，不自动覆盖。
- `DisclosureDecision` 分离必要性、变换方式、外发状态和依据。加班核对子场景另给有界候选、保留理由、信息损失和硬约束淘汰原因。正式规则和硬性禁止不能被界面调整绕过。
- `ProcessingBasis` 与案件保密类别分开记录：必要性、可处理性、残余风险不合成安全分。律师法条号若引用须用 2026-09-01 文本第41条（旧第38条映射）。
- `DomainPack` 与 `TaskDefinition` 独立注册，任务冻结其版本。一案选择一个案由，不自动合并多案由规则。`DomainPackV2` 保存任务—字段—必要性矩阵，并可带待审的条件披露规则；草案缺矩阵时只生成 `uncertain` 保守项。劳动争议 V2 包仍为 `draft`，`dispatch_allowed=false`。
- `ApprovedRequest` 冻结模型、地址、消息、参数及材料、配置、规则、任务和累计披露版本。云端请求冻结已启用槽位（主槽；备用仅在已审核时纳入），配置页目标与批准目标同一套对象，不得用固定双槽补洞。运行时选用与逐次 Attempt 写入账本，不改 `request_hash`。审批本身不执行发送。
- 网关使用 HMAC 验证请求与具名审批，检查依赖、有效期、V2 wire contract 和目标白名单。V2 wire 顶层仍是 `{contract_version,task,facts}`；facts 项可含 `field`，禁止 `mapping` / `original_value` / `local_text` / `anchors`。
- 仅确认请求未离开本地的失败才允许切已批准备用；主方已收包后的超时、服务端错误或崩溃记为可能披露，不因无 token 自动扩接收方。JSON 不合格或断流且已有 token 记 `unknown`，不自动重发。
- 摘要按条目返回 `text/source_ids`；原文锚点和真实身份只在边侧解析。入站结果可带 `unused_fact_ids` 与 `gaps`；未使用事实 id 由边侧按外发集合减去引用计算，云端回写不一致只记 `feedback_issues`，不整单作废、不自动重发。

`TaskDefinitionV2` 使用受限 JSON Schema。本地确定性任务目前只内置在 [`lexaegis/task_engine.py`](../lexaegis/task_engine.py)；`task_engine` 会扫描 `lexaegis.tasks` entry point 的 `definition()` / `run(payload)`，但该组 **尚未在** [`pyproject.toml`](../pyproject.toml) 声明，仓库里没有已安装的任务插件。v1 `TASKS` 仍留在 [`lexaegis/registry.py`](../lexaegis/registry.py)，工作台用 `task_definitions || tasks` 回退。UI 渲染器只能从契约白名单选择，扩展不能注入前端代码。案由包只允许声明式数据。

## 主状态转换

`draft → review / blocked → approved → queued → sending → complete / unknown / failed`

尚未发送的任务可停止。内容修改回到 draft 并清除审批；材料或配置修改标记旧任务 stale。queued/sending 时拒绝案件编辑。完成任务不可重发。

发送意图与队列在同一业务事务中写入，然后由工作进程调用网关。网关先持久化 sending 再调用服务商。请求 ID 去重；超时后不主动重复调用。reconcile 只读取网关已有记录。

规则未发布、四类攻击未完成、材料未复核、事实来源失效、残留直接标识、硬性禁止或已知组合风险都会阻断。`capability` 与 `risk completion/outcome` 不能互相替代。

## 账户、服务商与复原

首次启动创建 `admin` 本地账户（scrypt + 独立盐）。管理员可建立 `case_operator`、`legal_reviewer`、`approver`。不能停用或降级最后一个管理员。审计写入具名操作者。

服务商档案修改后回到 `draft`，具名复核是独立动作。关键字段缺一不可复核。任务冻结各接收方 provider hash 与 `pack_hash`；档案过期或规则退役即使哈希未变也拒绝尚未离开发送。

复原页并列云端假名化陈述、边侧身份回填、外发支持事实和版本化原文锚点。默认导出 `cloud_view`；`local_review_bundle` 须在逐项确认后取得绑定任务版本与产物哈希的 15 分钟具名确认。

## API

- 案件与材料：`/api/v1/cases`、`/cases/{id}/documents`、`/documents/{id}/correction`、`/anchors`。
- 事实：`/cases/{id}/facts`、`/facts/{id}`、`/extract`。
- 任务：`/cases/{id}/tasks`、`/tasks/{id}/decisions/{fact}`、`evaluate`、`approve`、`send`、`stop`、`reconcile`、`attacks/run`。
- 校核：`/tasks/{id}/claims/{claim}/review`、`confirm`、`restoration`、`export?view=cloud|local`。
- 扩展与治理：`/domains`、`/task-definitions`、`/packs/import`、`validate`、`transition`、`publish`、`/providers`、`/risk-protocols`。
- 配置与状态：`/bootstrap`、`/settings`、`/capabilities`、`/cases/{id}/events`。

业务接口需要本地会话。写操作校验 Origin，Host 白名单。浏览器会话 8 小时；重启 API 后需重新登录。

## 限制

- 材料：20MB / 文件、200 页 / PDF；边侧提取单任务 5 万字；正式案可上传 TXT。跨轮外发另有工程预算（默认 5 万字 / 20 条，`LEX_DISCLOSURE_BUDGET_*` 或运行配置），超限评估阻断，不写入法学包。
- DOCX 图片、嵌入对象和脚注不保证完整提取；混合 PDF 有文字层但仍夹杂图片的页需律师核实。
- 边侧小模型仅用于正式案件事实提取。演示、规则、风险、摘要和复原不增加第二个生产调用点。
- 推理后端（CPU/GPU）由 Ollama/llama.cpp 等适配器决定；本仓库不自动下载权重。见 [MODELS.md](MODELS.md)。
- 网络隔离只在隔离部署并通过检查脚本后成立。见 [DEPLOY.md](DEPLOY.md)。

## 附录 A：隔离红队

正式任务先做确定性风险检验，生成由线协议载荷、任务版本、材料版本和累计披露版本构成的 `attack_input_hash`。Worker 只把假名化 `wire_payload`、受预算限制的既往披露和声明为攻击者可见的辅助数据发给 redteam。使用独立的 `LEX_REDTEAM_SECRET`，不得与网关 HMAC 密钥复用。

```bash
LEX_REDTEAM_SECRET=replace-with-a-separate-random-secret docker compose --profile redteam up -d
```

每类结果以 `AttackRun` 持久化。只有四类均为 `resisted` 才消除红队阻断；超时、契约错误、中断或内容变化记为 `error` 或拒绝写入。`attacks.evaluate` 把攻击器与评分器分开：攻击器只产出候选、排序、属性预测和检索证据，评分器独立对照真值或披露依据。无候选记为 `uncertain`，不得直接 `resisted`。已知泄漏的合成阳性对照必须让身份恢复为 `succeeded`。这是工程基线，不是正式攻击结论。

## 附录 B：Ianvs 隔离实验

`lexaegis bench --profile ianvs-pipl` 无输入时只报告 `input_required`，不从文本哈希构造伪向量。该 CLI 不被生产 API、worker 或 dispatch 导入。完整参数与约束见归档 [IMPLEMENTATION_V2.md](archive/IMPLEMENTATION_V2.md) 中「Ianvs 隔离实验」一节。
