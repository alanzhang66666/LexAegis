# 案隐盾 LexAegis 云—边—端完整实现计划

> **历史文档（归档）。** 这是 0.2 工程实施时的计划原文，不再作为现行规格。现行实现以 [架构说明](../ARCHITECTURE.md) 为准，验证证据以 [验证报告](../VALIDATION.md) 为准。对照表见 [PLAN_STATUS-2026-09-05.md](PLAN_STATUS-2026-09-05.md)。

---

## 一、目标、边界与总体架构

### 目标

将当前 0.1 演示骨架升级为：

- 支持 Windows、macOS、Linux/类 Unix 的本地优先法律工作台。
- 支持案由包和任务能力扩展。
- 支持正式材料解析、边侧事实提取、最小披露、再识别检验、具名审批、云端摘要、本地复原和证据回链。
- 在法学方案尚未定稿时完成技术内核、算法、界面、部署和半合成验证，但继续阻断正式外发。

### 固定链路

`材料 → DocumentIR → 人工复核 → 边侧事实提取/人工录入 → 事实确认 → 披露规则 → PII与风险检测 → 四类红队 → 具名审批 → 独立网关 → 云端摘要 → 边侧复原 → 原文校核`

### 不可破坏的边界

- 正式业务中，边侧小模型只用于事实提取。
- PII 检测、披露变换、风险检验和结果复原不得增加第二个生产小模型调用点。
- 云端只接收审批后的假名化事实 JSON，不接收原文、真实身份映射或原文锚点。
- 可逆假名只能称为去标识化/假名化，不宣称已经匿名化。
- 演示案例使用固定合成事实，不调用边侧模型和真实云端。
- 未发布规则、未完成攻击、服务商条件不明、审批过期、状态不明或隔离失败均硬阻断。
- 案由包只包含声明式数据，不允许携带可执行表达式或代码。

## 二、分阶段实现

### M0：固化 0.1 基线

- 保留并独立固化当前未提交的 Windows 兼容修改，包括 UTF-8、SQLite 路径、文件锁、权限降级和进程退出。
- 以当前后端 25 项测试通过、前端生产构建通过为回归基线。
- 建立数据库升级前自动备份和恢复检查；任何迁移失败均回滚并保留旧目录。
- 修复现有依赖弃用警告，冻结可复现的 Python 和前端依赖。
- 建立第三方来源台账、许可证清单和 `NOTICE`。

### M1：多平台部署与前端基础重构

- 提供统一命令：

  - `lexaegis start`
  - `lexaegis doctor`
  - `lexaegis backup`
  - `lexaegis restore`
  - `lexaegis check-isolation`

- Python 安装包内置前端构建产物；Node.js 仅用于开发。
- 部署划分为：

  - `native`：Windows、macOS、Linux 本机运行，正式云端外发关闭。
  - `isolated`：Linux 容器或 Windows/macOS Docker Desktop；API/worker 无公网，只有 gateway 有受限出口。
  - `edge-model`：可选 Ollama、llama.cpp 或其他 OpenAI-compatible 本地服务。
  - `benchmark`：独立实验环境，不挂载正式案件数据和网关密钥。

- 生成分平台 Python 约束文件，使用环境标记排除 Windows 不支持的依赖。
- 构建 `linux/amd64`、`linux/arm64` 镜像；服务以非 root、只读文件系统和最小能力运行。
- 将当前大型 `App.tsx` 和 `style.css` 拆分为页面、业务组件、基础组件和设计 Token，先保持行为不变。

### M2：案由与任务可扩展内核

#### 案由包

建立 `DomainPackV2`，包含：

- 案由、版本、生命周期和兼容版本。
- 事实字段、字段类型和说明。
- 任务—字段—必要性矩阵。
- 直接标识模式、风险权重、禁止项和人工复核条件。
- 法源、适用日期、审核记录和风险协议。
- 配套的合成回归案例。

生命周期固定为：

`draft → pending_review → reviewed → published → retired`

正式发布时冻结内容哈希、审核人、审核时间和适用范围；同版本不得覆盖。v1 包迁移后只能保持 `draft/demo`，不得自动变为正式规则。

法学规则未定时采用保守默认：

```json
{
  "necessity": "uncertain",
  "transform": "delete",
  "status": "pending_legal_review",
  "dispatch_allowed": false
}
```

#### 任务扩展

建立 `TaskDefinitionV2`：

- 输入、输出 JSON Schema。
- 执行类型：`local_deterministic` 或 `approved_cloud`。
- 提示词模板、结果验证器、允许的传输方式和负载限制。
- 从固定白名单选择 UI 渲染器，不动态加载第三方前端代码。

数据型任务复用内置处理器；全新执行逻辑通过管理员安装的 `lexaegis.tasks` Python entry point 注册。

首批状态：

