# V2.2 架构对齐：差距分析与分阶段实施计划

> 本文档是**目标架构对齐计划**：对照 `LexAegis_系统架构设计书_V2.2_KubeEdge_多案由可扩展平台.md`（下称 V2.2）逐项映射当前 V1.0 代码，给出改造顺序与接口设计。
>
> - **不是现行规格。** 规格三角仍为 ARCHITECTURE + VALIDATION + PROVENANCE；V2.2 文档自称 "Implemented Architecture Baseline"，但代码实态为 V1.0，本文件显式声明这一错位。
> - **不是发送授权。** 不改变 `dispatch_allowed=false`、不改动 `outbound_gate` G0–G10 语义、不宣称任何真实外发已开通。
> - **不是验收结论。** 所有「目标」列均为待实现项；真实验收仍须真实证据。

版本：V1.0（`1.0.0`）→ 目标 V2.2。文档日期：2026-09-22。

---

## 0. 决策记录（Jev 置信度辅助）

2026-09-22 通过 Jev API（`POST /api/v1/decide`，jev-1.13.0）对四个开放决策点取 typed decision，结果为**决策支持而非授权**：

| 决策点 | 选择 | 概率 | 置信度 | 采纳口径 |
| --- | --- | --- | --- | --- |
| 本轮交付物 | 差距分析 + 分阶段计划 | 0.77 | 0.69 | 即本文档；不写业务代码 |
| KubeEdge 范围 | 产 manifests 不实跑集群 | 0.54 | 0.31（低） | P7 交付 manifests + 部署文档；**真实集群验证列为独立验收门禁**，环境就绪后执行（保留需求方"真实集群验证"意图） |
| 兼容性 | 绿地并行 | 0.40 | 0.10（三选近持平） | 新 V2.2 机制与旧路径并存双写，旧路径设退役门禁；风险偏高（另测 2.15/3），见 §6 |
| 第一阶段 | 运行时绑定模型 | 0.81 | 0.74 | P1 = 绑定/上下文/快照/步骤对象模型；包拆分排 P2 |

补充探测：阶段序「包拆分→绑定→注册表→编排→KubeEdge」noul = 0.69，与首选序方向一致——绑定模型与包拆分先后可调换，但绑定先行可让快照过渡期直接对整包分节求哈希，避免二次改签名口径。

兼容性一项三个选项概率 0.40/0.30/0.30 几乎持平，KubeEdge 0.54/0.43 两项接近——两项均属低置信决策，文档保留替代路线说明（§6）。

---

## 1. 现状 → V2.2 逐项映射

