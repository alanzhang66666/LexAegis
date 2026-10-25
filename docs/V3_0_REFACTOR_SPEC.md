# 案隐盾（LexAegis）——基于云边协同与双链解耦治理的跨境劳动争议材料可信智能处理系统

# V3.0 完整系统重构设计与迭代实施规格

> **文档状态**：Proposed / 待法学、算法、安全及架构联合评审；**不是已实现版本，也不是正式外发授权**。  
> **技术迭代编号**：V3.0（不改变法学方案规定的系统名称）。  
> **基线**：LexAegis `main` @ `263b2275091ef9ae1c8228eda553da6bf7ee69bc`（2026-09-26）；Ianvs `main` @ `8cd593ea0888a3d1c3f1d788897b53eb1fd8980c`（2026-10-08）。  
> **原则**：现有主分支的 `formal_dispatch=blocked` 和 `product_dispatch_state()` 恒阻断是**迁移前实际状态**，不是 V3.0 的目标默认行为。V3.0 的验收目标为**默认具备可执行的受控真实外发能力**：一旦请求满足法学准入、最小披露、版本冻结、角色审批和网关 G0–G10，即可正常发出并形成实际送达/未知态收据，不额外受产品级永久总闸门拦截。未满足条件一律拒绝。保留身份映射/证据原文边侧隔离和一次性许可。迁移完成与独立验收前不可提前在生产开放。

> **门禁精简决策（最新）**：V3.0 使用 **G-L 法律/接收方、G-D 最小披露/风险、G-H 按 L 等级一次确认、G-S 网关即时执行** 四项用户可见关口，旧 G0–G10 作为内部审计映射；环境/Provider/法源等有效证书前置复用。默认具备受控真实外发能力，不是默认授权发送。详见 [V3.0 门禁精简 ADR](V3_0_GATE_SIMPLIFICATION_ADR.md)。


## 0. 来源、决策权与可证明范围

| 来源 | 主要贡献 | 本规格使用方式 |
| --- | --- | --- |
| 法学专家《案隐盾法学方案1022(1)》 | 五段处理闭环、L0–L4、A/B 双链、七维准入、五类审计、证据冲突与人审、九维基准 | **规范需求和优先约束**；法律规则及条文须由法学责任人核验当期有效文本 |
| 《基于 PIPL 合规的云边协同隐私保护提示处理框架》（2026-01） | 敏感度分类、Gaussian DP、动态路由、会话预算、Encoder / Adapter / JL / HE、Ianvs 四维评估 | **研究设计输入**；数学和实验结果须单独复现 |
| Ianvs Proposal `docs/proposals/scenarios/PIPL-…` | 64维匿名向量、最小标签、模型配置、数据集和 benchmark 结构 | **上游目标说明**；不能等同于已运行代码 |
| Ianvs `examples/PIPL/edge-cloud_collaborative_learning_bench` | 分类、NER、规则风险、DP、投影、mask、MIA 测试骨架 | **实验参考源码**；当前主链存在模拟结果、伪向量及接口不兼容 |
| LexAegis 现有源码和 `docs/ARCHITECTURE.md`、`docs/VALIDATION.md` | 本地证据、领域包、技术/法律门禁、冻结请求、独立网关、返回九阶段、审计、V2.2 对齐 | **可保留的工程基线**；必须与真实运行测试结果区分 |

**三条不可替代关系**：
1. DP 机制的 `(ε,δ)` 结果不等于法律匿名化、跨境合法性或数据最小必要性结论。
2. 风险分类器只产生安全信号和建议路径；模型不得签发 A/B 法律许可、突破 L4 禁令或修改网关 G 门。
3. 具有来源 ID 不等于已经获原文支持；事实采信必须区分主张、文书记载、反证与人工认定。

**现状事实**：已见 `lexaegis/experiments.py` 中 L2 裁剪、Gaussian DP、RDP 及投影，但该模块明确离线实验、未导入正式 dispatch；上游 Ianvs 示例的 `_edge_inference` 与多项指标为硬编码演示，`_text_to_embeddings` 是文本哈希伪向量；`privacy_preserving_llm` 不是当前 Ianvs 已注册的 Paradigm。当前仓库已部署过的 KubeEdge 演练不等于生产边缘节点/独立云域服务全链路验证。

## 1. 产品目标、非目标及发布原则

### 1.1 总目标

服务于中国—越南跨境劳动争议材料核对，保证：原始证据留在边侧、外发只限本任务必须字段、A（业务跨境协作）/B（第三方模型调用）分别审查、任何模型结论均可核验证据锚点，最终认定归具名法律专业人员。

V3.0 是跨领域通用平台内核 + 首发劳动争议包：平台识别 `case_id`、`task_type`、`capability_id`、`purpose`、`recipient`、`jurisdiction` 和版本化领域包；劳动争议的计薪、工时、工资差额和争议事实语义留在包/专业能力中，不硬编码进网关。

### 1.2 明确不做

- 不把整个案卷、原文、真实主体映射、SourceAnchor 定位、律师意见或未批准的内部笔记送第三方模型。
- 不承诺「DP 向量=不可识别个人信息=可自由出境」。
- 不使用论文里的固定 ε、固定显存/时延、MIA 成功率或 F1 直接作为生产安全阈值。
- 不把普通 Chat Completions 的向量 JSON 文本输入称为连续隐空间联合推理；未完成真实 Adapter 实验前 `DP_VECTOR` 仅限隔离环境。
- 不让业务协作 A 链借用 B 链许可，也不因 A 链的人力资源管理相关豁免推定 B 链自动获批。
- 不以「多微服务」为重构目标；只有跨信任边界的持证书/密钥/外网出口部分独立部署。

### 1.3 V3.0 里程碑口径