- `fact_summary`：正式迁入通用任务引擎。
- `timeline`：实现本地确定性版本，验证功能扩展能力。
- `evidence_inventory`、`issue_extraction`：保留注册项但显示未实现，不得静默执行。

验收要求：新增合成案由不修改核心代码；新增数据型任务不修改状态机；扩展自动继承版本冻结、审批、审计和失效规则。

### M3：文档、Ianvs 算法与稳定假名

#### 文档处理

- 建立解析器和 OCR Provider 接口，正式支持 DOCX、文本型 PDF、扫描 PDF；PNG/JPEG 作为可选 OCR 输入能力。
- `DocumentIRV2` 保存段落、表格、页码、坐标、置信度、材料版本和人工复核状态。
- OCR 不允许云端回退；缺少 OCR 时保留扫描页并进入人工转录。
- 校正文档生成新版本，受影响事实标记 `stale`，历史任务继续指向旧版本且不能复用审批。
- 本轮继续保持 20 MB、200 页和 5 万字提取上限，不做跨材料自动分批。

#### Ianvs 生产算法

固定参考 Ianvs PR #283 合入提交 `8150672e6c8abcecfefd1f8377e5e40b17d7ace9`，遵守 [Apache-2.0](https://github.com/kubeedge/ianvs/blob/main/LICENSE)。

选择性移植：

- `PIIDetector`：保留正则、坐标、重叠合并和类别风险；移除 spaCy/Transformer 调用，模式由案由包配置。
- `PIPLClassifier`：改为 `SensitivitySignalEvaluator`，只输出敏感类别和解释；删除自动判断能否出境的接口。
- `RiskEvaluator`：改为 `RiskSignalEngine`，保留实体、密度、上下文和组合放大；权重必须来自冻结协议。
- `ComplianceMonitor`：迁移审计、传输记录和报告结构；删除笼统的 `compliance_verified` 布尔值，改为逐项检查结果。

所有检测结果必须绑定 `SourceAnchor`；无法定位的结果只能形成警告，不能自动修改材料。

#### 稳定假名

以结构化 `MappingEntry` 替代自然语言字符串映射：

- `entity_id`
- `wire_token`，固定格式 `[[LEX:P0001]]`
- `display_alias`
- `original_value`
- `source_ids`
- `mapping_version`

外发文本只包含 `wire_token`。云端返回未知、破损或不属于支持事实的 token 时，陈述进入 `needs_review`。

### M4：端到端复原、网关与法学治理

#### 复原产物

建立 `ClaimArtifactV2`：

- `text`：云端原始陈述。
- `local_text`：边侧身份回填视图。
- `source_ids`：引用的披露事实。
- `anchors`：原文锚点及材料版本。
- `support`：实际外发的支持文本。
- `issues`：token、数字、引用和版本问题。
- `status`、复核人、复核时间。

复原顺序固定为：

1. 校验响应结构和引用。
2. 校验 token、数字、日期和披露范围。
3. 从事实展开原文锚点。
4. 在边侧按 token 回填真实身份。
5. 由律师查看原文并逐项确认。

导出分为：

- `cloud_view`：默认，只含假名化视图。
- `local_review_bundle`：含真实身份和原文回链，要求具名二次确认并记录审计。

#### 服务商治理

建立 `ProviderProfile`，记录：

- 受托人或其他个人信息处理者角色。
- 实际数据处理地区。
- 留存、训练使用、人工访问、分包商和删除机制。
- 合同、影响评估、有效期和允许任务。
- 允许的案由、字段和传输方式。

不得使用 IP 地理位置代替人工登记；任何关键字段未知即阻断。

#### 用户与审批

增加本地角色：

- `admin`
- `case_operator`
- `legal_reviewer`
- `approver`

审批绑定完整请求哈希、服务商、模型、参数、规则包、材料版本、任务版本、累计披露版本和有效期。内容或配置变化后旧审批失效。

### M5：四类红队与 Ianvs 隔离实验

#### 正式风险门禁

实现冻结式 `RiskProtocol`：

- 身份恢复。
- 候选集合缩小。
- 敏感事实推断。
- 跨轮关联。

每个协议冻结攻击者可见信息、辅助数据、查询轮数、时间预算、成功标准、阈值和随机种子。

结果统一为：

`resisted | succeeded | uncertain | error | not_run`

只有 `resisted` 能满足对应门禁；其他状态全部阻断。红队服务不得挂载原文、mapping 或真值目录。

#### Ianvs 实验算法

通过 `lexaegis bench --profile ianvs-pipl` 提供隔离研究能力：