| # | V2.2 构件 | 现状（锚点） | 差距 | 改造方式 |
| --- | --- | --- | --- | --- |
| 1 | Platform Kernel（CaseRuntime / TaskRuntime / DomainPackageResolver / ContextVersionManager / ControlPlane / OutboundGatewayClient / ReturnPipeline / HumanDecisionRuntime / AuditRuntime / ArtifactRuntime） | 逻辑散于 `lexaegis/service.py`（case/task/evaluate/approve）、`worker.py`（job 队列与回流）、`policy.py`（最小化与门禁评估）、`outbound_gate.py`（门禁聚合） | 无内核边界；劳动争议语义硬编码在内核路径（`disclosure.py` 加班规则、`d_path.py` LA/SMP 名单） | 抽内核模块边界，领域语义下沉包内；kernel 只认契约不认案由 |
| 2 | DomainPackageSet 八件套（CausePack / LegalRulePack / CapabilityBinding / ReviewSchema / ArtifactSchema / MinimizationProfile / GateProfile / DomainAcceptanceSuite） | 单文件 `DomainPackV2`（`contracts.py:272`）混合全部字段：fact_fields、task_field_matrix、rules、legal_sources×142、sensitive_object_rules、manual_review_conditions、reply_templates、conflict_checklist、direct_identifier_patterns、forbidden_terms、risk_weights、synthetic_cases（`packs/labor_v2_draft.json`） | 一个聚合承载八种包语义，版本、审核、失效只能整包操作 | P2 拆分为八类独立 package_type 聚合，各自版本化、签名、失效 |
| 3 | Package Registry（draft→validated→signed→published→deprecated→revoked；签名 / publisher / platform_api_version / compatibility manifest / supersedes / provenance） | `registry.py` pack 状态 draft/pending_review/reviewed/published/retired；`runtime_pack.py` 内容寻址 draft→reviewed→published→retire + 法05 证据绑定 + 失效传播 | 生命周期缺 validated / signed / deprecated / revoked；无签名、platform_api、supersedes、provenance | 扩展包状态机与元数据字段；签名与 provenance 以 content_hash 链承载 |
| 4 | Support Registry（supported_causes，按 environment 声明；loadable ≠ supported） | 无；pack `published_scope` + `dispatch_allowed` 兼任支持声明 | 缺独立支持注册表与 per-environment 声明 | P3 新建 `supported_cause` 聚合；create_case / create_task / outbound 评估读它 |
| 5 | CaseDomainBinding（显式绑定 cause_id + 包 id/version + jurisdiction + binding_status + bound_by/at；禁止静默升级） | `case.domain` 字符串字段（`service.create_case` `service.py:93`）；`create_task` 取 `packs[-1]`（`service.py:300`） | 无绑定记录；任务建时现查最新包即静默升级 | P1 新建 `case_domain_binding` 聚合；绑定写死包 id+version+hash |
| 6 | CaseContextVersion（domain_runtime_snapshot_id、verified_fact_set_hash、source_material_set_hash、identity_mapping_version、cumulative_disclosure_state、status、superseded_by） | 无；task 内联 `fact_snapshot` / `case_revision` / `settings_version` / `ledger_version`（`service.py:331`） | 上下文版本只在 task 字段内，无独立聚合、无 supersede 链 | P1 新建 `case_context_version` 聚合；task 改持 context_version_id |
| 7 | DomainPackageResolver → DomainRuntimeSnapshot（不可变，七类包 hash + platform_api_version，绑定到 Task） | 无；`dependencies.pack_hash` 进入 request 近似承担 | 无快照对象；无 resolver | P1 新建 `domain_runtime_snapshot` 聚合与 resolver；过渡期 snapshot 对 DomainPackV2 分节求子哈希 |
| 8 | Task / TaskStep（step_type: LOCAL / CONTROL / CLOUD / VALIDATION / HUMAN / STATE_TRANSITION；仅 Orchestrator 推进） | task.status 平面状态机 + worker job kinds（parse/extract/redteam/send/reconcile，`worker.py:147-345`） | 无 TaskStep 记录；状态推进分散在 service/worker/gateway | P1 建 TaskStep 聚合双写；P4 转权威、Orchestrator 唯一推进 |
| 9 | Capability Registry + CapabilityBinding（capability_id + api_version + input/output/privacy contracts；cause×task_type→capability+minimization+provider_profile） | `task_engine.registered_tasks`（fact_summary/timeline/evidence_inventory/issue_extraction）为事实能力表；`ProviderProfile` 契约已有（`contracts.py:451`）；无 binding | 能力与案由绑定隐式；provider 由 settings 直连不经 binding | P5 新建 capability 聚合 + `capability_binding` 聚合；provider_profile 经 binding 引用 |
| 10 | CloudContext 信封（case_ref / task_id / cause_id / capability_id / context_version / request_hash / facts / contract_version） | `wire_payload = {contract_version:2, task:{id,version}, facts}`（`service.py:854`） | 信封缺 cause_id/context_version/snapshot 关联；case_ref 未不透明化 | P4 扩展信封字段；case_ref 用不透明引用 |
| 11 | request_hash 绑定扩展（+ snapshot_hash / capability_binding_hash / provider_profile_hash / build manifest） | request 绑 pack_hash/provider_hash/materials/ledger/prompt/attack_input_hash（`service.py:962`） | 缺快照与 binding 哈希入哈希链 | P4 扩展 request 依赖字典 |
| 12 | Control & Trust Plane + 唯一 outbound_gate（G0–G10 + G-product） | `outbound_gate.collect_outbound_blockers`（G0/G2/G3/G5/G7/G8/G9，`outbound_gate.py:147-206`）+ `policy.assess`（G0）+ `formal_release.py` 证据链 + `product_dispatch_state()` 恒 blocked | 已具雏形；GateProfile 未参数化到包 | **保持不动**。仅 P2 把 gate 参数（risk_weights、manual_review_conditions.gate_id）挂到 GateProfile 包；禁改 G 编号语义 |
| 13 | Cloud Capability Gateway（云域：限流、provider 适配、审计、provenance） | `gateway.py` 为**边侧**本地进程（持密钥、白名单、账本、签验 dispatch envelope） | V2.2 的 CGW 在云域；当前实现是边侧出站执行器 | 短期同进程双角色（边侧执法 + 云侧适配）；P7 部署期拆分为云域组件 |
| 14 | Return Pipeline（信封→hash→schema→source_ids→provenance→domain mapper→evidence re-link→identity re-link→review schema→human decision） | `worker.finish_response`（`worker.py:46`）+ `policy.check_claims`/`check_cloud_feedback` 内联完成 schema/来源/锚点重链 | 管道为单体内联，无阶段对象、无领域 mapper 钩子 | P6 阶段化显式管道；mapper 由包提供 |
| 15 | 包沙箱 SPI（FactReader / EvidenceResolver / ContextBuilder / RuleEvaluator / ReviewSchemaProvider / ArtifactBuilder；包禁触凭证/G10/他案数据） | 包为纯声明式 JSON 数据（`registry.validate_pack` 拒执行表达式）——「无代码」已满足，但无显式 SPI 接口 | 无受控接口边界；包数据由内核代码直读 | P2/P5 定义 SPI 协议类，Domain Runtime 只经接口消费包 |
| 16 | AuditEvent 扩展字段（cause_id / context_version_id / snapshot_id / pack hashes / capability_binding / request_hash / gate_snapshot_id / actor / edge_node_id / workload_version / cloud_invocation_id / provider_request_id / result_hash / human_decision_id / artifact_id） | `util.audit` 通用事件 + 自由 metadata | 缺上述结构字段 | P4 扩 audit 事件字段，各阶段逐步回填 |
| 17 | 故障语义（package_resolution_failed / platform_api_mismatch / failed_before_send vs unknown / invalid_cloud_result / 撤包→blocked 或 review_required） | `unknown`/`failed_before_disclosure` 已有（`worker.py:373-375`）；`invalidate_runtime_pack_dependents` 做部分撤包传播 | 缺命名故障类别与门禁映射；invalid_cloud_result 未独立分类 | P1 定义故障枚举；P4/P6 挂接各触发点 |
| 18 | 边缘自治（断连本地可继续；cloud-required 记 waiting-cloud；禁 mock 冒充 provenance） | demo profile 离线运行；无断连语义与 waiting-cloud 状态 | 缺自治策略与等待状态 | P6 新增 waiting-cloud step 状态与断连策略 |
| 19 | Matter（复合案由容器，预留） | 无 | 预留 | P1 契约预留字段，不实现逻辑 |
| 20 | DomainAcceptanceSuite（18 项基线：CausePack 校验、法源版本、绑定兼容、最小化、泄漏、request_hash 稳定、G0–G10、唯一 gate、provider schema、错 source_ids 阻断、回流重链、人审三分支、ContextVersion 失效、非静默升级、断连自治、撤包、审计完整、独立 fixture） | `synthetic_cases` + `run_pack_regressions`（仅字段规则回归） | 套件形态缺；多数基线由散落测试覆盖但未按包声明 | P8 建套件清单格式 + 运行器，映射现有测试 |
| 21 | 三类版本轴（platform_api / domain_package / rule_effective） | `compatible_core`（如 `>=0.2,<2`）+ pack.version + legal_sources.effective_from 各自存在 | 无统一分轴声明与兼容性矩阵 | P2 compatibility manifest 显式三轴 |
| 22 | Kubernetes + KubeEdge 部署（CloudCore/EdgeCore、包下发、云边双通道） | 无；native 三进程（`launcher.py`）或 Compose | 基础设施层整体缺失 | P7 产 manifests + 部署文档；真实集群验证为独立验收门禁 |