- **V3.0-alpha**：新契约、**四道门禁聚合与旧 G0–G10 兼容映射**、分类/路由、预算实验接口、A/B 评估快照；联通真实发送的合成集成路径，记录成功/拒绝/unknown 三类证据。
- **V3.0-beta**：完成生产 B 链通用请求级授权及 A 链独立执行器、证据冲突回链、UI 和账本；**无产品级永久阻断**，生产开通仍需部署及各链验收。
- **V3.0-rc**：生产隔离、法学规则签署、红队及法域核验完成；在获批准入范围内进行真实端到端发送验收，范围外仍失败关闭。
- **V3.0 正式发布**：支持已完成环境/收件方/领域包准入的任务走常态化真实发送流程；每条请求仍需独立冻结、审查和具名授权。无额外产品级恒阻断，不存在任何人可一键绕过法律/技术门禁。

## 1.4 V3.0 默认可外发：产品行为契约（优先实现）

**定义**：`outbound_capability=available` 是部署级能力状态，不等于 `dispatch_authorized=true`。V3.0 在具备经核验的服务商、已发布法学包、隔离运行环境和真实出站凭据时，向用户提供可用的真实外发功能；不能再以常量 `product_dispatch_state() == "blocked"` 作为最终产品设计。

- **默认路径**：非纯本地任务可选择 `MINIMIZED_TEXT_B`；适配的任务完成事实卡裁剪与人工审查后，正常进入请求级审批、一次性许可与外发，而不是跳转到“实验功能未开通”。
- **四门编排**：面向用户仅有 G-L（法律/接收方）、G-D（最小披露与风险）、G-H（L 级别一次确认）、G-S（网关即时验证）；G1/G3/G5/G9 等可稳定条件优先按签名证明前置，仍按版本/过期/撤销校验；G8 必须按具体攻击输入哈希维持有效结论。详见门禁精简 ADR。
- **初始状态**：每个新请求为 `pending_assessment` / `pending_approval`，不是 `authorized`；只有符合全部条件才变为 `ready_to_dispatch`。不满足的返回**具体可修复原因**（缺少包、法源、接收方合同、PIA/CTIA 确认、服务商能力、密钥、签名、隔离、攻击验证等），不是抽象的“产品尚未开通”。
- **可执行权限**：形式上 `can_dispatch = deployment_ready AND recipient_ready AND legal_chain_approved AND gate_snapshot_allowed AND human_approval_valid AND payload_bytes_match AND one_time_grant_live`；任一项缺失即仅阻断当前请求/具体链路。
- **流程责任**：普通案件满足以上谓词后，系统须实际调用所登记的服务端点，返回有证据的 `complete` 或 `unknown`，绝不以 `mock` 和静态回执冒充外发。
- **范围与有效期**：可被准入的任意案号、案由/法域组合与任务类型都可进入流程，不再把 `FIRST_RELEASE_TUPLE`（LA-001）硬编码为 V3.0 永久条件；所有新增范围仍需对应的包/法域/提供者准入与签名证明。
- **默认 UI**：“外发可用 / 待准备 / 待法学审查 / 待具名批准 / 可发送 / 发送中 / 已送达 / 结果未知 / 已阻断”是分开的状态，**不得把系统默认能力可用显示为案件已经合规**。
- **部署策略**：新安装时初始化 `capability=available_when_provisioned`，无必要条件时展示可配置项与待完成门禁；不是硬编码全局 `blocked`。这不意味着无审查地自动上传用户数据。生产实发必须由具名授权者确认且经网关检测。
- **迁移窗口**：现有 `main` 仍是硬阻断版本；先用合成材料完成 `integration` 真实调用和生产等价隔离验证，再替换恒阻断语义及试点固定范围。迁移前不得用直接修改常量绕过门禁。

**验收判据 A**：准备就绪的真实、获批最小事实卡在 `production` 端到端实际发送、收到服务商返回、形成真实 `provenance=cloud`、不可重放许可和完整网关日志；不能因为产品硬锁失败。  
**验收判据 B**：L4、缺法域审查、无签名材料、变更请求哈希、过期批准或无法确认的隔离仍然阻断，不能因默认能力可用而误发。  
**验收判据 C**：A 链和 B 链各自有正向真实发送与否定案例；B 链完整不使 A 链绕过法域门禁，反之亦然。

## 2. 总体架构：可信域、控制面和两条独立数据面

```text
[法律工作台 React]
       │ 仅本地具名会话
       ▼
┌────────── 边侧可信数据域 ─────────────────────────────────────┐
│ 案卷/版本/DocumentIR/SourceAnchor/身份映射/证据图谱/本地密钥       │
│ 边侧模型: 提取 → 规则PII+语义敏感度 → 争议标注 → 最小披露候选        │
│ V3 PrivacyEngine: S0–S2 + L0–L4 + 风险组合 + 路由 + DP预算账本      │
│ LegalDecision: 管辖/目的/接收方/处理地点/留存/使用人 + 法学审批      │
│ Orchestrator: 冻结上下文/请求/许可/可验证发出载荷/证据步骤          │
└─────────────────┬───────────────────────┬────────────────────┘
                  │ A链                   │ B链
                  ▼                       ▼
         [业务传输执行器]          [模型调用独立网关]
         独立授权/配额/日志         现有G0–G10及一发一证
                  │                       │
                  ▼                       ▼
         境外HR/子公司/律所         合规服务商/受控算力
                  │                       │
                  └─────已批准结果/回执───┘
                                 │
                                 ▼
                [边侧CloudResultEnvelope与ReturnPipeline]
                [主张/反证并列 + SourceAnchor逐项验证]
                [具名HumanDecision → 受约束的文书/分享]
 
  控制面（非证据数据面）：KubeEdge控制/配置、签名领域包、撤销、版本回执。
  验证面（与生产凭据隔离）：Ianvs、真实红队、合成案例、消融实验。
```

