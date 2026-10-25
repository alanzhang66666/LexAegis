# 案隐盾（LexAegis）V3.0 交付矩阵与 PR 开发任务清单

> 该文件是 `docs/V3_0_REFACTOR_SPEC.md` 的工程落地矩阵。**提案阶段，不代表代码已实现。** 每个 PR 必须附：代码、覆盖率、迁移、攻击用例、可逆性/回滚说明、实测证据。当前主分支 `formal_dispatch=blocked` 不会仅因文档合并而解除；**V3.0 的交付目标为生产环境中通过法学和技术门禁后正常真实外发，不设产品级永久阻断**。

## 0. 不可破坏的基线

- 系统名称以法学专家方案为准，不更改对外品牌。
- 原件、PII 映射、证据锚点和本地律师批注不出边侧；只批准**任务、接收方、用途、版本与具体字节绑定**的内容。
- A 链业务跨境协作和 B 链外部模型调用：批准、许可、账本、失败恢复相互独立。
- `L4` 与未知的身份/法域/算法/审批状态默认阻断。
- `G0–G10` 语义不修改；审批人、算法模型、云端返回都不能授予网关越权发送能力。
- 新 V3 隐私算法以 `feature flag` 开启实验；`DP_VECTOR_EXPERIMENT` 永不接受生产案件自动调用。但经过真实验证的最小化事实卡（`MINIMIZED_TEXT_B`）是 V3.0 **默认可执行外发路径**，不等待向量实验。
- 旧 `DomainRuntimeSnapshot`、`CloudTaskEnvelope`、`CloudResultEnvelope`、`HumanDecision` 保持兼容；代码变更之前保留冻结请求的黄金序列化 fixture。

## 0.1 产品验收修订：默认真实外发能做到

用户确认 **“应该默认外发已经可以做到”**。据此把“受控真外发可用”提升为 V3.0 的优先验收目标，而非发布末期的可选需求：

1. **能力默认可用**：V3.0 可配置完成的 `production` 安装应具有 `OutboundCapability=available`，正常 UI 展示“可以申请真实外发”，没有产品级恒 `blocked` 锁。
2. **请求不默认放行**：新任务仍 `pending_assessment`；法学 L0–L4、A/B 审查、真实服务商白名单、G0–G10、审批、载荷哈希和一次授权完成后才得到 `ready_to_dispatch`。
3. **B 链已有真发送基础**：`gateway.py` 有 `provider.dispatch(...)` 云端请求，`integration` 支持合成任务 `transport=cloud`；但 `outbound_gate.product_dispatch_state()` 恒阻断、`formal_release.FIRST_RELEASE_TUPLE` 单例范围，尚不能表述为通用正式案件可发。
4. **正向验收必有真实响应**：至少一个经过合法审批的最小事实卡样本，确认供应商实际收到并产生 `provenance=cloud`、具名许可消耗、网关真实回执；另有 L4/无授权/依赖哈希变化的拒绝验证。
5. **DP 不阻塞文本主路**：差分隐私、向量 Adapter、Ianvs 只影响 `DP_VECTOR_EXPERIMENT` 开通，不应成为真实 `MINIMIZED_TEXT_B` 的全局前置依赖。
6. **A 链另外验收**：跨境企业业务协作必须实现独立接收方与法域授权及真实传输，不能拿 B 链的调用成功代替。

### 0.2 尽早交付的垂直切片

| 顺序 | 最小变更 | 验收 |
| --- | --- | --- |
| T0 | 锁定 `main` 真发送接口、合成 `integration` 端到端测试与部署配置现状 | 实测 `cloud` 成功/错误/unknown，真实业务数据禁参与 |
| T1 | 新 V3 `OutboundCapability` 和 `ReleaseScope` Schema + 旧字段映射 | 老试点字节签名与冻结请求仍兼容 |
| T2 | B 链受控常态外发：法律准入绑定、现有 G 门、动态请求级 `grant` | **合格正式任务能真发**，无额外总闸门 |
| T3 | A 链业务分享/法域双向流程及独立账本 | A/B 不串权，真发送与拒绝路径都实测 |
| T4 | S/L 分类、DP 预算、证据强化、KubeEdge、Ianvs 验证 | 增强质量和隐私，不能降低 T2/T3 的审批底线 |

## 1. PR 排序与明确代码任务

### PR-01 版本化契约与向后兼容