---

## 2. 分阶段实施路线

顺序依据 Jev 置信度（§0）：**绑定模型 → 包拆分 → 支持注册表 → 编排/信封 → 能力绑定 → 返回管道/边缘自治 → KubeEdge → 验收套件/文档**。

### P1 · 运行时绑定对象模型（Jev 首选 0.81 / conf 0.74）

> **状态：已落地**（2026-09-22，Windows 本机）。契约在 `contracts.py`（`PLATFORM_API_VERSION` + 4 类），逻辑在 `lexaegis/domain_runtime.py`，挂钩在 `service.py`/`worker.py`，观测端点 3 个在 `api.py`，测试 `tests/test_domain_runtime.py` 10 项。快照为过渡期分节哈希口径；TaskStep 现经 `transition_task` 漏斗记录全部状态迁移，`LEX_ORCHESTRATOR_AUTHORITY` 一致性检查可用（默认关，见 P4）。`CloudResultEnvelope`/`HumanDecision` 契约与记录已补（见 P4 状态行）。

**目标**：建立 V2.2 的四个核心对象，旧路径保持权威、新对象双写。

- 新契约（`contracts.py` 或新 `contracts_v22.py`）：`CaseDomainBinding`、`CaseContextVersion`、`DomainRuntimeSnapshot`、`TaskStep`、`CloudTaskEnvelope`、`CloudResultEnvelope`、`HumanDecision`；`Matter` 仅预留字段。
- 新聚合 kind：`case_domain_binding`、`case_context_version`、`domain_runtime_snapshot`、`task_step`。
- 新模块 `lexaegis/domain_runtime.py`（落地时命名，覆盖 resolver + binding/context/step）：输入 case binding + environment → 输出不可变 snapshot；过渡期对 `DomainPackV2` 各字段分组（cause/legal_rule/minimization/review/artifact/gate/acceptance）分别求子哈希填入七类包哈希位。
- `service.create_case` 写 binding；`create_task` 建 context_version + 绑 snapshot；`evaluate_task` request 依赖追加 `snapshot_hash`；状态迁移处双写 TaskStep。
- 故障枚举：`package_resolution_failed`、`platform_api_mismatch`（绑 platform_api_version 校验）。
- 验收：新聚合可由测试构造；旧 520 测试全绿；request_hash 口径变化在测试中显式断言。