**控制面规则**：KubeEdge CloudCore、EdgeCore、ConfigMap 下发不自动证明数据驻留。生产要求节点准入、双向认证、签名配置/包、撤包时效、断连自治、版本回执；**禁止经控制面同步原卷宗、身份映射、可定位原文的样本或真实 API 密钥**。

**单一真正出口**：B 链保留 `gateway.py` 已有凭据边界；A 链增加独立的业务传输执行器和账本。所有跨域内容只能从受控执行器发出。`gateway` 的当前 `LEX_GATEWAY_ROLE` 标志不意味着边侧接单、云侧出站已经物理拆开。

## 3. 两层风险标记与一次路径规划

### 3.1 双风险轴，不得互相简化

- `SensitivityClass ∈ {S0,S1,S2,UNKNOWN}`：论文侧个人信息敏感性。S0 一般公共/不涉及个人信息，S1 一般个人信息，S2 高敏/特殊敏感性信号。上游 Ianvs 当前仅有 `general`/`high_sensitivity` 二值实现，不能冒充三分类模型。
- `DisclosureGrade ∈ {L0,L1,L2,L3,L4,UNKNOWN}`：法学方案的外发治理级别，受任务必要字段、精确日期/金额、个人身份、组合同一性、法域、商业秘密、接收方和使用目的影响。

**优先级**：`L4` 硬阻断；`UNKNOWN` 失败关闭；`L3` 默认不外发，经法学 PRD 要求的独立准入、PIA/CTIA 适用性核验、按角色双重审批、缩减材料后重新评估才可能形成特定许可；`L2` 原则上具名律师/合规专员审批；`L1` 常规专业复核；`L0` 即使无需逐案法律签字也不得绕过未满足的服务商、资源、网关和地区技术门禁。L3 不是「高 ε 一样可以直接传」。

分类器/规则结果必须含 `source_span`、检测理由、模型/规则版本、置信或不确定度、对比差异。模型离线或失败时不得降级为 S0/L0。

### 3.2 候选执行路径（任务级能力约束）

| Route | 实际执行 | 允许性 |
| --- | --- | --- |
| `LOCAL_DETERMINISTIC` | 现有确定性事实/时间线/证据整理 | 默认首选；本地处理无需外发许可 |
| `LOCAL_LLM` | 边侧模型读原文并生成待审候选 | 仅本地；不能作为法学审核者 |
| `MINIMIZED_TEXT_B` | 最小事实卡 + B链许可 + 独立网关 | **V3.0 正式主路径**；任务满足条件后真实发送；条件不足只阻断该请求 |
| `DP_VECTOR_EXPERIMENT` | Encoder → clip → Gaussian → 可选 JL → Adapter | **仅研究/隔离环境**，不能由现有 API 自动生产发送 |
| `BLOCK` | 无外发或外发停止，记录阻断理由 | 任一硬条件失效 |

A 链的 `BUSINESS_SHARE_A` **不是 B 链模型路线**：它是后置或独立的业务分享操作。每次单独创建 TransferIntent 与授权快照；分享结果亦可含个人信息和法律秘密，不能因 B 链已做文本脱敏而跳过重新评估。

**路径规划形式**：先由法学/安全谓词产生可行集 `A_eligible`，再对其中的候选以任务效用、隐私风险、成本/时延作可解释排名：`argmax U(a) subject to legal_allow(a) && tech_ready(a) && budget_valid(a)`。硬法学条件不可被加权分数抵消。任何路径建议都不是执行许可。

### 3.3 法律事实效用硬约束

任务包定义关键事实属性：`party_role`、`event_date`、`salary_due`、`salary_paid`、`denial`、`evidence_ids`、`opposing_evidence_ids`。对证据精确性的损耗必须显式解释；不允许 DP 噪声直接修改待核算的工资金额、时点或实体主张，再把变动结果说成原始证据。

## 4. 隐私算法层与研究到生产隔离

### 4.1 敏感度检测：规则先行、语义补足

流水线：SourceSpan 与确定性 PII 坐标 → 规则匹配和准标识组合 → 边侧受控语义模型 → 冲突合并与置信校准 → 人工标注复核样本库。不得在云端对未批准原文做「辅助分类」。

一期利用现有 `detection.py` 和 MiniCPM 边侧能力，研究中对比轻量中文实体模型与论文的 Llama-3-8B/4bit；不强制替换现有 GPU 资源调度。要求高敏召回、已知组合攻击检出率和人工标注一致性分别报告，不仅报告总体 accuracy。

### 4.2 正确的高斯机制契约

研究输入：真实、标记生成器版本的 Encoder 输出向量；伪随机 `hash(text)` Embedding 禁止用于真实效用结论。

对向量 `x` 先执行 `clip(x,C)=x·min(1,C/||x||₂)`，明确一次隐私单元、邻接定义和上界 `Δ₂` 后，采样 `N(0,σ²I)`。若采用替换邻接、单条向量受 `C` 约束，保守上界通常为 `2C`；不能一处按 `C` 核算，另一处按 `2C` 宣称保证。选择已验证的 Gaussian/RDP/PLD 会计实现，规定 `(ε,δ)`、采样机制和组合定理适用条件。

- 实验固定 `seed` 只用于可复现实验；**生产 DP 不可使用可预测固定种子或 Python `random.Random(seed)`**。
- DP 隐私预算账本按 `data_subject/cohort + purpose + recipient_scope + dataset_version` 组合计数，不能仅重建前端 Session 就重置。
- `BudgetReservation` 先检查和**原子预留**，只有预算及门禁均有效才有资格形成外发授权；发送后按真实送出或 `unknown` 的保守规则提交。确定 **未送出** 方可释放相应预留。
- 重复查询、重放相同 release、换接收方、改 Adapter、参数升级都必须有独立策略与账本解释。
- DP 是有条件的数学保证；外发向量仍必须通过 B 链的法律适用性判断和攻击/重识别审查。