**新对象**：`PrivacyAssessmentV3`、`ExecutionPlanV3`、`TransferIntentV3`、`ChainDecisionV3`、`PrivacyReleaseReceiptV3`、`WireReceiptV3`、`FactAssertionV3`；严格 Pydantic schema，禁止未知的跨域字段。

**文件**：`lexaegis/contracts.py`、`lexaegis/domain_runtime.py`、`lexaegis/storage.py`、`alembic/`（以真实树为准），`tests/test_v3_contracts.py`。

**接口**：
- `create_v3_context_snapshot(case, task, domain_pack, classifier_version, legal_rule_version, privacy_policy_version) -> snapshot`
- `freeze_execution_plan(snapshot, risk, route, transfer_intents) -> content_hash`
- `V2→V3` 内部适配器，不影响既有 V2 正式 wire payload。

**检查**：
1. Legacy request_hash golden fixture 不变。
2. 修改领域包/法源/模型/收件人后 V3 审批不再有效。
3. PII 原文、`mapping`、`anchors`、`local_text` 不进入云端协议。
4. `Orchestrator` 仍是唯一任务状态推进权威。

### PR-02 本地敏感度分类与检测策略

**文件**：新 `lexaegis/privacy/sensitivity_classifier.py`、`sensitivity_calibration.py`、`lexaegis/detection.py`、`tests/test_sensitivity.py`。

**接口**：`classify(text, source_spans, case_context, policy_hash) -> PrivacySignals`。

**实现**：复用坐标化 PII、加组合准标识规则；训练/加载的边侧语义模型作为候选贡献者；对每个事实给出 `S0/S1/S2/UNKNOWN`、证据 span、触发规则、版本、校准置信区间。

**检查**：手机号+岗位+日期组合、跨境外派岗位、医疗/工资/工伤、多主体聊天、OCR 噪声、空输入及模型故障；任一故障不会自动归零风险。输出不带未授权原文。

### PR-03 法学等级与任务路由

**文件**：`lexaegis/privacy/privacy_router.py`、`lexaegis/policy.py`、`lexaegis/disclosure.py`、`lexaegis/domain_packages.py`、`tests/test_privacy_router.py`。

**接口**：`plan_execution(task, privacy_assessment, legal_policy_snapshot, capability) -> ExecutionPlanV3`。候选 `LOCAL_DETERMINISTIC`、`LOCAL_LLM`、`MINIMIZED_TEXT_B`、`DP_VECTOR_EXPERIMENT`、`BLOCK`。

**约束**：法学 `L0–L4` 根据当前 PRD 经具名律师签署的 GateProfile 映射，禁止代码擅自估算高等级豁免。路由器只能提出计划，`approval_granted` 永远不会因模型输出直接置 true。

**检查**：L4 硬拒绝、L3 默认阻断、未知法源停机、精确工资金额/日期保护、未审批云端接口不能发出任何请求。

### PR-04 经过核验的 DP 与持久隐私预算

**文件**：`lexaegis/privacy/dp_mechanisms.py`、`privacy_accountant.py`、`feature_encoder.py`、`lexaegis/experiments.py`（仅适配实验输出）、迁移与并发测试。

**接口**：
- `reserve_budget(scope, mechanism_spec, payload_digest, release_id) -> BudgetReservation`
- `apply_dp(vector, clipping_norm, sensitivity_bound, accountant) -> ProtectedVector`
- `commit_release(reservation, wire_receipt)` / `release_unspent(reservation, verified_no_send)`

**检查**：
- 安全随机源、明确邻接/灵敏度、固定对照输入的理论与数值单测；
- 并发竞争只允许符合总预算的预留；
- Session 重建、Retry、Provider 切换不能重置已消耗预算；
- `unknown` 按潜在已披露保守计入；
- 如尚无适当密码学/DP 库，在此阶段只允许实验，不宣称 `ε` 正式保证。

### PR-05 A/B 独立法律评估

**文件**：`lexaegis/compliance/chain_assessment.py`、`jurisdiction_policy.py`、`recipient_registry.py`、`transfer_authorization.py`、`tests/test_dual_chain.py`。

**接口**：`assess_transfer(chain, sender, recipient, payload, context, legal_sources_version) -> ChainAssessment`。