### P2 · Domain Package Set 拆分

> **状态：已落地**（2026-09-24，Windows 本机）。契约在 `contracts.py`（`DomainPackage` / `DomainPackageManifest` / `PACKAGE_TYPES` / 快照可选字段），逻辑在 `lexaegis/domain_packages.py`（拆分器 + 生命周期 + 签名 + 撤销 + seed），resolver 升级在 `domain_runtime.py`，挂钩与种子在 `service.py`，4 个端点在 `api.py`，测试 `tests/test_domain_packages.py` 8 项。两个落地裁决：① manifest 按 `source_pack_id` 绑定**实际选中的单体 pack**，不按案由挑最高版本；② manifest 存在但不可解析（draft/revoked）时 **fail-closed 不回落**——回落只留给"该 pack 从未有 manifest"的案由。种子 manifest 止于 `validated`，未签名未发布；拆分只进快照/绑定层，disclosure/gate 消费侧仍读单体 pack（SPI 消费切换属 P5）。

- `DomainPackageManifest` 聚合 + `package_type` 字段：`cause_pack` / `legal_rule_pack` / `capability_binding` / `review_schema` / `artifact_schema` / `minimization_profile` / `gate_profile` / `domain_acceptance_suite`。
- 生命周期扩展：`draft → validated → signed → published → deprecated → revoked`；新增 signature、publisher、platform_api_version、compatibility manifest（三轴）、supersedes、provenance。
- `packs/` 下把 `labor_v2_draft.json` 重表达为 labor DomainPackageSet（八文件或单 manifest 引用八节）。
- resolver 改为解析 manifest → 各包；旧 DomainPackV2 由适配层视为等价 bundle（绿地并行）。
- `registry.py` 校验按 package_type 分派；撤包（revoked）联动 `invalidate_runtime_pack_dependents` 语义：新任务拒绝、在途任务 blocked/review_required。
- 验收：包拆分后 `run_pack_regressions` 等价通过；签名缺失/不匹配 fail-closed。