### 4.3 联合推理的现实技术约束

`DP_VECTOR_EXPERIMENT` 必须具有：
1. 边侧真实 Encoder 输出、投影矩阵/模型版本、数据维度与类型检查；
2. 可实际接收并利用受保护连续向量的云端 `VectorAdapter` 和可控推理模型（普通聊天 completion 不满足该条件）；
3. 指定向量数据类型、处理区域、保留和访问策略；
4. 独立隐私攻击/效用消融，特别是 inversion、属性推断、成员推断、链接攻击和跨轮组合攻击；
5. 任务特定的证据语义可靠性。不能用情感分类 F1 替代法律事实准确性。

`HE` 密文适配/同态推理独立作为科研支线。当前上游实现仅有文字/配置级描述，不将其列为任何 V3.0 主线发布依赖。

### 4.4 动态策略反馈

Cloud Risk Feedback 只能生成 **Proposal**；边侧 Policy Validator 检查与法律包、预算、最小化约束和签名版本兼容，经合规负责人/算法安全负责人审批后对**下一次新冻结任务**生效。禁止云端自动调大 ε、放宽 L 等级、自动更换境外接收方或调整在途获批请求。

## 5. A/B 双链解耦：独立法律事件与执行器

### 5.1 A 链（业务协作）

发送对象：中国母公司、越南子公司 HR、当地律所等；载荷类型可以是最小事实卡、经审批的核对结果或局部证据副本。建立 `TransferIntent(chain=A)`，单独确认数据输出方、境外接收方、法定角色、目的、转委托、处理地域、时限、二次分享、存储策略、人员范围、法域法律路径以及是否适用人事管理特殊制度。

根据法学方案，对中越双向案例至少区分「日常人事管理」「争议全案卷宗」「任务化最小事实卡」；不以“人力资源管理”字段的单一布尔值自动生成豁免。`PIA/CTIA` 的必要性、时限和豁免条文版本由具名法律评审决定并登记证明材料。具体法律条文、2026 年中越法域有效性、受限行业要求，应在签发规则包前独立重新核验。

### 5.2 B 链（外部算力）

`TransferIntent(chain=B)` 独立审查 API 提供者、实际计算/存储区域、DPA、训练利用限制、日志/留存、子处理方、接收目的、密钥、有效端点及具体冻结载荷。**B 链境外算力本身也可能构成数据出境处理活动**，不可被架构图默认排除。

B 链复用 `gateway.py`、`formal_release.py`、`outbound_gate.py`；由 **G-L/G-D/G-H/G-S 四门聚合器**统一展示和调度，旧 G0–G10 仍可追溯，不得创建绕过既有门禁的另一个模型 HTTP 客户端。

### 5.3 七维法学审查输出

两个链各自持有以下字段，不能拷贝对方结果：
`jurisdiction`、`task_purpose`、`recipient_role`、`field_scope`、`processing_regions`、`retention_and_reuse`、`result_authorized_users`。

法律判断对象 `ChainDecision`：`not_applicable | pending | approved | rejected | expired | revoked`，包含依据法源的受审版本、审核人、签章和证据引用、审批时间/有效期、适用链、`payload_digest`、`runtime_snapshot_hash`、`recipient_policy_hash`。修改内容、地点、角色、法源或策略后立即失效并重新评审。

### 5.4 独立状态与相互约束

B 链沿用现有任务 `draft→review/blocked→approved→queued→sending→complete/unknown/failed`，G0–G10 编号保持。A 链新增独立共享状态 `prepared→assessed→approved→queued→sending→delivered/unknown/blocked`。两个链不能共用 `approval_id`、`grant_nonce` 或表示“已送达”的事件。统一任务只持相应链引用，不合并权限；若一个工作流含两链，分别检查各次真实外发。

### 5.5 载荷真实性与失败恢复

- 冻结 **最终在网络层实际发送的规范化字节**，而不是仅哈希 Python 业务对象。比较 `approved_bytes_hash`、`attempted_wire_bytes_hash` 与相关 `request_hash`；差异触发 G-01，无发送。
- 真正发出前的连接失败 → `failed_before_send`，有证据时可释放预算预留；服务端可能已接收、超时或中断 → `unknown`，视为可能披露，禁止擅自重试。
- 事务性 outbox、单次许可、nonce 防重放、供应商幂等能力和网关先记账再发送。网关账本不得持有原件、映射表或可直接逆推出敏感信息的日志正文。

## 6. 契约：V3.0 新增的最小跨模块协议

> 以下为**建议协议**，不是已部署的 `contracts.py` 类定义。第一阶段先签 Schema，后接业务实现。

```json
{
  "PrivacyAssessmentV3": {
    "assessment_id": "pa_...",
    "task_id": "task_...",
    "source_context_hash": "sha256:...",
    "sensitivity_class": "S2",
    "disclosure_grade": "L3",
    "classifier_version_hash": "sha256:...",
    "ruleset_hash": "sha256:...",
    "signal_ids": ["signal_..."],
    "uncertainty": "review_required",
    "hard_prohibitions": [],
    "explanation_codes": ["QUASI_IDENTIFIER_COMBINATION"]
  },
  "ExecutionPlanV3": {
    "plan_id": "plan_...",
    "task_id": "task_...",
    "route": "LOCAL_ONLY",
    "purpose_id": "wage_dispute_summary",
    "assessment_hash": "sha256:...",
    "minimization_profile_hash": "sha256:...",
    "capability_binding_hash": "sha256:...",
    "dp_reservation_id": null,
    "requires_transfer_chains": [],
    "eligible": true,
    "approval_granted": false
  },
  "TransferIntentV3": {
    "transfer_id": "transfer_...",
    "chain": "B",
    "direction": "CN_TO_PROVIDER",
    "sender_role": "controller",
    "recipient_role": "processor",
    "recipient_id": "approved_provider_...",
    "processing_regions": ["..."],
    "legal_rule_version_hash": "sha256:...",
    "approved_wire_bytes_hash": "sha256:...",
    "request_hash": "sha256:...",
    "review_decision_id": "decision_...",
    "status": "pending"
  },
  "PrivacyReleaseReceiptV3": {
    "release_id": "rel_...",
    "mechanism_id": "gaussian_v1",
    "neighbor_relation": "replace_one",
    "encoder_hash": "sha256:...",
    "delta": 0.00001,
    "epsilon_accounted": null,
    "clipping_norm": null,
    "noise_sigma": null,
    "budget_reservation_id": null,
    "payload_digest": "sha256:...",
    "replay_protected": true,
    "experiment_only": true
  }
}
```