**数据**：七维（法域、目的、角色、字段、处理位置、保留及再利用、结果使用人）、法源签署、PIA/CTIA 适用判断、具名决定、过期时间。中越法域法律必须经过独立律师复核，不写死豁免。

**检查**：A 批不能 B 用；B 批不能 A 用；任一条件变化 invalidates 审批；记录不将动态法律判断简化为布尔值。

### PR-06 通用真实外发：先 B 链可用，后 A 链独立执行器

**文件**：先改 `outbound_gate.py`、`formal_release.py`、`gateway.py`、`worker.py`、`service.py`，再补独立的 `lexaegis/transfer/`（A 链）与部署网络、传输测试。

**接口**：`dispatch_frozen_transfer(transfer_intent, chain_decision, frozen_bytes_hash, grant_nonce)`。**验收为真调用**，不是仅 `can_dispatch=True`、`mock` 或静态回执。

**检查**：**B 链常态的真实生产最小事实卡应能发送成功**；去掉 `product_dispatch_state()` 恒阻断和 `FIRST_RELEASE_TUPLE` 永久限制，改用按任务绑定的 `ReleaseScope`；现有 G0–G10、具名审批、正式签名许可与供应商白名单一项不减；A 链新增独立网关及账本；批准内容=实际发送内容的字节级一致性；重复 nonce 无双发；没有密钥/网络/审查时硬拒绝；`unknown` 不自动重发；撤销和恢复测试；执行器不挂载原始案卷卷。

### PR-07 实质证据回链与人工决定

**文件**：`lexaegis/evidence/claim_verifier.py`、`conflict_detector.py`、`lexaegis/return_pipeline.py`、`lexaegis/policy.py`、`tests/test_evidence_validation.py`。

**检查**：带有效 ID 但内容矛盾不得通过；无来源的主张不能形成正式文书；工资表与聊天中反证并列且可定位；OCR 错误和材料版本变化触发重审；必须具名 HumanDecision 才能采纳。

### PR-08 工作台/审计/导出

**文件**：`frontend/`、`lexaegis/api.py`、`audit_chain.py`、`tests`、浏览器 E2E。

**内容**：最小事实卡 Diff、S/L 风险、独立 A/B 授权视图、隐私预算实验数据、冲突双栏、5 类可核验审计、模拟/实际发送区分、外签 checkpoint。正式导出与数据分享分别独立审查。

### PR-09 KubeEdge 签名包与边缘自治

**文件**：`lexaegis/package_controller.py`、`deploy/k8s/`、`scripts/kubeedge_local_drill.py`、部署测试。

**检查**：断连/重连、签名包更新/撤销、边缘自主本地任务，等待云端步骤为 `waiting-cloud`；受撤销或过期包约束的任务不能在离线期间完成真实外发；业务原文不可经 KubeEdge 配置通道流转。

### PR-10 Ianvs 真实基准 + 法学九维验收

**文件**：`benchmarks/ianvs_pipl/`、`lexaegis/acceptance_suite.py`、隔离环境依赖与数据说明。

**算法指标**：真实 Accuracy/F1、MIA AUC 和 TPR@FPR、向量反演与重识别、真实预算、p95 时延、显存/吞吐。

**法学指标**：事实抽取 F1、有效证据锚点、无源事实率、冲突反证召回、最小必要性、组合攻击、网关误放与误拒、审计完整率、人工审核耗时。

**硬规则**：禁止硬编码 mock 值进入验收，明示 `is_simulated`；普通 Chat Completions 不得冒充真实 `VectorAdapter`。

### PR-11 受控常态发送与发布签发

**交付**：双法域法律审查证据、安全红队、运行隔离清单、构建 provenance、验证运行证据、回滚预案、具名发布决定。

**原则**：生产条件满足的具体请求可正常发送，没有永久全局阻断；仍不存在任何人按一次按钮就能绕过法学、审批、供应商限制或冻结载荷绑定。

## 2. 测试门槛和风险归属