- Gaussian DP：使用真实实验向量、L2 clipping 和可组合的 RDP 记账，删除文本哈希伪向量。
- Saliency Masking：启发式与实验模型路径分开记录，不进入正式披露链。
- JL/PCA/随机投影：冻结投影矩阵、维度、种子和输入模型哈希。
- Neighbourhood MIA、LOSS、LiRA、反演指标：只使用真实目标模型输出；不适用时返回 `not_applicable`。
- Ianvs 向量方案只作为补充对照，不替代可读事实和证据回链。

不移植原 `PrivacyPreservingLLM` 总编排，因为其中的查询路由、模拟云调用、固定指标和空基线实现与案隐盾架构不兼容。参考 [PR #282](https://github.com/kubeedge/ianvs/pull/282)、[PR #283](https://github.com/kubeedge/ianvs/pull/283) 及后续问题 [#431](https://github.com/kubeedge/ianvs/issues/431)、[#439](https://github.com/kubeedge/ianvs/issues/439)。

### M6：半合成盲测与 1.0 试点

- 建设 100 份半合成劳动争议案例；真实案件只用于结构抽象，人物与事实重新组合。
- 完成双人独立标注、第三人仲裁和 70:30 开发/盲测划分。
- 盲测前冻结数据、规则、模型、提示词、参数、攻击协议、随机种子和依赖版本。
- 核心四组保持为：

  - 原文。
  - 查找替换。
  - 一致假名化。
  - 任务驱动最小披露。

- Ianvs 的掩码、DP、降维和向量传输作为补充第五组，单独报告。
- 指标覆盖隐私风险、法律任务可用性和流程成本；成功、失败、阻断、不确定、错误和不适用样本均须报告。
- 试点先使用半合成材料；真实案件与真实云端调用另行完成组织授权、法学审核、服务商审查和部署安全验收。

## 三、公共接口与存储迁移

### 新增类型

| 类型 | 作用 |
| --- | --- |
| `DomainPackV2` | 版本化案由、字段、规则和法源 |
| `TaskDefinitionV2` | 可扩展任务契约 |
| `DetectionFinding` | 坐标化 PII 检测结果 |
| `SensitivitySignal` | 敏感类别及解释 |
| `RiskSignal` | 实体、密度、上下文和组合风险 |
| `MappingEntry` | 本地 token 与真实身份映射 |
| `ClaimArtifactV2` | 云端视图、本地复原和证据回链 |
| `RiskProtocol/AttackRun` | 冻结攻击及真实运行结果 |
| `ProviderProfile` | 服务商与数据处理条件 |
| `ApprovalV2` | 具名、限时、绑定完整请求的审批 |
| `PrivacyTransformRun` | DP、掩码和降维实验产物 |
| `ComplianceCheck` | 单项治理检查及依据 |

### API

- 保留 `/api/v1`，新增字段保持向后兼容。
- `POST /cases/{id}/tasks` 增加 `task_type`、`pack_id`、`transport`。
- 新增 `/domains`、`/task-definitions`。
- 新增 `/packs/import`、`/packs/{id}/validate`、`/packs/{id}/publish`。
- 新增 `/providers`、`/risk-protocols`。
- 新增 `/tasks/{id}/restoration`。
- `/tasks/{id}/export?view=cloud|local`，默认 `cloud`。
- `/capabilities` 分别报告技术实现、运行配置、实际验证和法学发布状态。
- Ianvs 实验仅通过本地 CLI/离线报告使用，不暴露生产 dispatch。

### 云端线协议

请求只包含版本化任务和假名化事实：

```json
{
  "contract_version": 2,
  "task": {"id": "fact_summary", "version": "2.0"},
  "facts": [{"id": "fact_x", "text": "[[LEX:P0001]]于……"}]
}
```

响应固定为：

```json
{
  "claims": [{"text": "[[LEX:P0001]]于……", "source_ids": ["fact_x"]}]
}
```

mapping、原文、anchors 和 `local_text` 永不进入线协议或 gateway 账本。

### 存储

- 对现有 aggregate store 增加 schema 版本和迁移记录。
- 历史任务、审批、请求和产物不重写，只通过兼容投影读取。
- 迁移前强制生成校验备份，迁移在单事务内执行。
- SQLite 继续用于单实例，不允许通过网络文件系统共享。
- 多组织采用独立实例、密钥、卷和网关，不建设共享 SaaS 多租户。

## 四、前端设计与交互

### 设计来源

基于 [awesome-design-md](https://github.com/HU-UH/awesome-design-md) 编写案隐盾原创 `DESIGN.md`。该仓库采用 [MIT 许可证](https://github.com/HU-UH/awesome-design-md/blob/main/LICENSE)，其中品牌设计属于非官方提取，只作设计参考。

- [Notion](https://github.com/HU-UH/awesome-design-md/blob/main/design-md/notion/DESIGN.md)：长文阅读、暖色中性背景和轻边框。
- [Linear](https://github.com/HU-UH/awesome-design-md/blob/main/design-md/linear.app/DESIGN.md)：高密度状态、流程导航和工具栏。
- [Stripe](https://github.com/HU-UH/awesome-design-md/blob/main/design-md/stripe/DESIGN.md)：表单焦点、数据层级和克制卡片。
- IBM：借鉴企业信息架构和可访问性，不复制品牌视觉。

不复制品牌 Logo、专用字体、插画或营销装饰；不加载 CDN 和远程字体。

### 视觉基线

- 默认浅色、暖中性纸张感；深色为可选主题。
- 保留案隐盾绿色作为主色；警告、阻断、成功和信息状态使用独立语义色。
- 8px 间距系统、6px 控件圆角、8px 面板圆角、轻边框和弱阴影。
- 中文使用本地系统字体栈；金额、版本、哈希使用等宽数字。
- 状态不得只靠颜色表达，必须同时使用图标和文字。
- 满足键盘操作、可见焦点、屏幕阅读器、WCAG AA 对比度和减少动画偏好。

### 页面结构

```text
AppShell
├─ CaseDashboard
├─ CaseWorkbench
│  ├─ SourceViewer
│  ├─ FactWorkspace
│  ├─ DisclosureWorkspace
│  ├─ RiskWorkspace
│  ├─ RestorationWorkspace
│  └─ ContextRail
├─ LegalPackCenter
├─ ProviderCenter
├─ BenchmarkCenter
└─ RuntimeSettings
```

基础组件统一为 `Button`、`StatusBadge`、`Panel`、`DataTable`、`StageStepper`、`Dialog`、`IssueList`、`AnchorViewer`、`DecisionControl` 和 `AuditTimeline`。

### 法学未定状态

`LegalPackCenter` 必须显示：

- 案由包生命周期。
- 字段矩阵完成率。
- 待确认规则和缺失法源。
- 攻击协议是否冻结。
- 当前阻断正式外发的原因。

界面始终区分：

- 技术已实现。
- 运行能力已配置。
- 法学规则已发布。
- 风险协议已完成。
- 当前案件已通过。

不得用单一绿色状态或综合百分比表达“安全/合规”。

### 响应式

- 桌面：原文、工作区、依据三栏。
- 900–1200px：依据栏改为抽屉。
- 650–900px：原文和工作区双页签。
- 650px 以下：单栏流程，关键审批必须展示完整请求摘要。
- 使用 Playwright 固定 1440、1280、900、650、390 像素视觉基线。

## 五、测试、验收与默认假设

### 测试

- 保留现有后端和浏览器回归测试。
- 覆盖 v1 数据迁移、历史读取、备份恢复和迁移失败回滚。
- 覆盖新案由导入、包版本不可覆盖、未审核包阻断和任务扩展。
- 覆盖 PII 坐标、重叠实体、OCR 锚点、风险分项及缺少正式权重。
- 覆盖边侧模型未配置、非法 URL、无效 JSON、未知来源、超量输出和提取期间材料变化。
- 覆盖 token 冲突、破损 token、未知 token、历史锚点、数字幻觉和双轨导出。
- 四类攻击分别测试 `resisted/succeeded/uncertain/error/not_run`。
- 网关测试 HMAC、白名单、密钥隔离、幂等、超时结果不明、崩溃恢复和禁止盲目重发。
- 实验算法验证 DP 裁剪和预算组合、JL 距离保持、投影复现及真实 MIA 输入；检测常量指标、模拟 loss 或空实现时 CI 失败。
- Windows、macOS、Linux 均运行安装、Unicode 路径、文件锁、进程退出、前端构建和浏览器 E2E。
- 隔离测试证明 API/worker 无公网、gateway 无案件卷、redteam/benchmark 无正式数据库和 mapping。

### 正式外发门槛

只有同时满足以下条件才允许出现正式外发操作：

- 材料和 OCR 已复核。
- 所有事实已确认且未过期。
- 正式案由包已发布。
- 服务商资料和影响评估有效。
- 确定性门禁无直接标识和禁止项。
- 四类攻击均完成并达到冻结标准。
- 请求、规则、材料、模型和累计披露版本已冻结。
- 具名审批有效。
- 隔离部署自检通过。

### 默认假设

- 法学方案未定不阻塞工程建设，但正式外发持续关闭。
- DataInfra 仅借鉴产品思想；因其 [Personal Use License](https://github.com/ttttccxxui/DataInfra-RedactionEverything/blob/main/LICENSE)，不进入依赖树。
- Ianvs 的 PII、风险和审计进入生产；DP、掩码、降维和 MIA 仅用于隔离实验。
- 所有 Ianvs 移植文件保留 Apache-2.0、固定提交来源和修改声明。
- 不分发模型权重、API 密钥、真实案件、实验真值或运行数据库。
- 法律规则以法学团队的版本化审核为准；系统不自动作出法律意见或合规认定。