要求：JSON Schema/Pydantic 对所有枚举封闭、禁止多余字段；不能在日志/API 中返回 `source_anchor` 的本地 locator、原始名字或带有敏感文本的检测片段；每个快照都有内容哈希、版本、构建来源和失效传播。Schema 升级采取 `contract_version=3` 并提供 `V2→V3` 适配器，**不得在未升级当前网关白名单校验之前改动现有 V2 真实线契约**。

## 7. 案件事实、证据链接与返回九阶段

### 7.1 事实对象

`FactAssertionV3` 至少包括：
- `assertion_id, case_id, statement, fact_type, asserted_by, verification_state`；
- `supporting_anchor_ids[]`、`opposing_anchor_ids[]`、`conflict_group_id`；
- `material_version_hash`、`source_role`（当事人主张 / 对方否认 / 文书记载 / 已核查事实）；
- `critical_fields`（金额/日期/工资周期/实体）；
- `human_decision_id`、`disposition`（仅经人工确认后为正式采纳）。

**每项法律事实陈述必须绑定真正支持该句话的原文锚点，不能仅检查 `source_id` 是否存在。** 将支持/反对关系分别存储，若存在冲突并列、标注「待人工审定」，不可由 LLM 隐式选择其中一边。

### 7.2 在已有返回管道中挂钩

保留 `return_pipeline.py` 的 9 阶段：
`envelope→hash→schema→provenance→domain_mapper→identity_relink→evidence_relink→review_schema→human_decision`。

在 `evidence_relink` 增加主张/数值/日期/否定关系匹配与源文位置验证；在 `review_schema` 强制对反证遗漏和实体定性作红旗标注；`human_decision` 没有具名采纳则只展示候选，禁止正式文书/业务分享。

### 7.3 五类审计证据

1. 案卷证据：原文版本、证据 ID、页/段/单元格定位及来源哈希；
2. 最小披露：源→候选→冻结事实卡的字段级 diff、保留必要性和损失说明；
3. 风险审批：S/L 标签、PII/组合攻击、DP/路由、A/B 各自法律审查、具名签名；
4. 网关发送：冻结字节哈希、实际尝试字节哈希、服务商/接收方、状态与失败语义；
5. 结果与人工：模型候选、事实-正反证回链、冲突、修订、采纳/驳回、导出与分享记录。

原有 `audit_chain.py` 是 hash-chain；对于管理员修改历史后重算链的威胁，新增外部签名 checkpoint/只追加对象存储并验证恢复演练，不能只凭「有哈希」宣称不可篡改。

## 8. 持久化、API、安全隔离与前端

### 8.1 存储演进

继续以单实例 SQLite WAL + Alembic 为现阶段基线，不提前改 PostgreSQL。新增业务聚合 `privacy_assessment`、`execution_plan`、`transfer_intent`、`chain_decision`、`dp_release_receipt`、`fact_assertion`、`conflict_group`、`wire_payload_receipt`、`audit_checkpoint` 等可走已存在的 `records(kind,scope,body)`。

但**并发预算预留与一次性发送去重必须具有数据库级事务/唯一键约束**，必要时将 `privacy_budget_scope`、`budget_reservation`、`dispatch_grant` 从 JSON 聚合抽为具唯一键的专用表：`(budget_scope_id, request_hash, mechanism_version)` 去重，`reservation_nonce` 唯一，状态只能单向演进。不可用进程内 dict 代替持久化会计。

### 8.2 计划 API（未实现）

| 接口 | 意图 | 校验重点 |
| --- | --- | --- |
| `POST /api/cases/{id}/privacy/assess` | 本地敏感度与治理评估 | 用户具名、证据版本、无外发 |
| `POST /api/tasks/{id}/execution-plan` | 路由候选与理由 | 仅 plan，无 dispatch |
| `GET /api/tasks/{id}/privacy-budget` | 经授权的预算摘要 | 不透露主体身份或私有数据 |
| `POST /api/tasks/{id}/chain-assessments` | 针对 A 或 B 链构造七维审查 | 链字段强校验、不可交叉授予 |
| `POST /api/transfers/{id}/review` | 具名法学决定 | 快照一致、角色分离、有效期 |
| `POST /api/transfers/{id}/dispatch` | 走对应独立执行器 | 正式 release gate + nonce + 审批 + 字节哈希 |
| `GET /api/tasks/{id}/evidence-conflicts` | 正反证及定位 | 仅本地、权限隔离 |
| `POST /api/tasks/{id}/human-decision` | 事实采纳与文书许可 | 来源可信、冲突已呈示 |

API 命名应在 PR-01 冻结并对齐现有资源风格。所有写操作需要幂等、角色鉴权、审计和版本冲突检测，不能让前端自行拼接审批 token。

### 8.3 前端工作台