| 测试类别 | 最低通过证据 | 主要责任人 |
| --- | --- | --- |
| 静态契约 | schema/类型/黄金载荷快照，无 V2 兼容破坏 | 架构/后端 |
| 数据安全 | 原文和映射不进入 A/B 无权限出口 | 安全/边缘 |
| 法域法律 | 中越双向对应法源、豁免与 PIA/CTIA 的责任签署 | 中国/越南法律负责人 |
| DP 正确性 | 灵敏度证明、机制参数、会计组合、CSPRNG 与并发记录 | 隐私算法 |
| 决策授权 | **批准的真实请求可发、未批准请求不能发**；L4/unknown、A/B 双链隔离、具名权限 | 合规/QA |
| 回流可信 | 原文支持、反证并列、有效 HumanDecision | 律师/证据标注 |
| 可靠性 | 崩溃、断网、超时、`unknown` 不重复释放 | 平台/网关 |
| 隔离与部署 | 外网出口受控、KubeEdge 包撤销、审计不含原文 | SRE/安全 |
| 科研真实性 | 确认非模拟、真实数据/模型/统计、完整实验目录 | 算法/评测 |
| 发布 | 实测门禁和法学/安全签字 | 发行负责人 |

## 3. 建议开发目录（仅作提案）

```text
lexaegis/
  privacy/
    sensitivity_classifier.py
    sensitivity_calibration.py
    privacy_router.py
    feature_encoder.py
    dp_mechanisms.py
    privacy_accountant.py
    risk_feedback.py
  compliance/
    chain_assessment.py
    jurisdiction_policy.py
    recipient_registry.py
    transfer_authorization.py
  transfer/
    intent.py
    a_gateway.py
    receipts.py
  inference/
    text_fact_adapter.py
    vector_adapter_client.py     # 实验开关，默认关闭
  evidence/
    claim_verifier.py
    conflict_detector.py
benchmarks/
  ianvs_pipl/                  # 无真实案件卷和生产密钥
tests/
  test_v3_contracts.py
  test_sensitivity.py
  test_privacy_router.py
  test_dp_accountant.py
  test_dual_chain.py
  test_evidence_validation.py
```

**迁移注意**：`contracts.py` 可能已是超大文件，重构过程中可先增加 `contracts_v3.py` 或 `contracts/privacy_v3.py` 以避免循环导入。必须先读当前依赖树和迁移命名，禁止直接照本提案路径批量改现有模块。

## 4. 第一次代码 PR 的具体完成条件

先提交 **PR-01**：新增类型定义与 schema roundtrip/deny-unknown 单测；增加 `PrivacyAssessmentV3` 和 `TransferIntentV3` 的版本/指纹验证；冻结 V2 请求快照；保证旧 API/网关未改变。  
完成这一步后 PR-02 与 PR-05 可并行。**PR-01 不连外部服务、不修改 `formal_dispatch`、不在 UI 宣称已通过法律验收**。

## 5. 风险登记与决策记录

| ID | 风险 | 缓解或阻断 |
| --- | --- | --- |
| R-01 | L3 变为低风险建议外发 | 先做 legal eligibility，后做评分 |
| R-02 | 原文 embedding 可逆/跨轮链接 | 实际攻击测试，DP 不等于法定匿名 |
| R-03 | 掩码破坏证据事实 | 关键字段保真，冲突/否定词专项测试 |
| R-04 | 上游 Ianvs 假指标 | 隔离实验、真实重算、标记模拟 |
| R-05 | DP ε 机制公式与邻接不一致 | 独立数学审核 + accountant |
| R-06 | 并发 / 网关未知态导致两次外发 | 事务预留、nonce、未知不重试 |
| R-07 | 法源变更或越南新法律造成旧批准越权 | 规则版本签名、强制失效与复审 |
| R-08 | KubeEdge 配置误带敏感案卷 | 安全标签、数据面隔离与静态检测 |
| R-09 | 多微服务过早拆分造成一致性断裂 | 保留模块化单体，A/B 出口独立 |
| R-10 | 模型「法律判断」污染输出 | 人工决定明确、来源验证、不导出未审事实 |

## 6. 下一步执行操作

1. 联合法学与研发评审 `V3_0_REFACTOR_SPEC.md`，留下逐条签署的开口问题。
2. 将本矩阵落成 GitHub issue/工程看板，锁定 PR-01 Schema 契约。
3. 编写独立的合成测试数据和现有 V2 字节级黄金快照。
4. PR-01 合并前不直接拆除现有门禁或以常量翻转冒充功能完成；完成 PR-05/06 的真实外发正反向验收后，才把产品级恒阻断替换为受控可用状态。
5. 各阶段完成必须更新 `docs/VALIDATION.md`，区分静态审核、模拟测试、实测与未验证。

**本文件只启动方案与工作分解；不是安全授权，也不是全部代码已改造的声明。**
