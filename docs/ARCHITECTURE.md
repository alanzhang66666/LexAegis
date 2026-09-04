# 架构与接口约定

LexAegis 0.1 使用模块化单体和独立外发网关。所有敏感原文留在边侧；云端仅负责经过批准的事实摘要生成。

## 代码组织

| 位置 | 职责 |
| --- | --- |
| `frontend/` | React 工作台、事实和披露编辑、审批、结果回链、运行配置 |
| `lexaegis/api.py` | 单用户会话、HTTP API、材料上传和页面渲染、SSE |
| `lexaegis/service.py` | 案件版本、事实与任务、审批及发送状态转换 |
| `lexaegis/storage.py` | SQLAlchemy 聚合存储、SQLite WAL、Alembic 迁移 |
| `lexaegis/parsing.py` | DOCX、PDF、扫描识别和可选本地 OCR |
| `lexaegis/policy.py` | 标识检测、映射、披露变换、门禁及结果检查 |
| `lexaegis/providers.py` | 边侧和云端 HTTP 适配器，无服务商自动回退 |
| `lexaegis/gateway.py` | 签名核验、目标白名单、独立请求账本与实际调用 |
| `lexaegis/worker.py` | 单进程队列、解析、提取、发送与恢复 |
| `lexaegis/redteam.py` | 无原件/真值访问的攻击者输入占位接口 |
| `packs/` | 版本化声明式案由知识包 |

业务聚合统一保存在 `records(id, kind, scope, body)` 中，`kind/scope` 建索引。首版只有一个本地用户，以案件为 scope；需要进一步关系查询或多人写入时，迁移至显式关系表及 PostgreSQL，而不是直接共享 SQLite 文件。迁移编号保存在 `alembic_version`；当前迁移是 `0001_aggregates`。

## 数据和安全契约

- `SourceAnchor` 保存材料版本、段落/单元格或 PDF 页和归一化左上坐标。PDF 文本版目前采用页内文本联合区域；OCR 使用文本框坐标。
- `DocumentIR` 保存版本、来源块、置信度、警告与复核状态。OCR 低质量、缺失、失败都不会计为完成复核。
- `Fact` 保存字段、陈述、来源列表、提取来源和确认状态。不同或矛盾陈述并存，不自动覆盖；首版没有自动完成事实间矛盾消解。
- `DisclosureDecision` 分离必要性、变换方式、外发状态和依据。正式规则和硬性禁止不能被界面调整绕过。
- `DomainPack` 和 `TaskDefinition` 独立注册，任务冻结其版本。当前案由采用最新导入的匹配包，历史任务仍用原包；首版一案选择一个案由，不自动合并多案由规则。
- `ApprovedRequest` 冻结模型、地址、消息和参数，以及材料、配置、规则、任务和累计披露版本。审批本身不执行发送。
- 网关使用 HMAC 验证请求与审批，重新计算请求摘要，并检查有效期和目标白名单。首版明确拒绝正式案件外发；只有固定合成数据能进入演示例外。
- 摘要按条目返回 `text/source_ids`；实际原文锚点和真实身份在边侧解析。无引用、无依据数字或无原文支撑的陈述不会自动成为已核实结果。

## 主状态转换

`draft → review / blocked → approved → queued → sending → complete / unknown / failed`

尚未发送的任务可停止。内容修改回到 draft，并清除审批；材料或配置修改标记旧任务 stale。queued/sending 时拒绝案件编辑，冻结派发边界。完成任务不可重发，需创建新任务并考虑累计披露。

发送意图与队列在同一业务事务中写入，然后由工作进程调用网关。网关先持久化 sending 再调用服务商。请求 ID 在网关账本中去重；超时后不主动重复调用。reconcile 只读取网关已有记录。对外部服务无法保证数学意义上的 exactly-once。

规则未发布、四类攻击未完成、材料未复核、事实来源失效、残留直接标识、硬性禁止或已知组合风险都会阻断。`capability` 和 `risk completion/outcome` 是不同字段，不能以“接口存在”代替“检验通过”。

## API

- 案件与材料：`/api/v1/cases`、`/cases/{id}/documents`、`/documents/{id}/correction`、`/anchors`。
- 事实：`/cases/{id}/facts`、`/facts/{id}`、`/extract`。
- 任务：`/cases/{id}/tasks`、`/tasks/{id}/decisions/{fact}`、`evaluate`、`approve`、`send`、`stop`、`reconcile`。
- 校核：`/tasks/{id}/claims/{claim}/review`、`confirm`、`export`。
- 配置与状态：`/bootstrap`、`/settings`、`/capabilities`、`/cases/{id}/events`。

所有业务接口需要本地会话。写操作校验 Origin，Host 使用白名单，前端资源不请求第三方 CDN。首次访问使用本地生成口令；浏览器会话 8 小时有效，重启 API 后需重新登录。

## 限制与后续接入

- 首版材料限制：20MB / 文件、200 页 / PDF；边侧提取单任务 5 万字。暂不做跨材料自动分批云端调用。
- DOCX 的图片、嵌入对象和脚注不保证完整提取，图片证据应转换为 PDF；混合 PDF 按页检测，有文字层但仍夹杂图片的页需律师核实是否遗漏。
- 语义攻击、独立盲测评分、精细矛盾校核、OCR模型精度评测和正式规则审核尚未完成。
- 本地服务支持 CPU/GPU 的选择由适配器背后的推理服务决定；没有自动安装、下载权重或切换云端处理原文。
- 前端的“已实现”“未配置”“未实现”与真实模型验证记录分开解释。网络隔离只在隔离部署并通过检查脚本后成立。