对现有大型 `App.tsx` 与 Governance 页面渐进拆分；优先新增「案件证据」「最小事实卡 Diff」「S/L 风险评估」「A 链审查」「B 链审查」「DP 预算及实验状态」「正反证对照」「审计与人工结论」视图。界面必须显式区分 **待批准**、**已批准**、**未发送**、**可能已披露（unknown）**、**已送达** 和 **模型模拟**；不得展示总合规评分来替代条件证明。

### 8.4 异常码

在原有 G0–G10/技术错误之外增加名字空间，不重编号现有门禁：
- `A-01` A 链业务跨境接收方未获合法准入；
- `B-01` B 链模型服务条件未通过；
- `G-01` 批准载荷与实际发送字节哈希不一致；
- `E-01` 模型陈述缺有效证据；
- `E-02` 与相反证据冲突，须人工并列审定；
- `C-01` 重要配置变更导致审批失效；
- `P-01` 隐私预算不足或账本状态未知；
- `P-02` 算法/模型/裁剪定义无法证明；
- `R-01` 路由与领域任务效用硬约束冲突。

## 9. Ianvs 的正式集成边界与实证

### 9.1 不直接移植上游主执行链

上游存在已确认的阻断点：`PrivacyPreservingLLM._edge_inference` 固定返回置信度 0.85、`_requires_cloud_inference` 低于 0.8 才上云；`masking` 返回 dict 后传给 `DP.add_noise`，后续降维接口也不对齐；`_text_to_embeddings` 使用 `hash(text)` 的伪向量；`evaluate` 返回硬编码 metrics。上游 `algorithm.yaml` 指定未注册的 `privacy_preserving_llm` 类型；数据 `data/chnsenticorp_lite` 缺失。具体修复必须通过真实运行证明。

### 9.2 实验职责与四路对比

独立 `benchmarks/ianvs_pipl` 环境只接收合成或合法授权数据，禁生产网关密钥与真实案件映射。对比：
- 纯边侧确定性与本地 LLM；
- 经授权的最小文本事实卡；
- 实验 `Encoder→Gaussian DP→Adapter`；
- 实验 `DP+JL`（HE 为可选研究，不纳入必要基线）。

修复 Ianvs 标准 `jointinference` 所需 `edgemodel/cloudmodel/hard_example_mining` 模块接口，或显式注册自定义 Paradigm；真实训练/测试集、版本、标注人独立性、消融参数及推理输出一并冻结。

### 9.3 两类指标不可混为一谈

**算法四维**：效用（Accuracy/F1、语义/字段任务表现）、隐私（MIA AUC/TPR@FPR、重识别/反演/链接攻击、预算）、合规工程（零原文泄露率、审计覆盖、预算/门禁拒绝）、性能（延迟 p50/p95/p99、RPS、边侧内存/显存/能耗）。

**法学 PRD 九维**：字段事实 F1、证据锚点覆盖/正确率、无源事实率、反向冲突证据召回、冗余敏感外发率、组合重识别攻击、网关误放/误拒、审计证据完整率、法律专业人员耗时节省。完整数据来源需独立标注，不能把 PRD 提到的约 80 组样本写成已入库；已检查到当前工程 catalog 以 8 个 mock 记录为主。

**公用验收数据字段**：`metric_name`、`definition`、`numerator/denominator`、`dataset_hash`、`model_hash`、`attack_protocol_hash`、`sample_count`、`confidence_interval`、`runtime_env_hash`、`raw_trace_hash`、`evaluator_version`、`is_simulated`。含 `is_simulated=true` 的结果不得参加正式门禁。

## 10. 重构实施顺序与仓库映射

> **总体路线**：架构契约先行 → 算法隔离接入 → 法律 A/B 独立执行 → 证据/审计完成 → KubeEdge/Ianvs 验证 → 生产签发。每个 PR 单独可审、可回滚，不允许长时间并存两条生产外发路径。

| 交付 | 代码范围 | 最低验收条件 | 依赖 |
| --- | --- | --- | --- |
| PR-00 规格基线 | `docs/V3_0_REFACTOR_SPEC.md`、`docs/V3_0_DELIVERY_MATRIX.md` | 与现有安全边界无冲突；法学/算法评审问题明确 | 无 |
| PR-01a 四门聚合/兼容 | `gate_orchestrator.py`（新增）、旧 `outbound_gate.py`、`formal_release.py` | 新旧门禁等价、4 关一屏、旧证据可追溯 | PR-00 |
| PR-01b 前置证书/复用 | 法学/服务商/隔离证明、任务哈希缓存与回归 | 只有未变 scope/TTL/hash 复用；变更和撤销立即失效；高风险红队不复用异源结果 | PR-01a |
| PR-01 V3 契约/版本 | `contracts.py`、`domain_runtime.py`、迁移与 `tests` | Schema 严格，旧 V2 请求字节、冻结哈希、旧用例保持兼容 | PR-00 |
| PR-02 边侧分类与风险 | `privacy/sensitivity_classifier.py`、`detection.py`、模型能力绑定 | 高敏/组合漏检基线、未配置失败关闭、模型离线回退不降级 | PR-01 |
| PR-03 最小化与路由 | `privacy/privacy_router.py`、`disclosure.py`、`policy.py` | L4 阻断、UNKNOWN 阻断、金额日期否定关系保真、无自授权 | PR-02 |
| PR-04 DP 机制/会计 | `privacy/dp_mechanisms.py`、`privacy/privacy_accountant.py`、持久表 | 数学已审核、随机数安全、并发预算、unknown 保守、重复释放阻断 | PR-01,03 |
| PR-05 A 链独立治理/分享 | `compliance/chain_assessment.py`、`transfer/*`、规则包与 API | A-01/七维核验/法域签署，未批不可出网，与 B 完全解耦 | PR-01,03 |
| PR-06 B 链通用可用发送与物理验证 | `service.py`、`formal_release.py`、`outbound_gate.py`、`gateway.py`、容器网络 | **去除 V3 产品级恒阻断和首试点固定范围限制**，保留全部 G0–G10，符合授权要求的真实生产请求可发送并留回执；不满足条件逐请求拒绝 | PR-01,03,05 |
| PR-07 事实和反证验证 | `return_pipeline.py`、`policy.py`、`evidence/*` | E-01/E-02、生效材料版本、具名 HumanDecision、禁止虚假导出 | PR-01,03 |
| PR-08 UI 与审计完整性 | `frontend/`、`audit_chain.py`、外签 checkpoint | 明确 A/B 状态、5类收据、unknown 与 simulation，审计恢复可查 | PR-05,06,07 |
| PR-09 KubeEdge 控制面 | `package_controller.py`、`deploy/k8s`、配置分发/撤销 | 真断连、签名、撤销、边侧自治；控制面无案件敏感内容 | PR-01,06 |
| PR-10 Ianvs 真实基准 | `benchmarks/ianvs_pipl`、`acceptance_suite.py`、样本 | 非模拟 MIA、真实 Adapter、法学九维、CI 闸口与证据报告 | PR-02,04,07 |
| PR-11 发布总验收 | `docs/VALIDATION.md`、安全/法学批准记录、发布清单 | 全部前置法学及安全测试，显式 release grant，绝无默认放行 | PR-06…10 |