### P3 · Support Registry

> **状态：已落地**（2026-09-24，Windows 本机）。契约 `SupportedCause`（`contracts.py` 末尾），逻辑在 `lexaegis/support_registry.py`，挂钩在 `service.py`（create_case/create_task/evaluate_task）与 `registry.py`/`runtime_pack.py`（发布自动并入），3 个端点在 `api.py`，测试 `tests/test_support_registry.py` 8 项。落地裁决：① publish/activate 即 vetting 事件，已 supported 案由的新版本自动入 `pack_ids`；② suspend 复用 P2 传播模式打在途任务 stale；③ evaluate_task 失支持 → blocker + approval_allowed=false，不新增 G 门；④ 种子仅 labor，contract_test 保持可加载未支持。

- `supported_cause` 聚合：cause_id + 允许的包版本集合 + status + environment + 支持的能力列表。
- `create_case` / `create_task` / outbound 评估改读 Support Registry；包可加载 ≠ 已支持。
- `product_dispatch_state()` 恒 blocked 不变；G-product 语义不变。
- 验收：包 published 但未入 supported_cause 时 create_task 拒绝；environment 错配拒绝。

### P4 · 编排器与云信封

> **状态：已落地，权威化已可用**（2026-09-24，Windows 本机）。契约 `CloudTaskEnvelope` + `FAILURE_CODES`（`contracts.py`），逻辑在 `lexaegis/orchestrator.py`（transition 漏斗 + `derive_status` + `LEX_ORCHESTRATOR_AUTHORITY` 权威开关）、`domain_runtime.build_cloud_envelope`，网关信封强制校验在 `gateway.py`，worker 挂接在 `worker.py`，测试 `tests/test_orchestrator.py` 12 项。落地裁决：① 信封只对快照绑定任务构建，手工/demo 请求不受影响；② **全部任务状态写点已收敛到 `transition_task`**（service/worker/review/upgrade/runtime_pack/support_registry/domain_packages），`authorize_dispatch`（approve/enqueue/send 共享门）与 `finish_response` 入口接 `assert_consistent`；③ `VALIDATION`/`CLOUD` 移出状态推导集——`return:*` 阶段标签与 `waiting-cloud` 连接标记是观察通道不是任务状态；④ 包撤销/支持暂停传播现在真正置 `status="stale"`（原只置 stale 标志却记 stale 步骤，自相矛盾已修）；⑤ `from_status` 一律取真实前置状态；⑥ 老任务 request_hash 公式逐字节不变。**`LEX_ORCHESTRATOR_AUTHORITY=1` 全量回归通过**——开关仍默认关，转默认需真实环境观察期。补落 P1 名录剩余两契约（2026-09-24）：`CloudResultEnvelope`（`cloud_result_envelope` 聚合，管道成功写 `pending_human`、拒绝写 `rejected`+`result_hash` 绑定回包字节、无结果不写）与 `HumanDecision`（`human_decision` 聚合，`/tasks/{id}/confirm` 采纳时落 `adopted`+`artifact_hash`+actor，审计带 `human_decision_id`）；`send.*` 审计补 `result_hash`；只读端点 `/tasks/{id}/cloud-result-envelopes` 与 `/tasks/{id}/human-decisions`；测试 `tests/test_result_envelope.py` 5 项。

- `lexaegis/orchestrator.py`：TaskStep 转权威，task.status 由步骤推导；service/worker/gateway 的状态迁移收敛到 Orchestrator。
- CloudContext 信封（`CloudTaskEnvelope`）：case_ref（不透明）/task_id/cause_id/capability_id/context_version/request_hash/facts/contract_version；`gateway.py` 验签信封。
- request_hash 依赖追加 `capability_binding_hash`、`provider_profile_hash`、build manifest 哈希。
- `util.audit` / AuditEvent 扩展字段（§1-16）并逐步回填。
- 故障类别挂接：`invalid_cloud_result`（返回 schema 校验失败 → failed_closed）、`failed_before_send` vs `unknown` 语义按 V2.2 定义。
- 验收：双写→权威切换有门禁开关；信封缺字段 fail-closed。