**依赖说明**：`MINIMIZED_TEXT_B` 的常态化外发不依赖 DP_VECTOR 实验成功或 DP 账本生产化；只有执行 DP 释放的路线才需要预算会计。优先完成 B 链真实受控外发，再迭代 A 链、DP 实验和复合流程。

### 10.1 现有文件要保留的边界

- `service.py` 从大型流程函数中抽出评估/规划/许可 façade，不把权限移给 LLM；
- `policy.py` 保持确定性 G 门权威，接收 PrivacyAssessment 的**只读**风险信号；
- `domain_runtime.py` 的不可变 snapshot 增加模型/预算/路由/法域包 hashes；
- `contracts.py` 使用加法式版本升级，不重写全部现有对象；
- `outbound_gate.py`、`formal_release.py`、`gateway.py` 保持原 G0–G10/一次授权/日志定位；
- `return_pipeline.py` 保留九阶段，仅在 evidence/review 添加校验证据；
- `experiments.py` 保留历史结果可重复性，不直接 import 到生产 dispatch；
- `package_controller.py` 作为 KubeEdge 传输无关的控制面，沿用 signed manifest / receipt；
- `domain_packages.py` 既有八类包中，领域内容和跨法域版本分别维护，发布时必须冻结所有依赖。

### 10.2 版本与迁移

版本轴独立：`platform_api_version`、`domain_package_version`、`legal_effective_version`、`privacy_algorithm_version`、`provider_policy_version`。旧案件保留旧 `DomainRuntimeSnapshot`；新任务按显式最新规则创建新版快照，禁止静默迁移。迁移顺序：备份→构建兼容 schema→旧对象只读升级→双写审计→回归→切新读路径→经过独立回滚窗口后退旧逻辑。撤包、算法撤销、法源失效均要触发未发送任务重新审查。

### 10.3 产品级全局阻断迁移的细粒度代码方案

当前 `outbound_gate.product_dispatch_state()` 恒返回 `blocked`；`formal_release.FIRST_RELEASE_TUPLE` 限定首批范围，`install_policy` 与 `issue_grant` 采取从 blocked 到 armed_once 的一次性试点模型，真实网关要求签名许可、G 门及隔离凭据。V3.0 应迁移**产品能力标志**、**请求准入结果**与**实际发送状态**三种不同语义：

| 状态面 | 目标属性 | 允许变化 | 不允许变化 |
| --- | --- | --- | --- |
| 部署能力 `OutboundCapability` | `available / setup_required / suspended` | 按环境、构建、服务商/接收方配置计算；默认面向真实发送可配置 | 不能以开关直接充当法学审批 |
| 单次审查 `DispatchEligibility` | `pending / ready / denied / expired` | 每请求读取 G0–G10 / A-B 法域/审批与冻结哈希 | 未批准不能自动 `ready` |
| 执行账本 `DispatchReceipt` | `not_sent / sending / complete / unknown / failed_before_send` | 由持凭据的独立网关持久化 | 客户端不能自行宣告成功 |

计划引入按 `case_id/task_id/purpose/recipient/provider_profile/route` 绑定的 `ReleaseScope`，其可配置和签署的适用范围可覆盖劳动争议真实案件，替换仅对 `LA-001` 的固定试点限制。延续 `OneTimeDispatchGrant`、`GateDecision`、`ReleaseBuildManifest`、`gateway_claim` 的不重放与签验机制，而不新增绕过出口。

**切换点**：PR-01 冻结旧请求签名与迁移 schema；PR-05 完成 B 链法律签署接口；**新 PR-06A 单独实施 B 链正常外发**；PR-06B 实施 A 链独立业务传输，且 A 的进度不应影响 B 已有合法可用能力。原 V2.2 试点入口维持版本兼容，禁止直接擦除历史授权记录。

**CI 必需**：生产态有真实 API 凭据且满足门禁的 `cloud` 请求实际发送一次；没有批准的绝不发送；只有部分配置但缺法源包/攻击验证时不得“假就绪”；`unknown` 无自动重发；跨案/跨法人/跨法域/跨服务商的旧 `grant` 不得复用。

## 11. 必须覆盖的攻击与失效场景

| 场景 | 预期 |
| --- | --- |
| L4 明文姓名/证件/银行号/商业秘密进入准备发送载荷 | 网关硬阻断；模型/律师不能绕过；重构任务 |
| 高敏分类器缺模型、超时或把输入识别成低敏 | 结果未知/复核，不得自动跨境 |
| L2 精确计薪记录被掩码/DP 改变金额或时间 | 路由本地或有审批的最小文本；禁止把变化内容当事实 |
| A 合规但 B 服务商未知处理区域 | 只允许 A 的合法路径，B-01 阻断 |
| B 完整许可但 A 数据将送越南律所且无 PIA/CTIA 判断 | B 许可不外溢，A-01 阻断 |
| 内容或 provider / legal rule / recipient / 模型变更 | C-01 旧批准立即失效 |
| 发送载荷重新序列化导致网络字节变化 | G-01 阻断并记录差异；不借对象哈希放行 |
| 发送超时且云端可能接收 | unknown + 可能披露 + 保守预算计入，不自动重发 |
| 预算已耗尽/双并发竞争/新 Session 刷新 | P-01 拒绝，无双花 |
| 明确来源 ID 但与原文金额不一致 | E-01 阻断采纳，来源 ID 不算有效支持 |
| 工资表与聊天记录出现相反主张 | E-02 并列，需 HumanDecision |
| 云端返回文本凭空增加姓名、金额或受托人 | provenance/evidence 阶段隔离候选 |
| Node 离线、旧规则包仍留边端、撤销延迟 | 能运行合法本地步骤；外发因策略无法确认而阻断 |
| 生产日志记录完整 prompt、PII 片段、Embedding 或密钥 | 敏感日志检测/隔离测试失败；不签发 |
| 模拟 F1/MIA 代替实测 | 验收拒绝，记录 `is_simulated=true` |

## 12. 发布闸口与完成定义

1. **技术**：现有测试 + 新契约/迁移/红队/网络隔离/一次许可/预算并发/审计恢复测试；最新实际 CI 证据可查询；使用真实 provider 实测且有明确法学许可。
2. **法学**：劳动争议规则包和适用法源独立核对；中越双向所需合法性基础及 PIA/CTIA 判断签署；七维审查满足；L3 双重审批与 L4 不可覆盖。
3. **算法**：分类错漏和不确定性公开；DP 数学、邻接敏感度、随机数、预算模型经过独立检查；Ianvs 模拟指标全部隔离；实验结果不能冒充法学合规。
4. **证据**：关键事实 ID 与真实原文锚点一致、反证并列、人工审定、导出/分享持合法许可。
5. **部署**：边云物理信任隔离、KubeEdge 签名包/撤包及断连自治、日志无原件、外部审计 checkpoint。
6. **发布操作**：旧主分支在迁移前保持原有阻断；V3.0 在部署/法学/安全验收完成后将**常态受控外发**作为默认可用产品能力，不再额外设置恒为 `blocked` 的产品锁。每次发送仅在当前环境、链路、案件、收件方、材料和规则版本全部合格、且具名授权有效时执行；不具备这些条件即失败关闭。

## 13. 待法学/安全/算法专家确认的开放问题

| 决策 | 负责人 | 默认保守选择 |
| --- | --- | --- |
| 2026 年有效 PIPL、中国出境制度与越南 PDP 法及实施法令的具体适用条件/豁免边界 | 法律负责人/当地律所 | `pending`、禁止自动豁免 |
| 日常人事管理、争议卷宗和事实卡分类及第三方委托法律角色 | 中国及越南律师 | 分别建案、分别评估 |
| L1/L2/L3 准确字段、审批角色和最低授权证明 | 法学负责人 | 未冻结规则一律不给正式许可 |
| DP 隐私单元、邻接定义、ε/δ 上界与预算共享边界 | 隐私算法负责人 | DP_VECTOR 仅实验 |
| 真实 Encoder/Adapter 的模型推理接口、部署区域和成本 | 模型平台负责人 | 保持 MINIMIZED_TEXT_B 与 LOCAL_ONLY |
| 实证金标准的案例数量、标注协议、法学争议标注方法 | 数据治理及法学评审 | 不拿 8 mock 或提案的 80/3000 充当真值 |
| 哈希/签名 key 管理、不可变日志保护和恢复测试 | 安全负责人 | 未验收请求拒绝，已验收范围允许受控发送 |
| 现有 2B 模型能否满足 S2 检出与工资事实保真 | 算法负责人 | 规则优先、未知阻断 |
| A 链独立执行器的收件端确认、密钥生命周期、撤销及可能披露语义 | 安全/业务负责人 | 未通过验收不开通 |

## 14. 外部与仓库链接

- 现有仓库：<https://github.com/alanzhang66666/LexAegis>
- 现行架构：<https://github.com/alanzhang66666/LexAegis/blob/main/docs/ARCHITECTURE.md>
- 现行验证：<https://github.com/alanzhang66666/LexAegis/blob/main/docs/VALIDATION.md>
- Ianvs Proposal：<https://github.com/kubeedge/ianvs/tree/main/docs/proposals/scenarios/PIPL-Compliant%20Cloud-Edge%20Collaborative%20Privacy-Preserving%20Prompt%20Processing%20Framework>
- Ianvs 示例：<https://github.com/kubeedge/ianvs/tree/main/examples/PIPL/edge-cloud_collaborative_learning_bench>
- Ianvs 公开问题：<https://github.com/kubeedge/ianvs/issues/859>
- 上游数据/源码讨论：<https://github.com/kubeedge/ianvs/pull/283>

---

**审查声明**：本文为逐仓库静态分析与所附方案融合形成的**目标规格**；尚未更改生产执行代码、没有重新运行完整 pytest/Ianvs，不代表跨境法律许可已经核实或任何受保护向量已满足匿名化。法学方案属于目标需求，其法律断言需要当期有效法源复核；论文/PIPL GitHub 实验中的固定指标和模拟路径不能作为实测证据。