### P5 · Capability Registry 与 CapabilityBinding

> **状态：已落地**（2026-09-24，Windows 本机）。契约 `Capability`，逻辑在 `lexaegis/capability_registry.py`（种子/登记/断言），SPI 只读适配在 `lexaegis/spi.py`（MappingProxy 内容视图 + 类型化 reader），挂钩在 `service.create_task`（binding + capability 双重断言，task 记 `capability_id`）与 `domain_runtime`（binding 经 SPI 读 task_type），测试 `tests/test_capability_registry.py` 6 项。落地裁决：① `provider_profile` 引用必须指向真实 provider 记录否则 409；② binding 的 task_type/capability_id 与注册能力不一致 fail-closed；③ capability 未注册不阻断建任务——未注册 task_type 仍由 pack/task_engine 校验前置拒绝，registry 在首次使用时补登记。

- `capability` 聚合（capability_id、api_version、input/output/privacy contracts、deterministic/cloud 类型）；`task_engine` 现有定义迁移注册。
- `capability_binding` 聚合：cause_id + task_type → capability + minimization_profile_ref + provider_profile_ref；ProviderProfile 经 binding 引用而非 settings 直连。
- SPI 协议类（`spi.py`）：FactReader / EvidenceResolver / ContextBuilder / RuleEvaluator / ReviewSchemaProvider / ArtifactBuilder；Domain Runtime 只经 SPI 消费包。
- 验收：labor 各 task_type 经 binding 解析；无 binding 的能力调用拒绝。

### P6 · 返回管道与边缘自治

> **状态：已落地**（2026-09-24，Windows 本机）。`lexaegis/return_pipeline.py` 承接原 `finish_response` complete 分支为九阶段管道（envelope→hash→schema→provenance→domain_mapper→identity_relink→evidence_relink→review_schema→human_decision），每阶段落 VALIDATION task_step；断连策略：`httpx.ConnectError`（TCP 未建立=可证未发出）→ send 作业挂起 `waiting-cloud` + `not_before` 退避，ReadTimeout 等仍 `unknown` 不重发；`provenance_for_transport` 严格映射，mock 永不可能标 cloud。测试 `tests/test_return_pipeline.py` 5 项 + `tests/test_domain_mapper.py` 11 项。**domain_mapper 已是真语义**：`lexaegis/domain_mapper.py` 通用引擎执行 `cause_pack` 内容里的声明式 mapper 配置（`applies_to`/`claim_list_key`/`field_map`/`value_map`/`defaults`/`required_fields`，未知键拒绝），包是数据不跑代码；阶段出口五态 `mapped`/`skipped`/`unbound`/`none`/`failed`（失败→`invalid_cloud_result` fail-closed）；mapper 的 `package_id`+`content_hash` 写入 artifact 作版本绑定。labor 包（2.0.0-draft.3）带最小真实配置（必填字段断言 + `domain:"labor"` 默认标记，不虚构法律分类）；demo V1 包无 manifest → `unbound`。

- `lexaegis/return_pipeline.py`：把 `finish_response` + `check_claims`/`check_cloud_feedback` 重构为阶段化管道（envelope→hash→schema→source_ids→provenance→domain mapper→evidence re-link→identity re-link→review schema→human），domain mapper 由包提供钩子。
- TaskStep 增 `waiting-cloud` 状态；断连策略：本地允许的步骤继续、cloud-required 挂起为 waiting-cloud、禁止 mock 结果伪装 cloud provenance。
- 验收：既有回流测试全绿；断连模拟下 waiting-cloud 不推进、不产伪 provenance。

### P7 · KubeEdge 部署层

> **状态：manifests 已落地，集群未验证**（2026-09-24）。`deploy/k8s/` 8 个文件（namespace/configmap/secret 模板/edge-storage/edge-api/edge-worker/cloud-gateway/network-policy + README），按 compose 拓扑映射：边域 api/worker 钉 `lexaegis.io/domain: edge` 节点，云域 CGW 唯一持云凭据唯一出网，NetworkPolicy 复刻 internal/publish 隔离；`docs/DEPLOY.md` 增 KubeEdge 章节。包下发链路已落代码：bundle 机制（`export_bundle`/`import_bundle`）+ **控制面 `lexaegis/package_controller.py`**（`edge_node` 注册 / `package_assignment` 期望状态 / `package_receipt` 回执 / `reconcile` 对账报告，assigned→delivered→verified→active 与 revoking→revoked 两线，回执校验节点与 manifest 哈希，错序/错节点/错哈希一律拒，失败回执自动重试至 `MAX_ATTEMPTS=3` 后 failed 终态；`published` 不导入）。端点：`/api/v1/edge-nodes`、`/api/v1/package-assignments`、`/{id}/deliver`、`/{id}/receipts`、`/{id}/revoke`、`/api/v1/package-distribution/reconcile`（均 admin）。测试 `tests/test_package_controller.py` 11 项。**未在真实集群验证**——部署与断连/包下发/撤包演练是独立验收门禁。`gateway.py` 云侧角色已落启动期断言：`LEX_GATEWAY_ROLE`（unified/edge/cloud）——edge 角色禁止持云凭据（云域 CGW 唯一持凭据）、cloud 角色无凭据拒启动（fail closed 提前于发送时 409），`/health` 回 `gateway_role`；claim/queue 跨角色拆分仍是部署期工作未做。另补 P4 遗留：audit 扩展字段回填（`cause_id`/`domain_runtime_snapshot_id`/`capability_id`/`edge_node_id`，后者经 `LEX_EDGE_NODE_ID` 注入）。

- `deploy/k8s/`：云域（CloudCore、Package Registry、Support Registry、CGW 云侧角色）与边域（EdgeCore + kernel workloads）manifests；包下发链路（manifest → 边域）；云边双通道。
- `gateway.py` 拆出云侧适配角色（短期可同进程双角色，部署拓扑分离）。
- `docs/DEPLOY.md` 增 KubeEdge 章节。
- **验收门禁**：真实 KubeEdge 集群部署与断连/包下发/撤包演练——环境就绪后独立执行；无集群不宣称通过。

### P8 · DomainAcceptanceSuite 与文档收尾

> **状态：已落地**（2026-09-24，Windows 本机）。`lexaegis/acceptance_suite.py` 19 项基线：10 项 `package_asserted` 在进程内执行（CausePack/法源/绑定兼容/最小化/门禁/哈希稳定/manifest 一致/platform_api/provenance/fixture），8 项 `test_mapped` 显式映射到 pytest 文件，1 项 `manual_gate`（G10 真实外发，永不自动标过）；CLI `python -m lexaegis.acceptance_suite --data <dir> --cause labor` 非零退出即失败。新案由接入流程成文 `docs/DOMAIN_ONBOARDING.md`，已入 docs 索引。测试 `tests/test_acceptance_suite.py` 3 项（含漂移 fail-closed 与空包集非空洞为真）。

- `DomainAcceptanceSuite` 包格式 + `lexaegis/acceptance_suite.py` 运行器；把 18 项基线映射到现有测试与新增包级断言。
- labor_dispute 套件成文；新案由接入流程（定义范围→写包→验收套件→签名发布→部署→独立验收→Support Registry 激活）文档化。
- 更新 ARCHITECTURE / VALIDATION / PROJECT_MAP / AGENTS.md 状态口径；本文件转入 docs/ 现行索引或归档。
- 验收：套件可独立运行；文档无「外发已开通」「N 案已通过」类禁写口径。

## 3. 故障语义对照（新增枚举）

| V2.2 故障 | 触发点 | 现状对应 | 落位阶段 |
| --- | --- | --- | --- |
| `package_resolution_failed` | resolver 解析失败/包缺失 | —（当前隐式 500/校验错） | P1 |
| `platform_api_mismatch` | 包 platform_api_version 与内核不符 | — | P1 |
| `failed_before_send` | 可证明未发出的失败 | `failed_before_disclosure` 近似 | P4 命名对齐 |
| `unknown` | 无法证明的云端不确定 | `unknown`（`worker.py:375`） | 已有，语义对齐 |
| `invalid_cloud_result` | 返回 schema 校验失败 → failed_closed | check_claims 内联拒绝 | P4/P6 |
| 包 revoked | 撤包传播 | `invalidate_runtime_pack_dependents` 部分覆盖 | P2 |

## 4. 三类版本轴

| 轴 | 现状 | V2.2 目标 |
| --- | --- | --- |
| platform_api | 无显式轴（`compatible_core` 近似） | 包声明 `platform_api_version`；内核拒绝不匹配包（fail-closed） |
| domain_package | pack.version 单轴 | 八类包各自语义化版本 + supersedes 链 |
| rule_effective | legal_sources.effective_from | LegalRulePack 级 effective_from/until + 法源条目级日期 |

## 5. 不变式与禁改边界

- `outbound_gate.collect_outbound_blockers` / `policy.assess` / `validate_formal_gate` / `authorize_dispatch` 语义不得削弱；G0–G10 + G-product 唯一编号。
- `product_dispatch_state()` 恒 `blocked`；仓库 pack 保持 draft + `dispatch_allowed=false`。
- 409 阻断是控制行为不是 bug；工程攻击结果不得写成法学 `resisted`；分词 ≠ 匿名。
- 绿地并行期间旧路径语义为准，新对象双写须经一致性校验后才可切换权威（门禁开关）。
- 云返回结果永远只是候选输出，须返回管道 + 人审采纳；不得直入已核事实。
- 包保持纯声明式数据（禁执行代码）；SPI 只读接口，包不可触凭证/原始 socket/G10/他案数据。

## 6. 风险与开放问题

1. **绿地并行漂移**（Jev 评 2.15/3 偏高）：双写两套语义存在不一致风险。缓解：每阶段设一致性校验测试 + 显式权威切换开关 + 旧路径退役门禁（新路径验收通过 + 无在途旧任务后才删）。
2. **compatibility 低置信**（0.10，三选近持平）：若后续评估绿地并行成本过高，可降级为 breaking schema_version 3 + 只读兼容旧数据——需在 P1 评审时复核。
3. **KubeEdge 低置信**（0.31）：manifests_no_cluster 与 code_alignment_only 接近；若资源允许直接上真实集群更佳，反之可先只做代码层云边职责对齐。文档按「manifests 先行、真实集群验收独立门禁」落笔。
4. **V2.2 自称已实现基线与代码 V1.0 的错位**：本文件逐项标注「目标 vs 现状」，任何对外材料不得引用 V2.2 的 "implemented" 表述描述当前系统。
5. **storage 为通用 records 表**：新聚合继续走 `records(kind,scope,body)` 模式，不引入新存储引擎；若聚合数膨胀影响查询，后续单独立项。

## 7. 术语对照

| V2.2 | 当前近似 | 说明 |
| --- | --- | --- |
| CausePack | DomainPackV2 的 fact_fields/rules/task_field_matrix 节 | P2 拆出 |
| LegalRulePack | DomainPackV2.legal_sources + `legal_assets.py` | P2 拆出 |
| CapabilityBinding | 无（task_ids + provider settings 隐式） | P5 新建 |
| ReviewSchema | manual_review_conditions + reply_templates + conflict_checklist + `review.py` | P2 拆出 |
| ArtifactSchema | 隐式（claims artifact，`worker.finish_response`） | P2 拆出 |
| MinimizationProfile | direct_identifier_patterns + forbidden_terms + rules transforms + budget | P2 拆出 |
| GateProfile | risk_weights + manual_review_conditions.gate_id | P2 拆出，参数化既有 G 门 |
| DomainAcceptanceSuite | synthetic_cases + run_pack_regressions | P8 扩为套件 |
| Support Registry | pack.published_scope + dispatch_allowed | P3 独立 |
| DomainRuntimeSnapshot | dependencies.pack_hash 近似 | P1 新建 |
| CaseContextVersion | task.fact_snapshot/case_revision 内联 | P1 新建 |
| TaskStep | task.status + worker job kinds | P1 双写 / P4 权威 |
